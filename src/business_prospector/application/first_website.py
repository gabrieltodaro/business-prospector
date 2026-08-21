from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business_prospector.domain.exceptions import ProspectorError, ValidationError
from business_prospector.domain.first_website import (
    FIRST_WEBSITE_PRESENCES,
    FirstWebsiteMarketReport,
    is_first_website_candidate,
)
from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment, utc_now
from business_prospector.domain.normalization import normalize_domain, normalize_text
from business_prospector.domain.scoring import calculate_first_website_score
from business_prospector.domain.website_presence import WebsitePresence, classify_website_presence

from .batch import BatchProspectingService
from .config import ProspectingConfig
from .ports import DuplicateMatch, LeadRepository


@dataclass(frozen=True, slots=True)
class FirstWebsiteOutcome:
    outcome: str
    lead: Lead | None = None
    duplicate: DuplicateMatch | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "lead": self.lead.to_dict() if self.lead else None,
            "duplicate": None if self.duplicate is None else {
                "lead_id": self.duplicate.lead_id,
                "match_type": self.duplicate.match_type,
                "confidence": self.duplicate.confidence,
            },
            "reason": self.reason,
        }


class FirstWebsiteProspectingService:
    def __init__(self, repository: LeadRepository, config: ProspectingConfig) -> None:
        self._repository = repository
        self._config = config

    def select_competitors(
        self, raw_target: dict[str, Any], raw_candidates: list[dict[str, Any]], maximum: int = 2
    ) -> list[BusinessCandidate]:
        target = BusinessCandidate(**raw_target)
        limit = min(maximum, self._config.first_website.max_competitors)
        if limit < 1:
            raise ValidationError("maximum competitors must be positive")
        selected: list[BusinessCandidate] = []
        seen: set[str] = set()
        for raw in raw_candidates[: self._config.first_website.max_competitor_candidates]:
            try:
                item = BusinessCandidate(**raw)
            except (ProspectorError, TypeError, ValueError):
                continue
            if item.external_place_id and item.external_place_id == target.external_place_id:
                continue
            if normalize_text(item.category) != normalize_text(target.category):
                continue
            presence = classify_website_presence(item.website_url).presence
            if presence not in {WebsitePresence.OWN_WEBSITE, WebsitePresence.HOSTED_WEBSITE}:
                continue
            if item.rating < self._config.minimum_rating or item.review_count < self._config.minimum_reviews:
                continue
            identity = item.external_place_id or normalize_domain(item.website_url) or f"{item.name}:{item.city}"
            if identity in seen:
                continue
            seen.add(identity)
            selected.append(item)
            if len(selected) >= limit:
                break
        return selected

    def qualify_and_save(
        self, raw_candidate: dict[str, Any], raw_research: dict[str, Any], batch_id: str,
        contacts: dict[str, Any] | None = None,
    ) -> FirstWebsiteOutcome:
        if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 100:
            return FirstWebsiteOutcome("invalid", reason="invalid batch_id")
        try:
            candidate = BusinessCandidate(**BatchProspectingService._merge_contacts(raw_candidate, contacts or {}))
            report = FirstWebsiteMarketReport.from_dict(raw_research)
        except (ProspectorError, TypeError, ValueError) as exc:
            return FirstWebsiteOutcome("invalid", reason=str(exc))
        policy = self._config.first_website
        presence = classify_website_presence(candidate.website_url).presence
        if presence not in FIRST_WEBSITE_PRESENCES:
            return FirstWebsiteOutcome("invalid", reason="candidate is not a first website opportunity")
        if not is_first_website_candidate(candidate, policy.minimum_rating, policy.minimum_reviews):
            return FirstWebsiteOutcome("not_qualified_first_website", reason="reputation threshold not met")
        duplicate = self._repository.find_duplicate(candidate)
        if duplicate:
            return FirstWebsiteOutcome("duplicate", duplicate=duplicate)
        if report.status == "failed":
            return FirstWebsiteOutcome("research_failed", reason=report.failure_reason)
        if report.status != "complete" or len(report.competitors) < policy.minimum_competitors:
            return FirstWebsiteOutcome("research_insufficient", reason=report.failure_reason or "insufficient competitors")
        score = calculate_first_website_score(candidate, report, policy.scoring)
        if score.total < policy.minimum_score:
            return FirstWebsiteOutcome("not_qualified_first_website", reason=f"score below threshold: {score.total}")
        lead = Lead(
            name=candidate.name, category=candidate.category, city=candidate.city,
            rating=candidate.rating, review_count=candidate.review_count,
            website_url=candidate.website_url or "", assessment=WebsiteAssessment(reason="First website opportunity"),
            external_place_id=candidate.external_place_id, address=candidate.address, maps_url=candidate.maps_url,
            phone=candidate.phone, whatsapp=candidate.whatsapp,
            whatsapp_confirmed=candidate.whatsapp_confirmed, whatsapp_source=candidate.whatsapp_source,
            email=candidate.email, instagram=candidate.instagram, score=score.total, status="qualified",
            source=candidate.source, batch_id=batch_id, opportunity_type="first_website",
            first_website_reason=presence.value, market_research=report.to_dict(),
            market_research_status=report.status, market_research_checked_at=utc_now(),
        )
        try:
            return FirstWebsiteOutcome("saved_qualified_first_website", lead=self._repository.save(lead))
        except ValueError:
            duplicate = self._repository.find_duplicate(candidate)
            if duplicate:
                return FirstWebsiteOutcome("duplicate", duplicate=duplicate)
            raise
