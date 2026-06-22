"""
Multi-source job scraper for MOpsWork.
Each source returns a list of JobPosting objects.
"""

import re
import json
import logging
import urllib.parse
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from backend.filters import JobPosting
from backend.new_scrapers import scrape_new_sources

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


# ---------- Adzuna API (UK) — DISABLED: free trial exhausted ----------
# import urllib.parse
# def scrape_adzuna() -> list[JobPosting]:
#     logger.info("Adzuna: trial exhausted, skipping")
#     return []


# ---------- Source 2: We Work Remotely ----------

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


# ---------- Source 3: Remote OK API ----------

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


# ---------- Source 4: Jobicy API ----------

def scrape_jobicy() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    categories = ["marketing", "sales", "data-science"]
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


# ---------- Source 5: Google for Jobs (via SerpAPI or scrape) ----------

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


# ---------- Source 6: RevOps Roles (SSR scrape) ----------

def scrape_revops_roles() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    urls = [
        "https://revopsroles.com/?location=united-kingdom",
        "https://revopsroles.com/remote-jobs",
    ]

    seen_urls = set()

    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    logger.warning(f"RevOpsRoles returned {resp.status_code} for {url}")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")

                for li in soup.select("li.job-row, li[class*=job]"):
                    link_el = li.find("a", href=True)
                    if not link_el:
                        continue
                    href = link_el["href"]
                    if not href.startswith("http"):
                        href = "https://revopsroles.com" + href
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    title_el = li.select_one("[class*=font-extrabold]")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)

                    full_text = li.get_text(" ", strip=True)

                    company = "Unknown"
                    company_match = re.search(rf'{re.escape(title)}\s*(.+?)\s*·', full_text)
                    if company_match:
                        company = company_match.group(1).strip()

                    location = "Remote"
                    loc_match = re.search(r'·\s*(.+?)\s*·', full_text)
                    if loc_match:
                        location = loc_match.group(1).strip()

                    level = "Unknown"
                    level_match = re.search(r'·\s*(Senior|Mid|Junior|Director|Lead|Principal)', full_text)
                    if level_match:
                        level = level_match.group(1)

                    salary = None
                    salary_match = re.search(r'(\$[\d,]+k?\s*–\s*\$?[\d,]+k?|£[\d,]+k?\s*–\s*£?[\d,]+k?)', full_text)
                    if salary_match:
                        salary = salary_match.group(1)

                    category = ""
                    cat_match = re.search(r'·\s*(RevOps|Marketing Ops|Sales Ops|GTM Engineering|CS Ops|Deal Desk|Enablement|GTM Strategy|CRM Administration)', full_text)
                    if cat_match:
                        category = cat_match.group(1)

                    country = "Worldwide"
                    loc_lower = location.lower()
                    if "united kingdom" in loc_lower or "uk" in loc_lower or "london" in loc_lower or "england" in loc_lower:
                        country = "UK"
                    elif any(c in loc_lower for c in ["united states", "usa", "new york", "san francisco"]):
                        country = "US"

                    description = f"{category} role. Level: {level}. Location: {location}. {full_text[:500]}"

                    is_remote = "remote" in loc_lower or "remote" in url

                    company_url = None  # RevOpsRoles doesn't expose company URLs in listing

                    jobs.append(JobPosting(
                        title=title,
                        company=company,
                        location=location,
                        country=country,
                        description=description,
                        url=href,
                        source="RevOpsRoles",
                        salary=salary,
                        work_type="Remote" if is_remote else "On-site",
                        company_url=company_url,
                    ))

                    if len(jobs) >= 100:
                        break

                logger.info(f"  -> RevOpsRoles {url}: {len(jobs)} jobs so far")

            except Exception as e:
                logger.warning(f"RevOpsRoles error: {e}")

    seen = set()
    unique = []
    for j in jobs:
        key = (j.title.lower(), j.company.lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)

    logger.info(f"  -> RevOpsRoles total: {len(unique)} unique jobs")
    return unique


# ---------- Source 7: LinkedIn Guest API ----------

def scrape_linkedin() -> list[JobPosting]:
    jobs: list[JobPosting] = []
    queries = [
        "marketing operations",
        "revenue operations",
        "revops",
        "marketing automation",
        "martech",
    ]
    # Also search by specific target companies to catch jobs that don't rank in generic queries
    company_queries = [
        "Fonoa", "Exclaimer", "Improvado", "Poka",
    ]

    seen_urls = set()

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        all_search_terms = queries + company_queries
        for q in all_search_terms:
            for start in range(0, 50, 25):
                try:
                    url = (
                        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                        f"?keywords={urllib.parse.quote(q)}"
                        f"&location=United%20Kingdom"
                        f"&f_WT=2,3"
                        f"&start={start}"
                    )
                    resp = client.get(url, headers={
                        **HEADERS,
                        "Accept": "text/html,application/xhtml+xml",
                        "Referer": "https://www.linkedin.com/jobs/",
                    })
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")

                    # Find all job list items — LinkedIn returns a flat list of <li> items
                    for card in soup.find_all("li"):
                        link_el = card.find("a", href=True)
                        if not link_el:
                            continue
                        href = link_el["href"]
                        # Only follow LinkedIn job view links
                        if not href.startswith("https://") or "/jobs/view/" not in href:
                            continue
                        if href in seen_urls:
                            continue
                        seen_urls.add(href)

                        full_text = card.get_text(" ", strip=True)

                        # Title is the link text (job title is the clickable text)
                        title = link_el.get_text(strip=True)
                        if not title or len(title) < 5:
                            continue

                        # Extract company name — LinkedIn shows it as the next significant text
                        # after the title, often separated by "·" or on a new line
                        company = "Unknown"
                        # Look after the title in the text
                        for tag in card.find_all(["h4", "span", "p", "div"]):
                            cls = " ".join(tag.get("class", [])) if tag.get("class") else ""
                            cls_lower = cls.lower()
                            if any(x in cls_lower for x in ["company", "subtitle", "employer"]):
                                company = tag.get_text(strip=True)
                                break
                        if company == "Unknown":
                            # Fallback: split on separator chars
                            parts = full_text.split("·")
                            for part in parts:
                                pt = part.strip()
                                if pt and pt != title and len(pt) < 60 and not any(
                                    c in pt.lower() for c in
                                    ["hour", "day", "week", "month", "ago", "apply", "active",
                                     "be an early", "actively hiring"]
                                ):
                                    company = pt
                                    break

                        # Location
                        location = "UK"
                        for tag in card.find_all(["span", "div", "p", "small"]):
                            cls = " ".join(tag.get("class", [])) if tag.get("class") else ""
                            if "location" in cls.lower():
                                location = tag.get_text(strip=True)
                                break
                        if location == "UK":
                            # Try to find location info from text patterns
                            loc_match = re.search(r'·\s*(.+?)\s*·', full_text)
                            if loc_match:
                                candidate = loc_match.group(1).strip()
                                if candidate and len(candidate) < 80 and "linkedin" not in candidate.lower():
                                    location = candidate

                        jobs.append(JobPosting(
                            title=title,
                            company=company,
                            location=location,
                            country="UK",
                            description=full_text[:1000],
                            url=href,
                            source="LinkedIn",
                            work_type=detect_work_type_from_text(title, full_text, location),
                            company_url=None,
                        ))

                except Exception as e:
                    logger.warning(f"LinkedIn error for q={q}, start={start}: {e}")

    seen = set()
    unique = []
    for j in jobs:
        key = (j.title.lower(), j.company.lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)

    logger.info(f"  -> LinkedIn total: {len(unique)} unique jobs")
    return unique


# ---------- Source 8: Welcome to the Jungle ----------

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
    """Indeed UK via search pages."""
    jobs: list[JobPosting] = []
    search_terms = [
        ('marketing+operations', 'what=marketing+operations'),
        ('revenue+operations', 'what=revenue+operations'),
        ('marketing+automation', 'what=marketing+automation'),
        ('revops', 'what=revops'),
        ('martech', 'what=martech'),
    ]
    seen = set()
    for label, params in search_terms:
        try:
            url = f"https://uk.indeed.com/jobs?q={params}&l=United+Kingdom&sc=0kf%3Aattr%28DSQF7%29jt%28fulltime%29%3B&limit=10&sort=date"
            resp = httpx.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.job_seen_beacon, div.cardOutline, div[data-testid^='job-card']")
            for card in cards[:20]:
                title_el = card.select_one("h2 a, a.jcs-JobTitle, h2[class*='jobTitle'] a, a[data-jk]")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and href.startswith("/"):
                    href = "https://uk.indeed.com" + href
                company_el = card.select_one("[data-testid='company-name'], span.companyName, .companyName, [class*='company']")
                company = company_el.get_text(strip=True) if company_el else ""
                loc_el = card.select_one("[data-testid='text-location'], div.companyLocation, [class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else "UK"
                salary_el = card.select_one(".salary-snippet-container, [class*='salary'], div[id*='salary']")
                salary = salary_el.get_text(strip=True) if salary_el else None
                key = (title.lower(), company.lower())
                if key in seen:
                    continue
                seen.add(key)
                jobs.append(JobPosting(
                    title=title, company=company,
                    location=location, country="UK",
                    description="", url=href,
                    source="Indeed", salary=str(salary) if salary else None,
                    posted_date=None, work_type=None,
                ))
        except Exception as e:
            logger.warning(f"Indeed UK failed for q={label}: {e}")
    logger.info(f"     IndeedUK: {len(jobs)} jobs found")
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


# ---------- Master scrape function ----------

def scrape_all() -> list[JobPosting]:
    logger.info("Starting full job scrape...")
    all_jobs: list[JobPosting] = []

    sources = [
        # Adzuna — trial expired
        ("WeWorkRemotely", scrape_we_work_remotely),
        ("RemoteOK", scrape_remote_ok),
        ("Jobicy", scrape_jobicy),
        ("GoogleJobs", scrape_google_jobs),
        ("RevOpsRoles", scrape_revops_roles),
        ("LinkedIn", scrape_linkedin),
        ("WTTJ", scrape_wttj),
        # New sources
        ("Remotive", scrape_remotive),
        ("Reed", scrape_reed),
        ("IndeedUK", scrape_indeed_uk),
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

    logger.info(f"Total raw jobs collected: {len(unique)}")
    return unique