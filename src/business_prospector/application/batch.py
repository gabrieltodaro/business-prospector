from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from business_prospector.domain.exceptions import ProspectorError, ValidationError
from business_prospector.domain.models import BusinessCandidate, Lead, utc_now
from business_prospector.domain.scoring import calculate_score
from business_prospector.domain.website_assessment import WebsiteAssessmentReport
from business_prospector.domain.website_presence import WebsitePresence, classify_website_presence

from .config import ProspectingConfig
from .ports import DuplicateMatch, LeadRepository
from .prospecting import ProspectingService


@dataclass(slots=True)
class DeferredFirstWebsite:
    candidate: BusinessCandidate
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"candidate": self.candidate.to_dict(), "reason": self.reason}


@dataclass(slots=True)
class BatchPreparation:
    batch_id: str
    target_qualified_leads: int
    max_candidates: int
    mode: str
    website_candidates: list[BusinessCandidate] = field(default_factory=list)
    first_website_candidates: list[DeferredFirstWebsite] = field(default_factory=list)
    deferred_first_website: list[DeferredFirstWebsite] = field(default_factory=list)
    rejected_reputation: list[BusinessCandidate] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        groups = {
            "website_candidates": [item.to_dict() for item in self.website_candidates],
            "first_website_candidates": [item.to_dict() for item in self.first_website_candidates],
            "deferred_first_website": [item.to_dict() for item in self.deferred_first_website],
            "rejected_reputation": [item.to_dict() for item in self.rejected_reputation],
            "duplicates": self.duplicates,
            "invalid": self.invalid,
        }
        return {
            "batch_id": self.batch_id,
            "target_qualified_leads": self.target_qualified_leads,
            "max_candidates": self.max_candidates,
            "mode": self.mode,
            **groups,
            "summary": {name: len(items) for name, items in groups.items()},
        }


@dataclass(frozen=True, slots=True)
class QualificationOutcome:
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


class BatchProspectingService:
    def __init__(self, repository: LeadRepository, config: ProspectingConfig) -> None:
        self._repository = repository
        self._config = config

    @staticmethod
    def new_batch_id() -> str:
        return f"batch-{uuid4()}"

    def prepare(
        self,
        raw_candidates: list[dict[str, Any]],
        batch_id: str | None = None,
        target_qualified_leads: int | None = None,
        max_candidates: int | None = None,
        mode: str = "redesign",
    ) -> BatchPreparation:
        target = target_qualified_leads or self._config.target_leads
        maximum = max_candidates or self._config.max_businesses
        if not 1 <= target <= self._config.max_businesses:
            raise ValidationError("target_qualified_leads is outside configured bounds")
        if not 1 <= maximum <= self._config.max_businesses:
            raise ValidationError("max_candidates is outside configured bounds")
        if mode not in {"redesign", "first_website", "both"}:
            raise ValidationError("mode must be redesign, first_website or both")
        result = BatchPreparation(
            batch_id=batch_id or self.new_batch_id(),
            target_qualified_leads=target,
            max_candidates=maximum,
            mode=mode,
        )
        for index, raw in enumerate(raw_candidates[:maximum]):
            try:
                candidate = BusinessCandidate(**raw)
            except (ProspectorError, TypeError, ValueError) as exc:
                result.invalid.append({"index": index, "reason": str(exc)})
                continue
            if candidate.rating < self._config.first_website.minimum_rating:
                result.rejected_reputation.append(candidate)
                continue
            duplicate = self._repository.find_duplicate(candidate)
            if duplicate:
                result.duplicates.append({
                    "candidate": candidate.to_dict(),
                    "lead_id": duplicate.lead_id,
                    "match_type": duplicate.match_type,
                    "confidence": duplicate.confidence,
                })
                continue
            presence = classify_website_presence(candidate.website_url)
            if presence.presence == WebsitePresence.INVALID_URL:
                result.invalid.append({"index": index, "reason": "invalid website URL"})
                continue
            if presence.presence in {
                WebsitePresence.NO_WEBSITE,
                WebsitePresence.SOCIAL_ONLY,
                WebsitePresence.THIRD_PARTY_PROFILE,
            }:
                deferred = DeferredFirstWebsite(candidate, presence.presence.value)
                eligible = (
                    candidate.rating >= self._config.first_website.minimum_rating
                    and candidate.review_count >= self._config.first_website.minimum_reviews
                )
                if mode in {"first_website", "both"} and eligible:
                    result.first_website_candidates.append(deferred)
                elif mode == "redesign":
                    result.deferred_first_website.append(deferred)
                else:
                    result.rejected_reputation.append(candidate)
                continue
            if (
                candidate.rating < self._config.minimum_rating
                or candidate.review_count < self._config.minimum_reviews
            ):
                result.rejected_reputation.append(candidate)
                continue
            if mode in {"redesign", "both"}:
                result.website_candidates.append(candidate)
        return result

    def qualify_and_save(
        self,
        raw_candidate: dict[str, Any],
        raw_report: dict[str, Any],
        batch_id: str,
        contacts: dict[str, Any] | None = None,
    ) -> QualificationOutcome:
        if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 100:
            return QualificationOutcome("invalid", reason="batch_id must be a non-empty string up to 100 characters")
        if not isinstance(raw_report, dict):
            return QualificationOutcome("invalid", reason="assessment must be an object")
        try:
            candidate = BusinessCandidate(**self._merge_contacts(raw_candidate, contacts or {}))
            report = WebsiteAssessmentReport.from_dict(raw_report)
        except (ProspectorError, TypeError, ValueError) as exc:
            return QualificationOutcome("invalid", reason=str(exc))
        presence = classify_website_presence(candidate.website_url)
        if presence.presence in {
            WebsitePresence.NO_WEBSITE,
            WebsitePresence.SOCIAL_ONLY,
            WebsitePresence.THIRD_PARTY_PROFILE,
        }:
            return QualificationOutcome("deferred_first_website", reason=presence.presence.value)
        if presence.presence == WebsitePresence.INVALID_URL:
            return QualificationOutcome("invalid", reason="invalid website URL")
        if report.status != "assessed":
            outcome = "assessment_insufficient" if report.status == "insufficient_evidence" else "assessment_failed"
            return QualificationOutcome(outcome, reason=report.failure_reason)
        if not report.scoring_eligible:
            return QualificationOutcome("assessment_insufficient", reason="assessment is incomplete")
        if report.website_url != candidate.website_url:
            return QualificationOutcome("invalid", reason="assessment website_url does not match candidate")
        duplicate = self._repository.find_duplicate(candidate)
        if duplicate:
            return QualificationOutcome("duplicate", duplicate=duplicate)
        legacy = report.to_website_assessment()
        if legacy.issue_count < self._config.minimum_website_issues:
            return QualificationOutcome("not_qualified_website", reason="website issue threshold not met")
        lead = ProspectingService._to_lead(candidate, legacy)
        lead.score = calculate_score(lead, self._config.scoring).total
        lead.status = "qualified"
        lead.batch_id = batch_id
        lead.website_assessment = report.to_dict()
        lead.assessment_status = report.status
        lead.assessment_checked_at = utc_now()
        try:
            saved = self._repository.save(lead)
        except ValueError:
            duplicate = self._repository.find_duplicate(candidate)
            if duplicate:
                return QualificationOutcome("duplicate", duplicate=duplicate)
            raise
        return QualificationOutcome("saved_qualified", lead=saved)

    @staticmethod
    def _merge_contacts(candidate: dict[str, Any], contacts: dict[str, Any]) -> dict[str, Any]:
        allowed = {"phone", "whatsapp", "whatsapp_confirmed", "whatsapp_source", "email", "instagram"}
        unknown = set(contacts) - allowed
        if unknown:
            raise ValidationError(f"unsupported contact fields: {', '.join(sorted(unknown))}")
        merged = dict(candidate)
        merged.update(contacts)
        if merged.get("whatsapp_confirmed") and merged.get("whatsapp_source") != "website_link":
            raise ValidationError("confirmed website WhatsApp requires website_link evidence")
        return merged
