"""Scrape targets and tunables, all in one place."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BASE = "https://thehub.io"
LIST_ENDPOINT = f"{BASE}/api/companies"
DETAIL_ENDPOINT = f"{BASE}/api/companies/{{key}}"
PROFILE_URL = f"{BASE}/startups/{{key}}"

# The API hard-caps page size at 15 regardless of any `limit` we send.
PAGE_SIZE = 15

NORDIC = {
    "DK": "Denmark",
    "FI": "Finland",
    "IS": "Iceland",
    "NO": "Norway",
    "SE": "Sweden",
}

INDUSTRY = "itsoftware"       # The Hub's slug for "IT & Software"
FUNDING = "notLooking"        # "Currently not looking for funding"

# Role-based addresses are company contact points, not personal data about an
# identifiable person. Anything outside this set is treated as personal and is
# only kept when the caller explicitly opts in.
ROLE_LOCALPARTS = {
    "info", "contact", "hello", "hi", "sales", "support", "office",
    "mail", "team", "admin", "enquiries", "inquiries", "press", "business",
    "kontakt", "post", "firmapost",
}

CONTACT_PATHS = ("", "/contact", "/contact-us", "/about", "/about-us", "/kontakt", "/imprint", "/legal-notice")


@dataclass(slots=True)
class Settings:
    out_dir: Path = Path("data")
    countries: set[str] = field(default_factory=lambda: set(NORDIC))
    industry: str = INDUSTRY
    funding: str = FUNDING

    # Politeness. The Hub's robots.txt only disallows /startups/joblistwidget/,
    # but a public site still deserves a gentle request rate.
    concurrency: int = 6
    delay: float = 0.25
    timeout: float = 30.0
    max_retries: int = 5

    # Stage 3 (company websites) is off unless asked for.
    harvest_emails: bool = False
    email_concurrency: int = 10
    email_timeout: float = 15.0
    include_personal_emails: bool = False

    user_agent: str = (
        "thehub-nordic-scraper/1.0 (research contact scraping; "
        "+https://thehub.io/robots.txt respected)"
    )
