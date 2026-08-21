from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from business_prospector.domain.exceptions import ProspectorError, ValidationError
from business_prospector.domain.first_website import (
    FIRST_WEBSITE_PRESENCES,
    FirstWebsiteMarketReport,
    is_first_website_candidate,
)
from business_prospector.domain.identity import IdentityMatch, match_business_identity
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


@dataclass(frozen=True, slots=True)
class BenchmarkRejection:
    candidate: dict[str, Any]
    reason: str
    match: IdentityMatch | None = None
    matched_against: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"candidate": self.candidate, "reason": self.reason}
        if self.match and self.matched_against:
            data["match"] = self.match.to_dict(self.matched_against)
        return data


@dataclass(frozen=True, slots=True)
class BenchmarkSelection:
    raw_count: int
    country: str
    benchmark_market: str
    selected: tuple[BusinessCandidate, ...]
    rejected: tuple[BenchmarkRejection, ...]
    minimum_required: int

    def to_dict(self) -> dict[str, Any]:
        reasons = Counter(item.reason for item in self.rejected)
        return {
            "country": self.country,
            "benchmark_market": self.benchmark_market,
            "selected": [item.to_dict() for item in self.selected],
            "rejected": [item.to_dict() for item in self.rejected],
            "summary": {
                "raw": self.raw_count,
                "evaluated": len(self.selected) + len(self.rejected),
                "selected": len(self.selected),
                "rejected": len(self.rejected),
                "minimum_required": self.minimum_required,
                "research_status": (
                    "ready" if len(self.selected) >= self.minimum_required else "research_insufficient"
                ),
                "reasons": dict(sorted(reasons.items())),
            },
        }


def _categories_are_compatible(
    left: str, right: str, groups: tuple[tuple[str, ...], ...],
) -> bool:
    normalized = {normalize_text(left), normalize_text(right)}
    if len(normalized) == 1:
        return True
    return any(normalized <= {normalize_text(item) for item in group} for group in groups)


def _invalid_candidate_snapshot(raw: object, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"candidate_index": index}
    allowed = BusinessCandidate.__dataclass_fields__
    return {
        key: value for key, value in raw.items()
        if key in allowed and (value is None or isinstance(value, (str, int, float, bool)))
    }


class FirstWebsiteProspectingService:
    def __init__(self, repository: LeadRepository, config: ProspectingConfig) -> None:
        self._repository = repository
        self._config = config

    @staticmethod
    def _benchmark_rank(item: BusinessCandidate) -> tuple[float, int, str, str, str]:
        return (
            -item.rating,
            -item.review_count,
            normalize_text(item.name),
            item.external_place_id or "",
            normalize_domain(item.website_url) or "",
        )

    def select_benchmarks(
        self, raw_target: dict[str, Any], raw_candidates: list[dict[str, Any]], maximum: int = 2,
    ) -> BenchmarkSelection:
        target = BusinessCandidate(**raw_target)
        policy = self._config.first_website
        benchmark_policy = policy.benchmark_research
        limit = min(maximum, benchmark_policy.max_benchmarks)
        if limit < 1:
            raise ValidationError("maximum benchmarks must be positive")
        selected: list[BusinessCandidate] = []
        rejected: list[BenchmarkRejection] = []
        seen: list[BusinessCandidate] = []
        parsed: list[BusinessCandidate] = []
        bounded = raw_candidates[: benchmark_policy.max_candidates]
        for index, raw in enumerate(bounded):
            try:
                item = BusinessCandidate(**raw)
            except (ProspectorError, TypeError, ValueError):
                snapshot = _invalid_candidate_snapshot(raw, index)
                website = raw.get("website_url") if isinstance(raw, dict) else None
                reason = ("invalid_url" if isinstance(website, str) and
                          classify_website_presence(website).presence is WebsitePresence.INVALID_URL
                          else "invalid_candidate")
                rejected.append(BenchmarkRejection(snapshot, reason))
                continue
            parsed.append(item)

        for item in sorted(parsed, key=self._benchmark_rank):
            target_match = match_business_identity(item, target)
            if target_match:
                rejected.append(BenchmarkRejection(
                    item.to_dict(), "target_business", target_match, "target",
                ))
                continue
            if not _categories_are_compatible(
                item.category, target.category, policy.compatible_category_groups,
            ):
                rejected.append(BenchmarkRejection(item.to_dict(), "category_mismatch"))
                continue
            presence = classify_website_presence(item.website_url).presence
            if presence not in {WebsitePresence.OWN_WEBSITE, WebsitePresence.HOSTED_WEBSITE}:
                rejected.append(BenchmarkRejection(item.to_dict(), presence.value))
                continue
            if item.rating < benchmark_policy.minimum_rating or item.review_count < benchmark_policy.minimum_reviews:
                rejected.append(BenchmarkRejection(item.to_dict(), "reputation_below_threshold"))
                continue
            pool_match = None
            for previous in seen:
                pool_match = match_business_identity(item, previous)
                if pool_match:
                    break
            if pool_match:
                rejected.append(BenchmarkRejection(
                    item.to_dict(), "duplicate", pool_match, "benchmark_pool",
                ))
                continue
            seen.append(item)
            if len(selected) >= limit:
                rejected.append(BenchmarkRejection(item.to_dict(), "max_benchmarks_reached"))
                continue
            selected.append(item)
        return BenchmarkSelection(
            len(raw_candidates), benchmark_policy.country, benchmark_policy.default_market,
            tuple(selected), tuple(rejected), benchmark_policy.minimum_benchmarks,
        )

    def select_competitors(
        self, raw_target: dict[str, Any], raw_candidates: list[dict[str, Any]], maximum: int = 2,
    ) -> BenchmarkSelection:
        """Deprecated compatibility alias; use select_benchmarks."""
        return self.select_benchmarks(raw_target, raw_candidates, maximum)

    def validate_benchmark_report(
        self, target: BusinessCandidate, report: FirstWebsiteMarketReport,
    ) -> str | None:
        policy = self._config.first_website
        benchmark_policy = policy.benchmark_research
        if report.benchmark_market != benchmark_policy.default_market:
            return "benchmark_market does not match configured market"
        seen_place_ids: set[str] = set()
        for benchmark in report.benchmarks:
            if benchmark.rating is None or benchmark.rating < benchmark_policy.minimum_rating:
                return "benchmark rating below configured threshold"
            if benchmark.review_count is None or benchmark.review_count < benchmark_policy.minimum_reviews:
                return "benchmark reviews below configured threshold"
            if benchmark.category is None or not _categories_are_compatible(
                benchmark.category, target.category, policy.compatible_category_groups,
            ):
                return "benchmark category is incompatible with target"
            if benchmark.external_place_id:
                if benchmark.external_place_id == target.external_place_id:
                    return "target business cannot be used as benchmark"
                if benchmark.external_place_id in seen_place_ids:
                    return "duplicate benchmark external_place_id"
                seen_place_ids.add(benchmark.external_place_id)
        return None

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
        invalid_report = self.validate_benchmark_report(candidate, report)
        if invalid_report:
            return FirstWebsiteOutcome("invalid", reason=invalid_report)
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
        if report.status != "complete" or len(report.benchmarks) < policy.benchmark_research.minimum_benchmarks:
            return FirstWebsiteOutcome("research_insufficient", reason=report.failure_reason or "insufficient benchmarks")
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
