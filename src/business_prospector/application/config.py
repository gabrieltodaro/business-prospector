from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from pathlib import Path

from business_prospector.domain.scoring import ScoreWeights


@dataclass(frozen=True, slots=True)
class ProspectingConfig:
    minimum_rating: float = 4.7
    minimum_reviews: int = 40
    target_leads: int = 10
    max_businesses: int = 25
    minimum_website_issues: int = 2
    cities: tuple[str, ...] = field(default_factory=tuple)
    scoring: ScoreWeights = ScoreWeights()
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
        raw["cities"] = tuple(raw.get("cities", ()))
        return cls(scoring=scoring, **raw)
