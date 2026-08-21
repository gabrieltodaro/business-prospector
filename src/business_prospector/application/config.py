from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from pathlib import Path

from business_prospector.domain.scoring import FirstWebsiteScoreWeights, ScoreWeights


@dataclass(frozen=True, slots=True)
class BenchmarkResearchPolicy:
    country: str = "BR"
    default_market: str = "São Paulo, SP"
    minimum_rating: float = 4.5
    minimum_reviews: int = 100
    minimum_benchmarks: int = 2
    max_benchmarks: int = 3
    max_candidates: int = 10

    def __post_init__(self) -> None:
        if self.country != "BR" or not self.default_market.strip():
            raise ValueError("invalid first website benchmark market")
        if not 0 <= self.minimum_rating <= 5 or self.minimum_reviews < 0:
            raise ValueError("invalid first website benchmark reputation policy")
        if not 1 <= self.minimum_benchmarks <= self.max_benchmarks <= 3:
            raise ValueError("first website benchmark limits must be between 1 and 3")
        if not self.max_benchmarks <= self.max_candidates <= 25:
            raise ValueError("invalid first website benchmark candidate limit")


@dataclass(frozen=True, slots=True)
class FirstWebsitePolicy:
    minimum_rating: float = 3.5
    minimum_reviews: int = 20
    minimum_score: int = 55
    compatible_category_groups: tuple[tuple[str, ...], ...] = (("dentist", "dental_clinic"),)
    benchmark_research: BenchmarkResearchPolicy = BenchmarkResearchPolicy()
    scoring: FirstWebsiteScoreWeights = FirstWebsiteScoreWeights()

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_rating <= 5 or self.minimum_reviews < 0:
            raise ValueError("invalid first website lead reputation policy")
        if not 0 <= self.minimum_score <= 100:
            raise ValueError("invalid first website minimum score")
        if any(len(group) < 2 or any(not isinstance(item, str) or not item.strip() for item in group)
               for group in self.compatible_category_groups):
            raise ValueError("compatible category groups must contain at least two category names")


@dataclass(frozen=True, slots=True)
class ProspectingConfig:
    minimum_rating: float = 4.7
    minimum_reviews: int = 40
    target_leads: int = 10
    max_businesses: int = 25
    minimum_website_issues: int = 2
    cities: tuple[str, ...] = field(default_factory=tuple)
    scoring: ScoreWeights = ScoreWeights()
    first_website: FirstWebsitePolicy = FirstWebsitePolicy()
    discovery_provider: str = "fake"
    browser_provider: str = "openclaw-playwright"

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_rating <= 5:
            raise ValueError("minimum_rating must be between 0 and 5")
        if self.minimum_reviews < 0:
            raise ValueError("minimum_reviews cannot be negative")
        if self.target_leads < 1 or self.max_businesses < 1:
            raise ValueError("target_leads and max_businesses must be positive")
        if self.target_leads > self.max_businesses:
            raise ValueError("target_leads cannot exceed max_businesses")
        if not 1 <= self.minimum_website_issues <= 6:
            raise ValueError("minimum_website_issues must be between 1 and 6")

    @classmethod
    def from_path(cls, path: Path) -> "ProspectingConfig":
        return cls.from_resource(path)

    @classmethod
    def from_resource(cls, resource: Traversable) -> "ProspectingConfig":
        raw = json.loads(resource.read_text(encoding="utf-8"))
        scoring = ScoreWeights(**raw.pop("scoring", {}))
        first_raw = raw.pop("first_website", {})
        first_scoring = FirstWebsiteScoreWeights(**first_raw.pop("scoring", {}))
        benchmark_research = BenchmarkResearchPolicy(**first_raw.pop("benchmark_research", {}))
        if "compatible_category_groups" in first_raw:
            first_raw["compatible_category_groups"] = tuple(
                tuple(group) for group in first_raw["compatible_category_groups"]
            )
        first_website = FirstWebsitePolicy(
            scoring=first_scoring, benchmark_research=benchmark_research, **first_raw,
        )
        raw["cities"] = tuple(raw.get("cities", ()))
        return cls(scoring=scoring, first_website=first_website, **raw)
