"""MCP server exposing the scraped Nordic IT companies to LLM agents.

Three read-only tools: search, lookup by key, and grouped counts. Results carry
company-level facts only. Team members, LinkedIn URLs and emails never leave
this module, and emails, personal LinkedIn links and team members' names that
companies put in their own description are redacted too.
tests/test_mcp_server.py enforces it.

Run with `thehub-mcp` (stdio). Set THEHUB_DATA to point at a different JSONL.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .models import Company

DATA_FILE = Path("data") / "companies_raw.jsonl"  # where `thehub` writes by default
# Only meaningful for an editable install, where this file still sits in the repo.
REPO_DATA = Path(__file__).resolve().parents[2] / DATA_FILE
Country = Literal["DK", "FI", "IS", "NO", "SE"]
Employees = Literal["1-10", "11-50", "51-100", "101-200", "200+"]
EMPLOYEE_ORDER = list(Employees.__args__)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PERSONAL_LINKEDIN = re.compile(r"(?:https?://)?(?:[\w-]+\.)?linkedin\.com/in/[\w%-]*/?", re.I)
WHAT_WE_DO_MAX = 300

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

mcp = MCPServer(
    "thehub-nordic",
    instructions=(
        "Nordic (DK, FI, IS, NO, SE) IT & software companies listed on thehub.io "
        "that are not currently raising funding. Use count_companies for "
        "statistics and search_companies to list companies."
    ),
)


def data_path() -> Path:
    """THEHUB_DATA if set, else ./data from the working directory, else the repo's data/."""
    if env := os.environ.get("THEHUB_DATA"):
        path = Path(env).expanduser()
        if path.is_file():
            return path
        raise ToolError(f"THEHUB_DATA points at {path}, which does not exist.")
    tried = [Path.cwd() / DATA_FILE]
    if (REPO_DATA.parents[1] / "pyproject.toml").is_file():  # an editable install
        tried.append(REPO_DATA)
    for path in tried:
        if path.is_file():
            return path
    raise ToolError(
        f"No data found (looked in {', '.join(map(str, tried))}). "
        "Run `thehub` to scrape it, then set THEHUB_DATA to the companies_raw.jsonl it writes."
    )


@cache
def companies() -> list[Company]:
    with data_path().open(encoding="utf-8") as f:
        return [Company.model_validate_json(line) for line in f if line.strip()]


class CompanySummary(BaseModel):
    # Company-level facts only: no team members, LinkedIn URLs or emails.
    key: str
    name: str
    website: str | None
    profile_url: str
    countries: list[str]
    employees: str | None
    founded: str | None
    funding_stage: str | None
    what_we_do: str | None


class SearchResult(BaseModel):
    total: int = Field(description="How many companies matched, before the limit.")
    companies: list[CompanySummary]


def team_names(c: Company) -> list[str]:
    # Two-word names or longer, so a lone first name never redacts an ordinary
    # word. A "team member" that is really the company's own name is kept.
    names = {p.full_name for p in c.team if len(p.full_name.split()) >= 2}
    return sorted(names - {c.name}, key=len, reverse=True)


def redact(c: Company) -> str:
    """The description with emails, personal LinkedIn links and team names removed."""
    text = EMAIL.sub("[email removed]", c.whatWeDo or "")
    text = PERSONAL_LINKEDIN.sub("[link removed]", text)
    for name in team_names(c):
        text = re.sub(re.escape(name), "[name removed]", text, flags=re.I)
    return " ".join(text.split())


def shorten(text: str) -> str | None:
    if len(text) > WHAT_WE_DO_MAX:
        text = text[:WHAT_WE_DO_MAX].rsplit(" ", 1)[0] + "…"
    return text or None


def summarize(c: Company) -> CompanySummary:
    return CompanySummary(
        key=c.key,
        name=c.name,
        # Some companies list a founder's LinkedIn profile as their website.
        website=None if c.website and PERSONAL_LINKEDIN.search(c.website) else c.website,
        profile_url=c.profile_url,
        countries=c.country_codes,
        employees=c.numberOfEmployees,
        founded=c.founded,
        funding_stage=c.fundingStage,
        what_we_do=shorten(redact(c)),
    )


def founded_year(c: Company) -> int | None:
    try:
        return int((c.founded or "")[:4])
    except ValueError:
        return None


@mcp.tool(annotations=READ_ONLY)
def search_companies(
    query: Annotated[
        str,
        Field(description="Words to look for in the name or description. Each word must start a word in the text (so 'ai' does not match 'maintain'). Empty matches everything."),
    ] = "",
    country: Annotated[Country | None, Field(description="Only companies present in this country.")] = None,
    employees: Annotated[Employees | None, Field(description="Only companies of this size.")] = None,
    founded_after: Annotated[int | None, Field(description="Only companies founded after this year (exclusive).")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum companies to return.")] = 10,
) -> SearchResult:
    """Search Nordic IT & software companies that are not looking for funding.

    Name matches rank above description-only matches. `total` says how many
    matched in all, so you can tell when results were cut off by `limit`.
    """
    # Match at word starts. Not \b, which needs a letter next, so ".net" would fail.
    words = [re.compile(rf"(?<!\w){re.escape(w)}") for w in query.lower().split()]
    hits: list[tuple[int, Company]] = []
    for c in companies():
        if country and country not in c.country_codes:
            continue
        if employees and c.numberOfEmployees != employees:
            continue
        if founded_after is not None and (founded_year(c) or 0) <= founded_after:
            continue
        # Redacted text, so searching for a person's name finds nothing.
        name, text = c.name.lower(), f"{c.name} {redact(c)}".lower()
        if not all(w.search(text) for w in words):
            continue
        hits.append((sum(bool(w.search(name)) for w in words), c))
    hits.sort(key=lambda h: (-h[0], h[1].name.lower()))
    return SearchResult(total=len(hits), companies=[summarize(c) for _, c in hits[:limit]])


@mcp.tool(annotations=READ_ONLY)
def get_company(
    key: Annotated[str, Field(description="The company's thehub.io key, e.g. '10monkeys'.")],
) -> CompanySummary:
    """Get one company by its thehub.io key (the last part of its profile URL)."""
    wanted = key.strip().lower().rstrip("/").rsplit("/", 1)[-1]
    for c in companies():
        if c.key.lower() == wanted:
            return summarize(c)
    # ToolError, not ValueError: the SDK hides other exceptions' text from the model.
    raise ToolError(f"No company with key {key!r}. Use search_companies to find the right key.")


@mcp.tool(annotations=READ_ONLY)
def count_companies(
    by: Annotated[
        Literal["country", "employees", "founded", "funding_stage"],
        Field(description="Field to group by. A company in several countries counts once per country."),
    ],
    country: Annotated[Country | None, Field(description="Only count companies present in this country.")] = None,
) -> dict[str, int]:
    """Count companies grouped by one field, optionally within one country."""
    counts: Counter[str] = Counter()
    for c in companies():
        if country and country not in c.country_codes:
            continue
        if by == "country":
            counts.update(c.country_codes or ["unknown"])
        elif by == "employees":
            counts[c.numberOfEmployees or "unknown"] += 1
        elif by == "founded":
            counts[str(founded_year(c) or "unknown")] += 1
        else:
            counts[c.fundingStage or "unknown"] += 1

    if by == "employees":
        order = {k: i for i, k in enumerate(EMPLOYEE_ORDER)}
        keys = sorted(counts, key=lambda k: order.get(k, len(order)))
    elif by == "founded":
        keys = sorted(counts)
    else:
        keys = [k for k, _ in counts.most_common()]
    return {k: counts[k] for k in keys}


def main() -> None:
    mcp.run()  # stdio by default


if __name__ == "__main__":
    main()
