"""
MOpsWork job search configuration.
Edit these lists to tweak scoring weights and criteria.
"""

import os
from dotenv import load_dotenv

# ── City scores ──
CITY_SCORES = {
    "london": 10,
    "reading": 10,
    "bristol": 20,
    "exeter": 20,
    "bath": 20,
    "swindon": 20,
    "gloucester": 20,
    "cheltenham": 20,
}

# ── Work type scores ──
WORK_TYPE_SCORES = {
    "remote": 20,
    "hybrid": 10,
    "onsite": 0,
    "on-site": 0,
}

# ── Salary bands (annual GBP) ──
SALARY_BANDS = [
    (0, 60000, 0),
    (60000, 90000, 10),
    (90000, 120000, 20),
    (120000, float("inf"), 20),
]

# ── Seniority groups ──
SENIORITY_HIGH = {
    "manager", "head of", "lead", "director", "senior",
    "sr", "vp", "vice president", "principal", "staff",
}
SENIORITY_MID = {
    "analyst", "specialist", "coordinator", "associate", "executive",
}

# ── Keyword scores ──
KEYWORDS_SCORE_10 = [
    "sales operations", "revops", "revenue operations",
    "marketing automation", "lifecycle automation", "lifecycle marketing",
]

KEYWORDS_SCORE_20 = [
    "marketing operations", "martech", "marketing technology", "marketing tech",
    "gtm engineer", "go-to-market engineer",
    "marketing data", "data analytics", "marketing analytics",
    "marketing systems", "demand generation", "growth marketing",
    "marketing platform", "email marketing",
    "data ops", "data operations", "reporting",
]

KEYWORDS_EXCLUDE = [
    "sales manager", "business development", "account executive",
    "sdr", "bdr", "account manager", "inside sales",
    "sales rep", "sales representative", "sales development",
    "customer success manager", "customer support",
    "presales", "pre-sales", "pre sales",
    "solution architect", "solutions architect",
    "product manager", "pmm", "product marketing manager",
    "national accounts", "national account manager",
    "field marketing", "field sales",
    "lead generation",
    "talent acquisition", "talent acquisition manager",
    "chief of staff", "caretaker", "executive assistant",
    "supply chain manager", "growth marketing manager", "consultant",
    "commercial director", "design engineer",
]

KEYWORD_SCORES = {}
for kw in KEYWORDS_SCORE_10:
    KEYWORD_SCORES[kw] = 10
for kw in KEYWORDS_SCORE_20:
    KEYWORD_SCORES[kw] = 20
for kw in KEYWORDS_EXCLUDE:
    KEYWORD_SCORES[kw] = -50

# ── Title must contain at least one of these to be included ──
TITLE_REQUIRED_TERMS = [
    "marketing operations",
    "marketing analyst",
    "marketing data analyst",
    "ai marketing specialist",
    "gtm engineer",
    "gtm strategy & operations",
    "gtm execution",
    "revenue operations",
    "revops",
    "revenue ai & automation",
    "data ops & reporting",
    "operations & automation",
    "marketing automation",
    "go-to-market engineer",
    "martech",
    "marketing technology",
    "marketing program & enablement",
    "marketing analytics",
    "lead",
    "data analyst",
    "go-to-market technology",
    "business automation",
    "agentops",
    "sales operations",
]

# ── Desired skills (for CV skills matching) ──
# Expanded with user's actual skills
DESIRED_SKILLS = [
    # Emma's confirmed skills
    "hubspot", "salesforce", "marketo", "pardot", "eloqua",
    "salesforce marketing cloud", "salesforce sales cloud", "salesforce service cloud",
    "tableau", "power bi", "powerbi", "looker", "sql",
    "google analytics", "ga4", "google tag manager",
    "crm", "api", "rest api", "python", "r programming", "r language",
    "html", "html5", "css", "css3", "javascript",
    "jira", "asana", "airtable",
    "wordpress", "webflow",
    "leandata", "lean data",
    "vimeo", "visio", "turtl", "canva",
    "zoominfo",
    # Additional MarTech skills (not Emma's — used to detect gaps)
    "dynamics 365", "ms dynamics",
    "snowflake", "bigquery", "redshift",
    "dbt", "fivetran", "stitch",
    "segment", "mparticle", "rudderstack",
    "braze", "customer.io", "intercom", "drift",
    "outreach", "salesloft", "gong", "chili piper",
    "terminus", "metadata.io", "census",
    "hightouch", "workato", "tray.io", "make", "make.com",
    "zapier", "klaviyo", "activecampaign",
    "mailchimp", "constant contact",
    "adobe analytics", "adobe experience cloud",
    "hotjar", "crazy egg", "lucky orange",
    "optimizely", "vwo", "google optimize",
    "sprout social", "hootsuite", "buffer",
    "linkedin ads", "google ads", "meta ads", "facebook ads",
    "6sense", "demandbase",
    "b2b marketing", "a/b testing", "seo", "sem", "ppc",
    "account based marketing", "lead scoring",
    "customer journey", "lifecycle",
    # AI / automation tools
    "claude", "chatgpt", "openai", "copilot", "gemini",
    "clay", "clay.com",
    "n8n",
    # Compliance
    "gdpr",
    # Product analytics
    "mixpanel",
    # Additional MarTech / RevOps
    "salesforce pardot", "pendo", "fullstory", "amplitude",
    "iterable", "sendgrid", "twilio",
    "notion", "monday", "clickup",
    "figma", "mural", "miro", "lucidchart",
    "domo", "thoughtspot", "sisense",
    "windsor.ai", "supermetrics",
    "leanplum", "onesignal", "clevertap",
    "typeform", "survey monkey", "qualtrics",
    "adobe campaign", "adobe target", "adobe audience manager",
    "tealium", "ensighten", "gtm",
    "looker studio", "data studio", "mode", "hex",
    "github", "gitlab", "bitbucket",
    "docker", "kubernetes", "terraform",
    "jenkins", "circleci", "github actions",
    "databricks", "apache spark", "kafka",
    "customer data platform", "cdp",
    "marketo engage", "hubspot marketing hub",
    "salesforce crm", "sap",
    "netsuite", "oracle", "workday",
    "anaplan", "adaptive insights",
    "clari", "insight squared", "people.ai",
    "lean data", "ringlead", "openprise",
    "validity", "demandtools", "cloudingo",
    "litmus", "stensul", "knak", "taxi for email",
    "bynder", "brandfolder", "frontify",
    "sprinklr", "brandwatch", "talkwalker",
    "rollworks", "integrify",
    "snaplogic", "boomi", "celigo", "jitterbit",
    "mulesoft", "informatica", "talend",
    "alteryx", "knime", "rapidminer",
    "power automate", "uipath", "automation anywhere",
]

# Remove duplicates while preserving order
seen = set()
DESIRED_SKILLS_UNIQUE = []
for s in DESIRED_SKILLS:
    key = s.strip().lower()
    if key not in seen:
        seen.add(key)
        DESIRED_SKILLS_UNIQUE.append(s)
DESIRED_SKILLS = DESIRED_SKILLS_UNIQUE

# ── API keys (loaded from .env) ──
try:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
    ADZUNA_API_KEY = os.getenv("ADZUNA_API_KEY", "")
    SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
    JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "")
    CAREERJET_API_KEY = os.getenv("CAREERJET_API_KEY", "")
    APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
except ImportError:
    ADZUNA_APP_ID = ""
    ADZUNA_API_KEY = ""
    SERPAPI_API_KEY = ""
    JOOBLE_API_KEY = ""
    CAREERJET_API_KEY = ""
    APIFY_API_TOKEN = ""

# How often to re-scan in minutes
SCAN_INTERVAL_MINUTES = 60

# Only keep roles posted within this many days
MAX_POSTED_AGE_DAYS = 7

# Tracker target companies (name -> website). Used for ATS boards and company_url.
TARGET_COMPANY_SITES = {
    "6sense": "https://6sense.com",
    "9fin": "https://9fin.com",
    "Access Group": "https://www.theaccessgroup.com",
    "Advanced": "https://www.oneadvanced.com",
    "Adyen": "https://www.adyen.com",
    "Aircall": "https://aircall.io",
    "Airtable": "https://www.airtable.com",
    "Airwallex": "https://www.airwallex.com",
    "Algolia": "https://www.algolia.com",
    "Amplitude": "https://amplitude.com",
    "Asana": "https://asana.com",
    "Aspen Technology": "https://www.aspentech.com",
    "Atlassian": "https://www.atlassian.com",
    "Braze": "https://www.braze.com",
    "Camunda": "https://camunda.com",
    "Causeway Technologies": "https://www.causeway.com",
    "Checkout.com": "https://www.checkout.com",
    "Circit": "https://www.circit.io",
    "Clariness": "https://www.clariness.com",
    "ClearBank": "https://clear.bank",
    "ClickUp": "https://clickup.com",
    "Cognism": "https://www.cognism.com",
    "Confluent": "https://www.confluent.io",
    "Contentful": "https://www.contentful.com",
    "Contentsquare": "https://contentsquare.com",
    "Culture Amp": "https://www.cultureamp.com",
    "Databricks": "https://www.databricks.com",
    "Datadog": "https://www.datadoghq.com",
    "Deel": "https://www.deel.com",
    "DeepL": "https://www.deepl.com",
    "Demandbase": "https://www.demandbase.com",
    "DocuSign": "https://www.docusign.com",
    "Dojo": "https://dojo.tech",
    "Dropbox": "https://www.dropbox.com",
    "Elastic": "https://www.elastic.co",
    "F5": "https://www.f5.com",
    "Figma": "https://www.figma.com",
    "Fivetran": "https://www.fivetran.com",
    "Flexera": "https://www.flexera.com",
    "FreeAgent": "https://www.freeagent.com",
    "Front": "https://front.com",
    "Frontify": "https://www.frontify.com",
    "GitLab": "https://about.gitlab.com",
    "GoCardless": "https://gocardless.com",
    "Gong": "https://www.gong.io",
    "HiBob": "https://www.hibob.com",
    "Hightouch": "https://hightouch.com",
    "HubSpot": "https://www.hubspot.com",
    "Intercom": "https://www.intercom.com",
    "IRIS Software Group": "https://www.iris.co.uk",
    "Iterable": "https://iterable.com",
    "Keystone Education Group": "https://www.keg.com",
    "Klaviyo": "https://www.klaviyo.com",
    "Lattice": "https://lattice.com",
    "LeanData": "https://www.leandata.com",
    "Lucanet": "https://www.lucanet.com",
    "Luminance": "https://www.luminance.com",
    "Macrobond": "https://www.macrobond.com",
    "Miro": "https://miro.com",
    "monday.com": "https://monday.com",
    "MongoDB": "https://www.mongodb.com",
    "Multiverse": "https://www.multiverse.io",
    "Notion": "https://www.notion.so",
    "OakNorth": "https://www.oaknorth.com",
    "Octopus Deploy": "https://octopus.com",
    "Paddle": "https://www.paddle.com",
    "Pendo": "https://www.pendo.io",
    "Pennylane": "https://www.pennylane.com",
    "Personetics": "https://personetics.com",
    "Personio": "https://www.personio.com",
    "Plaid": "https://plaid.com",
    "Pleo": "https://www.pleo.io",
    "PolyAI": "https://poly.ai",
    "Qonto": "https://qonto.com",
    "Quantexa": "https://www.quantexa.com",
    "Recurly": "https://recurly.com",
    "Remote": "https://remote.com",
    "Sage": "https://www.sage.com",
    "Sentry": "https://sentry.io",
    "Siteimprove": "https://www.siteimprove.com",
    "Snowflake": "https://www.snowflake.com",
    "Soldo": "https://www.soldo.com",
    "Stripe": "https://stripe.com",
    "Synthesia": "https://www.synthesia.io",
    "Thought Machine": "https://www.thoughtmachine.net",
    "Tide": "https://www.tide.co",
    "Transfer Room": "https://www.transferroom.com",
    "TrueLayer": "https://truelayer.com",
    "Trustpilot": "https://www.trustpilot.com",
    "Twilio": "https://www.twilio.com",
    "Typeform": "https://www.typeform.com",
    "Unit4": "https://www.unit4.com",
    "Vertice": "https://www.vertice.one",
    "Wise": "https://wise.com",
    "Workato": "https://www.workato.com",
    "Xero": "https://www.xero.com",
    "YOOBIC": "https://www.yoobic.com",
    "Zapier": "https://zapier.com",
    "Zendesk": "https://www.zendesk.com",
}

TARGET_COMPANY_LOOKUP = {name.lower(): (name, url) for name, url in TARGET_COMPANY_SITES.items()}


def target_company_url(company: str) -> str | None:
    if not company:
        return None
    hit = TARGET_COMPANY_LOOKUP.get(company.strip().lower())
    return hit[1] if hit else None