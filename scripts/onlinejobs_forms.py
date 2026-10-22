"""OnlineJobs.ph external-application discovery: pure parsing and gating, no browser, no network.

Why this exists: most postings are applied to natively (autonomousapply.com does that, and it spends
apply points). A minority send the candidate OUT of the site, to a Google Form, a Typeform or an ATS
page, or ask for an email. Those are free to apply to and nobody else on the board's side of the
automation looks at them. onlinejobs-check.py calls this module on a schedule to find them; the
`/onlinejobs-apply` skill reads the queue it leaves in oj-state.json and does the filling.

Tested in tests/battle/test_onlinejobs_forms.py with posting texts shaped like the live pages of
2026-10-20 (140 postings across five keywords: 10 with a form link, 8 with only an email).
"""
import re
from urllib.parse import quote

SEARCH_KEYWORDS = ["full stack developer", "ai engineer", "web developer", "automation", "software developer"]

# Jiv's floor in USD per month. Below it the role is a skip, same rule as the apply skill.
RATE_FLOOR_MONTHLY = 2000
HOURS_PER_MONTH = 160    # 40 h/week, used only to turn an hourly wage into a monthly one
PESO_PER_USD = 56        # coarse; the floor test does not need more (P40-50k is about $700-900)
PESO_AMOUNT_FROM = 15000

# Form hosts that mean "applying happens off the site". Greenhouse/Lever/Ashby/Workable are ATS pages.
_FORM_RE = re.compile(
    r"(?:https?://)?(?:www\.)?("
    r"forms\.gle/[\w-]+"
    r"|docs\.google\.com/forms/[^\s\"'<>)]+"
    r"|[\w.-]*typeform\.com/[^\s\"'<>)]+"
    r"|tally\.so/[^\s\"'<>)]+"
    r"|[\w.-]*jotform\.com/[^\s\"'<>)]+"
    r"|airtable\.com/(?:app|shr)[^\s\"'<>)]+"
    r"|[\w.-]*(?:greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|breezy\.hr|recruitee\.com)/[^\s\"'<>)]+"
    r")",
    re.I,
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Two ways the board says a posting is dead: a deleted page, or a banner under the title.
CLOSED_BANNER = "This job has been closed."

# The board's own footer carries support@onlinejobs.ph. It is page chrome, never an apply address.
_SITE_DOMAINS = ("onlinejobs.ph",)

_DEV_TITLE = re.compile(
    r"\b(developer|engineer|full[- ]?stack|software|programmer|backend|back-end|frontend|front-end|devops|"
    r"automation|n8n|ai|llm|python|django|react|node|typescript|laravel|php|rails|web)\b", re.I)
# Roles the keywords drag in that are not engineering work (the skill's misfit gate).
_MISFIT_TITLE = re.compile(
    r"\b(accountant|bookkeep|seo|geo|marketing|appointment setter|virtual assistant|recruit|talent acquisition|"
    r"sales|customer (?:support|service)|phone|content|editor|designer|writer|social media|data entry|"
    r"hubspot specialist|operations specialist|qa tester|website qa|"
    # Slipped through on 2026-10-21/22: "AI" or "Engineer" in the title is not enough.
    r"estimator|quantity surveyor|it project|network engineer|(?:system|systems|network) administrator|sysadmin|"
    r"help ?desk|technician)\b", re.I)


def search_url(keyword, offset=0):
    """Page 1 is where external applications cluster. Pagination is a PATH offset (30 per page);
    the `pageNo=` query parameter is ignored by the site."""
    path = "jobsearch" if not offset else f"jobsearch/{offset}"
    return (f"https://www.onlinejobs.ph/jobseekers/{path}?jobkeyword={quote(keyword)}"
            "&skill_tags=&gig=on&partTime=on&fullTime=on&isFromJobsearchForm=1")


def posting_id(url):
    """Trailing number of the slug, e.g. .../senior-ai-full-stack-software-developer-remote-1723774."""
    m = re.search(r"-(\d+)/?(?:[?#].*)?$", url)
    return m.group(1) if m else url.rstrip("/").rsplit("/", 1)[-1]


def body_of(text):
    """The description only: from JOB OVERVIEW to the share footer. Nav and footer are stripped so
    their links and emails can never be read as the employer's."""
    start = text.find("JOB OVERVIEW")
    body = text[start + len("JOB OVERVIEW"):] if start >= 0 else text
    end = body.find("SHARE THIS POST")
    return body[:end] if end >= 0 else body


def extract_form_links(body):
    seen, out = set(), []
    for m in _FORM_RE.finditer(body):
        link = "https://" + m.group(1).rstrip(".,;:!?)\"'")
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


def extract_apply_emails(body):
    out = []
    for e in _EMAIL_RE.findall(body):
        e = e.rstrip(".,;:").lower()
        if any(e.endswith(d) for d in _SITE_DOMAINS) or e in out:
            continue
        out.append(e)
    return out


def _header(text):
    """(employer, title) from the block between the back link and TYPE OF WORK. Some postings show the
    employer on the line above the title, some do not; the title is always the last real line."""
    m = re.search(r"< Back to search results\s*\n(.*?)TYPE OF WORK", text, re.S)
    if not m:
        return "", ""
    chrome = ("APPLY FOR THIS JOB", "Applied", "Bookmark", CLOSED_BANNER)
    lines = [l.strip() for l in m.group(1).split("\n")
             if l.strip() and l.strip() not in chrome and not l.strip().startswith("Date Applied")]
    if not lines:
        return "", ""
    return (lines[-2] if len(lines) > 1 else ""), lines[-1]


def _wage_line(text):
    m = re.search(r"WAGE / SALARY\s*\n+\s*([^\n]+)", text)
    return m.group(1).strip() if m else ""


def monthly_usd(wage, hours_per_week=40):
    """Best monthly figure the posting offers, or None when the line has no number we trust.
    Takes the TOP of a range: the floor test is "can this ever reach my rate", not "is the low end ok".
    Currencies other than USD are treated as USD; the gate is a coarse filter, not a quote."""
    if not wage:
        return None
    nums = [float(n.replace(",", "")) for n in re.findall(r"(\d[\d,]*(?:\.\d+)?)", wage)]
    nums = [n for n in nums if n > 0]
    if not nums:
        return None
    top = max(nums)
    w = wage.lower()
    if re.search(r"php|₱|peso", w):
        return top / PESO_PER_USD
    if re.search(r"(?:/|\bper\b|\ba\b)\s*(?:hr|hour)|hourly|\bp hr\b", w):
        return top * (hours_per_week * 4 if hours_per_week else HOURS_PER_MONTH)
    if re.search(r"(?:/|\bper\b|\ba\b)\s*(?:month|mo)\b|monthly", w):
        return top
    if re.search(r"(?:/|\bper\b)\s*(?:week|wk)\b", w):
        return top * 4
    # A bare number carries no unit. Under 300 it can only be hourly ("20" was AUD 20/hr); from 15,000 up
    # it is not a plausible USD month for this work, so it is pesos; in between it is a monthly figure.
    if top < 300:
        return top * (hours_per_week * 4 if hours_per_week else HOURS_PER_MONTH)
    if top >= PESO_AMOUNT_FROM:
        return top / PESO_PER_USD
    return top


def parse_posting(url, text):
    """One posting page's inner text -> a lead record. `method` is FORM, EMAIL or native."""
    closed = "Job No Longer Posted" in text or CLOSED_BANNER in text
    applied = bool(re.search(r"Date Applied:|You have applied|You applied on", text))
    body = body_of(text)
    forms = [] if closed else extract_form_links(body)
    emails = [] if closed else extract_apply_emails(body)
    hours = None
    hm = re.search(r"HOURS PER WEEK\s*\n+\s*(\d+)", text)
    if hm:
        hours = int(hm.group(1))
    wage = _wage_line(text)
    employer, title = _header(text)
    return {
        "id": posting_id(url),
        "url": url,
        "title": title,
        "employer": employer,
        "wage": wage,
        "monthly_usd": monthly_usd(wage, hours or 40),
        "form_url": forms[0] if forms else "",
        "apply_email": emails[0] if emails else "",
        "applied": applied,
        "closed": closed,
        "method": "FORM" if forms else ("EMAIL" if emails else "native"),
    }


def judge(lead):
    """(True, "") when the lead is worth queueing, else (False, reason). Native postings are out of
    scope. An unknown wage is NOT a skip: many good postings omit it and the skill reads the full text."""
    if lead["closed"]:
        return False, "closed"
    if lead["method"] == "native":
        return False, "native"
    if lead["applied"]:
        return False, "applied_on_site"
    title = lead["title"]
    if _MISFIT_TITLE.search(title) or not _DEV_TITLE.search(title):
        return False, "misfit_role"
    m = lead["monthly_usd"]
    if m is not None and m < RATE_FLOOR_MONTHLY:
        return False, "below_rate_floor"
    return True, ""
