from __future__ import annotations

from dataclasses import dataclass

from .models import Lead
from .website_presence import WebsitePresence, classify_website_presence
from .first_website import FirstWebsiteMarketReport


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


@dataclass(frozen=True, slots=True)
class FirstWebsiteScoreWeights:
    business_quality: int = 40
    digital_presence_gap: int = 30
    contactability: int = 15
    market_opportunity: int = 15

    def __post_init__(self) -> None:
        values = (self.business_quality, self.digital_presence_gap, self.contactability, self.market_opportunity)
        if min(values) < 0 or sum(values) != 100:
            raise ValueError("first website score weights must be non-negative and total 100")


@dataclass(frozen=True, slots=True)
class FirstWebsiteScore:
    business_quality: int
    digital_presence_gap: int
    contactability: int
    market_opportunity: int

    @property
    def total(self) -> int:
        return self.business_quality + self.digital_presence_gap + self.contactability + self.market_opportunity


def calculate_first_website_score(
    candidate: "BusinessCandidate", report: FirstWebsiteMarketReport,
    weights: FirstWebsiteScoreWeights = FirstWebsiteScoreWeights(),
) -> FirstWebsiteScore:
    rating_factor = max(0.0, min(1.0, (candidate.rating - 3.5) / 1.5))
    reviews_factor = min(1.0, candidate.review_count / 200)
    business = round(weights.business_quality * (rating_factor * 0.6 + reviews_factor * 0.4))
    presence = classify_website_presence(candidate.website_url).presence
    gap_factor = {
        WebsitePresence.NO_WEBSITE: 1.0,
        WebsitePresence.SOCIAL_ONLY: 0.85,
        WebsitePresence.THIRD_PARTY_PROFILE: 0.75,
    }.get(presence, 0.0)
    gap = round(weights.digital_presence_gap * gap_factor)
    if candidate.whatsapp_confirmed and candidate.whatsapp:
        contact_factor = 1.0
    elif candidate.phone:
        contact_factor = 0.75
    elif candidate.email:
        contact_factor = 0.55
    elif candidate.instagram or presence == WebsitePresence.SOCIAL_ONLY:
        contact_factor = 0.35
    else:
        contact_factor = 0.0
    contact = round(weights.contactability * contact_factor)
    confidence_factor = {"high": 1.0, "medium": 0.75, "low": 0.4}[report.confidence]
    evidence_factor = min(1.0, len(report.common_features) / 5)
    market = round(weights.market_opportunity * confidence_factor * (0.6 + 0.4 * evidence_factor))
    return FirstWebsiteScore(business, gap, contact, market)
