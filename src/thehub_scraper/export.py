"""Flatten records and write CSV / JSONL / XLSX."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import polars as pl

from .config import NORDIC, Settings
from .models import Company

log = logging.getLogger(__name__)

COLUMNS = [
    "name", "website", "emails", "email_source", "linkedin_urls",
    "countries", "country_codes", "city_count", "industries",
    "funding", "funding_stage", "stage", "employees", "founded",
    "active_jobs", "founders", "team_size", "description",
    "thehub_profile", "thehub_id", "thehub_key",
]


def flatten(c: Company) -> dict[str, object]:
    founders = [p.full_name for p in c.team if p.isFounder and p.full_name]
    return {
        "name": c.name,
        "website": c.website or "",
        "emails": "; ".join(c.emails),
        "email_source": c.email_source or "",
        "linkedin_urls": "; ".join(c.team_linkedins),
        "countries": "; ".join(NORDIC.get(x, x) for x in c.nordic_codes),
        "country_codes": "; ".join(c.nordic_codes),
        "city_count": len(c.countries),
        "industries": "; ".join(c.industries),
        "funding": c.funding or "",
        "funding_stage": c.fundingStage or "",
        "stage": c.stage or "",
        "employees": c.numberOfEmployees or "",
        "founded": c.founded or "",
        "active_jobs": c.numberOfActiveJobs,
        "founders": "; ".join(founders),
        "team_size": len(c.team),
        "description": " ".join((c.whatWeDo or "").split()),
        "thehub_profile": c.profile_url,
        "thehub_id": c.id,
        "thehub_key": c.key,
    }


def write(companies: list[Company], settings: Settings) -> dict[str, Path]:
    out = settings.out_dir
    out.mkdir(parents=True, exist_ok=True)

    raw = out / "companies_raw.jsonl"
    with raw.open("w", encoding="utf-8") as fh:
        for c in companies:
            fh.write(c.model_dump_json() + "\n")

    df = pl.DataFrame([flatten(c) for c in companies], schema_overrides={"city_count": pl.Int64})
    df = df.select(COLUMNS).sort("name")

    csv_path = out / "nordic_it_software_not_seeking_funding.csv"
    xlsx_path = out / "nordic_it_software_not_seeking_funding.xlsx"
    df.write_csv(csv_path)
    df.write_excel(xlsx_path, autofit=True)

    summary = {
        "total": df.height,
        "with_website": int(df.filter(pl.col("website") != "").height),
        "with_email": int(df.filter(pl.col("emails") != "").height),
        "with_linkedin": int(df.filter(pl.col("linkedin_urls") != "").height),
        "by_country": {
            NORDIC[code]: int(df.filter(pl.col("country_codes").str.contains(code)).height)
            for code in sorted(NORDIC)
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {"csv": csv_path, "xlsx": xlsx_path, "jsonl": raw, "summary": out / "summary.json"}
