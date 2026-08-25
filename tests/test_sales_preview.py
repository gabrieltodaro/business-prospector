from __future__ import annotations

import json
from pathlib import Path

import pytest

from business_prospector.application.sales_preview import (
    PreviewDeploymentProvider,
    SalesPreviewLifecycleService,
    propose_sales_preview_slug,
)
from business_prospector.application.site_generation import SiteDraftService, SiteGenerationService
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import Lead, WebsiteAssessment
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository

from test_site_generation import lead as site_lead, research


def internal_lead(repository: SQLiteLeadRepository, opportunity_type: str = "first_website") -> Lead:
    return repository.save(Lead(
        name="Dra. Laura Exemplo", slug=f"dra-laura-exemplo-{opportunity_type.replace('_', '-')}",
        category="dentist", city="Catanduva, SP", rating=5.0, review_count=22,
        website_url="" if opportunity_type == "first_website" else "https://laura.example",
        assessment=WebsiteAssessment(reason="fixture"), status="internal_website",
        opportunity_type=opportunity_type,
        first_website_reason="no_website" if opportunity_type == "first_website" else None,
        external_place_id=f"place-{opportunity_type}",
    ))


def generated_artifact(tmp_path: Path, stored: Lead) -> tuple[SiteDraftService, Path]:
    raw = site_lead(
        name=stored.name, slug=stored.slug, city=stored.city, category=stored.category,
        rating=stored.rating, review_count=stored.review_count,
        external_place_id=stored.external_place_id, opportunity_type="first_website",
    )
    result = SiteGenerationService(tmp_path / "sites").generate(raw, research())
    site = Path(result.site_path or "")
    manifest_path = site / "site-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["opportunity_type"] = stored.opportunity_type
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return SiteDraftService(tmp_path / "sites"), site


def test_valid_internal_site_readiness_requires_human_content_acknowledgement(tmp_path: Path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    stored = internal_lead(repository)
    drafts, _ = generated_artifact(tmp_path, stored)
    lifecycle = SalesPreviewLifecycleService(repository, drafts)
    before = lifecycle.readiness(stored)
    assert not before.ready and before.artifact_valid and before.assets_publishable
    assert "visible business content review must be acknowledged" in before.blocking_reasons
    after = lifecycle.readiness(stored, content_review_acknowledged=True)
    assert after.ready and after.proposed_preview_slug == "drlaura"


def test_missing_malformed_and_visible_placeholder_sites_are_not_ready(tmp_path: Path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    missing = internal_lead(repository)
    lifecycle = SalesPreviewLifecycleService(repository, SiteDraftService(tmp_path / "sites"))
    assert lifecycle.readiness(missing, content_review_acknowledged=True).blocking_reasons == (
        "valid generated site is required",
    )
    drafts, site = generated_artifact(tmp_path, missing)
    (site / "site-manifest.json").write_text("{bad")
    assert not SalesPreviewLifecycleService(repository, drafts).readiness(
        missing, content_review_acknowledged=True,
    ).artifact_valid

    # Restore a valid artifact, then inject a visible internal marker.
    SiteGenerationService(tmp_path / "sites").generate(
        site_lead(name=missing.name, slug=missing.slug), research(), overwrite=True,
    )
    index = site / "index.html"
    index.write_text(index.read_text().replace("Seu próximo contato", "Conteúdo a validar"))
    result = SalesPreviewLifecycleService(repository, drafts).readiness(
        missing, content_review_acknowledged=True,
    )
    assert any("visible internal placeholder" in reason for reason in result.blocking_reasons)


@pytest.mark.parametrize("approval, rights, ready", [
    ("approved_for_draft", "likely_business_owned", False),
    ("approved_for_publish", "likely_business_owned", True),
    ("approved_for_publish", "generated", True),
    ("rejected", "generated", False),
    ("approved_for_publish", "do_not_use", False),
])
def test_asset_publication_gate(
    tmp_path: Path, approval: str, rights: str, ready: bool,
) -> None:
    repository = SQLiteLeadRepository(tmp_path / f"{approval}-{rights}.db")
    stored = internal_lead(repository)
    drafts, site = generated_artifact(tmp_path, stored)
    manifest_path = site / "site-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["assets"][0]["approval_status"] = approval
    manifest["assets"][0]["rights_status"] = rights
    manifest_path.write_text(json.dumps(manifest))
    result = SalesPreviewLifecycleService(repository, drafts).readiness(
        stored, content_review_acknowledged=True,
    )
    assert result.ready is ready


@pytest.mark.parametrize("opportunity_type", ["first_website", "redesign"])
def test_explicit_approval_updates_manifest_and_status(
    tmp_path: Path, opportunity_type: str,
) -> None:
    repository = SQLiteLeadRepository(tmp_path / f"{opportunity_type}.db")
    stored = internal_lead(repository, opportunity_type)
    drafts, site = generated_artifact(tmp_path, stored)
    lifecycle = SalesPreviewLifecycleService(repository, drafts)
    approval = lifecycle.approve(
        stored.id or 0, content_review_acknowledged=True,
        asset_keys_approved_for_publish=[], approved_by="gabriel",
    )
    assert approval.lead.status == "sales_preview"
    assert approval.preview_slug == "drlaura"
    metadata = json.loads((site / "site-manifest.json").read_text())["sales_preview"]
    assert metadata["preview_status"] == "approved_not_published"
    assert metadata["preview_url"] is None and metadata["approved_by"] == "gabriel"


def test_failed_approval_preserves_internal_status(tmp_path: Path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "failure.db")
    stored = internal_lead(repository)
    lifecycle = SalesPreviewLifecycleService(repository, SiteDraftService(tmp_path / "sites"))
    with pytest.raises(ValidationError, match="not ready"):
        lifecycle.approve(
            stored.id or 0, content_review_acknowledged=True,
            asset_keys_approved_for_publish=[], approved_by="gabriel",
        )
    assert repository.get(stored.id or 0).status == "internal_website"  # type: ignore[union-attr]


def test_qualified_lead_and_unknown_asset_keys_cannot_be_approved(tmp_path: Path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "qualified.db")
    stored = internal_lead(repository)
    drafts, _ = generated_artifact(tmp_path, stored)
    repository.update(stored.id or 0, {"status": "qualified"})
    lifecycle = SalesPreviewLifecycleService(repository, drafts)
    with pytest.raises(ValidationError, match="Internal Website"):
        lifecycle.approve(
            stored.id or 0, content_review_acknowledged=True,
            asset_keys_approved_for_publish=[], approved_by="gabriel",
        )


@pytest.mark.parametrize("name, expected", [
    ("Dra. Laura Baesso", "drlaura"),
    ("Dr. João Ávila", "drjoao"),
    ("Clínica Sorriso & Saúde Ltda", "clinicasorriso"),
])
def test_preview_slug_is_deterministic_safe_and_unicode_normalized(name: str, expected: str) -> None:
    assert propose_sales_preview_slug(name, "identity") == expected
    assert propose_sales_preview_slug(name, "identity") == expected


def test_preview_slug_handles_reserved_collisions_and_long_names() -> None:
    reserved = propose_sales_preview_slug("Admin", "place-admin")
    collision = propose_sales_preview_slug("Clínica Sorriso", "place-2", {"clinicasorriso"})
    long_slug = propose_sales_preview_slug("Clínica Super Extraordinariamente Longa e Local", "long")
    assert reserved.startswith("admin-") and collision.startswith("clinicasorriso-")
    assert len(reserved) <= 32 and len(collision) <= 32 and len(long_slug) <= 32
    assert all(char.islower() or char.isdigit() or char == "-" for char in collision)


def test_deployment_provider_is_only_an_application_port() -> None:
    assert hasattr(PreviewDeploymentProvider, "publish")
    assert hasattr(PreviewDeploymentProvider, "unpublish")
    assert hasattr(PreviewDeploymentProvider, "status")
