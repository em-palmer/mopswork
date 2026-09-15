"""
Multi-source job scraper for MOpsWork.
Each source returns a list of JobPosting objects.
"""

import re
import json
import logging
import time
import urllib.parse
from typing import Optional
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from backend.filters import JobPosting
from backend.config import (
    ADZUNA_APP_ID, ADZUNA_API_KEY, JOOBLE_API_KEY, CAREERJET_API_KEY,
    target_company_url, TARGET_COMPANY_SITES,
    SCRAPINGDOG_API_KEY, SCRAPINGBEE_API_KEY, JSEARCH_API_KEY, SCRAPFLY_API_KEY,
)
from backend.new_scrapers import scrape_new_sources, GREENHOUSE_BOARDS, LEVER_BOARDS, ASHBY_BOARDS

logger = logging.getLogger(__name__)

# ---------- helpers ----------

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


def extract_salary(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"£[\d,]+(?:k)?\s*[-–to]+\s*£?[\d,]+(?:k)?",
        r"£[\d,]+(?:k)?",
        r"\$[\d,]+(?:k)?\s*[-–to]+\s*\$?[\d,]+(?:k)?",
        r"\$[\d,]+(?:k)?",
        r"€[\d,]+(?:k)?\s*[-–to]+\s*€?[\d,]+(?:k)?",
        r"€[\d,]+(?:k)?",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None


def detect_work_type_from_text(title: str, description: str, location: str) -> str:
    combined = f"{title} {description} {location}".lower()
    if "remote" in combined and "hybrid" not in combined:
        return "Remote"
    if "hybrid" in combined:
        return "Hybrid"
    return "On-site"


# ---------- Source 1: Adzuna API (UK) ----------

BOARD_QUERIES = [
    "marketing operations",
    "revenue operations",
    "revops",
    "marketing automation",
    "martech",
    "gtm engineer",
    "marketing analytics",
    "data operations",
    "sales operations",
]


def scrape_adzuna() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    app_id = ADZUNA_APP_ID
    api_key = ADZUNA_API_KEY
    if not app_id or not api_key:
        logger.warning("Adzuna: no API keys configured, skipping (set ADZUNA_APP_ID and ADZUNA_API_KEY on Render)")
        return jobs

    seen = set()
    with httpx.Client(timeout=20.0) as client:
        for q in BOARD_QUERIES:
            for page in (1, 2, 3):
                try:
                    url = (
                        f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
                        f"?app_id={app_id}&app_key={api_key}"
                        f"&what={urllib.parse.quote_plus(q)}"
                        f"&results_per_page=50&content-type=application/json"
                        f"&sort_by=date&max_days_old=7"
                    )
                    resp = client.get(url, headers={"Accept": "application/json"})
                    if resp.status_code != 200:
                        logger.warning(f"Adzuna returned {resp.status_code} for q={q} page={page}")
                        break
                    data = resp.json()
                    results = data.get("results") or []
                    if not results:
                        break
                    for raw in results:
                        title = raw.get("title", "")
                        if not title:
                            continue
                        company = (raw.get("company") or {}).get("display_name", "Unknown")
                        key = (title.strip().lower(), company.strip().lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        location = (raw.get("location") or {}).get("display_name", "") or ""
                        description = (raw.get("description") or "")[:2000]
                        salary_min = raw.get("salary_min")
                        salary_max = raw.get("salary_max")
                        salary_str = None
                        if salary_min or salary_max:
                            lo = int(salary_min) if salary_min else None
                            hi = int(salary_max) if salary_max else None
                            if lo and hi:
                                salary_str = f"£{lo:,} - £{hi:,}"
                            elif lo:
                                salary_str = f"£{lo:,}"
                        jobs.append(JobPosting(
                            title=title, company=company,
                            location=location, country="UK",
                            description=description, url=raw.get("redirect_url", ""),
                            source="Adzuna", salary=salary_str,
                            posted_date=raw.get("created"),
                            work_type=detect_work_type_from_text(title, description, location),
                            company_url=target_company_url(company),
                        ))
                    logger.info(f"  Adzuna q={q} page={page}: {len(results)} jobs")
                except Exception as e:
                    logger.warning(f"Adzuna error for q={q} page={page}: {e}")
                    break

    logger.info(f"  Adzuna total: {len(jobs)} unique jobs")
    return jobs


# ---------- Source 2: Arbeitnow (free, no auth, Europe/remote) ----------

def scrape_arbeitnow() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    try:
        resp = httpx.get(
            "https://arbeitnow.com/api/job-board-api",
            params={"visa_sponsorship": "false"},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning(f"Arbeitnow returned {resp.status_code}")
            return jobs
        data = resp.json()
        for raw in data.get("data", []):
            title = raw.get("title", "")
            if not title:
                continue
            company = raw.get("company_name", "Unknown")
            location = raw.get("location", "Remote") or "Remote"
            description = raw.get("description", "")[:2000]
            tags = " ".join(raw.get("tags", []))
            combined_text = f"{title} {description} {tags}".lower()
            # Only keep roles relevant to marketing/revenue ops
            relevant_kw = ["marketing", "revenue", "revops", "operations", "gtm",
                           "martech", "analytics", "data", "automation", "growth"]
            if not any(kw in combined_text for kw in relevant_kw):
                continue

            country = ""
            loc_lower = location.lower()
            if any(c in loc_lower for c in ["uk", "london", "england", "united kingdom", "britain"]):
                country = "UK"
            elif "remote" in loc_lower or "anywhere" in loc_lower:
                country = ""
            else:
                country = "Worldwide"

            salary = raw.get("salary", "")
            if isinstance(salary, (int, float)):
                salary = f"£{int(salary):,}" if salary else None

            jobs.append(JobPosting(
                title=title, company=company,
                location=location, country=country,
                description=description, url=raw.get("url", ""),
                source="Arbeitnow", salary=str(salary) if salary else None,
                posted_date=raw.get("created_at", ""),
                work_type="Remote" if raw.get("remote") else detect_work_type_from_text(title, description, location),
            ))
        logger.info(f"  Arbeitnow: {len(jobs)} jobs found")
    except Exception as e:
        logger.warning(f"Arbeitnow error: {e}")
    return jobs


# ---------- Source 3: Jooble API (free key, UK jobs) ----------

def scrape_jooble() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    api_key = JOOBLE_API_KEY
    if not api_key:
        logger.info("Jooble: no API key configured, skipping")
        return jobs

    queries = [
        "marketing operations", "revenue operations", "revops", "marketing automation",
        "martech", "marketing analytics", "data operations", "gtm engineer",
        "business automation", "marketing data analyst", "agentops",
    ]

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                resp = client.post(
                    f"https://jooble.org/api/{api_key}",
                    json={"keywords": q, "location": "United Kingdom"},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning(f"Jooble returned {resp.status_code} for q={q}")
                    continue
                data = resp.json()
                for raw in data.get("jobs", [])[:50]:
                    title = raw.get("title", "")
                    if not title:
                        continue
                    company = raw.get("company", "Unknown")
                    location = raw.get("location", "UK")
                    snippet = raw.get("snippet", "")
                    salary = raw.get("salary", "")
                    if salary and "£" not in salary:
                        salary = None

                    jobs.append(JobPosting(
                        title=title, company=company,
                        location=location, country="UK",
                        description=snippet[:2000], url=raw.get("link", ""),
                        source="Jooble", salary=salary,
                        posted_date=raw.get("updated", ""),
                        work_type=detect_work_type_from_text(title, snippet, location),
                    ))
                logger.info(f"  Jooble q={q}: {len(data.get('jobs', []))} jobs found")
            except Exception as e:
                logger.warning(f"Jooble error for q={q}: {e}")

    return jobs


# ---------- Source 4: Careerjet API (free non-commercial, UK) ----------

def scrape_careerjet() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    api_key = CAREERJET_API_KEY
    if not api_key:
        logger.info("Careerjet: no API key configured, skipping")
        return jobs

    queries = [
        "marketing operations", "revenue operations", "revops", "marketing automation",
        "martech", "marketing analytics", "data operations", "gtm engineer",
    ]

    with httpx.Client(timeout=20.0) as client:
        for q in queries:
            try:
                url = (
                    f"https://search.api.careerjet.net/v4/query"
                    f"?locale_code=en_GB&keywords={urllib.parse.quote(q)}"
                    f"&affid={api_key}&user_ip=0.0.0.0"
                    f"&user_agent={urllib.parse.quote(USER_AGENT)}"
                    f"&pagesize=50&sort=date"
                )
                resp = client.get(url, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    logger.warning(f"Careerjet returned {resp.status_code} for q={q}")
                    continue
                data = resp.json()
                if data.get("type") != "JOBS":
                    continue
                for raw in data.get("jobs", []):
                    title = raw.get("title", "")
                    if not title:
                        continue
                    company = raw.get("company", "Unknown")
                    locations = raw.get("locations", "UK")
                    salary = raw.get("salary", "")
                    description = raw.get("description", "")[:2000]

                    jobs.append(JobPosting(
                        title=title, company=company,
                        location=locations, country="UK",
                        description=description, url=raw.get("url", ""),
                        source="Careerjet", salary=salary if salary else None,
                        posted_date=raw.get("date", ""),
                        work_type=detect_work_type_from_text(title, description, locations),
                    ))
                logger.info(f"  Careerjet q={q}: {len(data.get('jobs', []))} jobs found")
            except Exception as e:
                logger.warning(f"Careerjet error for q={q}: {e}")

    return jobs


# ---------- Source 5: Improved LinkedIn Guest API with better reliability ----------

def scrape_linkedin() -> list[JobPosting]:
    """LinkedIn guest job search, last 7 days, UK."""
    jobs: list[JobPosting] = []
    ats_covered = set(GREENHOUSE_BOARDS) | set(LEVER_BOARDS) | set(ASHBY_BOARDS)
    company_queries = [
        name for name in TARGET_COMPANY_SITES
        if name not in ats_covered
    ]
    searches = [(q, 50) for q in BOARD_QUERIES] + [(name, 25) for name in company_queries]
    seen_urls = set()

    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for q, max_start in searches:
            for start in range(0, max_start, 25):
                try:
                    url = (
                        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                        f"?keywords={urllib.parse.quote(q)}"
                        f"&location=United%20Kingdom"
                        f"&f_TPR=r604800"
                        f"&sortBy=DD"
                        f"&start={start}"
                    )
                    resp = client.get(url, headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-GB,en;q=0.9",
                        "Referer": "https://uk.linkedin.com/jobs",
                    })
                    if resp.status_code != 200:
                        logger.warning(f"LinkedIn returned {resp.status_code} for q={q}, start={start}")
                        break

                    soup = BeautifulSoup(resp.text, "lxml")
                    cards = soup.select("div.base-card, div.base-search-card")
                    if not cards:
                        break
                    cards_found = 0
                    for card in cards:
                        link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
                        if not link_el or not link_el.get("href"):
                            continue
                        href = link_el["href"].split("?")[0]
                        if href in seen_urls:
                            continue
                        seen_urls.add(href)
                        cards_found += 1

                        title_el = card.select_one("h3.base-search-card__title, h3")
                        title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)
                        if not title or len(title) < 5:
                            continue
                        company_el = card.select_one("h4.base-search-card__subtitle, h4")
                        company = company_el.get_text(strip=True) if company_el else "Unknown"
                        loc_el = card.select_one("span.job-search-card__location")
                        location = loc_el.get_text(strip=True) if loc_el else "United Kingdom"
                        time_el = card.select_one("time")
                        posted = time_el.get("datetime") if time_el else None
                        if not posted and time_el:
                            posted = time_el.get_text(strip=True)
                        full_text = card.get_text(" ", strip=True)

                        jobs.append(JobPosting(
                            title=title, company=company,
                            location=location, country="UK",
                            description=full_text[:1000], url=href,
                            source="LinkedIn",
                            posted_date=posted,
                            work_type=detect_work_type_from_text(title, full_text, location),
                            company_url=target_company_url(company),
                        ))

                    logger.info(f"  LinkedIn q={q}, start={start}: {cards_found} cards")
                    if cards_found == 0:
                        break
                    time.sleep(0.35)
                except Exception as e:
                    logger.warning(f"LinkedIn error for q={q}, start={start}: {e}")
                    break

    seen = set()
    unique = []
    for j in jobs:
        key = (j.title.lower(), j.company.lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)
    logger.info(f"  LinkedIn total: {len(unique)} unique jobs")
    return unique


# ---------- Remaining sources ----------

def scrape_we_work_remotely() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    urls = [
        "https://weworkremotely.com/categories/remote-marketing-jobs",
        "https://weworkremotely.com/categories/remote-business-and-management-jobs",
    ]

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "lxml")
                for article in soup.select("li article"):
                    title_el = article.select_one("span.title")
                    company_el = article.select_one("span.company")
                    link_el = article.find("a", href=True)
                    if not title_el or not company_el or not link_el:
                        continue
                    href = link_el["href"]
                    if href.startswith("/"):
                        href = "https://weworkremotely.com" + href
                    item_text = article.get_text(" ", strip=True)
                    location = "Remote Worldwide" if "anywhere" in item_text.lower() else "Remote"

                    jobs.append(JobPosting(
                        title=title_el.get_text(strip=True),
                        company=company_el.get_text(strip=True),
                        location=location,
                        country="Worldwide",
                        description=item_text,
                        url=href,
                        source="WeWorkRemotely",
                        work_type="Remote",
                        company_url=None,
                    ))
            except Exception as e:
                logger.warning(f"WeWorkRemotely error: {e}")
    return jobs


# ---------- Source 6: Remote OK API ----------

def scrape_remote_ok() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get("https://remoteok.com/api", headers={**HEADERS, "Accept": "application/json"})
            if resp.status_code != 200:
                return jobs
            data = resp.json()
            for raw in data:
                if not isinstance(raw, dict):
                    continue
                title = raw.get("position", "")
                company = raw.get("company", "")
                location = raw.get("location", "Remote")
                country = "Worldwide" if location.lower() in ("remote", "anywhere") else location
                description = BeautifulSoup(raw.get("description", ""), "lxml").get_text(" ", strip=True)
                company_url = raw.get("company_url") or raw.get("url") or None

                jobs.append(JobPosting(
                    title=title,
                    company=company,
                    location=location,
                    country=country,
                    description=description[:2000],
                    url=raw.get("url", ""),
                    source="RemoteOK",
                    salary=extract_salary(description),
                    posted_date=raw.get("date"),
                    work_type="Remote",
                    company_url=company_url,
                ))
    except Exception as e:
        logger.warning(f"RemoteOK error: {e}")
    return jobs


# ---------- Source 7: Jobicy API ----------

def scrape_jobicy() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    categories = ["marketing"]
    with httpx.Client(timeout=20.0) as client:
        for cat in categories:
            try:
                url = f"https://jobicy.com/api/v2/remote-jobs?count=20&industry={cat}&geo=uk"
                resp = client.get(url, headers={"User-Agent": USER_AGENT})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for raw in data.get("jobs", []):
                    title = raw.get("jobTitle", "")
                    company = raw.get("companyName", "")
                    locations = raw.get("jobGeo", "")
                    description = BeautifulSoup(raw.get("jobExcerpt", "") or raw.get("jobDescription", ""), "lxml").get_text(" ", strip=True)
                    company_url = raw.get("companyURL") or raw.get("companyUrl") or None

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=locations or "Remote",
                        country="Worldwide" if "remote" in locations.lower() else "UK",
                        description=description[:2000],
                        url=raw.get("url", raw.get("jobURL", "")),
                        source="Jobicy",
                        salary=extract_salary(description),
                        posted_date=raw.get("pubDate"),
                        work_type="Remote",
                        company_url=company_url,
                    ))
            except Exception as e:
                logger.warning(f"Jobicy error: {e}")
    return jobs


# ---------- Source 8: Google for Jobs (via SerpAPI) ----------

def scrape_google_jobs() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = [
        "marketing+operations+UK+remote",
        "revenue+operations+UK",
        "marketing+automation+UK+remote",
        "revops+UK",
        "martech+UK+remote",
    ]

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            try:
                url = f"https://www.google.com/search?q={q}&ibp=htl;jobs&hl=en-GB"
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "lxml")
                for script in soup.select("script[type='application/ld+json']"):
                    try:
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            items = data.get("itemListElement", [data])
                            for item in items:
                                if isinstance(item, dict):
                                    job_data = item.get("item", item)
                                    title = job_data.get("title", "")
                                    if not title:
                                        continue
                                    company = job_data.get("hiringOrganization", {}).get("name", "Unknown")
                                    company_url = job_data.get("hiringOrganization", {}).get("url") or None
                                    location = job_data.get("jobLocation", {})
                                    loc_str = ""
                                    country = ""
                                    if isinstance(location, dict):
                                        loc_str = location.get("address", {}).get("addressLocality", "")
                                        country = location.get("address", {}).get("addressCountry", "")
                                    elif isinstance(location, list):
                                        for l in location:
                                            loc_str += l.get("address", {}).get("addressLocality", "") + " "
                                            country = l.get("address", {}).get("addressCountry", "")
                                    desc = BeautifulSoup(job_data.get("description", ""), "lxml").get_text(" ", strip=True)

                                    jobs.append(JobPosting(
                                        title=title,
                                        company=company,
                                        location=loc_str.strip() or "Remote",
                                        country=country or "UK",
                                        description=desc[:2000],
                                        url=job_data.get("url", ""),
                                        source="GoogleJobs",
                                        salary=job_data.get("baseSalary", {}).get("value", {}).get("value"),
                                        posted_date=job_data.get("datePosted"),
                                        work_type=detect_work_type_from_text(title, desc, loc_str),
                                        company_url=company_url,
                                    ))
                    except (json.JSONDecodeError, AttributeError):
                        continue
            except Exception as e:
                logger.warning(f"GoogleJobs error: {e}")
    return jobs


# ---------- Source 9: RevOps Roles (SSR scrape) ----------

def scrape_revops_roles() -> list[JobPosting]:
    """RevOps Roles JSON API — UK/London, dates from posted_at."""
    jobs: list[JobPosting] = []
    seen_ids = set()

    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for q in ("united kingdom", "london"):
            for page in range(1, 5):
                try:
                    url = (
                        "https://revopsroles.com/api/jobs"
                        f"?q={urllib.parse.quote(q)}&hitsPerPage=50&page={page}"
                    )
                    resp = client.get(url, headers={**HEADERS, "Accept": "application/json"})
                    if resp.status_code != 200:
                        logger.warning(f"RevOpsRoles API returned {resp.status_code} for q={q} page={page}")
                        break
                    data = resp.json() or {}
                    hits = data.get("hits") or []
                    if not hits:
                        break
                    for raw in hits:
                        job_id = raw.get("id")
                        if job_id in seen_ids:
                            continue
                        seen_ids.add(job_id)
                        title = (raw.get("title") or "").strip()
                        if not title:
                            continue
                        company = raw.get("company_name") or "Unknown"
                        location = raw.get("location_raw") or raw.get("location_city") or "Remote"
                        countries = [c.lower() for c in (raw.get("location_countries") or []) if c]
                        country_code = (raw.get("location_country") or "").upper()
                        loc_l = str(location).lower()
                        if country_code in ("GB", "UK") or "gb" in countries or "uk" in loc_l or "united kingdom" in loc_l or "london" in loc_l:
                            country = "UK"
                        else:
                            country = "Worldwide"
                        salary = None
                        lo, hi = raw.get("salary_min"), raw.get("salary_max")
                        cur = raw.get("salary_currency") or "GBP"
                        if lo or hi:
                            salary = f"{cur} {int(lo) if lo else ''}-{int(hi) if hi else ''}".strip("- ")
                        posted = raw.get("posted_at") or raw.get("created_at")
                        if posted is not None:
                            posted = str(posted)
                        href = raw.get("source_url") or f"https://revopsroles.com/jobs/{job_id}"
                        desc = f"{raw.get('category') or ''} role. {title} at {company}. Location: {location}."
                        jobs.append(JobPosting(
                            title=title,
                            company=company,
                            location=str(location),
                            country=country,
                            description=desc,
                            url=href,
                            source="RevOpsRoles",
                            salary=salary,
                            posted_date=posted,
                            work_type=(raw.get("work_mode") or "On-site").title(),
                            company_url=raw.get("company_website_url") or target_company_url(company),
                        ))
                    logger.info(f"  RevOpsRoles q={q} page={page}: {len(hits)} hits")
                    if page >= int(data.get("totalPages") or 1):
                        break
                except Exception as e:
                    logger.warning(f"RevOpsRoles error q={q} page={page}: {e}")
                    break

    logger.info(f"  RevOpsRoles total: {len(jobs)} unique jobs")
    return jobs


# ---------- Source 10: Welcome to the Jungle ----------

def scrape_wttj() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = [
        "marketing operations",
        "revenue operations",
        "revops",
        "marketing automation",
        "martech",
    ]

    api_url = "https://www.welcometothejungle.com/api/v2/jobs"

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            try:
                params = {
                    "query": q,
                    "aroundQuery": "United Kingdom",
                    "page": 1,
                    "perPage": 30,
                    "remote": "all",
                    "contractType": ["permanent", "full_time"],
                }
                resp = client.get(api_url, params=params, headers={
                    **HEADERS,
                    "Accept": "application/json",
                    "Referer": "https://www.welcometothejungle.com/en/jobs",
                })
                if resp.status_code == 200:
                    data = resp.json()
                    for raw in data.get("data", []):
                        title = raw.get("name", raw.get("job_name", ""))
                        if not title:
                            continue
                        company_data = raw.get("company", {}) or raw.get("organization", {})
                        company = company_data.get("name", "Unknown")
                        company_url = company_data.get("url") or company_data.get("website_url") or None
                        location_data = raw.get("location", raw.get("office", {}))
                        location = location_data.get("city", "")
                        country_code = location_data.get("country", "UK")
                        description = raw.get("description", raw.get("job_description", ""))
                        desc_text = BeautifulSoup(description, "lxml").get_text(" ", strip=True) if description else ""

                        country_map = {"GB": "UK", "FR": "France", "US": "US", "DE": "Germany"}
                        country = country_map.get(country_code, country_code)

                        work_type = raw.get("remote_status", raw.get("remotify", ""))
                        if isinstance(work_type, str):
                            work_type = work_type.replace("_", " ").title() if work_type else None

                        jobs.append(JobPosting(
                            title=title,
                            company=company,
                            location=location or "UK",
                            country=country,
                            description=desc_text[:2000],
                            url=raw.get("url", raw.get("job_url", "")),
                            source="WTTJ",
                            salary=extract_salary(desc_text),
                            posted_date=raw.get("published_at", raw.get("created_at")),
                            work_type=work_type or detect_work_type_from_text(title, desc_text, location),
                            company_url=company_url,
                        ))
                else:
                    logger.info(f"WTTJ API returned {resp.status_code} for q={q}, falling back to HTML scrape")
                    html_url = f"https://www.welcometothejungle.com/en/jobs?query={urllib.parse.quote(q)}&aroundQuery=United%20Kingdom"
                    html_resp = client.get(html_url, headers=HEADERS)
                    if html_resp.status_code != 200:
                        logger.warning(f"WTTJ HTML page returned {html_resp.status_code} for {html_url}")
                        continue

                    soup = BeautifulSoup(html_resp.text, "lxml")

                    for link in soup.find_all("a", href=True):
                        href = link["href"]
                        if not href.startswith("/en/jobs/"):
                            continue
                        href = "https://www.welcometothejungle.com" + href

                        title_el = link.find(["h2", "h3", "strong", "span"])
                        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
                        if not title or len(title) < 3:
                            continue

                        card = link.find_parent(["article", "li", "div", "section"])
                        card_text = card.get_text(" ", strip=True) if card else title

                        company = "Unknown"
                        if card:
                            company_el = card.select_one(
                                "[class*=company], [class*=organization], "
                                "[data-testid*=company], [class*=employer], "
                                "p span, small, [class*=subtitle]"
                            )
                            if company_el:
                                company = company_el.get_text(strip=True)

                        jobs.append(JobPosting(
                            title=title,
                            company=company,
                            location="UK",
                            country="UK",
                            description=card_text[:1000],
                            url=href,
                            source="WTTJ",
                            work_type=detect_work_type_from_text(title, card_text, "UK"),
                            company_url=None,
                        ))

                logger.info(f"  -> WTTJ q={q}: {len(jobs)} jobs so far")

            except Exception as e:
                logger.warning(f"WTTJ error for q={q}: {e}")

    seen = set()
    unique = []
    for j in jobs:
        key = (j.title.lower(), j.company.lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)

    logger.info(f"  -> WTTJ total: {len(unique)} unique jobs")
    return unique


# ---------- New scraper: Remotive (free REST API) ----------

def scrape_remotive() -> list[JobPosting]:
    """Remotive.io free jobs API."""
    jobs: list[JobPosting] = []
    search_terms = ["marketing operations", "revops", "marketing automation", "martech", "revenue operations", "data operations", "data analytics"]
    try:
        # Remotive has a public /api/remote-jobs endpoint
        resp = httpx.get("https://remotive.com/api/remote-jobs?limit=100", headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"Remotive returned {resp.status_code}")
            return jobs
        data = resp.json()
        listings = data.get("jobs", [])
        seen = set()
        for item in listings:
            title = (item.get("title") or "").strip()
            company = (item.get("company_name") or "").strip()
            desc = item.get("description", "")[:2000]
            tag_str = " " + " ".join(item.get("tags", [])) + " " + title.lower() + " " + desc.lower()
            matched = False
            for term in search_terms:
                if term in tag_str:
                    matched = True
                    break
            if not matched:
                continue
            url = item.get("url", "")
            location = item.get("candidate_required_location", "") or "Remote"
            salary = item.get("salary", "")
            posted = item.get("publication_date", "")
            key = (title.lower(), company.lower())
            if key in seen:
                continue
            seen.add(key)
            jobs.append(JobPosting(
                title=title, company=company,
                location=location, country="",
                description=desc, url=str(url),
                source="Remotive", salary=str(salary) if salary else None,
                posted_date=posted,
                work_type="Remote",
            ))
        logger.info(f"     Remotive: {len(jobs)} jobs found")
    except Exception as e:
        logger.warning(f"Remotive failed: {e}")
    return jobs


# ---------- New scraper: Reed.co.uk (free search) ----------

def scrape_reed() -> list[JobPosting]:
    """Reed.co.uk job board via web scraping."""
    jobs: list[JobPosting] = []
    search_terms = ["marketing+operations", "revenue+operations", "marketing+automation", "revops", "martech", "data+operations"]
    seen = set()
    for term in search_terms[:3]:  # Limit to avoid rate limiting
        try:
            url = f"https://www.reed.co.uk/jobs/{term}-jobs?pageno=1"
            resp = httpx.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("article.job-result, div.job-result, div.job-card")
            if not cards:
                cards = soup.select("article[data-element='job-result'], div[class*='job-result']")
            for card in cards[:20]:
                title_el = card.select_one("h3 a, h2 a, .job-result-heading__title a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://www.reed.co.uk" + href
                company_el = card.select_one(".job-result-heading__posted-by a, .job-card__company, [class*='company']")
                company = company_el.get_text(strip=True) if company_el else ""
                loc_el = card.select_one(".job-metadata__item--location, .job-card__location, [class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else "UK"
                salary_el = card.select_one(".job-metadata__item--salary, .job-card__salary, [class*='salary']")
                salary = salary_el.get_text(strip=True) if salary_el else None
                key = (title.lower(), company.lower())
                if key in seen:
                    continue
                seen.add(key)
                jobs.append(JobPosting(
                    title=title, company=company,
                    location=location, country="UK",
                    description="", url=href,
                    source="Reed", salary=str(salary) if salary else None,
                    posted_date=None, work_type=None,
                ))
        except Exception as e:
            logger.warning(f"Reed failed for q={term}: {e}")
    logger.info(f"     Reed: {len(jobs)} jobs found")
    return jobs


# ---------- New scraper: Indeed UK (RSS feed) ----------

def scrape_indeed_uk() -> list[JobPosting]:
    """Indeed UK via RSS (HTML is usually blocked from datacentre IPs)."""
    jobs: list[JobPosting] = []
    seen = set()
    rss_blocked = False

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in BOARD_QUERIES:
            if rss_blocked:
                break
            try:
                url = (
                    "https://uk.indeed.com/rss"
                    f"?q={urllib.parse.quote_plus(q)}"
                    f"&l=United+Kingdom&sort=date&fromage=7"
                )
                resp = client.get(url, headers={**HEADERS, "Accept": "application/rss+xml, application/xml, text/xml"})
                if resp.status_code in (403, 429):
                    logger.warning(f"Indeed RSS blocked ({resp.status_code}); UK Indeed ads still come through Adzuna")
                    rss_blocked = True
                    break
                if resp.status_code != 200 or "<rss" not in resp.text[:500].lower() and "<item>" not in resp.text.lower():
                    logger.warning(f"Indeed RSS returned {resp.status_code} for q={q}")
                    continue
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    title = (item.findtext("title") or "").strip()
                    href = (item.findtext("link") or "").strip()
                    desc = (item.findtext("description") or "")
                    posted = (item.findtext("pubDate") or "").strip() or None
                    if not title:
                        continue
                    company = "Unknown"
                    loc = "United Kingdom"
                    m = re.search(r"(?:at| - )\s*([^<\n-]+)", desc)
                    if m:
                        company = m.group(1).strip()[:80]
                    key = (title.lower(), company.lower(), href)
                    if key in seen:
                        continue
                    seen.add(key)
                    jobs.append(JobPosting(
                        title=title, company=company,
                        location=loc, country="UK",
                        description=re.sub(r"<[^>]+>", " ", desc)[:2000],
                        url=href, source="Indeed",
                        posted_date=posted,
                        work_type=detect_work_type_from_text(title, desc, loc),
                        company_url=target_company_url(company),
                    ))
                logger.info(f"  Indeed RSS q={q}: {len(jobs)} jobs so far")
            except Exception as e:
                logger.warning(f"Indeed UK failed for q={q}: {e}")

        if not jobs:
            for q in BOARD_QUERIES[:4]:
                try:
                    url = (
                        "https://uk.indeed.com/jobs"
                        f"?q={urllib.parse.quote_plus(q)}"
                        f"&l=United+Kingdom&fromage=7&sort=date"
                    )
                    resp = client.get(url, headers=HEADERS)
                    if resp.status_code != 200:
                        logger.warning(f"Indeed HTML returned {resp.status_code} for q={q}")
                        break
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select("div.job_seen_beacon, div.cardOutline, div[data-testid^='slider_item']")
                    for card in cards[:25]:
                        title_el = card.select_one("h2 a, a.jcs-JobTitle, a[data-jk]")
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)
                        href = title_el.get("href", "")
                        if href.startswith("/"):
                            href = "https://uk.indeed.com" + href
                        company_el = card.select_one("[data-testid='company-name'], span.companyName")
                        company = company_el.get_text(strip=True) if company_el else "Unknown"
                        loc_el = card.select_one("[data-testid='text-location'], div.companyLocation")
                        location = loc_el.get_text(strip=True) if loc_el else "UK"
                        date_el = card.select_one("span.date, [data-testid='myJobsStateDate']")
                        posted = date_el.get_text(strip=True) if date_el else None
                        key = (title.lower(), company.lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        jobs.append(JobPosting(
                            title=title, company=company,
                            location=location, country="UK",
                            description="", url=href, source="Indeed",
                            posted_date=posted,
                            work_type=detect_work_type_from_text(title, "", location),
                            company_url=target_company_url(company),
                        ))
                except Exception as e:
                    logger.warning(f"Indeed HTML failed for q={q}: {e}")
                    break

    logger.info(f"     IndeedUK: {len(jobs)} jobs found")
    if not jobs:
        jobs = _scrape_indeed_via_unblocker()
        logger.info(f"     IndeedUK via unblocker: {len(jobs)} jobs found")
    return jobs


def _fetch_unblocked(url: str) -> Optional[str]:
    """Fetch a blocked board page through Scrapfly or ScrapingBee."""
    if SCRAPFLY_API_KEY:
        try:
            r = httpx.get(
                "https://api.scrapfly.io/scrape",
                params={
                    "key": SCRAPFLY_API_KEY,
                    "url": url,
                    "render_js": "true",
                    "unblocker": "true",
                    "country": "gb",
                },
                timeout=90.0,
            )
            if r.status_code == 200:
                data = r.json()
                html = ((data.get("result") or {}).get("content")) or ""
                if html:
                    return html
            logger.warning(f"Scrapfly returned {r.status_code} for {url[:80]}")
        except Exception as e:
            logger.warning(f"Scrapfly error: {e}")
    if SCRAPINGBEE_API_KEY:
        try:
            r = httpx.get(
                "https://app.scrapingbee.com/api/v1/",
                params={
                    "api_key": SCRAPINGBEE_API_KEY,
                    "url": url,
                    "render_js": "true",
                    "country_code": "gb",
                },
                timeout=60.0,
            )
            if r.status_code == 200 and r.text:
                return r.text
            logger.warning(f"ScrapingBee returned {r.status_code} for {url[:80]}")
        except Exception as e:
            logger.warning(f"ScrapingBee error: {e}")
    return None


def _parse_indeed_html(html: str, seen: set) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.job_seen_beacon, div.cardOutline, div[data-testid^='slider_item'], li.css-5lf99z")
    for card in cards[:40]:
        title_el = card.select_one("h2 a, a.jcs-JobTitle, a[data-jk]")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        if href.startswith("/"):
            href = "https://uk.indeed.com" + href
        company_el = card.select_one("[data-testid='company-name'], span.companyName")
        company = company_el.get_text(strip=True) if company_el else "Unknown"
        loc_el = card.select_one("[data-testid='text-location'], div.companyLocation")
        location = loc_el.get_text(strip=True) if loc_el else "UK"
        date_el = card.select_one("span.date, [data-testid='myJobsStateDate']")
        posted = date_el.get_text(strip=True) if date_el else None
        key = (title.lower(), company.lower())
        if key in seen:
            continue
        seen.add(key)
        jobs.append(JobPosting(
            title=title, company=company,
            location=location, country="UK",
            description="", url=href, source="Indeed",
            posted_date=posted,
            work_type=detect_work_type_from_text(title, "", location),
            company_url=target_company_url(company),
        ))
    return jobs


def _scrape_indeed_via_unblocker() -> list[JobPosting]:
    if not SCRAPINGBEE_API_KEY and not SCRAPFLY_API_KEY:
        logger.info("Indeed unblocker skipped (set SCRAPINGBEE_API_KEY or SCRAPFLY_API_KEY)")
        return []
    jobs: list[JobPosting] = []
    seen: set = set()
    for q in BOARD_QUERIES[:3]:
        url = (
            "https://uk.indeed.com/jobs"
            f"?q={urllib.parse.quote_plus(q)}&l=United+Kingdom&fromage=7&sort=date"
        )
        html = _fetch_unblocked(url)
        if not html:
            continue
        jobs.extend(_parse_indeed_html(html, seen))
    return jobs


def scrape_scrapingdog() -> list[JobPosting]:
    """ScrapingDog LinkedIn job search — last week, UK. Needs SCRAPINGDOG_API_KEY."""
    jobs: list[JobPosting] = []
    if not SCRAPINGDOG_API_KEY:
        logger.info("ScrapingDog: no API key, skipping")
        return jobs
    seen = set()
    with httpx.Client(timeout=40.0) as client:
        for q in BOARD_QUERIES[:4]:
            try:
                resp = client.get(
                    "https://api.scrapingdog.com/jobs",
                    params={
                        "api_key": SCRAPINGDOG_API_KEY,
                        "field": q,
                        "location": "United Kingdom",
                        "geoid": "101165590",
                        "sort_by": "week",
                        "page": "1",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"ScrapingDog returned {resp.status_code} for q={q}")
                    continue
                data = resp.json()
                rows = data if isinstance(data, list) else data.get("jobs") or data.get("results") or []
                for raw in rows:
                    title = (raw.get("job_title") or raw.get("title") or "").strip()
                    company = raw.get("company_name") or raw.get("company") or "Unknown"
                    if not title:
                        continue
                    key = (title.lower(), str(company).lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    location = raw.get("job_location") or raw.get("location") or "United Kingdom"
                    href = raw.get("job_link") or raw.get("url") or raw.get("linkedin_url") or ""
                    posted = raw.get("job_posted") or raw.get("listed_at") or raw.get("date")
                    jobs.append(JobPosting(
                        title=title, company=str(company),
                        location=str(location), country="UK",
                        description=str(raw.get("job_description") or raw.get("description") or "")[:2000],
                        url=href, source="ScrapingDog",
                        posted_date=str(posted) if posted else None,
                        work_type=detect_work_type_from_text(title, "", str(location)),
                        company_url=target_company_url(str(company)),
                    ))
                logger.info(f"  ScrapingDog q={q}: {len(rows)} jobs")
            except Exception as e:
                logger.warning(f"ScrapingDog error for q={q}: {e}")
    logger.info(f"  ScrapingDog total: {len(jobs)}")
    return jobs


def scrape_jsearch() -> list[JobPosting]:
    """JSearch via OpenWeb Ninja — Google Jobs (Indeed, LinkedIn, and others)."""
    jobs: list[JobPosting] = []
    if not JSEARCH_API_KEY:
        logger.info("JSearch: no API key, skipping")
        return jobs
    seen = set()
    with httpx.Client(timeout=90.0) as client:
        for q in BOARD_QUERIES[:3]:
            try:
                resp = client.get(
                    "https://api.openwebninja.com/jsearch/search-v2",
                    headers={
                        "X-API-Key": JSEARCH_API_KEY,
                        "x-api-key": JSEARCH_API_KEY,
                    },
                    params={
                        "query": f"{q} in United Kingdom",
                        "date_posted": "week",
                        "country": "gb",
                        "language": "en",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"JSearch returned {resp.status_code} for q={q}: {resp.text[:200]}")
                    continue
                payload = resp.json() or {}
                data = payload.get("data")
                if isinstance(data, dict):
                    rows = data.get("jobs") or data.get("results") or []
                elif isinstance(data, list):
                    rows = data
                else:
                    rows = payload.get("jobs") or payload.get("results") or []
                for raw in rows:
                    if not isinstance(raw, dict):
                        continue
                    title = (raw.get("job_title") or raw.get("title") or "").strip()
                    company = raw.get("employer_name") or raw.get("company") or "Unknown"
                    if not title:
                        continue
                    key = (title.lower(), str(company).lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    loc = raw.get("job_location") or raw.get("job_city") or raw.get("job_country") or "United Kingdom"
                    href = raw.get("job_apply_link") or raw.get("job_google_link") or raw.get("job_min_url") or ""
                    posted = raw.get("job_posted_at_datetime_utc") or raw.get("job_posted_at_timestamp")
                    jobs.append(JobPosting(
                        title=title, company=str(company),
                        location=str(loc), country="UK",
                        description=str(raw.get("job_description") or "")[:2000],
                        url=href, source="JSearch",
                        posted_date=str(posted) if posted else None,
                        work_type=detect_work_type_from_text(title, str(raw.get("job_is_remote") or ""), str(loc)),
                        company_url=raw.get("employer_website") or target_company_url(str(company)),
                    ))
                logger.info(f"  JSearch q={q}: {len(rows)} jobs")
            except Exception as e:
                logger.warning(f"JSearch error for q={q}: {e}")
    logger.info(f"  JSearch total: {len(jobs)}")
    return jobs


def scrape_cv_library() -> list[JobPosting]:
    """CV-Library UK RSS search, last-week dates from pubDate."""
    jobs: list[JobPosting] = []
    seen = set()

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in BOARD_QUERIES:
            for offset in (0, 25, 50):
                try:
                    url = (
                        "https://www.cv-library.co.uk/cgi-bin/jobs.rss"
                        f"?q={urllib.parse.quote_plus(q)}&geo=1&search=1&offset={offset}"
                    )
                    resp = client.get(url, headers={**HEADERS, "Accept": "application/rss+xml, application/xml"})
                    if resp.status_code != 200:
                        logger.warning(f"CV-Library RSS returned {resp.status_code} for q={q}")
                        break
                    root = ET.fromstring(resp.content)
                    items = root.findall(".//item")
                    if not items:
                        break
                    for item in items:
                        raw_title = (item.findtext("title") or "").strip()
                        href = (item.findtext("link") or item.findtext("guid") or "").strip()
                        desc = item.findtext("description") or ""
                        posted = (item.findtext("pubDate") or "").strip() or None
                        if not raw_title:
                            continue
                        title, location = raw_title, "UK"
                        if "," in raw_title:
                            title, location = raw_title.rsplit(",", 1)
                            title, location = title.strip(), location.strip() or "UK"
                        company = "Unknown"
                        lines = [ln.strip() for ln in re.sub(r"<[^>]+>", "\n", desc).splitlines() if ln.strip()]
                        for ln in lines:
                            if ln.lower() == title.lower() or ln.lower() == location.lower():
                                continue
                            if len(ln) < 80 and not ln.lower().startswith(("a ", "an ", "the ", "this ", "we ")):
                                company = ln
                                break
                        key = (title.lower(), href)
                        if key in seen:
                            continue
                        seen.add(key)
                        jobs.append(JobPosting(
                            title=title, company=company,
                            location=location, country="UK",
                            description=re.sub(r"<[^>]+>", " ", desc)[:2000],
                            url=href, source="CV-Library",
                            posted_date=posted,
                            work_type=detect_work_type_from_text(title, desc, location),
                            company_url=target_company_url(company),
                        ))
                    logger.info(f"  CV-Library q={q} offset={offset}: {len(items)} items")
                except Exception as e:
                    logger.warning(f"CV-Library error for q={q} offset={offset}: {e}")
                    break

    logger.info(f"  CV-Library total: {len(jobs)} unique jobs")
    return jobs


# ---------- New scraper: CWJobs ----------

def scrape_cwjobs() -> list[JobPosting]:
    """CWJobs.co.uk — UK tech jobs."""
    jobs: list[JobPosting] = []
    search_terms = ["marketing+operations", "revenue+operations", "marketing+automation", "revops", "martech"]
    seen = set()
    for term in search_terms[:3]:
        try:
            url = f"https://www.cwjobs.co.uk/jobs/{term}?q={term}&sort=date"
            resp = httpx.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.job, article, div[data-at='job-item'], div[class*='job-item']")
            for card in cards[:20]:
                title_el = card.select_one("h2 a, h3 a, a[class*='job-title'], a[href*='/job/']")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and href.startswith("/"):
                    href = "https://www.cwjobs.co.uk" + href
                company_el = card.select_one("[class*='company'], [class*='employer'], span[class*='brand']")
                company = company_el.get_text(strip=True) if company_el else ""
                loc_el = card.select_one("[class*='location'], span[class*='loc']")
                location = loc_el.get_text(strip=True) if loc_el else "UK"
                salary_el = card.select_one("[class*='salary'], span[class*='sal']")
                salary = salary_el.get_text(strip=True) if salary_el else None
                key = (title.lower(), company.lower())
                if key in seen:
                    continue
                seen.add(key)
                jobs.append(JobPosting(
                    title=title, company=company,
                    location=location, country="UK",
                    description="", url=href,
                    source="CWJobs", salary=str(salary) if salary else None,
                    posted_date=None, work_type=None,
                ))
        except Exception as e:
            logger.warning(f"CWJobs failed for q={term}: {e}")
    logger.info(f"     CWJobs: {len(jobs)} jobs found")
    return jobs


# ---------- New scraper: TotalJobs ----------

def scrape_totaljobs() -> list[JobPosting]:
    """TotalJobs.co.uk — large UK job board."""
    jobs: list[JobPosting] = []
    search_terms = ["marketing+operations", "revenue+operations", "marketing+automation", "revops", "martech"]
    seen = set()
    for term in search_terms[:3]:
        try:
            url = f"https://www.totaljobs.com/jobs/{term}?sort=date"
            resp = httpx.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.job, article, div[class*='job-card'], div[class*='job-item']")
            for card in cards[:20]:
                title_el = card.select_one("h2 a, h3 a, a[class*='job-title'], a[href*='/job/']")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and href.startswith("/"):
                    href = "https://www.totaljobs.com" + href
                company_el = card.select_one("[class*='company'], [class*='employer']")
                company = company_el.get_text(strip=True) if company_el else ""
                loc_el = card.select_one("[class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else "UK"
                salary_el = card.select_one("[class*='salary']")
                salary = salary_el.get_text(strip=True) if salary_el else None
                key = (title.lower(), company.lower())
                if key in seen:
                    continue
                seen.add(key)
                jobs.append(JobPosting(
                    title=title, company=company,
                    location=location, country="UK",
                    description="", url=href,
                    source="TotalJobs", salary=str(salary) if salary else None,
                    posted_date=None, work_type=None,
                ))
        except Exception as e:
            logger.warning(f"TotalJobs failed for q={term}: {e}")
    logger.info(f"     TotalJobs: {len(jobs)} jobs found")
    return jobs


# ---------- Jobgether (remote jobs, SSR HTML) ----------

JOBGETHER_BASE = "https://jobgether.com"
JOBGETHER_SEARCH_PATHS = [
    "marketing-operations",
    "revenue-operations",
    "marketing-automation",
    "revops",
    "crm-direct-marketing",
    "growth-performance",
    "united-kingdom/marketing-operations",
]


def _parse_jobgether_card(anchor) -> Optional[dict]:
    """Extract job fields from a Jobgether offer link and its card container."""
    href = anchor.get("href", "")
    title = (anchor.get("title") or anchor.get_text(strip=True) or "").strip()
    if not title or len(title) < 5:
        return None
    if href and not href.startswith("http"):
        href = JOBGETHER_BASE + href

    card = anchor
    for _ in range(12):
        if not card.parent:
            break
        card = card.parent
        card_text = card.get_text(" ", strip=True)
        if "Remote from" in card_text or "Full time" in card_text or "Part time" in card_text:
            break

    company = ""
    comp_el = card.select_one('a[href*="/remote-jobs/company-"]')
    if comp_el:
        company = comp_el.get_text(strip=True)

    card_text = card.get_text(" ", strip=True)
    location = ""
    loc_match = re.search(
        r"Remote from\s+(.+?)(?:\s+(?:Full time|Part time|Contract|Freelance|Internship)\b|$)",
        card_text,
    )
    if loc_match:
        location = loc_match.group(1).strip()

    posted = None
    for el in card.select("div, span"):
        t = el.get_text(strip=True)
        if t in ("Today", "Yesterday") or re.match(r"^\d+ days? ago$", t):
            posted = t
            break

    country = "Remote"
    loc_lower = location.lower()
    if "united kingdom" in loc_lower or "(uk)" in loc_lower or loc_lower.endswith(" uk"):
        country = "UK"
    elif "united states" in loc_lower or "(usa)" in loc_lower:
        country = "USA"

    return {
        "title": title,
        "company": company or "Unknown",
        "location": location or "Remote",
        "country": country,
        "url": href,
        "posted_date": posted,
    }


def scrape_jobgether() -> list[JobPosting]:
    """Jobgether.com — remote job listings via server-rendered category pages."""
    jobs: list[JobPosting] = []
    seen: set[tuple[str, str]] = set()

    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for path in JOBGETHER_SEARCH_PATHS:
            url = f"{JOBGETHER_BASE}/remote-jobs/{path}"
            try:
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    logger.warning(f"Jobgether returned {resp.status_code} for {path}")
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                for anchor in soup.select('a[href*="/offer/"]'):
                    parsed = _parse_jobgether_card(anchor)
                    if not parsed:
                        continue
                    key = (parsed["title"].lower(), parsed["company"].lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    jobs.append(JobPosting(
                        title=parsed["title"],
                        company=parsed["company"],
                        location=parsed["location"],
                        country=parsed["country"],
                        description="",
                        url=parsed["url"],
                        source="Jobgether",
                        salary=None,
                        posted_date=parsed["posted_date"],
                        work_type="Remote",
                    ))
            except Exception as e:
                logger.warning(f"Jobgether failed for path={path}: {e}")

    logger.info(f"     Jobgether: {len(jobs)} jobs found")
    return jobs


# ---------- Master scrape function ----------

def scrape_all() -> list[JobPosting]:
    logger.info("Starting full job scrape...")
    all_jobs: list[JobPosting] = []

    sources = [
        # ── UK boards Emma actually uses ──
        ("Adzuna", scrape_adzuna),
        ("LinkedIn", scrape_linkedin),
        ("RevOpsRoles", scrape_revops_roles),
        ("IndeedUK", scrape_indeed_uk),
        ("CVLibrary", scrape_cv_library),
        ("ScrapingDog", scrape_scrapingdog),
        ("JSearch", scrape_jsearch),
        # ── Other APIs ──
        ("Arbeitnow", scrape_arbeitnow),
        ("Jooble", scrape_jooble),
        ("Careerjet", scrape_careerjet),
        ("WeWorkRemotely", scrape_we_work_remotely),
        ("RemoteOK", scrape_remote_ok),
        ("Jobicy", scrape_jobicy),
        ("Remotive", scrape_remotive),
        ("GoogleJobs", scrape_google_jobs),
        ("WTTJ", scrape_wttj),
        ("Jobgether", scrape_jobgether),
        ("Reed", scrape_reed),
        ("CWJobs", scrape_cwjobs),
        ("TotalJobs", scrape_totaljobs),
    ]

    for name, fn in sources:
        try:
            logger.info(f"  -> scraping {name}...")
            results = fn()
            logger.info(f"     {name}: {len(results)} jobs found")
            all_jobs.extend(results)
        except Exception as e:
            logger.error(f"     {name} failed: {e}")

    # New ATS sources
    try:
        new_jobs = scrape_new_sources()
        all_jobs.extend(new_jobs)
    except Exception as e:
        logger.error(f"New sources failed: {e}")

    # Deduplicate: same title+company+source = duplicate
    seen = set()
    unique = []
    for job in all_jobs:
        key = (job.title.strip().lower(), job.company.strip().lower(), job.source.strip().lower())
        if key not in seen:
            seen.add(key)
            unique.append(job)
    dupes = len(all_jobs) - len(unique)
    if dupes > 0:
        logger.info(f"Removed {dupes} duplicate jobs")

    for job in unique:
        if not job.company_url:
            job.company_url = target_company_url(job.company)

    logger.info(f"Total raw jobs collected: {len(unique)}")
    return unique