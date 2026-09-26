"""Typed views over The Hub's API payloads.

The API returns a lot of fields we do not care about (image blobs, geo polygons,
credit balances). These models pick out what matters and normalise it, so the
rest of the pipeline never touches raw dicts.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .config import NORDIC, PROFILE_URL


class Person(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: dict[str, str] = Field(default_factory=dict)
    title: str | None = None
    isFounder: bool = False
    linkedinUrl: str | None = None

    @property
    def full_name(self) -> str:
        n = self.name or {}
        return " ".join(p for p in (n.get("first"), n.get("last")) if p).strip()


class CountryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    countryCode: str | None = None
    status: str | None = None


class Company(BaseModel):
    """One startup/company record."""

    model_config = ConfigDict(extra="ignore")

    id: str
    key: str
    name: str
    website: str | None = None
    whatWeDo: str | None = None
    founded: str | None = None
    numberOfEmployees: str | None = None
    stage: str | None = None
    funding: str | None = None
    fundingStage: str | None = None
    industries: list[str] = Field(default_factory=list)
    businessModels: list[str] = Field(default_factory=list)
    countries: list[CountryEntry] = Field(default_factory=list)
    team: list[Person] = Field(default_factory=list)
    numberOfActiveJobs: int = 0

    # Filled in by later stages, not by The Hub.
    emails: list[str] = Field(default_factory=list)
    email_source: str | None = None

    @property
    def profile_url(self) -> str:
        return PROFILE_URL.format(key=self.key)

    @property
    def country_codes(self) -> list[str]:
        seen: list[str] = []
        for c in self.countries:
            code = (c.countryCode or "").upper()
            if code and code not in seen:
                seen.append(code)
        return seen

    @property
    def nordic_codes(self) -> list[str]:
        return [c for c in self.country_codes if c in NORDIC]

    @property
    def team_linkedins(self) -> list[str]:
        return [p.linkedinUrl for p in self.team if p.linkedinUrl]

    def matches(self, countries: set[str], industry: str, funding: str) -> bool:
        """Re-check every filter locally.

        This is not redundant: the API accepts a `countries` query parameter and
        then ignores it entirely, so server-side country filtering cannot be
        trusted. We verify industry and funding here too, cheaply, rather than
        assume the other parameters behave.
        """
        return (
            bool(countries & set(self.country_codes))
            and industry in self.industries
            and self.funding == funding
        )
