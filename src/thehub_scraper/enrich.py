"""Stage 2 - fetch each company's detail record for team/LinkedIn and stage."""
from __future__ import annotations

import asyncio
import logging

from rich.progress import Progress

from .client import HubClient
from .config import DETAIL_ENDPOINT, Settings
from .models import Company

log = logging.getLogger(__name__)


async def enrich(
    client: HubClient, companies: list[Company], settings: Settings, progress: Progress
) -> list[Company]:
    """Replace each listing record with its fuller detail record.

    The listing endpoint omits `team` (and therefore every LinkedIn URL) and
    `stage`, so one detail call per company is the only way to get them.
    """
    task = progress.add_task("[green]Stage 2 company details", total=len(companies))

    async def one(company: Company) -> Company:
        try:
            raw = await client.get_json(DETAIL_ENDPOINT.format(key=company.key))
            detailed = Company.model_validate(raw)
        except Exception as exc:  # keep the listing data rather than dropping the row
            log.warning("detail fetch failed for %s: %s", company.key, exc)
            detailed = company
        progress.advance(task)
        return detailed

    return list(await asyncio.gather(*(one(c) for c in companies)))
