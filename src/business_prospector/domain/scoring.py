from __future__ import annotations

from dataclasses import dataclass

from .models import Lead


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    business_quality: int = 40
    website_opportunity: int = 40
    contactability: int = 20

    def __post_init__(self) -> None:
        if min(self.business_quality, self.website_opportunity, self.contactability) < 0:
            raise ValueError("score weights cannot be negative")
        if self.business_quality + self.website_opportunity + self.contactability != 100:
            raise ValueError("score weights must total 100")


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    business_quality: int
    website_opportunity: int
    contactability: int

    @property
    def total(self) -> int:
        return self.business_quality + self.website_opportunity + self.contactability


def calculate_score(lead: Lead, weights: ScoreWeights = ScoreWeights()) -> ScoreBreakdown:
    rating_factor = max(0.0, min(1.0, (lead.rating - 4.0) / 1.0))
    reviews_factor = min(1.0, lead.review_count / 200)
    business = round(weights.business_quality * (rating_factor * 0.6 + reviews_factor * 0.4))

    issue_factor = min(1.0, lead.assessment.issue_count / 4)
    website = round(weights.website_opportunity * issue_factor)

    if lead.whatsapp_confirmed and lead.whatsapp:
        contact_factor = 1.0
    elif lead.phone:
        contact_factor = 0.75
    elif lead.email:
        contact_factor = 0.55
    elif lead.instagram:
        contact_factor = 0.35
    else:
        contact_factor = 0.0
    contact = round(weights.contactability * contact_factor)
    return ScoreBreakdown(business, website, contact)

