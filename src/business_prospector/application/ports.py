from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from pathlib import Path

from business_prospector.domain.site_assets import SiteAsset

from business_prospector.domain.models import BusinessCandidate, Lead
from business_prospector.domain.website_assessment import WebsiteAssessmentReport


@dataclass(frozen=True, slots=True)
class SearchQuery:
    niche: str
    city: str
    limit: int


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    lead_id: int
    match_type: str
    confidence: str

    def diagnostic(self) -> dict[str, str]:
        strength = {"exact": "exact", "likely": "strong", "possible": "possible"}[self.confidence]
        return {
            "rule": self.match_type,
            "strength": strength,
            "matched_against": "existing_lead",
        }


@dataclass(frozen=True, slots=True)
class PersistenceConflict:
    lead_id: int
    field: str
    value: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "type": "technical_identifier_conflict",
            "field": self.field,
            "value": self.value,
            "existing_lead_id": self.lead_id,
        }


class BusinessDiscoveryProvider(Protocol):
    def search(self, query: SearchQuery) -> list[BusinessCandidate]: ...


class WebsiteAssessmentProvider(Protocol):
    def assess(self, candidate: BusinessCandidate) -> WebsiteAssessmentReport: ...


class LeadRepository(Protocol):
    def save(self, lead: Lead) -> Lead: ...
    def get(self, lead_id: int) -> Lead | None: ...
    def list(self, limit: int = 100) -> list[Lead]: ...
    def update(self, lead_id: int, changes: dict[str, object]) -> Lead: ...
    def find_duplicate(self, candidate: BusinessCandidate | Lead) -> DuplicateMatch | None: ...
    def find_slug_conflict(self, slug: str) -> PersistenceConflict | None: ...
    def save_benchmark_selection(self, selection_id: str, selection: dict[str, object]) -> None: ...
    def get_benchmark_selection(self, selection_id: str) -> dict[str, object] | None: ...
    def claim_deployment(self, lead_id: int, target_key: str, preview_url: str,
                         preview_slug: str, checksum: str) -> dict[str, Any]: ...
    def deployment_owner(self, target_key: str, preview_url: str) -> int | None: ...
    def record_deployment(self, lead_id: int, state: str, details: dict[str, Any], attempt_id: str) -> None: ...
    def get_deployment(self, lead_id: int) -> dict[str, Any] | None: ...
    def deployment_history(self, lead_id: int) -> list[dict[str, Any]]: ...


class ReviewedSiteAssetLibrary(Protocol):
    def load(self, lead: Lead, keys: list[str]) -> tuple[tuple[SiteAsset, ...], Path]: ...
