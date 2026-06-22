"""
Job filtering and scoring engine — max score is 100.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from backend.config import (
    CITY_SCORES,
    WORK_TYPE_SCORES,
    SALARY_BANDS,
    SENIORITY_HIGH,
    SENIORITY_MID,
    KEYWORD_SCORES,
    KEYWORDS_EXCLUDE,
    DESIRED_SKILLS,
)


@dataclass
class JobPosting:
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
    key_skills: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    skills_gap: list[str] = field(default_factory=list)
    salary_lower: Optional[float] = None
    salary_upper: Optional[float] = None
    match_score: float = 0.0
    match_reasons: list[str] = field(default_factory=list)
    score_detail: dict[str, float] = field(default_factory=dict)


def normalise(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def contains_any(text: str, keywords: list[str]) -> bool:
    """Check if any keyword appears in text."""
    n = normalise(text)
    for kw in keywords:
        if kw in n:
            return True
    return False


def extract_salary_numeric(salary_str: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """Try to parse a salary string into (lower, upper) numeric values."""
    if not salary_str:
        return None, None
    # Patterns: £40,000 - £60,000, £40k-£60k, $100k, etc.
    # First try range
    m = re.search(r'[£$€]?([\d,]+(?:\.\d+)?)\s*(?:k)?\s*[-–to]+\s*[£$€]?([\d,]+(?:\.\d+)?)' + r'\s*k?', salary_str)
    if m:
        try:
            lo = float(m.group(1).replace(",", ""))
            hi = float(m.group(2).replace(",", ""))
            # If values look like "40k" (40), multiply up
            if lo < 1000:
                lo *= 1000
            if hi < 1000:
                hi *= 1000
            return lo, hi
        except ValueError:
            pass
    # Single value
    m = re.search(r'[£$€]?([\d,]+(?:\.\d+)?)' + r'\s*k?', salary_str)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if v < 1000:
                v *= 1000
            return v, v
        except ValueError:
            pass
    return None, None


def extract_city(location: str) -> str:
    """Normalise location to a known city name for scoring."""
    loc_n = normalise(location)
    for city in CITY_SCORES:
        if city in loc_n:
            return city
    return ""


def detect_work_type(title: str, description: str, location: str) -> str:
    """Detect work type from text if not already set."""
    combined = normalise(f"{title} {description} {location}")
    if "remote" in combined and "hybrid" not in combined:
        return "Remote"
    if "hybrid" in combined:
        return "Hybrid"
    return "On-site"


def extract_skills(description: str, title: str = "") -> list[str]:
    """Find which desired skills are mentioned in the description/title.
    Uses word-boundary matching so short skills like 'r' don't match inside other words.
    """
    combined = normalise(f"{title} {description}")
    found = []
    for skill in DESIRED_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, combined):
            found.append(skill)
    return found


def score_job(job: JobPosting) -> float:
    """
    Score a job using the new criteria. Max = 100.
    Returns 0 if excluded.
    """
    title_n = normalise(job.title)
    desc_n = normalise(job.description)
    loc_n = normalise(job.location)
    combined_text = f"{title_n} {desc_n}"

    # ── Exclusion check (-50) ──
    for kw in KEYWORDS_EXCLUDE:
        if kw in title_n:
            return 0.0

    # ── Location eligibility ──
    # Country must be United Kingdom ONLY. Anything else is excluded.
    # Remote: anywhere in UK.
    # Hybrid: within ~2 hours commute of Bridgwater (by car or train).
    # Onsite: Bristol-Exeter M5 corridor only.
    country_raw = (job.country or "").strip().lower()
    loc_lower = loc_n.lower()

    # UK country codes — anything NOT in this set is non-UK
    uk_codes = {"uk", "united kingdom", "gb", "england", "scotland", "wales", "northern ireland", ""}

    # UK location words (used to confirm UK when country is blank)
    uk_words = {
        "london", "manchester", "birmingham", "leeds", "liverpool", "bristol", "exeter",
        "edinburgh", "glasgow", "cardiff", "belfast", "sheffield", "nottingham", "newcastle",
        "oxford", "cambridge", "brighton", "southampton", "portsmouth", "bournemouth",
        "reading", "bath", "swindon", "gloucester", "cheltenham", "taunton",
        "weston-super-mare", "bridgwater", "york", "leicester", "coventry", "stoke",
        "wolverhampton", "derby", "peterborough", "norwich", "ipswich", "plymouth",
        "sunderland", "aberdeen", "dundee", "swansea", "newport", "wrexham",
        "canterbury", "lincoln", "colchester", "salisbury", "truro", "bangor",
        "inverness", "stirling", "perth", "worcester", "hereford", "chester",
        "lancaster", "preston", "blackpool", "middlesbrough", "hull", "doncaster",
        "slough", "maidenhead", "bracknell", "windsor",
        "england", "scotland", "wales", "northern ireland",
        "united kingdom", "great britain", "south west", "south east", "midlands",
        "surrey", "kent", "essex", "sussex", "hampshire", "dorset", "devon",
        "cornwall", "somerset", "wiltshire", "gloucestershire", "oxfordshire",
        "berkshire", "buckinghamshire", "hertfordshire", "cambridgeshire",
        "norfolk", "suffolk", "warwickshire", "leicestershire", "nottinghamshire",
        "derbyshire", "staffordshire", "shropshire", "cheshire", "lancashire",
        "yorkshire", "durham", "northumberland", "cumbria",
    }

    # If country field is set and NOT a UK code, exclude immediately
    if country_raw and country_raw not in uk_codes:
        return 0.0

    # If country is blank, location MUST contain a UK location word
    if not country_raw:
        if not any(w in loc_lower for w in uk_words):
            return 0.0

    # Detect work type
    wt = (job.work_type or "").lower()
    if not wt:
        wt = detect_work_type(job.title, job.description, job.location).lower()
        job.work_type = wt.title()

    # Bristol-Exeter M5 corridor cities (for onsite eligibility)
    corridor_cities = [
        "bristol", "exeter", "bath", "swindon", "gloucester", "cheltenham",
        "taunton", "weston-super-mare", "bridgwater", "trowbridge", "chippenham",
        "yeovil", "wells", "stroud", "tewkesbury",
    ]

    is_in_corridor = any(c in loc_lower for c in corridor_cities)

    # Onsite: only allowed in Bristol-Exeter corridor
    if wt in ("onsite", "on-site"):
        if not is_in_corridor:
            return 0.0

    # Hybrid: within ~2 hours commute of Bridgwater
    # ~2h by car: Reading, Oxford, Southampton, Cardiff, Birmingham, etc.
    # ~2h by train: London Paddington (~2h), Reading (~1h)
    hybrid_cities = corridor_cities + [
        "london", "reading", "oxford", "southampton", "portsmouth", "bournemouth",
        "cardiff", "newport", "birmingham", "coventry", "leicester",
        "slough", "maidenhead", "bracknell", "windsor", "salisbury",
        "worcester", "hereford", "warwick", "banbury",
        "warminster", "frome", "devizes", "melksham", "westbury",
    ]
    if wt == "hybrid":
        if not any(c in loc_lower for c in hybrid_cities):
            return 0.0

    score = 0.0
    reasons = []
    detail = {}

    # ── 1. City (max 20) ──
    city = extract_city(job.location)
    city_pts = CITY_SCORES.get(city, 0)
    score += city_pts
    detail["city"] = city_pts
    if city_pts > 0:
        reasons.append(f"{city.title()}: {city_pts}pts")

    # ── 2. Work type (max 20) ──
    wt_pts = WORK_TYPE_SCORES.get(wt, 0)
    score += wt_pts
    detail["work_type"] = wt_pts
    if wt_pts > 0:
        reasons.append(f"{wt}: {wt_pts}pts")

    # ── 3. Salary (max 20) ──
    lo, hi = job.salary_lower, job.salary_upper
    if lo is None and hi is None:
        lo, hi = extract_salary_numeric(job.salary)
        job.salary_lower, job.salary_upper = lo, hi
    salary_pts = 0
    if lo is not None or hi is not None:
        # Use the higher of the two for band matching
        val = hi if hi is not None else (lo or 0)
        for band_lo, band_hi, pts in SALARY_BANDS:
            if band_lo <= val < band_hi:
                salary_pts = pts
                break
        # Also if < 60k from lower bound
        if lo is not None and lo < 60000:
            salary_pts = 0
    score += salary_pts
    detail["salary"] = salary_pts
    if salary_pts > 0:
        reasons.append(f"Salary: {salary_pts}pts")

    # ── 4. Seniority (max 20) ──
    seniority_pts = 0
    for level in SENIORITY_HIGH:
        if level in title_n:
            seniority_pts = 20
            reasons.append(f"Seniority (high): 20pts")
            break
    if seniority_pts == 0:
        for level in SENIORITY_MID:
            if level in title_n:
                seniority_pts = 10
                reasons.append(f"Seniority (mid): 10pts")
                break
    score += seniority_pts
    detail["seniority"] = seniority_pts

    # ── 5. Keyword match (max 20 or -50) ──
    keyword_pts = 0
    for kw, pts in KEYWORD_SCORES.items():
        if kw in title_n:
            keyword_pts = max(keyword_pts, pts)
    if keyword_pts == -50:
        return 0.0
    if keyword_pts == 0:
        # Check description
        for kw, pts in KEYWORD_SCORES.items():
            if kw in desc_n and pts > 0:
                keyword_pts = max(keyword_pts, pts)
    score += keyword_pts
    detail["keyword"] = keyword_pts
    if keyword_pts > 0:
        reasons.append(f"Keyword: {keyword_pts}pts")

    # ── 6. Skills matching ──
    found_skills = extract_skills(desc_n, title_n)
    job.key_skills = found_skills
    matched = []
    for s in found_skills:
        if s in DESIRED_SKILLS:
            matched.append(s)
    job.matched_skills = matched
    job.skills_gap = [s for s in DESIRED_SKILLS if s not in found_skills]

    # Bonus: up to 10 extra points for skills (capped)
    skills_extra = min(len(matched) * 3, 10)
    # But ensure we don't go over 100
    # We'll track this as part of the total cap

    total_before_skills = score
    score += skills_extra
    detail["skills"] = skills_extra
    if skills_extra > 0:
        reasons.append(f"Skills: {skills_extra}pts")

    # ── Cap at 100 ──
    score = min(score, 100.0)

    job.match_score = round(score, 1)
    job.match_reasons = reasons
    job.score_detail = detail
    return job.match_score


def filter_and_rank(jobs: list[JobPosting]) -> list[JobPosting]:
    """
    Score all jobs, exclude those with score 0, sort descending.
    """
    scored = []
    for job in jobs:
        s = score_job(job)
        if s > 0:
            scored.append(job)

    scored.sort(key=lambda j: j.match_score, reverse=True)
    return scored