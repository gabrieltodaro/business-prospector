from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import ValidationError
from .models import BusinessCandidate
from .website_presence import WebsitePresence, classify_website_presence

FIRST_WEBSITE_PRESENCES = {
    WebsitePresence.NO_WEBSITE,
    WebsitePresence.SOCIAL_ONLY,
    WebsitePresence.THIRD_PARTY_PROFILE,
}
RESEARCH_STATUSES = {"complete", "insufficient", "failed"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}


def _bounded_strings(value: Any, field_name: str, maximum: int = 20) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValidationError(f"{field_name} must be a list with at most {maximum} items")
    if not all(isinstance(item, str) and item.strip() and len(item) <= 500 for item in value):
        raise ValidationError(f"{field_name} items must be non-empty strings up to 500 characters")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class CompetitorObservation:
    name: str
    website_url: str
    facts: tuple[str, ...]
    features: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompetitorObservation":
        name = payload.get("name")
        website_url = payload.get("website_url")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValidationError("competitor name is required and limited to 200 characters")
        if classify_website_presence(website_url).presence not in {
            WebsitePresence.OWN_WEBSITE, WebsitePresence.HOSTED_WEBSITE,
        }:
            raise ValidationError("competitor must have an owned or hosted website")
        return cls(
            name=name,
            website_url=website_url,
            facts=_bounded_strings(payload.get("facts"), "competitor facts"),
            features=_bounded_strings(payload.get("features"), "competitor features"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "website_url": self.website_url, "facts": list(self.facts), "features": list(self.features)}


@dataclass(frozen=True, slots=True)
class FeatureFrequency:
    feature: str
    observed_in: int
    total: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureFrequency":
        feature = payload.get("feature")
        observed = payload.get("observed_in")
        total = payload.get("total")
        if not isinstance(feature, str) or not feature.strip() or len(feature) > 100:
            raise ValidationError("feature name is required and limited to 100 characters")
        if not isinstance(observed, int) or not isinstance(total, int) or total < 1 or observed < 0 or observed > total:
            raise ValidationError("feature frequency counts are invalid")
        return cls(feature, observed, total)

    def to_dict(self) -> dict[str, Any]:
        return {"feature": self.feature, "observed_in": self.observed_in, "total": self.total}


@dataclass(frozen=True, slots=True)
class FirstWebsiteMarketReport:
    status: str
    competitors: tuple[CompetitorObservation, ...]
    common_features: tuple[FeatureFrequency, ...]
    inferences: tuple[str, ...]
    recommendations: tuple[str, ...]
    confidence: str
    failure_reason: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FirstWebsiteMarketReport":
        if not isinstance(payload, dict):
            raise ValidationError("market research must be an object")
        status = payload.get("status")
        confidence = payload.get("confidence")
        if status not in RESEARCH_STATUSES:
            raise ValidationError("invalid market research status")
        if confidence not in CONFIDENCE_LEVELS:
            raise ValidationError("invalid market research confidence")
        raw_competitors = payload.get("competitors")
        if not isinstance(raw_competitors, list) or len(raw_competitors) > 3:
            raise ValidationError("market research supports at most 3 competitors")
        competitors = tuple(CompetitorObservation.from_dict(item) for item in raw_competitors)
        raw_features = payload.get("common_features")
        if not isinstance(raw_features, list) or len(raw_features) > 20:
            raise ValidationError("common_features supports at most 20 items")
        features = tuple(FeatureFrequency.from_dict(item) for item in raw_features)
        failure_reason = payload.get("failure_reason")
        if failure_reason is not None and (
            not isinstance(failure_reason, str) or not failure_reason.strip() or len(failure_reason) > 500
        ):
            raise ValidationError("failure_reason must be a string up to 500 characters")
        if status == "complete" and len(competitors) < 2:
            raise ValidationError("complete market research requires at least 2 competitors")
        if status == "complete" and failure_reason:
            raise ValidationError("complete market research cannot have a failure_reason")
        if status != "complete" and not failure_reason:
            raise ValidationError("incomplete market research requires a failure_reason")
        if status == "complete" and (not features or not payload.get("recommendations")):
            raise ValidationError("complete market research requires features and recommendations")
        if any(item.total != len(competitors) for item in features):
            raise ValidationError("feature totals must equal competitors inspected")
        return cls(
            status=status,
            competitors=competitors,
            common_features=features,
            inferences=_bounded_strings(payload.get("inferences"), "inferences"),
            recommendations=_bounded_strings(payload.get("recommendations"), "recommendations"),
            confidence=confidence,
            failure_reason=failure_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "competitors": [item.to_dict() for item in self.competitors],
            "common_features": [item.to_dict() for item in self.common_features],
            "inferences": list(self.inferences),
            "recommendations": list(self.recommendations),
            "confidence": self.confidence,
            "failure_reason": self.failure_reason,
        }


def is_first_website_candidate(candidate: BusinessCandidate, minimum_rating: float, minimum_reviews: int) -> bool:
    return (
        classify_website_presence(candidate.website_url).presence in FIRST_WEBSITE_PRESENCES
        and candidate.rating >= minimum_rating
        and candidate.review_count >= minimum_reviews
    )
