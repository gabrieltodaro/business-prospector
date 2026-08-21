from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any
from importlib.resources.abc import Traversable

from mcp.server.fastmcp import FastMCP

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.batch import BatchProspectingService
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.ports import SearchQuery
from business_prospector.application.prospecting import ProspectingService
from business_prospector.application.site_generation import SiteGenerationService, controlled_sites_root
from business_prospector.domain.exceptions import ProspectorError
from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment
from business_prospector.domain.scoring import calculate_score
from business_prospector.domain.scoring import calculate_first_website_score
from business_prospector.domain.first_website import FirstWebsiteMarketReport
from business_prospector.domain.website_assessment import WebsiteAssessmentReport
from business_prospector.infrastructure.fake_providers import (
    FakeBusinessDiscoveryProvider,
    FakeWebsiteAssessmentProvider,
)
from business_prospector.infrastructure.google_places import GooglePlacesBusinessDiscoveryProvider
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.package_resources import default_config_resource, fake_dentists_resource

LOGGER = logging.getLogger("business_prospector.mcp")
mcp = FastMCP("business-prospector")


def _data_dir() -> Path:
    configured = os.environ.get("BUSINESS_PROSPECTOR_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".openclaw" / "data" / "business-prospector").resolve()


def _config_resource() -> Traversable:
    configured = os.environ.get("BUSINESS_PROSPECTOR_CONFIG")
    return Path(configured).expanduser().resolve() if configured else default_config_resource()


def _repository() -> SQLiteLeadRepository:
    return SQLiteLeadRepository(_data_dir() / "business-prospector.db")


def _sites_root() -> Path:
    return controlled_sites_root(_data_dir())


def _response(action: str, data: Any = None, error: str | None = None) -> dict[str, Any]:
    return {"ok": error is None, "action": action, "data": data, "error": error}


@mcp.tool()
def list_leads(limit: int = 100) -> dict[str, Any]:
    """List prospecting leads ordered by score, then review count."""
    try:
        return _response("list_leads", [lead.to_dict() for lead in _repository().list(limit)])
    except (ProspectorError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("list_leads failed: %s", exc)
        return _response("list_leads", error=str(exc))


@mcp.tool()
def get_lead(lead_id: int) -> dict[str, Any]:
    """Get a prospecting lead by its numeric identifier."""
    try:
        lead = _repository().get(lead_id)
        return _response("get_lead", lead.to_dict() if lead else None, None if lead else "lead not found")
    except (ProspectorError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("get_lead failed for %s: %s", lead_id, exc)
        return _response("get_lead", error=str(exc))


@mcp.tool()
def find_duplicate(
    name: str,
    city: str,
    website_url: str = "",
    phone: str = "",
    whatsapp: str = "",
    address: str = "",
    external_place_id: str = "",
) -> dict[str, Any]:
    """Check layered duplicate signals before saving a candidate."""
    try:
        candidate = BusinessCandidate(
            name=name, category="unknown", city=city, rating=0, review_count=0,
            website_url=website_url or None, phone=phone or None, whatsapp=whatsapp or None,
            address=address or None, external_place_id=external_place_id or None,
        )
        match = _repository().find_duplicate(candidate)
        return _response("find_duplicate", None if match is None else {
            "lead_id": match.lead_id, "match_type": match.match_type, "confidence": match.confidence,
        })
    except (ProspectorError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("find_duplicate failed: %s", exc)
        return _response("find_duplicate", error=str(exc))


@mcp.tool()
def save_lead(
    name: str,
    category: str,
    city: str,
    rating: float,
    review_count: int,
    website_url: str,
    layout_issue: bool,
    mobile_issue: bool,
    cta_issue: bool,
    content_issue: bool,
    social_proof_issue: bool,
    platform_issue: bool,
    qualification_reason: str,
    external_place_id: str = "",
    address: str = "",
    maps_url: str = "",
    phone: str = "",
    whatsapp: str = "",
    whatsapp_confirmed: bool = False,
    whatsapp_source: str = "unknown",
    email: str = "",
    instagram: str = "",
    source: str = "manual",
) -> dict[str, Any]:
    """Validate, deterministically score, deduplicate, and save one qualified lead."""
    try:
        assessment = WebsiteAssessment(
            layout_issue, mobile_issue, cta_issue, content_issue, social_proof_issue, platform_issue,
            qualification_reason,
        )
        lead = Lead(
            name=name, category=category, city=city, rating=rating, review_count=review_count,
            website_url=website_url, assessment=assessment, external_place_id=external_place_id or None,
            address=address or None, maps_url=maps_url or None, phone=phone or None,
            whatsapp=whatsapp or None, whatsapp_confirmed=whatsapp_confirmed,
            whatsapp_source=whatsapp_source, email=email or None, instagram=instagram or None, source=source,
        )
        repository = _repository()
        duplicate = repository.find_duplicate(lead)
        if duplicate:
            return _response("save_lead", error=f"duplicate lead {duplicate.lead_id} ({duplicate.match_type})")
        config = ProspectingConfig.from_resource(_config_resource())
        if assessment.issue_count < config.minimum_website_issues:
            return _response("save_lead", error="website does not meet the configured issue threshold")
        lead.score = calculate_score(lead, config.scoring).total
        return _response("save_lead", repository.save(lead).to_dict())
    except (ProspectorError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("save_lead failed for %r: %s", name, exc)
        return _response("save_lead", error=str(exc))


@mcp.tool()
def update_lead(
    lead_id: int,
    name: str | None = None,
    category: str | None = None,
    city: str | None = None,
    address: str | None = None,
    maps_url: str | None = None,
    rating: float | None = None,
    review_count: int | None = None,
    website_url: str | None = None,
    phone: str | None = None,
    whatsapp: str | None = None,
    whatsapp_confirmed: bool | None = None,
    whatsapp_source: str | None = None,
    email: str | None = None,
    instagram: str | None = None,
    status: str | None = None,
    external_place_id: str | None = None,
) -> dict[str, Any]:
    """Update validated prospecting fields on an existing lead."""
    try:
        changes = {key: value for key, value in locals().items() if key != "lead_id" and value is not None}
        repository = _repository()
        lead = repository.update(lead_id, changes)
        config = ProspectingConfig.from_resource(_config_resource())
        if lead.opportunity_type == "first_website" and lead.market_research is not None:
            candidate = BusinessCandidate(
                name=lead.name, category=lead.category, city=lead.city, rating=lead.rating,
                review_count=lead.review_count, website_url=lead.website_url or None,
                external_place_id=lead.external_place_id, address=lead.address, maps_url=lead.maps_url,
                phone=lead.phone, whatsapp=lead.whatsapp, whatsapp_confirmed=lead.whatsapp_confirmed,
                whatsapp_source=lead.whatsapp_source, email=lead.email, instagram=lead.instagram,
                source=lead.source,
            )
            lead.score = calculate_first_website_score(
                candidate, FirstWebsiteMarketReport.from_dict(
                    lead.market_research, allow_legacy=True,
                ), config.first_website.scoring,
            ).total
        else:
            lead.score = calculate_score(lead, config.scoring).total
        lead = repository.update(lead_id, {"score": lead.score})
        return _response("update_lead", lead.to_dict())
    except (ProspectorError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("update_lead failed for %s: %s", lead_id, exc)
        return _response("update_lead", error=str(exc))


@mcp.tool()
def prospect_fake(niche: str, city: str) -> dict[str, Any]:
    """Run the deterministic offline fixture pipeline; never calls Google or the network."""
    try:
        fixture = fake_dentists_resource()
        service = ProspectingService(
            FakeBusinessDiscoveryProvider(fixture),
            FakeWebsiteAssessmentProvider(fixture),
            _repository(),
            ProspectingConfig.from_resource(_config_resource()),
        )
        return _response("prospect_fake", service.prospect(niche, city).to_dict())
    except (ProspectorError, ValueError, OSError, KeyError, sqlite3.Error) as exc:
        LOGGER.warning("prospect_fake failed: %s", exc)
        return _response("prospect_fake", error=str(exc))


@mcp.tool()
def google_places_status() -> dict[str, Any]:
    """Report whether Google Places is configured without exposing its API key."""
    return _response(
        "google_places_status",
        {"google_places_configured": GooglePlacesBusinessDiscoveryProvider().configured},
    )


@mcp.tool()
def prospect_places(niche: str, city: str, limit: int = 10) -> dict[str, Any]:
    """Run one bounded Places API (New) discovery; website assessment is not performed."""
    try:
        safe_limit = max(1, min(limit, 25))
        candidates = GooglePlacesBusinessDiscoveryProvider().search(
            SearchQuery(niche=niche, city=city, limit=safe_limit)
        )
        return _response("prospect_places", {
            "candidates": [candidate.to_dict() for candidate in candidates],
            "count": len(candidates),
            "website_assessment": "not_run",
            "leads_saved": 0,
        })
    except (ProspectorError, ValueError, OSError) as exc:
        LOGGER.warning("prospect_places failed: %s", exc)
        return _response("prospect_places", error=str(exc))


@mcp.tool()
def prepare_batch_candidates(
    candidates: list[dict[str, Any]],
    target_qualified_leads: int = 10,
    max_candidates: int = 25,
    batch_id: str = "",
    mode: str = "redesign",
) -> dict[str, Any]:
    """Deterministically prefilter one bounded Places result before any browser work."""
    try:
        service = BatchProspectingService(
            _repository(), ProspectingConfig.from_resource(_config_resource())
        )
        prepared = service.prepare(
            candidates,
            batch_id=batch_id or None,
            target_qualified_leads=target_qualified_leads,
            max_candidates=max_candidates,
            mode=mode,
        )
        return _response("prepare_batch_candidates", prepared.to_dict())
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("prepare_batch_candidates failed: %s", exc)
        return _response("prepare_batch_candidates", error=str(exc))


@mcp.tool()
def qualify_and_save_candidate(
    candidate: dict[str, Any],
    assessment: dict[str, Any],
    batch_id: str,
    contacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate evidence, recheck duplicates, score in Python, and save one qualified lead."""
    try:
        service = BatchProspectingService(
            _repository(), ProspectingConfig.from_resource(_config_resource())
        )
        outcome = service.qualify_and_save(candidate, assessment, batch_id, contacts)
        return _response("qualify_and_save_candidate", outcome.to_dict())
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("qualify_and_save_candidate failed: %s", exc)
        return _response("qualify_and_save_candidate", error=str(exc))


@mcp.tool()
def get_first_website_benchmark_policy() -> dict[str, Any]:
    """Return the configured market and deterministic benchmark selection limits."""
    try:
        config = ProspectingConfig.from_resource(_config_resource())
        policy = config.first_website.benchmark_research
        return _response("get_first_website_benchmark_policy", {
            "country": policy.country,
            "benchmark_market": policy.default_market,
            "minimum_rating": policy.minimum_rating,
            "minimum_reviews": policy.minimum_reviews,
            "minimum_benchmarks": policy.minimum_benchmarks,
            "max_benchmarks": policy.max_benchmarks,
            "max_candidates": policy.max_candidates,
        })
    except (ProspectorError, TypeError, ValueError, OSError) as exc:
        return _response("get_first_website_benchmark_policy", error=str(exc))


@mcp.tool()
def select_first_website_benchmarks(
    target: dict[str, Any], candidates: list[dict[str, Any]], max_benchmarks: int = 2,
) -> dict[str, Any]:
    """Select the strongest bounded market benchmarks for first-website research."""
    try:
        service = FirstWebsiteProspectingService(
            _repository(), ProspectingConfig.from_resource(_config_resource())
        )
        selection = service.select_benchmarks(target, candidates, max_benchmarks)
        return _response("select_first_website_benchmarks", selection.to_dict())
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("select_first_website_benchmarks", error=str(exc))


@mcp.tool()
def select_first_website_competitors(
    target: dict[str, Any], candidates: list[dict[str, Any]], max_competitors: int = 2,
) -> dict[str, Any]:
    """Deprecated alias for select_first_website_benchmarks."""
    try:
        service = FirstWebsiteProspectingService(
            _repository(), ProspectingConfig.from_resource(_config_resource())
        )
        selection = service.select_benchmarks(target, candidates, max_competitors)
        data = selection.to_dict()
        data["deprecated"] = "use select_first_website_benchmarks"
        return _response("select_first_website_competitors", data)
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("select_first_website_competitors", error=str(exc))


@mcp.tool()
def validate_first_website_market_research(research: dict[str, Any]) -> dict[str, Any]:
    """Validate bounded benchmark facts, inferences and recommendations without browsing."""
    try:
        from business_prospector.domain.first_website import FirstWebsiteMarketReport
        report = FirstWebsiteMarketReport.from_dict(research)
        config = ProspectingConfig.from_resource(_config_resource())
        benchmark_policy = config.first_website.benchmark_research
        if report.benchmark_market != benchmark_policy.default_market:
            raise ValueError("benchmark_market does not match configured market")
        if any(
            item.rating is None or item.rating < benchmark_policy.minimum_rating or
            item.review_count is None or item.review_count < benchmark_policy.minimum_reviews
            for item in report.benchmarks
        ):
            raise ValueError("market research contains benchmark below configured reputation policy")
        return _response("validate_first_website_market_research", {"report": report.to_dict()})
    except (ProspectorError, TypeError, ValueError) as exc:
        return _response("validate_first_website_market_research", error=str(exc))


@mcp.tool()
def qualify_and_save_first_website_candidate(
    candidate: dict[str, Any], research: dict[str, Any], batch_id: str,
    contacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministically score and save one qualified first-website opportunity."""
    try:
        service = FirstWebsiteProspectingService(
            _repository(), ProspectingConfig.from_resource(_config_resource())
        )
        outcome = service.qualify_and_save(candidate, research, batch_id, contacts)
        return _response("qualify_and_save_first_website_candidate", outcome.to_dict())
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("qualify_and_save_first_website_candidate", error=str(exc))


@mcp.tool()
def generate_first_website_draft(
    lead: dict[str, Any], research: dict[str, Any], overwrite: bool = False,
) -> dict[str, Any]:
    """Generate one qualified first-website draft locally; never deploys or contacts anyone."""
    try:
        result = SiteGenerationService(_sites_root()).generate(lead, research, overwrite=overwrite)
        return _response("generate_first_website_draft", result.to_dict(), result.error)
    except (ProspectorError, TypeError, ValueError, OSError) as exc:
        LOGGER.warning("generate_first_website_draft failed: %s", exc)
        return _response("generate_first_website_draft", error=str(exc))


@mcp.tool()
def validate_website_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    """Validate Playwright-derived facts/inferences; never browses, scores, or saves a lead."""
    try:
        report = WebsiteAssessmentReport.from_dict(assessment)
        data: dict[str, Any] = {"report": report.to_dict(), "legacy_assessment": None}
        if report.scoring_eligible:
            legacy = report.to_website_assessment()
            data["legacy_assessment"] = {
                "layout_issue": legacy.layout,
                "mobile_issue": legacy.mobile,
                "cta_issue": legacy.cta,
                "content_issue": legacy.content,
                "social_proof_issue": legacy.social_proof,
                "platform_issue": legacy.platform,
                "qualification_reason": legacy.reason,
                "website_issue_count": legacy.issue_count,
            }
        return _response("validate_website_assessment", data)
    except (ProspectorError, TypeError, ValueError) as exc:
        LOGGER.warning("validate_website_assessment failed: %s", exc)
        return _response("validate_website_assessment", error=str(exc))


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("BUSINESS_PROSPECTOR_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    LOGGER.info("starting MCP with data directory %s", _data_dir())
    mcp.run()
