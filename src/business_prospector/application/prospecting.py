from __future__ import annotations

from dataclasses import dataclass, field

from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment
from business_prospector.domain.scoring import calculate_score

from .config import ProspectingConfig
from .ports import BusinessDiscoveryProvider, LeadRepository, SearchQuery, WebsiteAssessmentProvider


@dataclass(slots=True)
class ProspectingResult:
    leads: list[Lead] = field(default_factory=list)
    inspected: int = 0
    rejected_reputation: int = 0
    rejected_no_website: int = 0
    rejected_website: int = 0
    duplicates: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "leads": [lead.to_dict() for lead in self.leads],
            "inspected": self.inspected,
            "rejected_reputation": self.rejected_reputation,
            "rejected_no_website": self.rejected_no_website,
            "rejected_website": self.rejected_website,
            "duplicates": self.duplicates,
        }


class ProspectingService:
    def __init__(
        self,
        discovery: BusinessDiscoveryProvider,
        assessment: WebsiteAssessmentProvider,
        repository: LeadRepository,
        config: ProspectingConfig,
    ) -> None:
        self._discovery = discovery
        self._assessment = assessment
        self._repository = repository
        self._config = config

    def prospect(self, niche: str, city: str) -> ProspectingResult:
        query = SearchQuery(niche=niche, city=city, limit=self._config.max_businesses)
        result = ProspectingResult()
        for candidate in self._discovery.search(query)[: self._config.max_businesses]:
            result.inspected += 1
            if not self._passes_reputation(candidate):
                result.rejected_reputation += 1
                continue
            if not candidate.website_url:
                # TODO(first-website-opportunity): A reputable business without a website is a
                # separate future opportunity type, not a permanently worthless/rejected lead.
                # Build a distinct >=3.5-rating pipeline with competitor research and a
                # from-scratch website strategy; do not mix it into redesign qualification.
                result.rejected_no_website += 1
                continue
            if self._repository.find_duplicate(candidate):
                result.duplicates += 1
                continue
            assessment = self._assessment.assess(candidate)
            if assessment.issue_count < self._config.minimum_website_issues:
                result.rejected_website += 1
                continue
            lead = self._to_lead(candidate, assessment)
            lead.score = calculate_score(lead, self._config.scoring).total
            result.leads.append(self._repository.save(lead))
            if len(result.leads) >= self._config.target_leads:
                break
        result.leads.sort(key=lambda item: (-item.score, -item.review_count, item.name))
        return result

    def _passes_reputation(self, candidate: BusinessCandidate) -> bool:
        return candidate.rating >= self._config.minimum_rating and candidate.review_count >= self._config.minimum_reviews

    @staticmethod
    def _to_lead(candidate: BusinessCandidate, assessment: WebsiteAssessment) -> Lead:
        return Lead(
            name=candidate.name,
            category=candidate.category,
            city=candidate.city,
            rating=candidate.rating,
            review_count=candidate.review_count,
            website_url=candidate.website_url or "",
            assessment=assessment,
            external_place_id=candidate.external_place_id,
            address=candidate.address,
            maps_url=candidate.maps_url,
            phone=candidate.phone,
            whatsapp=candidate.whatsapp,
            whatsapp_confirmed=candidate.whatsapp_confirmed,
            whatsapp_source=candidate.whatsapp_source,
            email=candidate.email,
            instagram=candidate.instagram,
            source=candidate.source,
        )
