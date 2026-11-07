from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any
from importlib.resources.abc import Traversable

from mcp.server.fastmcp import FastMCP

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.deployment import SalesPreviewDeploymentService
from business_prospector.application.batch import BatchProspectingService
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.application.ports import SearchQuery
from business_prospector.application.prospecting import ProspectingService
from business_prospector.application.site_generation import (
    SiteDraftService,
    PersistedSiteGenerationWorkflow,
    SiteGenerationService,
    controlled_sites_root,
)
from business_prospector.application.site_assets import SiteAssetCandidateValidator
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.domain.exceptions import ProspectorError
from business_prospector.domain.models import BusinessCandidate, WebsiteAssessment
from business_prospector.domain.first_website import FirstWebsiteMarketReport
from business_prospector.domain.website_assessment import WebsiteAssessmentReport
from business_prospector.infrastructure.fake_providers import (
    FakeBusinessDiscoveryProvider,
    FakeWebsiteAssessmentProvider,
)
from business_prospector.infrastructure.google_places import GooglePlacesBusinessDiscoveryProvider
from business_prospector.infrastructure.cpanel import (
    CPanelDeploymentConfig,
    CPanelError,
    CPanelUapiClient,
    HostGatorPreviewDeploymentProvider,
    cpanel_connection_test as run_cpanel_connection_test,
    cpanel_configuration_status,
)
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.infrastructure.local_site_assets import LocalSiteAssetLibrary
from business_prospector.package_resources import fake_dentists_resource
from business_prospector.application.runtime import data_directory
from business_prospector.application.lead_update import LeadUpdateService
from business_prospector.application.lead_status import LeadStatusService
from business_prospector.application.research_refresh import ResearchRefreshService

LOGGER = logging.getLogger("business_prospector.mcp")
mcp = FastMCP("business-prospector")


def _data_dir() -> Path:
    return data_directory()


def _config_resource() -> Traversable:
    from business_prospector.application.runtime import config_resource
    return config_resource()


def _repository() -> SQLiteLeadRepository:
    return SQLiteLeadRepository(_data_dir() / "business-prospector.db")


def _sites_root() -> Path:
    return controlled_sites_root(_data_dir())


def _deployment_service() -> SalesPreviewDeploymentService:
    config = CPanelDeploymentConfig.from_environment()
    if config is None:
        raise ValueError("cPanel deployment is not configured")
    client = CPanelUapiClient(config)
    provider = HostGatorPreviewDeploymentProvider(config, client)
    return SalesPreviewDeploymentService(
        _repository(), SiteDraftService(_sites_root()), provider,
    )


def _response(action: str, data: Any = None, error: str | None = None) -> dict[str, Any]:
    return {"ok": error is None, "action": action, "data": data, "error": error}


@mcp.tool()
def list_leads(limit: int = 100) -> dict[str, Any]:
    """List prospecting leads ordered by score, then review count."""
    try:
        return _response("list_leads", [lead.to_dict() for lead in _repository().list(limit)])
    except (ProspectorError, ValueError, TypeError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("list_leads failed: %s", exc)
        return _response("list_leads", error=str(exc))


@mcp.tool()
def get_lead(lead_id: int) -> dict[str, Any]:
    """Get a prospecting lead by its numeric identifier."""
    try:
        lead = _repository().get(lead_id)
        return _response("get_lead", lead.to_dict() if lead else None, None if lead else "lead not found")
    except (ProspectorError, ValueError, TypeError, OSError, sqlite3.Error) as exc:
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
    except (ProspectorError, ValueError, TypeError, OSError, sqlite3.Error) as exc:
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
    website_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, deterministically score, deduplicate, and save one qualified lead."""
    try:
        if website_assessment is None:
            raise ValueError("structured website_assessment is required; use qualify_and_save_candidate")
        report = WebsiteAssessmentReport.from_dict(website_assessment)
        expected = WebsiteAssessment(
            layout_issue, mobile_issue, cta_issue, content_issue, social_proof_issue, platform_issue,
            qualification_reason,
        )
        if report.to_website_assessment() != expected:
            raise ValueError("assessment flags and reason must match structured evidence")
        candidate = BusinessCandidate(
            name=name, category=category, city=city, rating=rating, review_count=review_count,
            website_url=website_url, external_place_id=external_place_id or None,
            address=address or None, maps_url=maps_url or None, phone=phone or None,
            whatsapp=whatsapp or None, whatsapp_confirmed=whatsapp_confirmed,
            whatsapp_source=whatsapp_source, email=email or None, instagram=instagram or None, source=source,
        )
        outcome = BatchProspectingService(
            _repository(), ProspectingConfig.from_resource(_config_resource()),
        ).qualify_and_save(candidate.to_dict(), report.to_dict(), BatchProspectingService.new_batch_id())
        if outcome.lead is None:
            return _response("save_lead", error=outcome.reason or outcome.outcome)
        return _response("save_lead", outcome.lead.to_dict())
    except (ProspectorError, ValueError, TypeError, OSError, sqlite3.Error) as exc:
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
        config = ProspectingConfig.from_resource(_config_resource())
        statuses = LeadStatusService(repository, drafts=SiteDraftService(_sites_root()), config=config)
        lead = LeadUpdateService(repository, statuses, config).update(lead_id, changes)
        return _response("update_lead", lead.to_dict())
    except (ProspectorError, ValueError, TypeError, OSError, sqlite3.Error) as exc:
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
        repository = _repository()
        receipt = repository.get_benchmark_selection(report.selection_id) if report.selection_id else None
        if receipt is None:
            raise ValueError("valid benchmark selection_id is required")
        reason = FirstWebsiteProspectingService(repository, config).validate_benchmark_report(
            BusinessCandidate(**receipt["target"]), report,
        )
        if reason:
            raise ValueError(reason)
        return _response("validate_first_website_market_research", {"report": report.to_dict()})
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
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
def refresh_first_website_research(lead_id: int, research: dict[str, Any]) -> dict[str, Any]:
    """Replace qualified first-website research using a valid saved benchmark selection.

    Archives unpublished drafts and invalidates their approvals. Keeps the lead qualified;
    call generate_first_website_draft with the returned lead and its market_research next.
    """
    try:
        result = ResearchRefreshService(
            _repository(), ProspectingConfig.from_resource(_config_resource()), _sites_root(),
        ).refresh(lead_id, research)
        return _response("refresh_first_website_research", result.to_dict())
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("refresh_first_website_research", error=str(exc))


@mcp.tool()
def generate_first_website_draft(
    lead: dict[str, Any], research: dict[str, Any], overwrite: bool = False,
    reviewed_content: dict[str, Any] | None = None, asset_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a persisted qualified lead draft, then mark it internal_website."""
    try:
        lead_id = lead.get("id") if isinstance(lead, dict) else None
        repository = _repository()
        result, updated = PersistedSiteGenerationWorkflow(
            repository, SiteGenerationService(_sites_root()), LocalSiteAssetLibrary(_data_dir() / "reviewed-assets"),
        ).generate(lead_id, research, overwrite=overwrite, reviewed_content=reviewed_content, asset_keys=asset_keys)
        data = result.to_dict()
        data["lead_status"] = updated.status if updated else None
        return _response("generate_first_website_draft", data, result.error)
    except (ProspectorError, TypeError, ValueError, OSError) as exc:
        LOGGER.warning("generate_first_website_draft failed: %s", exc)
        return _response("generate_first_website_draft", error=str(exc))


@mcp.tool()
def revise_first_website_draft(
    lead_id: int, reviewed_content: dict[str, Any] | None = None,
    asset_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Revise an unpublished internal draft; preserve its prior revision and require fresh approval."""
    try:
        result, updated = PersistedSiteGenerationWorkflow(
            _repository(), SiteGenerationService(_sites_root()),
            LocalSiteAssetLibrary(_data_dir() / "reviewed-assets"),
        ).revise(lead_id, reviewed_content=reviewed_content, asset_keys=asset_keys)
        data = result.to_dict()
        data["lead_status"] = updated.status if updated else None
        return _response("revise_first_website_draft", data, result.error)
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("revise_first_website_draft", error=str(exc))


def _stock_service():
    from business_prospector.application.stock_photography import StockPhotographyService
    from business_prospector.infrastructure.pexels import PexelsStockPhotoProvider
    key = os.environ.get("PEXELS_API_KEY", "")
    provider = PexelsStockPhotoProvider(key, _data_dir() / "stock-cache") if key else None
    return StockPhotographyService(_repository(), provider, _data_dir())


@mcp.tool()
def search_stock_photos(lead_id: int, reviewed_content: dict[str, Any] | None = None) -> dict[str, Any]:
    """Find category/research-matched illustrative stock candidates; never approve or generate automatically.

    Display the returned Pexels and photographer attribution links while reviewing candidates.
    Missing configuration, unavailable providers and unsuitable results use typography fallback.
    """
    from business_prospector.infrastructure.pexels import StockProviderUnavailable
    try:
        return _response("search_stock_photos", _stock_service().search(lead_id, reviewed_content))
    except StockProviderUnavailable:
        return _response("search_stock_photos", {"status": "unavailable", "photos": [], "fallback": "minimal_typography"})
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("search_stock_photos", error=str(exc))


@mcp.tool()
def approve_stock_photo_for_draft(lead_id: int, selection_id: str, photo_id: str,
                                  reviewed_by: str, review_confirmed: bool = False) -> dict[str, Any]:
    """Download one selected photo after explicit relevance, license and illustrative-use review.

    Confirm no misleading depiction/endorsement, logos or unsuitable identifiable people.
    Returns a reviewed asset key for generate/revise_first_website_draft(asset_keys=[...]).
    This grants draft use only; commercial approval and publication remain separate operations.
    """
    try:
        asset = _stock_service().approve_for_draft(lead_id, selection_id, photo_id,
            reviewed_by=reviewed_by, review_confirmed=review_confirmed)
        return _response("approve_stock_photo_for_draft", {"asset": asset.to_dict(), "asset_key": asset.key})
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("approve_stock_photo_for_draft", error=str(exc))


@mcp.tool()
def validate_site_asset_candidates(
    lead: dict[str, Any], candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify observed image candidates without downloading or granting publish rights."""
    try:
        result = SiteAssetCandidateValidator().validate(lead, candidates)
        return _response("validate_site_asset_candidates", result.to_dict())
    except (ProspectorError, TypeError, ValueError) as exc:
        return _response("validate_site_asset_candidates", error=str(exc))


@mcp.tool()
def get_sales_preview_readiness(lead_id: int) -> dict[str, Any]:
    """Evaluate a persisted lead and local artifact; never deploys or changes status."""
    try:
        repository = _repository()
        lead = repository.get(lead_id)
        if lead is None:
            raise ValueError("lead not found")
        result = SalesPreviewLifecycleService(
            repository, SiteDraftService(_sites_root()),
        ).readiness(lead)
        return _response("get_sales_preview_readiness", result.to_dict())
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("get_sales_preview_readiness", error=str(exc))


@mcp.tool()
def approve_sales_preview(
    lead_id: int, content_review_acknowledged: bool,
    asset_keys_approved_for_publish: list[str], approved_by: str,
) -> dict[str, Any]:
    """Explicitly approve a validated internal website; never publishes it."""
    try:
        repository = _repository()
        approval = SalesPreviewLifecycleService(
            repository, SiteDraftService(_sites_root()),
        ).approve(
            lead_id, content_review_acknowledged=content_review_acknowledged,
            asset_keys_approved_for_publish=asset_keys_approved_for_publish,
            approved_by=approved_by,
        )
        return _response("approve_sales_preview", approval.to_dict())
    except (ProspectorError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        return _response("approve_sales_preview", error=str(exc))


@mcp.tool()
def cpanel_status() -> dict[str, Any]:
    """Report only whether trusted runtime cPanel configuration is complete; never calls cPanel."""
    return _response("cpanel_status", cpanel_configuration_status())


@mcp.tool()
def cpanel_connection_test() -> dict[str, Any]:
    """Run one safe, read-only cPanel connectivity and authentication diagnostic."""
    return _response("cpanel_connection_test", run_cpanel_connection_test().to_dict())


@mcp.tool()
def sales_preview_deployment_status(lead_id: int) -> dict[str, Any]:
    """Read persisted deployment state and attempt history; no hosting or public network requests."""
    try:
        return _response(
            "sales_preview_deployment_status", SalesPreviewDeploymentService(
                _repository(), SiteDraftService(_sites_root()),
            ).status(lead_id).to_dict(),
        )
    except (ProspectorError, CPanelError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("sales preview deployment status failed: %s", exc)
        return _response("sales_preview_deployment_status", error=str(exc))


@mcp.tool()
def sales_preview_deployment_readiness(lead_id: int) -> dict[str, Any]:
    """Check exact approval and configured destination locally; does not authorize publication."""
    try:
        return _response('sales_preview_deployment_readiness', _deployment_service().readiness(lead_id))
    except (ProspectorError, ValueError, OSError, sqlite3.Error):
        return _response('sales_preview_deployment_readiness', error='deployment readiness unavailable; check runtime configuration')


@mcp.tool()
def verify_sales_preview_deployment(lead_id: int) -> dict[str, Any]:
    """Verify existing remote inventory, DNS, TLS and approved public bytes; persists results, never uploads."""
    try:
        return _response('verify_sales_preview_deployment', _deployment_service().verify(lead_id).to_dict())
    except (ProspectorError, ValueError, OSError, sqlite3.Error):
        return _response('verify_sales_preview_deployment', error='verification unavailable; inspect readiness and deployment status')


@mcp.tool()
def publish_sales_preview(
    lead_id: int, explicitly_authorized: bool,
) -> dict[str, Any]:
    """Publish one approved Sales Preview after explicit human authorization; never changes lead status."""
    try:
        result = _deployment_service().publish(
            lead_id, explicitly_authorized=explicitly_authorized,
        )
        return _response("publish_sales_preview", result.to_dict())
    except (ProspectorError, CPanelError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        LOGGER.warning("sales preview publication failed: %s", exc)
        return _response("publish_sales_preview", error=str(exc))


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
