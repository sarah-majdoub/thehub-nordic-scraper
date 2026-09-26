"""Stage 1 - walk the filtered listing API and collect candidate companies."""
from __future__ import annotations

import asyncio
import logging

from rich.progress import Progress

from .client import HubClient
from .config import LIST_ENDPOINT, Settings
from .models import Company

log = logging.getLogger(__name__)


def _params(settings: Settings, page: int) -> dict[str, object]:
    return {
        "industries": settings.industry,
        "funding": settings.funding,
        "page": page,
    }


async def discover(client: HubClient, settings: Settings, progress: Progress) -> list[Company]:
    """Page through the listing endpoint, keeping only records that pass every filter.

    Page 1 is fetched on its own because its `pages` field tells us how many
    remaining pages exist; those are then fetched concurrently.
    """
    first = await client.get_json(LIST_ENDPOINT, _params(settings, 1))
    total, pages = first.get("total", 0), first.get("pages", 1)
    log.info("listing reports %s companies across %s pages", total, pages)

    task = progress.add_task("[cyan]Stage 1 listing pages", total=pages)
    kept: dict[str, Company] = {}

    def absorb(payload: dict) -> None:
        for raw in payload.get("docs", []):
            company = Company.model_validate(raw)
            if company.matches(settings.countries, settings.industry, settings.funding):
                kept[company.key] = company  # keyed, so a repeat page cannot duplicate
        progress.advance(task)

    absorb(first)

    async def fetch(page: int) -> dict:
        return await client.get_json(LIST_ENDPOINT, _params(settings, page))

    results = await asyncio.gather(
        *(fetch(p) for p in range(2, pages + 1)), return_exceptions=True
    )
    for page, payload in zip(range(2, pages + 1), results, strict=True):
        if isinstance(payload, BaseException):
            log.warning("page %s failed permanently: %s", page, payload)
            progress.advance(task)
            continue
        absorb(payload)

    log.info("kept %s companies after local filtering", len(kept))
    return sorted(kept.values(), key=lambda c: c.name.casefold())
