from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

import pytest

from business_prospector.application.deployment import DeploymentResult, DeploymentStatus
from business_prospector.application.site_generation import SiteDraftService, SiteGenerationService
from business_prospector.application.technical_deployment import (
    TechnicalDeploymentSmokeService,
    TechnicalDeploymentTarget,
)
from business_prospector.cpanel_smoke import _parser, run_command
from business_prospector.domain.exceptions import ValidationError

from test_site_generation import lead, research

LAURA_SITE_SLUG = (
    "dra-laura-baesso-dentista-em-catanduva-clareamento-dental-estetica-e-"
    "harmonizacao-facial-catanduva-sp"
)


class FakeTechnicalProvider:
    def __init__(self, *, fail_publish: bool = False) -> None:
        self.fail_publish = fail_publish
        self.publish_calls = 0
        self.status_calls = 0

    def target(self, preview_slug: str) -> TechnicalDeploymentTarget:
        if preview_slug != "drlaura":
            raise ValidationError("preview slug is invalid")
        return TechnicalDeploymentTarget(
            preview_slug, "drlaura.gapps.test", "public_html/sales-previews/drlaura",
        )

    def publish(self, site_path: Path, preview_slug: str) -> DeploymentResult:
        self.publish_calls += 1
        if self.fail_publish:
            raise RuntimeError("fake upload failure")
        return DeploymentResult(
            "published", preview_slug, "https://drlaura.gapps.test", 3,
            "created", "pending", "technical-test", "checksum", (),
        )

    def status(self, preview_slug: str) -> DeploymentStatus:
        self.status_calls += 1
        return DeploymentStatus(
            "published", preview_slug, "https://drlaura.gapps.test",
            True, True, True, "pending", (),
        )


def smoke_service(tmp_path: Path, provider: FakeTechnicalProvider) -> tuple[
    TechnicalDeploymentSmokeService, Path,
]:
    sites = tmp_path / "sites"
    generated = SiteGenerationService(sites).generate(
        lead(slug=LAURA_SITE_SLUG, name="Dra. Laura Exemplo"), research(),
    )
    site_path = Path(generated.site_path or "")
    return TechnicalDeploymentSmokeService(SiteDraftService(sites), provider), site_path


def namespace(**changes: Any) -> argparse.Namespace:
    values = {
        "site_slug": LAURA_SITE_SLUG,
        "preview_slug": "drlaura",
        "dry_run": True,
        "execute": False,
        "status": False,
        "confirm": None,
    }
    values.update(changes)
    return argparse.Namespace(**values)


def test_dry_run_validates_internal_artifact_without_provider_write(tmp_path: Path) -> None:
    provider = FakeTechnicalProvider()
    service, _ = smoke_service(tmp_path, provider)
    output = run_command(namespace(), service)
    assert output["technical_deployment"] is True
    assert output["deployment_purpose"] == "technical_test"
    assert output["fqdn"] == "drlaura.gapps.test"
    assert output["document_root"] == "public_html/sales-previews/drlaura"
    assert set(output["files"]) == {"index.html", "styles.css", "assets/hero-visual.svg"}
    assert output["executed"] is False and output["would_write"] is True
    assert output["lead_status_changed"] is False
    assert output["commercial_approval_changed"] is False
    assert provider.publish_calls == 0


@pytest.mark.parametrize("confirmation", [None, "wrong", "drlaura.gapps.test"])
def test_execute_requires_exact_second_gate_without_writing(
    tmp_path: Path, confirmation: str | None,
) -> None:
    provider = FakeTechnicalProvider()
    service, _ = smoke_service(tmp_path, provider)
    with pytest.raises(ValidationError, match="confirmation"):
        run_command(namespace(
            dry_run=False, execute=True, confirm=confirmation,
        ), service)
    assert provider.publish_calls == 0


def test_service_requires_explicit_execute_gate(tmp_path: Path) -> None:
    provider = FakeTechnicalProvider()
    service, _ = smoke_service(tmp_path, provider)
    with pytest.raises(ValidationError, match="--execute"):
        service.execute(
            LAURA_SITE_SLUG, "drlaura",
            explicitly_authorized=False, confirmation="drlaura",
        )
    assert provider.publish_calls == 0


def test_technical_execute_reuses_provider_without_mutating_manifest(tmp_path: Path) -> None:
    provider = FakeTechnicalProvider()
    service, site = smoke_service(tmp_path, provider)
    manifest = site / "site-manifest.json"
    before = manifest.read_bytes()
    output = run_command(namespace(
        dry_run=False, execute=True, confirm="drlaura",
    ), service)
    assert provider.publish_calls == 1
    assert output["executed"] is True
    assert output["deployment_purpose"] == "technical_test"
    assert output["result"]["ssl_status"] == "pending"
    assert output["cleanup"] == "manual_required"
    assert manifest.read_bytes() == before
    raw = json.loads(manifest.read_text())
    assert "sales_preview" not in raw and "deployment" not in raw


def test_fake_publish_failure_does_not_mutate_artifact(tmp_path: Path) -> None:
    provider = FakeTechnicalProvider(fail_publish=True)
    service, site = smoke_service(tmp_path, provider)
    before = (site / "site-manifest.json").read_bytes()
    with pytest.raises(RuntimeError, match="fake upload failure"):
        service.execute(
            LAURA_SITE_SLUG, "drlaura",
            explicitly_authorized=True, confirmation="drlaura",
        )
    assert provider.publish_calls == 1
    assert (site / "site-manifest.json").read_bytes() == before


def test_status_is_read_only_and_needs_no_site(tmp_path: Path) -> None:
    provider = FakeTechnicalProvider()
    service = TechnicalDeploymentSmokeService(SiteDraftService(tmp_path / "missing"), provider)
    output = run_command(namespace(
        site_slug=None, dry_run=False, status=True,
    ), service)
    assert output["read_only"] is True
    assert output["cleanup"] == "manual_required"
    assert output["result"]["ssl_status"] == "pending"
    assert provider.status_calls == 1 and provider.publish_calls == 0


@pytest.mark.parametrize("site_slug", ["../escape", "/tmp/site", "unknown"])
def test_arbitrary_or_missing_site_slug_is_rejected(tmp_path: Path, site_slug: str) -> None:
    provider = FakeTechnicalProvider()
    service, _ = smoke_service(tmp_path, provider)
    with pytest.raises(ValidationError, match="controlled site artifact"):
        service.plan(site_slug, "drlaura")
    assert provider.publish_calls == 0


def test_invalid_preview_slug_is_rejected_without_write(tmp_path: Path) -> None:
    provider = FakeTechnicalProvider()
    service, _ = smoke_service(tmp_path, provider)
    with pytest.raises(ValidationError, match="preview slug"):
        service.plan(LAURA_SITE_SLUG, "other.example")
    assert provider.publish_calls == 0


def test_cli_has_no_arbitrary_path_host_or_document_root_options() -> None:
    destinations = {action.dest for action in _parser()._actions}
    assert destinations == {
        "help", "site_slug", "preview_slug", "dry_run", "execute", "status", "confirm",
    }
    assert not {"path", "site_path", "host", "domain", "document_root", "base_dir"} & destinations


def test_smoke_application_has_no_sqlite_or_lead_repository_dependency() -> None:
    source = Path(__file__).parents[1] / "src/business_prospector/application/technical_deployment.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any("sqlite" in name.casefold() or "repository" in name.casefold() for name in imported)
