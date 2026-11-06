from __future__ import annotations

import json
from importlib.resources.abc import Traversable
from pathlib import Path

from business_prospector.application.ports import SearchQuery
from business_prospector.domain.models import BusinessCandidate, WebsiteAssessment
from business_prospector.domain.website_assessment import WebsiteAssessmentReport, CriterionEvidence, CRITERIA


class FakeBusinessDiscoveryProvider:
    def __init__(self, fixture_path: Path | Traversable) -> None:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        self._candidates = [BusinessCandidate(**item["business"]) for item in raw]

    def search(self, query: SearchQuery) -> list[BusinessCandidate]:
        niche = query.niche.casefold().rstrip("s")
        city = query.city.casefold()
        matches = [
            candidate for candidate in self._candidates
            if candidate.category.casefold().rstrip("s") == niche and candidate.city.casefold() == city
        ]
        return matches[: query.limit]


class FakeWebsiteAssessmentProvider:
    def __init__(self, fixture_path: Path | Traversable) -> None:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        self._assessments = {
            item["business"]["name"]: WebsiteAssessment(**item["assessment"]) for item in raw
        }

    def assess(self, candidate: BusinessCandidate) -> WebsiteAssessmentReport:
        assessment = self._assessments[candidate.name]
        return WebsiteAssessmentReport(candidate.website_url or "", "assessed", {
            name: CriterionEvidence(
                "issue" if getattr(assessment, name, False) else "no_issue",
                (f"Synthetic fixture observation: {name}",),
                assessment.reason if getattr(assessment, name, False) else None,
            ) for name in CRITERIA
        })
