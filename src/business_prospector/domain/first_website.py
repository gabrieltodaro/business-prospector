from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from typing import Any

from .exceptions import ValidationError
from .models import BusinessCandidate
from .normalization import normalize_domain
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
class BenchmarkObservation:
    name: str
    website_url: str
    category: str | None
    rating: float | None
    review_count: int | None
    external_place_id: str | None
    facts: tuple[str, ...]
    features: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, allow_legacy: bool = False) -> "BenchmarkObservation":
        if not isinstance(payload, dict):
            raise ValidationError("benchmark observation must be an object")
        name = payload.get("name")
        website_url = payload.get("website_url")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValidationError("benchmark name is required and limited to 200 characters")
        if not isinstance(website_url, str):
            raise ValidationError("benchmark website_url is required")
        if classify_website_presence(website_url).presence not in {
            WebsitePresence.OWN_WEBSITE, WebsitePresence.HOSTED_WEBSITE,
        }:
            raise ValidationError("benchmark must have an owned or hosted website")
        category = payload.get("category")
        rating = payload.get("rating")
        review_count = payload.get("review_count")
        external_place_id = payload.get("external_place_id")
        if not allow_legacy and (not isinstance(category, str) or not category.strip()):
            raise ValidationError("benchmark category is required")
        if category is not None and (not isinstance(category, str) or not category.strip() or len(category) > 200):
            raise ValidationError("benchmark category must be a non-empty string up to 200 characters")
        if not allow_legacy and (isinstance(rating, bool) or not isinstance(rating, (int, float))):
            raise ValidationError("benchmark rating is required")
        if rating is not None and (isinstance(rating, bool) or not isinstance(rating, (int, float)) or not 0 <= rating <= 5):
            raise ValidationError("benchmark rating must be between 0 and 5")
        if not allow_legacy and (isinstance(review_count, bool) or not isinstance(review_count, int)):
            raise ValidationError("benchmark review_count is required")
        if review_count is not None and (isinstance(review_count, bool) or not isinstance(review_count, int) or review_count < 0):
            raise ValidationError("benchmark review_count cannot be negative")
        if external_place_id is not None and (
            not isinstance(external_place_id, str) or not external_place_id.strip() or len(external_place_id) > 300
        ):
            raise ValidationError("benchmark external_place_id is invalid")
        features = _bounded_strings(payload.get("features"), "features")
        if not allow_legacy and any(len(feature) > 100 for feature in features):
            raise ValidationError("observed feature names are limited to 100 characters")
        return cls(
            name=name,
            website_url=website_url,
            category=category,
            rating=float(rating) if rating is not None else None,
            review_count=review_count,
            external_place_id=external_place_id,
            facts=_bounded_strings(payload.get("facts"), "benchmark facts"),
            features=_bounded_strings(payload.get("features"), "benchmark features"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "website_url": self.website_url,
            "category": self.category,
            "rating": self.rating,
            "review_count": self.review_count,
            "external_place_id": self.external_place_id,
            "facts": list(self.facts),
            "features": list(self.features),
        }


@dataclass(frozen=True, slots=True)
class FeatureFrequency:
    feature: str
    observed_in: int
    total: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureFrequency":
        if not isinstance(payload, dict):
            raise ValidationError("feature frequency must be an object")
        feature = payload.get("feature")
        observed = payload.get("observed_in")
        total = payload.get("total")
        if not isinstance(feature, str) or not feature.strip() or len(feature) > 100:
            raise ValidationError("feature name is required and limited to 100 characters")
        if type(observed) is not int or type(total) is not int or total < 1 or observed < 0 or observed > total:
            raise ValidationError("feature frequency counts are invalid")
        return cls(feature, observed, total)

    def to_dict(self) -> dict[str, Any]:
        return {"feature": self.feature, "observed_in": self.observed_in, "total": self.total}


@dataclass(frozen=True, slots=True)
class FirstWebsiteMarketReport:
    status: str
    benchmark_market: str | None
    benchmarks: tuple[BenchmarkObservation, ...]
    common_features: tuple[FeatureFrequency, ...]
    inferences: tuple[str, ...]
    recommendations: tuple[str, ...]
    confidence: str
    failure_reason: str | None = None
    selection_id: str | None = None

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], *, allow_legacy: bool = False,
    ) -> "FirstWebsiteMarketReport":
        if not isinstance(payload, dict):
            raise ValidationError("market research must be an object")
        status = payload.get("status")
        confidence = payload.get("confidence")
        if status not in RESEARCH_STATUSES:
            raise ValidationError("invalid market research status")
        if confidence not in CONFIDENCE_LEVELS:
            raise ValidationError("invalid market research confidence")
        benchmark_market = payload.get("benchmark_market")
        if not allow_legacy and (
            not isinstance(benchmark_market, str) or not benchmark_market.strip() or len(benchmark_market) > 200
        ):
            raise ValidationError("benchmark_market is required and limited to 200 characters")
        if benchmark_market is not None and (
            not isinstance(benchmark_market, str) or not benchmark_market.strip() or len(benchmark_market) > 200
        ):
            raise ValidationError("benchmark_market must be a non-empty string up to 200 characters")
        raw_benchmarks = payload.get("benchmarks")
        if raw_benchmarks is None and allow_legacy:
            raw_benchmarks = payload.get("competitors")
        if not isinstance(raw_benchmarks, list) or len(raw_benchmarks) > 3:
            raise ValidationError("market research supports at most 3 benchmarks")
        benchmarks = tuple(
            BenchmarkObservation.from_dict(item, allow_legacy=allow_legacy) for item in raw_benchmarks
        )
        raw_features = payload.get("common_features")
        if not isinstance(raw_features, list) or len(raw_features) > 20:
            raise ValidationError("common_features supports at most 20 items")
        features = tuple(FeatureFrequency.from_dict(item) for item in raw_features)
        failure_reason = payload.get("failure_reason")
        if failure_reason is not None and (
            not isinstance(failure_reason, str) or not failure_reason.strip() or len(failure_reason) > 500
        ):
            raise ValidationError("failure_reason must be a string up to 500 characters")
        if status == "complete" and len(benchmarks) < 2:
            raise ValidationError("complete market research requires at least 2 benchmarks")
        if status == "complete" and failure_reason:
            raise ValidationError("complete market research cannot have a failure_reason")
        if status != "complete" and not failure_reason:
            raise ValidationError("incomplete market research requires a failure_reason")
        if status == "complete" and (not features or not payload.get("recommendations")):
            raise ValidationError("complete market research requires features and recommendations")
        if any(item.total != len(benchmarks) for item in features):
            raise ValidationError("feature totals must equal benchmarks inspected")
        selection_id = payload.get("selection_id")
        if selection_id is not None and (
            not isinstance(selection_id, str) or not selection_id.strip() or len(selection_id) > 100
        ):
            raise ValidationError("invalid benchmark selection_id")
        if not allow_legacy:
            domains = [normalize_domain(item.website_url) for item in benchmarks]
            if len(set(domains)) != len(domains):
                raise ValidationError("duplicate benchmark website")
            place_ids = [item.external_place_id for item in benchmarks if item.external_place_id]
            if len(set(place_ids)) != len(place_ids):
                raise ValidationError("duplicate benchmark external_place_id")
            if status == "complete" and any(not item.facts or not item.features for item in benchmarks):
                raise ValidationError("complete benchmarks require facts and observed features")
            counts = Counter(feature for item in benchmarks for feature in set(item.features))
            if len({item.feature for item in features}) != len(features):
                raise ValidationError("duplicate common feature")
            if any(counts[item.feature] != item.observed_in or item.observed_in == 0 for item in features):
                raise ValidationError("common features must be supported by benchmark observations")
            if len(counts) > 20:
                raise ValidationError("observations support at most 20 distinct features")
            features = tuple(FeatureFrequency(feature, counts[feature], len(benchmarks))
                             for feature in sorted(counts))
        return cls(
            status=status,
            benchmark_market=benchmark_market,
            benchmarks=benchmarks,
            common_features=features,
            inferences=_bounded_strings(payload.get("inferences"), "inferences"),
            recommendations=_bounded_strings(payload.get("recommendations"), "recommendations"),
            confidence=confidence,
            failure_reason=failure_reason,
            selection_id=selection_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "benchmark_market": self.benchmark_market,
            "benchmarks": [item.to_dict() for item in self.benchmarks],
            "common_features": [item.to_dict() for item in self.common_features],
            "inferences": list(self.inferences),
            "recommendations": list(self.recommendations),
            "confidence": self.confidence,
            "failure_reason": self.failure_reason,
            "selection_id": self.selection_id,
        }


def is_first_website_candidate(candidate: BusinessCandidate, minimum_rating: float, minimum_reviews: int) -> bool:
    return (
        classify_website_presence(candidate.website_url).presence in FIRST_WEBSITE_PRESENCES
        and candidate.rating >= minimum_rating
        and candidate.review_count >= minimum_reviews
    )
