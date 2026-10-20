"""Stage 3 (opt-in) - find published contact addresses on each company's own site.

The Hub itself publishes no company email addresses anywhere in its API or on its
profile pages, so an email column can only be filled from a second source. This
stage visits the company's own website - the URL The Hub already gave us - and
reads addresses the company chose to publish publicly on its contact/about page.

By default only role-based addresses (info@, contact@, sales@ ...) are kept.
Those identify a company contact point rather than a person. Addresses that look
personal are discarded unless `--include-personal-emails` is passed, because
under GDPR a named person's work address is personal data and collecting it for
outreach carries obligations that a generic inbox does not.
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlsplit

import httpx
from rich.progress import Progress
from selectolax.lexbor import LexborHTMLParser

from .config import CONTACT_PATHS, ROLE_LOCALPARTS, Settings
from .models import Company

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", re.ASCII
)

# Tracking pixels, asset hashes and CDN noise routinely produce @-shaped strings.
JUNK_DOMAINS = re.compile(
    r"(sentry\.io|\.png|\.jpe?g|\.gif|\.svg|\.webp|\.css|\.js|example\.(com|org)"
    r"|domain\.com|yourcompany|sentry-cdn|wixpress|godaddy|cloudflare"
    r"|schema\.org|w3\.org)",
    re.I,
)


def is_role_based(email: str) -> bool:
    return email.split("@", 1)[0].lower() in ROLE_LOCALPARTS


def _registrable(host: str) -> str:
    """Crude eTLD+1: enough to tell a site's own address from a third party's."""
    parts = host.lower().removeprefix("www.").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def extract_emails(html: str, site_host: str) -> list[str]:
    """Pull addresses from mailto: links first, then from visible text."""
    tree = LexborHTMLParser(html)
    found: list[str] = []

    for node in tree.css("a[href^='mailto:']"):
        href = node.attributes.get("href") or ""
        addr = href.removeprefix("mailto:").split("?", 1)[0].strip()
        if m := EMAIL_RE.fullmatch(addr):
            found.append(m.group(0))

    for node in tree.css("script, style, noscript"):
        node.decompose()
    found += EMAIL_RE.findall(tree.text(separator=" "))

    site = _registrable(site_host)
    out: list[str] = []
    for raw in found:
        email = raw.strip(" .,;:<>()[]\"'").lower()
        if JUNK_DOMAINS.search(email) or len(email) > 100:
            continue
        # Only trust an address on the domain the company actually owns;
        # otherwise we collect the web agency's or a partner's inbox.
        if _registrable(email.split("@", 1)[1]) != site:
            continue
        if email not in out:
            out.append(email)
    return out


async def harvest(
    companies: list[Company], settings: Settings, progress: Progress
) -> list[Company]:
    targets = [c for c in companies if c.website]
    task = progress.add_task("[magenta]Stage 3 website emails", total=len(targets))
    gate = asyncio.Semaphore(settings.email_concurrency)

    async with httpx.AsyncClient(
        timeout=settings.email_timeout,
        follow_redirects=True,
        verify=False,  # many small-company sites have expired/misconfigured certs
        headers={"User-Agent": settings.user_agent, "Accept": "text/html,*/*"},
    ) as client:

        async def one(company: Company) -> None:
            site = company.website or ""
            if not urlsplit(site).scheme:
                site = "https://" + site
            host = urlsplit(site).netloc

            async with gate:
                for path in CONTACT_PATHS:
                    url = urljoin(site.rstrip("/") + "/", path.lstrip("/")) if path else site
                    try:
                        r = await client.get(url)
                        if r.status_code >= 400 or "html" not in r.headers.get(
                            "content-type", ""
                        ):
                            continue
                        hits = extract_emails(r.text, host)
                    except Exception as exc:
                        log.debug("%s -> %s: %s", company.key, url, exc)
                        continue

                    role = [e for e in hits if is_role_based(e)]
                    keep = hits if settings.include_personal_emails else role
                    if keep:
                        company.emails = keep
                        company.email_source = url
                        break
                await asyncio.sleep(settings.delay)
            progress.advance(task)

        await asyncio.gather(*(one(c) for c in targets))

    got = sum(1 for c in companies if c.emails)
    log.info("found emails for %s/%s companies with a website", got, len(targets))
    return companies
