"""Command line entry point."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from .client import HubClient
from .config import NORDIC, Settings
from .discover import discover
from .emails import harvest
from .enrich import enrich
from .export import write

console = Console()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="thehub",
        description="Scrape Nordic IT & Software companies on thehub.io that are not currently seeking funding.",
    )
    p.add_argument("--out", type=Path, default=Path("data"), help="output directory (default: data)")
    p.add_argument("--countries", default="DK,FI,IS,NO,SE",
                   help="comma-separated country codes (default: all five Nordics)")
    p.add_argument("--concurrency", type=int, default=6, help="parallel requests to thehub.io")
    p.add_argument("--delay", type=float, default=0.25, help="seconds between requests per worker")
    p.add_argument("--skip-details", action="store_true",
                   help="skip stage 2; faster, but no LinkedIn or stage data")
    p.add_argument("--emails", action="store_true",
                   help="stage 3: look for published contact addresses on company websites")
    p.add_argument("--email-concurrency", type=int, default=10,
                   help="parallel requests to company websites in stage 3")
    p.add_argument("--include-personal-emails", action="store_true",
                   help="also keep non-role addresses (personal data; see README)")
    p.add_argument("--limit", type=int, default=0, help="stop after N companies (for testing)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


async def run(args: argparse.Namespace) -> None:
    codes = {c.strip().upper() for c in args.countries.split(",") if c.strip()}
    if unknown := codes - set(NORDIC):
        console.print(f"[yellow]Warning:[/] non-Nordic country codes requested: {sorted(unknown)}")

    settings = Settings(
        out_dir=args.out,
        countries=codes,
        concurrency=args.concurrency,
        delay=args.delay,
        harvest_emails=args.emails,
        email_concurrency=args.email_concurrency,
        include_personal_emails=args.include_personal_emails,
    )

    columns = (
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )

    with Progress(*columns, console=console) as progress:
        async with HubClient(settings) as client:
            companies = await discover(client, settings, progress)
            if args.limit:
                companies = companies[: args.limit]
            if not args.skip_details:
                companies = await enrich(client, companies, settings, progress)

        if settings.harvest_emails:
            companies = await harvest(companies, settings, progress)

    paths = write(companies, settings)

    table = Table(title="Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Companies matched", str(len(companies)))
    table.add_row("With website", str(sum(1 for c in companies if c.website)))
    table.add_row("With LinkedIn (team)", str(sum(1 for c in companies if c.team_linkedins)))
    table.add_row("With email", str(sum(1 for c in companies if c.emails)))
    for code in sorted(codes):
        n = sum(1 for c in companies if code in c.country_codes)
        table.add_row(f"  {NORDIC.get(code, code)}", str(n))
    console.print(table)

    for label, path in paths.items():
        console.print(f"[green]{label:8}[/] {path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/]")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
