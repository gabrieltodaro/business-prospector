"""Qualification invariants shared by write boundaries."""
from __future__ import annotations

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import BusinessCandidate, Lead
from business_prospector.domain.website_assessment import WebsiteAssessmentReport
from business_prospector.domain.website_presence import WebsitePresence, classify_website_presence
from .config import ProspectingConfig
from .ports import LeadRepository


def validate_redesign(
    candidate: BusinessCandidate | Lead, report: WebsiteAssessmentReport,
    config: ProspectingConfig,
) -> None:
    if candidate.rating < config.minimum_rating or candidate.review_count < config.minimum_reviews:
        raise ValidationError("reputation threshold not met")
    if classify_website_presence(candidate.website_url).presence not in {
        WebsitePresence.OWN_WEBSITE, WebsitePresence.HOSTED_WEBSITE,
    }:
        raise ValidationError("redesign requires an owned or hosted website")
    if not report.scoring_eligible or report.website_url != candidate.website_url:
        raise ValidationError("complete matching structured website evidence is required")
    if report.to_website_assessment().issue_count < config.minimum_website_issues:
        raise ValidationError("website issue threshold not met")


def validate_qualified_lead(lead: Lead, config: ProspectingConfig, repository: LeadRepository) -> None:
    if lead.opportunity_type == "redesign":
        if lead.website_assessment is None:
            raise ValidationError("structured website assessment is required to qualify a lead")
        report = WebsiteAssessmentReport.from_dict(lead.website_assessment)
        validate_redesign(lead, report, config)
        if report.to_website_assessment() != lead.assessment:
            raise ValidationError("assessment flags must match structured evidence")
    else:
        from .first_website import FirstWebsiteProspectingService
        from business_prospector.domain.first_website import FirstWebsiteMarketReport, is_first_website_candidate
        from business_prospector.domain.scoring import calculate_first_website_score
        candidate = BusinessCandidate(**{
            key: getattr(lead, key) for key in BusinessCandidate.__dataclass_fields__
        })
        report = FirstWebsiteMarketReport.from_dict(lead.market_research)
        policy = config.first_website
        if not is_first_website_candidate(candidate, policy.minimum_rating, policy.minimum_reviews):
            raise ValidationError("first website reputation or presence threshold not met")
        reason = FirstWebsiteProspectingService(repository, config).validate_benchmark_report(candidate, report)
        if reason:
            raise ValidationError(reason)
        if report.status != "complete" or calculate_first_website_score(candidate, report, policy.scoring).total < policy.minimum_score:
            raise ValidationError("first website qualification threshold not met")
