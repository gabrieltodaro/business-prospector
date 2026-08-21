from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment


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
    def assess(self, candidate: BusinessCandidate) -> WebsiteAssessment: ...


class LeadRepository(Protocol):
    def save(self, lead: Lead) -> Lead: ...
    def get(self, lead_id: int) -> Lead | None: ...
    def list(self, limit: int = 100) -> list[Lead]: ...
    def update(self, lead_id: int, changes: dict[str, object]) -> Lead: ...
    def find_duplicate(self, candidate: BusinessCandidate | Lead) -> DuplicateMatch | None: ...
    def find_slug_conflict(self, slug: str) -> PersistenceConflict | None: ...
