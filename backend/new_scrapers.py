"""
Additional ATS/job-board scrapers for MOpsWork.
Each returns a list of JobPosting objects.
"""

import re
import json
import logging
import html as html_mod
import urllib.parse
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from backend.filters import JobPosting

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _detect_wt(title: str, desc: str, loc: str) -> str:
    combined = f"{title} {desc} {loc}".lower()
    loc_lower = loc.lower()
    # Location field is most reliable — check it first
    if "remote" in loc_lower:
        return "Remote"
    if "hybrid" in loc_lower:
        return "Hybrid"
    if "remote" in combined and "hybrid" not in combined:
        return "Remote"
    if "hybrid" in combined:
        return "Hybrid"
    return "On-site"


def _extract_salary(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"£[\d,]+(?:k)?\s*[-–to]+\s*£?[\d,]+(?:k)?",
        r"£[\d,]+(?:k)?",
        r"\$[\d,]+(?:k)?\s*[-–to]+\s*\$?[\d,]+(?:k)?",
        r"\$[\d,]+(?:k)?",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None


# ── 1. Greenhouse ──
# Greenhouse has a JSON API at boards-api.greenhouse.io
# We can search via their job board search endpoint.
# No central search exists, but we can try their public job board embed search.

def scrape_greenhouse() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing", "revenue", "revops", "martech"]

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                # Try Greenhouse's public board search
                url = f"https://boards-api.greenhouse.io/v1/boards/embed/jobs?query={urllib.parse.quote(q)}&content=true"
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    logger.info(f"  Greenhouse search returned {resp.status_code} for q={q}, trying board scrape")
                    # Fallback: scrape the main job board page
                    html_url = f"https://www.greenhouse.io/jobs?q={urllib.parse.quote(q)}&remote=true"
                    html_resp = client.get(html_url, headers=HEADERS, follow_redirects=True)
                    if html_resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(html_resp.text, "lxml")
                    for card in soup.select("[class*=job], [data-job-id], article"):
                        title_el = card.find(["h2", "h3", "a", "span"])
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)
                        if not title or len(title) < 5:
                            continue
                        link = card.find("a", href=True) or title_el.find_parent("a")
                        href = link["href"] if link and link.get("href") else ""
                        if href and not href.startswith("http"):
                            href = "https://greenhouse.io" + href
                        text = card.get_text(" ", strip=True)
                        jobs.append(JobPosting(
                            title=title,
                            company="Greenhouse",
                            location="Remote / UK",
                            country="UK",
                            description=text[:1000],
                            url=href or "",
                            source="Greenhouse",
                            work_type=_detect_wt(title, text, "Remote"),
                        ))
                    continue

                data = resp.json()
                for raw in data.get("jobs", []):
                    title = raw.get("title", "")
                    if not title:
                        continue
                    company = raw.get("company", {}).get("name", "Unknown")
                    location = raw.get("location", {}).get("name", "Remote")
                    desc = BeautifulSoup(raw.get("content", ""), "lxml").get_text(" ", strip=True) if raw.get("content") else ""
                    country = "UK" if any(c in location.lower() for c in ["uk", "london", "england", "united kingdom"]) else "Worldwide"

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=desc[:2000],
                        url=raw.get("absolute_url", raw.get("url", "")),
                        source="Greenhouse",
                        salary=_extract_salary(desc),
                        work_type=_detect_wt(title, desc, location),
                    ))

                logger.info(f"  Greenhouse q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Greenhouse error for q={q}: {e}")

    return jobs


# ── 2. Lever ──
# Lever has a public job postings API

def scrape_lever() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing", "revenue operations", "revops", "martech"]
    seen = set()

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                url = f"https://api.lever.co/v1/postings/search?q={urllib.parse.quote(q)}&limit=25"
                resp = client.get(url, headers={**HEADERS, "Accept": "application/json"})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for raw in data.get("data", []):
                    title = raw.get("text", raw.get("title", ""))
                    if not title:
                        continue
                    company = raw.get("company", {}).get("name", "Unknown")
                    location = raw.get("categories", {}).get("location", "Remote")
                    desc = BeautifulSoup(raw.get("description", "") or raw.get("descriptionPlain", ""), "lxml").get_text(" ", strip=True) or raw.get("descriptionPlain", "")
                    if not desc:
                        desc = raw.get("descriptionPlain", "")
                    country = "UK" if any(c in location.lower() for c in ["uk", "london", "england", "united kingdom"]) else "Worldwide"
                    href = raw.get("applyUrl", raw.get("hostedUrl", ""))

                    key = (title.lower(), company.lower())
                    if key in seen:
                        continue
                    seen.add(key)

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location or "Remote",
                        country=country,
                        description=desc[:2000],
                        url=href,
                        source="Lever",
                        salary=_extract_salary(desc),
                        work_type=_detect_wt(title, desc, location or ""),
                    ))
                logger.info(f"  Lever q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Lever error for q={q}: {e}")

    return jobs


# ── 3. Workable ──
# Workable has a job search API

def scrape_workable() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing operations", "revenue operations", "revops", "martech"]

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                url = f"https://jobs.workable.com/api/v1/jobs?query={urllib.parse.quote(q)}&location=united-kingdom&remote=remote&sort=date"
                resp = client.get(url, headers={**HEADERS, "Accept": "application/json"})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for raw in data.get("results", data.get("jobs", [])):
                    title = raw.get("title", "")
                    if not title:
                        continue
                    company = raw.get("company", {}).get("name", raw.get("organization", "Unknown"))
                    location = raw.get("location", {}).get("name", raw.get("location", "Remote"))
                    desc = raw.get("description", "") or ""
                    desc_text = BeautifulSoup(desc, "lxml").get_text(" ", strip=True) if desc else ""
                    country = "UK" if any(c in location.lower() for c in ["uk", "london", "england", "united kingdom"]) else "Worldwide"
                    href = raw.get("url", raw.get("applyUrl", ""))

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=desc_text[:2000] or title,
                        url=href,
                        source="Workable",
                        salary=_extract_salary(desc_text),
                        work_type=_detect_wt(title, desc_text, location),
                    ))
                logger.info(f"  Workable q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Workable error for q={q}: {e}")

    return jobs


# ── 4. Bebee (UK job aggregator) ──

def scrape_bebee() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing+operations", "revenue+operations", "revops", "martech"]

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            try:
                url = f"https://uk.bebee.com/jobs?term={q}&remote=true"
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "lxml")
                for card in soup.select("article, [class*=job], li[class*=job]"):
                    link = card.find("a", href=True)
                    if not link:
                        continue
                    href = link["href"]
                    if not href.startswith("http"):
                        href = "https://uk.bebee.com" + href

                    title_el = card.find(["h2", "h3", "h4", "strong"])
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue

                    text = card.get_text(" ", strip=True)
                    company = "Unknown"
                    # Company often appears after the title
                    for line in text.split("·"):
                        line = line.strip()
                        if line and line != title and len(line) < 60:
                            company = line
                            break

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location="UK",
                        country="UK",
                        description=text[:1000],
                        url=href,
                        source="Bebee",
                        work_type=_detect_wt(title, text, "UK"),
                    ))
                logger.info(f"  Bebee q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Bebee error for q={q}: {e}")

    return jobs


# ── 5. Ashby ──
# Ashby has a public API for job listings

def scrape_ashby() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing operations", "revenue operations", "revops", "martech"]

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                # Ashby uses a GraphQL-like API
                url = "https://jobs.ashbyhq.com/api/non-user-posting-listing"
                payload = {
                    "search": q,
                    "location": "United Kingdom",
                    "remote": True,
                    "limit": 30,
                }
                resp = client.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for raw in data.get("postings", []):
                    title = raw.get("title", "")
                    if not title:
                        continue
                    company = raw.get("company", {}).get("name", raw.get("organization", "Unknown"))
                    location = raw.get("location", raw.get("address", {}).get("locality", "Remote"))
                    desc = BeautifulSoup(raw.get("descriptionHtml", raw.get("description", "")), "lxml").get_text(" ", strip=True) if raw.get("descriptionHtml") else raw.get("description", "")
                    country = "UK" if any(c in location.lower() for c in ["uk", "london", "england", "united kingdom"]) else "Worldwide"
                    href = raw.get("applyUrl", raw.get("url", ""))

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=desc[:2000] if desc else title,
                        url=href,
                        source="Ashby",
                        salary=_extract_salary(desc or ""),
                        work_type=_detect_wt(title, desc or "", location),
                    ))
                logger.info(f"  Ashby q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Ashby error for q={q}: {e}")

    return jobs


# ── 6. Comeet ──

def scrape_comeet() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing", "revenue", "operations", "revops"]

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                url = f"https://www.comeet.com/rt/aj/search?q={urllib.parse.quote(q)}&remote=true&location=United+Kingdom"
                resp = client.get(url, headers={**HEADERS, "Accept": "application/json"})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for raw in data.get("results", data.get("jobs", [])):
                    title = raw.get("title", raw.get("position", ""))
                    if not title:
                        continue
                    company = raw.get("company", {}).get("name", raw.get("organization", "Unknown"))
                    location = raw.get("location", raw.get("city", "Remote"))
                    desc = raw.get("description", raw.get("details", ""))
                    desc_text = BeautifulSoup(desc, "lxml").get_text(" ", strip=True) if desc else ""
                    country = "UK" if any(c in location.lower() for c in ["uk", "london", "england", "united kingdom"]) else "Worldwide"
                    href = raw.get("url", raw.get("apply_url", ""))

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=desc_text[:2000] or title,
                        url=href,
                        source="Comeet",
                        salary=_extract_salary(desc_text),
                        work_type=_detect_wt(title, desc_text, location),
                    ))
                logger.info(f"  Comeet q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Comeet error for q={q}: {e}")

    return jobs


# ── 7. Jobvite ──

def scrape_jobvite() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing", "revenue", "operations", "revops"]

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                url = f"https://www.jobvite.com/jobs/api/v1/search?q={urllib.parse.quote(q)}&location=UK&remote=true"
                resp = client.get(url, headers={**HEADERS, "Accept": "application/json"})
                if resp.status_code != 200:
                    # Fallback to scrape
                    html_url = f"https://www.jobvite.com/jobs/?q={urllib.parse.quote(q)}"
                    html_resp = client.get(html_url, headers=HEADERS, follow_redirects=True)
                    if html_resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(html_resp.text, "lxml")
                    for card in soup.select("[class*=job], tr, [class*=position]"):
                        link = card.find("a", href=True)
                        if not link:
                            continue
                        title = link.get_text(strip=True) or card.find(["h2", "h3", "strong"])
                        title = title.get_text(strip=True) if hasattr(title, "get_text") else str(title)
                        if not title or len(title) < 5:
                            continue
                        href = link["href"]
                        if href and not href.startswith("http"):
                            href = "https://jobvite.com" + href
                        text = card.get_text(" ", strip=True)
                        jobs.append(JobPosting(
                            title=title,
                            company="Jobvite",
                            location="Remote / UK",
                            country="UK",
                            description=text[:1000],
                            url=href,
                            source="Jobvite",
                            work_type=_detect_wt(title, text, "UK"),
                        ))
                    continue

                data = resp.json()
                for raw in data.get("jobs", data.get("results", [])):
                    title = raw.get("title", raw.get("position", ""))
                    if not title:
                        continue
                    company = raw.get("company", raw.get("organization", "Unknown"))
                    location = raw.get("location", raw.get("city", "Remote"))
                    desc = raw.get("description", raw.get("details", ""))
                    desc_text = BeautifulSoup(desc, "lxml").get_text(" ", strip=True) if desc else ""
                    country = "UK" if any(c in location.lower() for c in ["uk", "london", "england", "united kingdom"]) else "Worldwide"
                    href = raw.get("url", raw.get("applyUrl", ""))

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=desc_text[:2000] or title,
                        url=href,
                        source="Jobvite",
                        salary=_extract_salary(desc_text),
                        work_type=_detect_wt(title, desc_text, location),
                    ))
                logger.info(f"  Jobvite q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Jobvite error for q={q}: {e}")

    return jobs


# ── 8. Teamtailor ──
# Teamtailor has a public API available at api.teamtailor.com
# But it requires an API key. We'll try their main job search page.

def scrape_teamtailor() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = ["marketing operations", "revenue operations", "revops", "martech"]

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            try:
                url = f"https://www.teamtailor.com/jobs?q={urllib.parse.quote(q)}&remote=true"
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "lxml")
                for card in soup.select("[class*=job], [data-job-id], article"):
                    link = card.find("a", href=True)
                    if not link:
                        continue
                    href = link["href"]
                    if not href.startswith("http"):
                        href = "https://teamtailor.com" + href

                    title_el = card.find(["h2", "h3", "strong", "span"])
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue

                    text = card.get_text(" ", strip=True)
                    company = "Unknown"
                    for line in text.split("·"):
                        line = line.strip()
                        if line and line != title and len(line) < 50:
                            company = line
                            break

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location="Remote / UK",
                        country="UK",
                        description=text[:1000],
                        url=href,
                        source="Teamtailor",
                        work_type=_detect_wt(title, text, "Remote"),
                    ))
                logger.info(f"  Teamtailor q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"  Teamtailor error for q={q}: {e}")

    return jobs


# ── 9. Greenhouse-specific boards (target companies) ──
# Greenhouse has a reliable JSON API for each company board.
# This catches jobs that the generic Greenhouse search doesn't find.

GREENHOUSE_BOARDS = {
    "Exclaimer": "exclaimer",
    "Poka EU": "pokaeu",
    # Add more target Greenhouse boards here
}

def scrape_greenhouse_boards() -> list[JobPosting]:
    """Scrape specific Greenhouse company boards using their JSON API."""
    jobs: list[JobPosting] = []

    with httpx.Client(timeout=20.0) as client:
        for company, board in GREENHOUSE_BOARDS.items():
            try:
                url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    logger.warning(f"  Greenhouse board {board} returned {resp.status_code}")
                    continue

                data = resp.json()
                for raw in data.get("jobs", []):
                    title = raw.get("title", "").strip()
                    if not title:
                        continue

                    location = raw.get("location", {}).get("name", "UK") or "UK"
                    loc_lower = location.lower()
                    # Only include UK/EU roles
                    if not any(c in loc_lower for c in
                               ["uk", "united kingdom", "london", "england",
                                "scotland", "wales", "northern ireland",
                                "ireland", "europe", "germany", "france",
                                "remote"]):
                        continue

                    # Fetch full job details including description
                    description = ""
                    salary = None
                    work_type = None
                    try:
                        job_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{raw['id']}"
                        job_resp = client.get(job_url, headers=HEADERS)
                        if job_resp.status_code == 200:
                            job_data = job_resp.json()
                            desc_html = job_data.get("content", "")
                            if desc_html:
                                description = BeautifulSoup(desc_html, "lxml").get_text(" ", strip=True)[:2000]
                            # Check metadata for work type / salary
                            for meta in job_data.get("metadata", []) or []:
                                meta_name = (meta.get("name") or "").lower()
                                meta_val = (meta.get("value") or "")
                                if "remote" in meta_name or "work" in meta_name or "hybrid" in meta_name:
                                    work_type = meta_val
                    except Exception as e:
                        logger.debug(f"  Greenhouse board {board} job {raw['id']} detail fetch: {e}")

                    if not description:
                        description = f"{title} at {company}. Location: {location}."

                    # Determine country — prefer UK if mentioned in location, even if other countries are also present
                    country = "UK" if any(c in loc_lower for c in
                                           ["uk", "united kingdom", "london", "england",
                                            "scotland", "wales", "northern ireland",
                                            "britain"]) else "Worldwide"

                    if not work_type:
                        work_type = _detect_wt(title, description, location)

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=description,
                        url=raw.get("absolute_url", ""),
                        source="Greenhouse",
                        salary=_extract_salary(description),
                        work_type=work_type,
                    ))

                logger.info(f"  Greenhouse board {board}: {len([j for j in jobs if j.company == company])} jobs")
            except Exception as e:
                logger.warning(f"  Greenhouse board {board} error: {e}")

    return jobs


# ── 10. JobScore (applytojob.com) scraper ──
# Used by Improvado and other companies.

JOBSCORE_COMPANIES = {
    "Improvado": "https://improvado.applytojob.com/apply/",
    # Add more JobScore companies here
}

def scrape_jobscore() -> list[JobPosting]:
    """Scrape JobScore ATS career pages (used by Improvado et al.)."""
    jobs: list[JobPosting] = []

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for company, url in JOBSCORE_COMPANIES.items():
            try:
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    logger.warning(f"  JobScore {company} returned {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")

                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    if not href.startswith("https://improvado.applytojob.com/apply/") and \
                       not href.startswith("/apply/"):
                        continue
                    if href.startswith("/"):
                        href = f"https://improvado.applytojob.com{href}"

                    title = link.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue

                    # Location is usually in a sibling or parent element
                    parent = link.find_parent(["li", "div", "tr"])
                    location = "Remote"
                    if parent:
                        text = parent.get_text(" ", strip=True)
                        # Try to find location info
                        for line in text.split("\n"):
                            line = line.strip()
                            if line and line != title and len(line) < 50:
                                parts = line.split("·")
                                for part in parts:
                                    pt = part.strip()
                                    if pt and pt not in title and len(pt) < 40:
                                        location = pt
                                        break

                    # Determine country
                    loc_lower = location.lower()
                    if any(c in loc_lower for c in ["uk", "united kingdom", "london", "england", "britain", "europe"]):
                        country = "UK"
                    elif "remote" in loc_lower or "anywhere" in loc_lower:
                        country = "UK"  # Treat remote as eligible for UK
                    else:
                        country = loc_lower.strip() or "Worldwide"

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=f"{title} at {company}. Location: {location}.",
                        url=href,
                        source="JobScore",
                        work_type="Remote" if "remote" in loc_lower else "On-site",
                    ))

                logger.info(f"  JobScore {company}: {len([j for j in jobs if j.company == company])} jobs")
            except Exception as e:
                logger.warning(f"  JobScore {company} error: {e}")

    return jobs


# ── 11. Direct company careers page scraper ──
# For companies that don't use a standard ATS, scrape their careers page directly.

COMPANY_CAREERS_URLS = [
    # Add direct career page URLs here as needed
    # Format: (company_name, careers_url)
]


def scrape_company_careers() -> list[JobPosting]:
    """Scrape direct company careers pages for non-standard ATS."""
    jobs: list[JobPosting] = []

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for company, url in COMPANY_CAREERS_URLS:
            try:
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "lxml")

                # Try to find job listings using common patterns
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    title = link.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue

                    # Look for keywords in the link text
                    title_lower = title.lower()
                    marketing_keywords = ["marketing", "revenue", "revops", "operations", "gtm",
                                          "growth", "sales operations", "marketing ops"]
                    if not any(kw in title_lower for kw in marketing_keywords):
                        continue

                    if href.startswith("/"):
                        from urllib.parse import urlparse
                        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                        href = base + href
                    elif not href.startswith("http"):
                        from urllib.parse import urljoin
                        href = urljoin(url, href)

                    parent = link.find_parent(["li", "div", "article", "tr", "section"])
                    text = parent.get_text(" ", strip=True) if parent else title

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location="UK",
                        country="UK",
                        description=text[:1000],
                        url=href,
                        source="CompanyCareers",
                        work_type=_detect_wt(title, text, "UK"),
                    ))

                logger.info(f"  CompanyCareers {company}: {len([j for j in jobs if j.company == company])} jobs")
            except Exception as e:
                logger.warning(f"  CompanyCareers {company} error: {e}")

    return jobs


# ── Master function ──

ALL_NEW_SOURCES = [
    ("Greenhouse", scrape_greenhouse),
    ("Lever", scrape_lever),
    ("Workable", scrape_workable),
    ("Bebee", scrape_bebee),
    ("Ashby", scrape_ashby),
    ("Comeet", scrape_comeet),
    ("Jobvite", scrape_jobvite),
    ("Teamtailor", scrape_teamtailor),
    ("GreenhouseBoards", scrape_greenhouse_boards),
    ("JobScore", scrape_jobscore),
    ("CompanyCareers", scrape_company_careers),
]


def scrape_new_sources() -> list[JobPosting]:
    """Run all new ATS scrapers and return combined results."""
    logger.info("Starting new sources scrape...")
    all_jobs: list[JobPosting] = []

    for name, fn in ALL_NEW_SOURCES:
        try:
            logger.info(f"  -> scraping {name}...")
            results = fn()
            logger.info(f"     {name}: {len(results)} jobs found")
            all_jobs.extend(results)
        except Exception as e:
            logger.error(f"     {name} failed: {e}")

    logger.info(f"Total from new sources: {len(all_jobs)}")
    return all_jobs