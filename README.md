# The Hub — Nordic IT & Software Scraper

A Python command-line tool that extracts company and startup data from [thehub.io](https://thehub.io)
for a specific slice of the Nordic market:

| Filter | Value |
|---|---|
| **Countries** | Denmark, Finland, Iceland, Norway, Sweden |
| **Industry** | IT & Software |
| **Funding status** | Currently not looking for funding |

For every matching company it collects the name, website, contact email, LinkedIn URLs,
plus company size, funding stage, founders, founding year and description. Results are
written as CSV, Excel and JSONL.

The last full run (26 Sep 2026) returned **2,719 companies**.

---

## Requirements

- Python 3.11 or newer
- No API key, no browser, no login — the data comes from a public JSON endpoint

## Installation

```bash
git clone https://github.com/sarah-majdoub/thehub-nordic-scraper.git
cd thehub-nordic-scraper

python3 -m venv .venv
./.venv/bin/pip install -e .
```

## Usage

```bash
# Names, websites and LinkedIn URLs. Takes about a minute.
./.venv/bin/thehub

# Same, plus a pass over every company website looking for contact emails.
# This is the slow part: 25-45 minutes for the full set.
./.venv/bin/thehub --emails --email-concurrency 24
```

Everything is written to `data/` by default.

Before committing to a full run, try a small one:

```bash
./.venv/bin/thehub --limit 12 --emails --out data/_test
```

### Command-line options

```
--out DIR                    output directory (default: data)
--countries DK,FI,IS,NO,SE   which countries to keep
--concurrency N              parallel requests to thehub.io (default 6)
--delay SECONDS              per-worker spacing between requests (default 0.25)
--skip-details               skip stage 2 — faster, but no LinkedIn URLs
--emails                     run stage 3 (email discovery)
--email-concurrency N        parallel company-website requests (default 10)
--include-personal-emails    keep non-role addresses (see the GDPR note below)
--limit N                    stop after N companies
-v / --verbose               debug logging
```

---

## Use it from an AI assistant (MCP)

The scraped data can also be queried by an AI assistant. `thehub-mcp` is an
[MCP](https://modelcontextprotocol.io) server (Python SDK v2) that serves
`data/companies_raw.jsonl` through three read-only tools, so Claude Code, Claude
Desktop or any other MCP client can answer questions about the dataset without
reading the file itself.

![Claude Code answering "Which Finnish companies founded after 2018 have 11–50 employees?" with one search_companies call](docs/demo/demo.svg)

That is a real session: Claude chose the tool and its filters itself, and one call
answered the question. `total` tells it how many companies matched, so it knows when
`limit` cut the list short.

| Tool | Does | Example question |
|---|---|---|
| `search_companies(query, country, employees, founded_after, limit)` | Keyword search on name and description, with optional filters | "Swedish companies doing computer vision" |
| `get_company(key)` | One company's profile, by key or thehub.io URL | "Tell me about 10Monkeys" |
| `count_companies(by, country)` | Counts grouped by country, employees, founded or funding stage | "Norwegian companies by size" |

### Set it up without cloning (uvx)

With [uv](https://docs.astral.sh/uv/) installed, two commands are enough. `uvx`
installs the package into a cached, throwaway environment and runs it, so there is no
clone and no venv to manage. The first run takes a few seconds; later ones start from
the cache.

```bash
# 1. Scrape. Writes data/companies_raw.jsonl in the current folder (about a minute).
uvx --from git+https://github.com/sarah-majdoub/thehub-nordic-scraper thehub

# 2. Register the server with Claude Code.
claude mcp add thehub --env THEHUB_DATA="$PWD/data/companies_raw.jsonl" \
  -- uvx --from git+https://github.com/sarah-majdoub/thehub-nordic-scraper thehub-mcp
```

For Claude Desktop or another client, add the same command to its MCP config, with
an absolute path in `THEHUB_DATA`:

```json
{
  "mcpServers": {
    "thehub": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/sarah-majdoub/thehub-nordic-scraper", "thehub-mcp"],
      "env": { "THEHUB_DATA": "/absolute/path/to/data/companies_raw.jsonl" }
    }
  }
}
```

### Set it up from a clone

After the [installation](#installation) steps and a scrape:

```bash
claude mcp add thehub --env THEHUB_DATA="$PWD/data/companies_raw.jsonl" \
  -- "$PWD/.venv/bin/thehub-mcp"
```

### Where the server looks for the data

1. `THEHUB_DATA`, if set. Use this with MCP clients: they start servers from a
   folder you do not control, so a relative path is unreliable.
2. `data/companies_raw.jsonl` under the folder the server was started from, which is
   where `thehub` writes by default.
3. The repo's own `data/` folder, for an editable install from a clone.

If none exists, the tools return an error that names each place checked.

**Personal data stays out.** The tools return company-level facts only: never team
members, LinkedIn URLs or emails. That is not enough on its own, because
companies also write people into their public fields. Across the 2,719 records, 26
descriptions contain an email address, founders name themselves in their company's
description, and one company's "website" is a founder's LinkedIn profile. The server
redacts all three, and searching for a person's name finds nothing. A test runs
every tool against a fixture seeded with fake team data and these same leaks, and
fails if any of it comes back. One-person firms named after their owner keep their
name, because that is the company's registered name.

```bash
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/pytest
```

The fixture in `tests/fixtures/` holds 20 real company records with fake team
members, LinkedIn URLs and emails, so the tests run without a scrape. To re-record
the demo, run the question through `claude -p ... --output-format stream-json
--verbose` and pass the output to `docs/demo/render.py`.

---

## What the data actually contains

Two of the four headline fields come directly from The Hub. The other two do not,
and the coverage numbers are worth knowing before you rely on them.

Measured across all 2,719 matching companies:

| Field | Source | Coverage |
|---|---|---|
| Company name | The Hub API | 2,719 / 2,719 (100%) |
| Website | The Hub API | 2,718 / 2,719 (99.96%) |
| LinkedIn | The Hub API (`team[].linkedinUrl`) | 717 (26%) — these are **team members' personal profiles**, not company pages |
| Email | Not published on The Hub at all — scraped from each company's own website | 859 (32%) |

Companies per country. A company with offices in more than one country is counted
in each, so these add up to more than 2,719:

| Denmark | Norway | Sweden | Finland | Iceland |
|---|---|---|---|---|
| 1,394 | 574 | 554 | 305 | 5 |

---

## How it works

### The listing data comes from a JSON API, not the HTML

The Hub is a Nuxt (Vue) single-page app. The obvious approach — run a headless
browser, wait for the cards to render, parse the DOM — would be slow and would
break the first time a CSS class gets renamed.

It is also unnecessary. The frontend fills itself from a JSON API that needs no
authentication:

```
GET https://thehub.io/api/companies?industries=itsoftware&funding=notLooking&page=1
```

```json
{ "docs": [ ... 15 company objects ... ], "total": 2719, "limit": 15, "page": 1, "pages": 182 }
```

Each entry in `docs` is already a full structured record: `name`, `website`,
`industries`, `funding`, `countries`, `numberOfEmployees`, `founded`. No HTML
parsing and no CSS selectors are involved, which is why the whole listing pass
finishes in under a minute.

The filter slugs come from the `window.__NUXT__` payload on the `/startups` page,
which ships the site's entire slug table. The UI label "IT & Software" is the slug
`itsoftware`; "Currently not looking for funding" is `notLooking`. Guessing
`software` instead returns `total: 0`, so the real vocabulary has to be read rather
than assumed.

### Stage 1 — Discovery (`discover.py`)

Fetches page 1, reads the `pages` count from the response (182), then fetches the
remaining pages concurrently and validates each record.

Two things about this endpoint caused problems and are handled explicitly:

1. **The `countries` parameter does not work.** The API accepts `?countries=DK` and
   then ignores it — one country, all five, or none at all all return the same
   `total: 2719`. A scraper that trusted it would produce unfiltered data that looks
   filtered. Country filtering is therefore done locally against each record's
   `countries[].countryCode`, and `Company.matches()` re-checks industry and funding
   locally too. Those two parameters do work, but the check is cheap.

2. **`limit` is capped at 15.** Sending `limit=500` still returns 15 rows, so the
   page size is fixed and all 182 requests are needed.

Records are stored in a dict keyed on the company slug, so a retried or overlapping
page cannot create duplicates.

### Stage 2 — Enrichment (`enrich.py`)

The listing record leaves out `team` and `stage`. One request per company to the
detail endpoint fills them in:

```
GET https://thehub.io/api/companies/{key}      # e.g. /api/companies/monta
```

This is where the LinkedIn URLs come from. If a detail request fails after retries,
the listing record is kept rather than dropped, so one flaky request never costs a
whole company.

### Stage 3 — Email discovery (`emails.py`, opt-in with `--emails`)

The Hub does not publish emails, so this stage visits the company's own website —
the URL The Hub provided — and reads addresses the company published itself. For
each company it tries these paths in order until it finds something:

```
/  →  /contact  →  /contact-us  →  /about  →  /about-us  →  /kontakt  →  /imprint  →  /legal-notice
```

Pages are parsed with **selectolax** (a Lexbor binding, considerably faster than
BeautifulSoup). `mailto:` links are read first because they are unambiguous, then
visible text, after stripping `<script>` and `<style>` so that JavaScript string
literals do not turn into fake addresses.

Three filters keep the output usable:

- **Junk rejection** — asset filenames, `sentry.io`, `example.com`, template placeholders.
- **Domain matching** — an address is kept only if its registrable domain matches the
  company's own site. Without this you end up collecting the web agency's inbox out
  of the footer.
- **Role-based allowlist** — by default only addresses like `info@`, `contact@`,
  `hello@`, `sales@` and `kontakt@` are kept. Addresses that look like a named person
  are discarded unless you pass `--include-personal-emails`.

That last default is a data-protection decision. All five target countries are in the
EEA. A generic company inbox is barely personal data; `firstname.lastname@company.com`
clearly is, and collecting it for cold outreach brings GDPR Article 14 notification
duties and an Article 6(1)(f) balancing test with it. The flag exists if you need it,
but the conservative behaviour is the default.

### Rate limiting and robustness (`client.py`)

- **`robots.txt` is checked first.** The Hub disallows exactly one path,
  `/startups/joblistwidget/`, which this project never requests.
- **Honest User-Agent** identifying the tool rather than impersonating a browser.
- **HTTP/2** with connection reuse through a single `httpx.AsyncClient`.
- **Bounded concurrency** with an `asyncio.Semaphore`, plus a per-worker delay inside
  the gate, so the sustained request rate stays low instead of only capping how many
  requests run at once.
- **Retries** through `tenacity` with exponential backoff and jitter, on `429`, `5xx`
  and transport errors only — never on a `404`, which is a real answer.
- **`verify=False` in stage 3 only.** Small-company sites often have expired
  certificates, and these are anonymous GETs of public pages, so a bad certificate is
  not worth losing the row over. Requests to The Hub's own API are always verified.

### Output (`export.py`)

`polars` flattens the records and writes four files:

| File | Contents |
|---|---|
| `nordic_it_software_not_seeking_funding.csv` | main deliverable |
| `nordic_it_software_not_seeking_funding.xlsx` | same data as Excel, columns auto-fitted |
| `companies_raw.jsonl` | every field the API returned, so you can re-export without re-scraping |
| `summary.json` | totals and the per-country breakdown |

Columns:

```
name, website, emails, email_source, linkedin_urls, countries, country_codes,
city_count, industries, funding, funding_stage, stage, employees, founded,
active_jobs, founders, team_size, description, thehub_profile, thehub_id, thehub_key
```

`email_source` records the URL each address was found on, so any row can be checked
by hand.

---

## Project layout

```
src/thehub_scraper/
  config.py     targets, slugs, tunables
  models.py     pydantic models and local filter re-validation
  client.py     async HTTP client, retries, rate limiting
  discover.py   stage 1 — listing pages
  enrich.py     stage 2 — detail records and LinkedIn URLs
  emails.py     stage 3 — email discovery on company websites
  export.py     flattening and CSV/XLSX/JSONL output
  cli.py        argparse and progress display
  mcp_server.py MCP server: search, lookup and counts for AI assistants
tests/          MCP server tests, run against tests/fixtures/companies.jsonl
docs/demo/      the recorded MCP session and the script that renders it
```

The generated data files are not committed — `.gitignore` excludes the CSV, XLSX and
JSONL outputs. Run the tool to produce them.

## Notes on use

Everything collected here is publicly published business information, taken from
endpoints that `robots.txt` permits. Two caveats worth reading anyway:

- The Hub's Terms of Service govern automated access independently of `robots.txt`.
  Worth reading if this becomes more than a one-off.
- If you use the emails for outreach, GDPR applies to how you contact people
  regardless of how lawfully the addresses were collected.

The `lastmod` dates in The Hub's sitemap show profiles changing weekly, so re-run the
scraper rather than treating an old export as current.
