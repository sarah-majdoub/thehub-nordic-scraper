"""Tests for the MCP server, run through a real MCP client against a fixture.

The fixture holds 20 real company records whose team members, LinkedIn URLs and
emails were replaced with fake ones, so the privacy test can check that exactly
those values never come out, without committing anyone's personal data. Three
records carry the leaks found in the real data: an email and a LinkedIn link in
the description (10monkeys), a founder named in it (10plus), and a founder's
LinkedIn profile as the website (117banker).
"""
import json
import os
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "companies.jsonl"
os.environ["THEHUB_DATA"] = str(FIXTURE)

from mcp import Client  # noqa: E402

from thehub_scraper.mcp_server import EMAIL, companies, mcp  # noqa: E402

RAW = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_cache():
    companies.cache_clear()
    yield
    companies.cache_clear()


async def call(tool: str, args: dict):
    async with Client(mcp) as client:
        return await client.call_tool(tool, args)


def private_values() -> list[str]:
    """Every personal value in the fixture that must never appear in output."""
    values = []
    for r in RAW:
        values += r["emails"]
        for p in r["team"]:
            values += [p["linkedinUrl"], p["name"]["first"] + " " + p["name"]["last"], p["name"]["last"]]
    return values + ["jane.doe@example.org", "linkedin.com/in/jane-doe-fixture"]


@pytest.mark.anyio
async def test_count_by_country_matches_fixture():
    result = await call("count_companies", {"by": "country"})
    assert result.structured_content == {"DK": 6, "NO": 4, "SE": 4, "FI": 4, "IS": 2}


@pytest.mark.anyio
async def test_count_by_employees_is_in_size_order():
    result = await call("count_companies", {"by": "employees"})
    counts = result.structured_content
    assert list(counts) == ["1-10", "11-50", "101-200", "200+"]
    assert sum(counts.values()) == len(RAW)


@pytest.mark.anyio
async def test_count_within_country():
    result = await call("count_companies", {"by": "funding_stage", "country": "IS"})
    assert sum(result.structured_content.values()) == 2


@pytest.mark.anyio
async def test_country_filter_only_returns_that_country():
    result = await call("search_companies", {"country": "FI", "limit": 50})
    found = result.structured_content["companies"]
    assert result.structured_content["total"] == len(found) == 4
    assert all("FI" in c["countries"] for c in found)


@pytest.mark.anyio
async def test_limit_cuts_results_but_total_does_not():
    result = await call("search_companies", {"limit": 3})
    assert len(result.structured_content["companies"]) == 3
    assert result.structured_content["total"] == len(RAW)


@pytest.mark.anyio
async def test_size_and_founded_filters():
    result = await call("search_companies", {"employees": "11-50", "founded_after": 2012, "limit": 50})
    found = result.structured_content["companies"]
    assert found
    assert all(c["employees"] == "11-50" and int(c["founded"]) > 2012 for c in found)


@pytest.mark.anyio
async def test_query_matches_word_starts_and_ranks_name_first():
    result = await call("search_companies", {"query": "strategies"})
    assert result.structured_content["companies"][0]["key"] == "4c-strategies"
    # "trat" sits inside "strategies" but starts no word, so it matches nothing.
    result = await call("search_companies", {"query": "trat"})
    assert result.structured_content["total"] == 0


@pytest.mark.anyio
async def test_query_can_start_with_punctuation():
    # A fixture description says "(HQ". \b would need a letter after the boundary
    # and miss it, the same way it missed ".net" in the real data.
    assert (await call("search_companies", {"query": "(hq"})).structured_content["total"] == 1


@pytest.mark.anyio
async def test_missing_data_file_says_what_to_do(monkeypatch):
    monkeypatch.setenv("THEHUB_DATA", "/no/such/companies.jsonl")
    result = await call("count_companies", {"by": "country"})
    assert result.is_error
    assert "No data at /no/such/companies.jsonl" in result.content[0].text


@pytest.mark.anyio
async def test_get_company_accepts_key_or_profile_url():
    by_key = await call("get_company", {"key": "10monkeys"})
    by_url = await call("get_company", {"key": "https://thehub.io/startups/10monkeys"})
    assert by_key.structured_content == by_url.structured_content
    assert by_key.structured_content["name"] == "10Monkeys"


@pytest.mark.anyio
async def test_unknown_key_gives_clear_error():
    result = await call("get_company", {"key": "no-such-company"})
    assert result.is_error
    assert "No company with key 'no-such-company'" in result.content[0].text


@pytest.mark.anyio
async def test_bad_country_is_rejected():
    result = await call("search_companies", {"country": "DE"})
    assert result.is_error


@pytest.mark.anyio
async def test_free_text_is_redacted_not_dropped():
    monkeys = (await call("get_company", {"key": "10monkeys"})).structured_content
    assert monkeys["what_we_do"].startswith("Contact [email removed] or [link removed].")
    tenplus = (await call("get_company", {"key": "10plus"})).structured_content
    assert tenplus["what_we_do"].startswith("Founded by [name removed].")
    banker = (await call("get_company", {"key": "117banker"})).structured_content
    assert banker["website"] is None


@pytest.mark.anyio
async def test_cannot_find_a_company_by_a_persons_name():
    result = await call("search_companies", {"query": "Test Person2"})
    assert result.structured_content["total"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool, args",
    [
        ("search_companies", {"limit": 50}),
        *[("get_company", {"key": r["key"]}) for r in RAW],
        *[("count_companies", {"by": by}) for by in ("country", "employees", "founded", "funding_stage")],
    ],
)
async def test_no_personal_data_ever_leaves(tool, args):
    result = await call(tool, args)
    assert not result.is_error
    out = json.dumps(result.structured_content) + "".join(getattr(c, "text", "") for c in result.content)
    assert '"team"' not in out and '"emails"' not in out
    assert "linkedin.com/in/" not in out.lower()
    assert not EMAIL.search(out), EMAIL.search(out)
    for value in private_values():
        assert value not in out, value
