from __future__ import annotations

import json

from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.application.website_projection import WebsiteDeploymentProjectionService
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository

from test_sales_preview import generated_artifact, internal_lead


def test_projection_distinguishes_internal_approved_and_published_without_provider(tmp_path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    lead = internal_lead(repository)
    drafts, site = generated_artifact(tmp_path, lead)
    service = WebsiteDeploymentProjectionService(drafts)

    internal = service.project(lead)
    assert internal.website_stage == "internal_website"
    assert internal.approval_status is None and internal.deployment_status is None

    approval = SalesPreviewLifecycleService(repository, drafts).approve(
        lead.id or 0, content_review_acknowledged=True,
        asset_keys_approved_for_publish=[], approved_by="reviewer",
    )
    approved = service.project(approval.lead)
    assert approved.website_stage == "sales_preview"
    assert approved.approval_status == "approved_not_published"
    assert approved.preview_slug == "drlaura"

    manifest_path = site / "site-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sales_preview"].update({
        "preview_status": "published", "preview_url": "https://drlaura.gapps.test",
    })
    manifest["deployment"] = {
        "deployment_status": "published",
        "preview_url": "https://drlaura.gapps.test",
        "deployment_mode": "direct_first_publish",
        "published_at": "2026-08-25T12:00:00+00:00",
        "ssl_status": "pending",
        "files_uploaded": 3,
        "artifact_checksum": "secret-checksum-not-for-dashboard",
        "document_root": "/home/private/public_html/sales-previews/drlaura",
        "api_token": "secret-token",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    contacted = repository.update(lead.id or 0, {"status": "contacted"})
    published = service.project(contacted).to_dict()
    assert published == {
        "website_stage": "published_sales_preview",
        "approval_status": "published",
        "preview_slug": "drlaura",
        "approved_at": approval.approved_at,
        "approved_by": "reviewer",
        "deployment_status": "published",
        "preview_url": "https://drlaura.gapps.test",
        "deployment_mode": "direct_first_publish",
        "published_at": "2026-08-25T12:00:00+00:00",
        "last_known_ssl_status": "pending",
        "files_uploaded": 3,
    }
    serialized = json.dumps(published)
    assert "secret-checksum" not in serialized
    assert "secret-token" not in serialized
    assert "/home/private" not in serialized


def test_projection_rejects_unsafe_manifest_values(tmp_path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    lead = internal_lead(repository)
    drafts, site = generated_artifact(tmp_path, lead)
    manifest_path = site / "site-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sales_preview"] = {
        "preview_status": "approved_not_published",
        "preview_slug": "../../escape",
        "preview_url": "file:///private/data",
        "approved_by": "x" * 101,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    projection = WebsiteDeploymentProjectionService(drafts).project(lead)
    assert projection.website_stage == "sales_preview"
    assert projection.preview_slug is None
    assert projection.preview_url is None
    assert projection.approved_by is None
