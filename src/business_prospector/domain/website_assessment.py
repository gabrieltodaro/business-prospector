from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import ValidationError
from .models import WebsiteAssessment, validate_http_url

ASSESSMENT_STATUSES = {
    "assessed",
    "unavailable",
    "blocked",
    "timeout",
    "insufficient_evidence",
    "error",
}
CRITERION_OUTCOMES = {"issue", "no_issue", "unknown"}
CRITERIA = (
    "mobile",
    "cta",
    "content",
    "social_proof",
    "layout",
    "platform",
    "broken_elements",
)
SCORING_CRITERIA = CRITERIA[:-1]


@dataclass(frozen=True, slots=True)
class CriterionEvidence:
    outcome: str
    facts: tuple[str, ...] = ()
    inference: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in CRITERION_OUTCOMES:
            raise ValidationError(f"invalid assessment outcome: {self.outcome}")
        if len(self.facts) > 10:
            raise ValidationError("assessment criterion cannot contain more than 10 facts")
        for fact in self.facts:
            if not isinstance(fact, str) or not fact.strip() or len(fact) > 500:
                raise ValidationError("assessment facts must be non-empty strings up to 500 characters")
        if self.inference is not None and (not self.inference.strip() or len(self.inference) > 500):
            raise ValidationError("assessment inference must be a non-empty string up to 500 characters")
        if self.outcome != "unknown" and not self.facts:
            raise ValidationError("observed outcomes require at least one fact")

    def to_dict(self) -> dict[str, object]:
        return {"outcome": self.outcome, "facts": list(self.facts), "inference": self.inference}


@dataclass(frozen=True, slots=True)
class WebsiteAssessmentReport:
    website_url: str
    status: str
    criteria: dict[str, CriterionEvidence]
    final_url: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        validate_http_url(self.website_url, "website_url")
        validate_http_url(self.final_url, "final_url")
        if self.status not in ASSESSMENT_STATUSES:
            raise ValidationError(f"invalid assessment status: {self.status}")
        if set(self.criteria) != set(CRITERIA):
            raise ValidationError("assessment must contain exactly the supported criteria")
        if self.failure_reason is not None and (
            not self.failure_reason.strip() or len(self.failure_reason) > 500
        ):
            raise ValidationError("failure_reason must be a non-empty string up to 500 characters")
        if self.status == "assessed":
            if self.failure_reason:
                raise ValidationError("assessed reports cannot contain a failure_reason")
        elif not self.failure_reason:
            raise ValidationError("non-assessed reports require a failure_reason")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WebsiteAssessmentReport":
        raw_criteria = payload.get("criteria")
        if not isinstance(raw_criteria, dict):
            raise ValidationError("assessment criteria must be an object")
        criteria: dict[str, CriterionEvidence] = {}
        for name, raw in raw_criteria.items():
            if not isinstance(name, str) or not isinstance(raw, dict):
                raise ValidationError("assessment criterion must be an object")
            facts = raw.get("facts", [])
            if not isinstance(facts, list) or not all(isinstance(item, str) for item in facts):
                raise ValidationError("assessment facts must be a list of strings")
            criteria[name] = CriterionEvidence(
                outcome=raw.get("outcome", ""),
                facts=tuple(facts),
                inference=raw.get("inference"),
            )
        return cls(
            website_url=payload.get("website_url", ""),
            final_url=payload.get("final_url"),
            status=payload.get("status", ""),
            failure_reason=payload.get("failure_reason"),
            criteria=criteria,
        )

    @property
    def scoring_eligible(self) -> bool:
        return self.status == "assessed" and all(
            self.criteria[name].outcome != "unknown" for name in SCORING_CRITERIA
        )

    def to_website_assessment(self) -> WebsiteAssessment:
        if not self.scoring_eligible:
            raise ValidationError("only complete assessed reports can be converted for scoring")
        issue = lambda name: self.criteria[name].outcome == "issue"
        inferences = [
            criterion.inference
            for criterion in self.criteria.values()
            if criterion.outcome == "issue" and criterion.inference
        ]
        return WebsiteAssessment(
            layout=issue("layout"),
            mobile=issue("mobile"),
            cta=issue("cta"),
            content=issue("content"),
            social_proof=issue("social_proof"),
            platform=issue("platform"),
            reason=" ".join(inferences),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "website_url": self.website_url,
            "final_url": self.final_url,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "criteria": {name: value.to_dict() for name, value in self.criteria.items()},
            "scoring_eligible": self.scoring_eligible,
        }
