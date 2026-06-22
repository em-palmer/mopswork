"""
FastAPI backend for MOpsWork Job Search OS.
Serves scraped + filtered job listings, CV parsing, profile management,
and application tracking.
"""

import csv
import hashlib
import io
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import DESIRED_SKILLS, KEYWORDS_SCORE_10, KEYWORDS_SCORE_20
from backend.filters import JobPosting, filter_and_rank, score_job
from backend.scraper import scrape_all

# ── logging ──
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── in-memory cache ──
cached_jobs: list[JobPosting] = []
last_scrape_time: Optional[datetime] = None

# ── CV / profile data ──
cv_text: str = ""
cv_skills: list[str] = []
profile_name: str = ""
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Application tracking ──
# { job_id: { "status": str, "date_applied": str, "date_updated": str, "notes": str } }
applications: dict[str, dict] = {}
APPLICATIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "applications.json")

CV_FILE = os.path.join(os.path.dirname(__file__), "..", "cv_profile.json")

# Load saved CV
if os.path.exists(CV_FILE):
    try:
        with open(CV_FILE, "r") as f:
            cv_data = json.load(f)
            cv_text = cv_data.get("text", "")
            cv_skills = cv_data.get("skills", [])
            profile_name = cv_data.get("name", "")
            logger.info(f"Loaded saved CV: {len(cv_skills)} skills")
    except: pass


def _save_applications():
    with open(APPLICATIONS_FILE, "w") as f:
        json.dump(applications, f, indent=2)


# Load saved applications
if os.path.exists(APPLICATIONS_FILE):
    try:
        with open(APPLICATIONS_FILE, "r") as f:
            applications = json.load(f)
            logger.info(f"Loaded {len(applications)} saved applications")
    except Exception as e:
        logger.error(f"Error loading applications.json: {e}")


# ── Pydantic models ──
class JobResponse(BaseModel):
    title: str
    company: str
    location: str
    country: str
    description: str
    url: str
    source: str
    salary: Optional[str] = None
    posted_date: Optional[str] = None
    work_type: Optional[str] = None
    company_url: Optional[str] = None
    hiring_manager: Optional[str] = None
    key_skills: list[str] = []
    matched_skills: list[str] = []
    skills_gap: list[str] = []
    salary_lower: Optional[float] = None
    salary_upper: Optional[float] = None
    match_score: float = 0.0
    match_reasons: list[str] = []
    score_detail: dict[str, float] = {}
    job_id: str = ""
    status: Optional[str] = None  # applied/rejected/withdrawn/interviewing/offer
    date_applied: Optional[str] = None
    date_updated: Optional[str] = None


class StatsResponse(BaseModel):
    total_jobs: int
    last_scrape: Optional[str] = None
    avg_match: float = 0.0


class ScrapeResponse(BaseModel):
    status: str
    jobs_found: int
    message: str = ""


class ProfileResponse(BaseModel):
    name: str
    filename: str
    skills: list[str]
    skill_count: int
    uploaded_at: str


# ── lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    global cached_jobs, last_scrape_time
    logger.info("Starting initial scrape...")
    try:
        raw = scrape_all()
        cached_jobs = filter_and_rank(raw)
        last_scrape_time = datetime.now()
        logger.info(f"Initial scrape complete: {len(cached_jobs)} matching jobs")
    except Exception as e:
        logger.error(f"Initial scrape failed: {e}")
    yield


# ── app ──
app = FastAPI(
    title="MOpsWork Job Search OS",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _make_job_id(job: JobPosting) -> str:
    key = f"{job.title}|{job.company}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _job_to_dict(job: JobPosting) -> dict:
    job_id = _make_job_id(job)

    # Format salary as single number
    salary_display = job.salary
    if job.salary_lower and job.salary_upper and job.salary_lower == job.salary_upper:
        salary_display = f"£{int(job.salary_lower):,}"
    elif job.salary_lower and job.salary_upper:
        salary_display = f"£{int(job.salary_lower):,} - £{int(job.salary_upper):,}"
    elif job.salary_lower:
        salary_display = f"£{int(job.salary_lower):,}"
    elif job.salary_upper:
        salary_display = f"£{int(job.salary_upper):,}"
    elif job.salary:
        salary_display = job.salary

    app_data = applications.get(job_id, {})

    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "country": job.country,
        "description": job.description[:400] + ("..." if len(job.description) > 400 else ""),
        "url": job.url,
        "source": job.source,
        "salary": salary_display,
        "posted_date": job.posted_date,
        "work_type": job.work_type or "To confirm",
        "company_url": job.company_url,
        "hiring_manager": job.hiring_manager,
        "key_skills": job.key_skills,
        "matched_skills": job.matched_skills,
        "skills_gap": job.skills_gap,
        "salary_lower": job.salary_lower,
        "salary_upper": job.salary_upper,
        "match_score": job.match_score,
        "match_reasons": job.match_reasons,
        "score_detail": job.score_detail,
        "job_id": job_id,
        "status": app_data.get("status"),
        "date_applied": app_data.get("date_applied"),
        "date_updated": app_data.get("date_updated"),
    }


# ── CV parsing helper ──

def parse_cv(file_bytes: bytes, filename: str) -> tuple[str, list[str]]:
    text = ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc:
                text += page.get_text()
        except ImportError:
            logger.warning("PyMuPDF not installed")
            return "", []
    elif ext in ("docx", "doc"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            for para in doc.paragraphs:
                text += para.text + "\n"
        except ImportError:
            logger.warning("python-docx not installed")
            return "", []
    else:
        text = file_bytes.decode("utf-8", errors="ignore")

    from backend.config import DESIRED_SKILLS
    import re as _re
    text_lower = text.lower()
    found_skills = []
    for skill in DESIRED_SKILLS:
        pattern = r'\b' + _re.escape(skill) + r'\b'
        if _re.search(pattern, text_lower):
            found_skills.append(skill)

    return text, found_skills


# ── endpoints ──

@app.get("/api/jobs", response_model=list[JobResponse])
def get_jobs(
    min_score: float = Query(0, ge=0, le=100),
    max_score: Optional[float] = Query(None, ge=0, le=100),
    source: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    work_type: Optional[str] = Query(None),
    seniority: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    salary_min: Optional[float] = Query(None),
    salary_max: Optional[float] = Query(None),
    status: Optional[str] = Query(None),
    posted_since: Optional[str] = Query(None),
    exclude_na: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    cv_compare: bool = Query(False),
):
    now = datetime.now(timezone.utc)
    filtered = []
    for j in cached_jobs:
        if j.match_score < min_score:
            continue
        if max_score is not None and j.match_score > max_score:
            continue
        if source and j.source.lower() != source.lower():
            continue
        if city and city.lower() not in j.location.lower():
            continue
        if work_type and (not j.work_type or work_type.lower() not in j.work_type.lower()):
            continue
        if seniority:
            sn = seniority.lower()
            title_n = j.title.lower()
            if sn == "high" and not any(l in title_n for l in ["manager", "head of", "lead", "director", "senior", "sr", "vp", "vice president", "principal", "staff"]):
                continue
            if sn == "mid" and not any(l in title_n for l in ["analyst", "specialist", "coordinator", "associate", "executive"]):
                continue
        if keyword and keyword.lower() not in j.title.lower() and keyword.lower() not in j.description.lower():
            continue
        if country and country.lower() not in j.country.lower():
            continue
        if salary_min is not None and (j.salary_upper is None or j.salary_upper < salary_min):
            continue
        if salary_max is not None and (j.salary_lower is None or j.salary_lower > salary_max):
            continue
        # Date posted filter
        if posted_since and j.posted_date:
            try:
                posted = datetime.fromisoformat(j.posted_date.replace("Z", "+00:00"))
            except Exception:
                posted = None
            if posted:
                delta = now - posted
                if posted_since == "24h" and delta.total_seconds() > 86400:
                    continue
                elif posted_since == "3d" and delta.total_seconds() > 259200:
                    continue
                elif posted_since == "1w" and delta.total_seconds() > 604800:
                    continue
                elif posted_since == "older" and delta.total_seconds() <= 604800:
                    continue
        # Exclude N/A
        if exclude_na:
            job_id = _make_job_id(j)
            if applications.get(job_id, {}).get("status") == "not_applicable":
                continue
        if status:
            job_id = _make_job_id(j)
            app_data = applications.get(job_id, {})
            if app_data.get("status") != status:
                continue
        filtered.append(j)

    if cv_compare and cv_text:
        import re as _re2
        cv_text_lower = cv_text.lower()
        result = []
        for j in filtered:
            j.matched_skills = []
            j.skills_gap = []
            # For each skill found in the job spec, check if it appears in the CV text
            for ks in j.key_skills:
                pattern = r'\b' + _re2.escape(ks) + r'\b'
                if _re2.search(pattern, cv_text_lower):
                    j.matched_skills.append(ks)
                else:
                    j.skills_gap.append(ks)
            result.append(j)
        filtered = result

    return [_job_to_dict(j) for j in filtered[:limit]]


@app.get("/api/jobs/sources")
def get_sources():
    sources = sorted(set(j.source for j in cached_jobs))
    return {"sources": sources}


@app.get("/api/applications")
def get_applications():
    """Return all tracked applications with full job data."""
    results = []
    for job in cached_jobs:
        job_id = _make_job_id(job)
        app_data = applications.get(job_id)
        if app_data:
            d = _job_to_dict(job)
            d["status"] = app_data["status"]
            d["date_applied"] = app_data.get("date_applied")
            d["date_updated"] = app_data.get("date_updated")
            d["notes"] = app_data.get("notes", "")
            results.append(d)
    return results


@app.get("/api/applications/export")
def export_applications():
    """Export applications as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Status", "Date Applied", "Date Updated", "Title", "Company",
        "Location", "Work Type", "Salary", "Source", "Match Score",
        "URL", "Company URL", "Key Skills", "Notes"
    ])

    for job in cached_jobs:
        job_id = _make_job_id(job)
        app_data = applications.get(job_id)
        if app_data:
            writer.writerow([
                app_data.get("status", ""),
                app_data.get("date_applied", ""),
                app_data.get("date_updated", ""),
                job.title, job.company, job.location,
                job.work_type or "", job.salary or "", job.source,
                job.match_score, job.url, job.company_url or "",
                ", ".join(job.key_skills),
                app_data.get("notes", ""),
            ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )


@app.post("/api/applications/{job_id}")
def update_application(job_id: str, status: str = Form(...), notes: str = Form("")):
    """Update application status for a job."""
    now = datetime.now().isoformat()
    if job_id in applications:
        applications[job_id]["status"] = status
        applications[job_id]["date_updated"] = now
        if notes:
            applications[job_id]["notes"] = notes
    else:
        applications[job_id] = {
            "status": status,
            "date_applied": now,
            "date_updated": now,
            "notes": notes,
        }
    _save_applications()
    return {"status": "ok", "job_id": job_id, "application": applications[job_id]}


@app.get("/api/stats", response_model=StatsResponse)
def get_stats():
    if not cached_jobs:
        return StatsResponse(total_jobs=0, avg_match=0.0)
    avg = sum(j.match_score for j in cached_jobs) / len(cached_jobs)
    return StatsResponse(
        total_jobs=len(cached_jobs),
        last_scrape=last_scrape_time.isoformat() if last_scrape_time else None,
        avg_match=round(avg, 1),
    )


@app.post("/api/scrape", response_model=ScrapeResponse)
def trigger_scrape():
    global cached_jobs, last_scrape_time
    try:
        raw = scrape_all()
        cached_jobs = filter_and_rank(raw)
        last_scrape_time = datetime.now()
        return ScrapeResponse(
            status="ok",
            jobs_found=len(cached_jobs),
            message=f"Scraped {len(raw)} raw jobs -> {len(cached_jobs)} matches",
        )
    except Exception as e:
        logger.error(f"Scrape failed: {e}")
        return ScrapeResponse(status="error", jobs_found=0, message=str(e))


@app.post("/api/profile/upload", response_model=ProfileResponse)
def upload_cv(file: UploadFile = File(...), name: str = Form("")):
    global cv_text, cv_skills, profile_name
    contents = file.file.read()
    filename = file.filename or "cv.pdf"
    save_path = os.path.join(UPLOAD_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(contents)
    text, skills = parse_cv(contents, filename)
    cv_text = text
    cv_skills = skills
    profile_name = name or filename.rsplit(".", 1)[0]
    # Persist to disk
    with open(CV_FILE, "w") as f:
        json.dump({"text": text, "skills": skills, "name": profile_name}, f)
    return ProfileResponse(
        name=profile_name,
        filename=filename,
        skills=skills,
        skill_count=len(skills),
        uploaded_at=datetime.now().isoformat(),
    )


@app.get("/api/profile")
def get_profile():
    return {
        "name": profile_name,
        "has_cv": bool(cv_text),
        "skills": cv_skills,
        "skill_count": len(cv_skills),
        "text_length": len(cv_text),
    }


@app.delete("/api/profile")
def delete_profile():
    global cv_text, cv_skills, profile_name
    cv_text = ""
    cv_skills = []
    profile_name = ""
    if os.path.exists(CV_FILE):
        os.remove(CV_FILE)
    return {"status": "ok", "message": "Profile deleted"}


@app.get("/api/config")
def get_config():
    from backend.config import (
        CITY_SCORES, WORK_TYPE_SCORES, SALARY_BANDS,
        KEYWORDS_SCORE_10, KEYWORDS_SCORE_20, KEYWORDS_EXCLUDE,
        DESIRED_SKILLS, SENIORITY_HIGH, SENIORITY_MID,
    )
    return {
        "city_scores": {k: v for k, v in sorted(CITY_SCORES.items())},
        "work_type_scores": WORK_TYPE_SCORES,
        "salary_bands": [
            {"label": f"£{int(lo):,}-{int(hi):,}" if hi != float("inf") else f"£{int(lo):,}+", "points": pts}
            for lo, hi, pts in SALARY_BANDS
        ],
        "keyword_score_10": KEYWORDS_SCORE_10,
        "keyword_score_20": KEYWORDS_SCORE_20,
        "keyword_exclude": KEYWORDS_EXCLUDE,
        "seniority_high": list(SENIORITY_HIGH),
        "seniority_mid": list(SENIORITY_MID),
        "desired_skills": DESIRED_SKILLS,
        "max_score": 100,
    }


@app.get("/api/skills-in-demand")
def skills_in_demand():
    """Analyse key_skills across all cached jobs, return ranked by frequency."""
    from collections import Counter
    counter = Counter()
    for j in cached_jobs:
        for skill in (j.key_skills or []):
            # Normalise: lowercase, strip whitespace
            s = skill.strip().lower()
            if s:
                counter[s] += 1
    total = len(cached_jobs)
    results = []
    for skill, count in counter.most_common(60):
        pct = round(count / total * 100) if total else 0
        # Capitalise nicely
        skill_display = " ".join(w.capitalize() if w != "api" and w != "crm" and w != "sql" and w != "ppc" and w != "seo" and w != "sem" and w != "css" and w != "css3" else w.upper() for w in skill.split())
        results.append({
            "skill": skill_display,
            "skill_key": skill,
            "count": count,
            "percentage": pct,
        })
    return {"total_jobs": total, "skills": results}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "cached_jobs": len(cached_jobs),
        "last_scrape": last_scrape_time.isoformat() if last_scrape_time else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8003, reload=True)