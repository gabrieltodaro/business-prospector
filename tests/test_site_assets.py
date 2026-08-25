from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from business_prospector.application.site_assets import (
    DownloadedImage,
    SiteAssetCandidateValidator,
    SiteAssetIngestionService,
)
from business_prospector.application.site_generation import SiteGenerationService
from business_prospector.domain.exceptions import ValidationError

from test_site_generation import lead, research


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def redesign_lead(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "name": "Clínica Atual", "city": "Catanduva, SP", "category": "dentist",
        "opportunity_type": "redesign", "website_url": "https://clinica.example",
        "external_place_id": "business-place",
    }
    value.update(changes)
    return value


def observation(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "key": "hero", "asset_type": "photo", "source_type": "existing_business_site",
        "source_url": "https://cdn.clinica.example/images/consultorio.png",
        "discovered_from": "https://clinica.example/sobre", "business_identity_match": True,
        "alt_text": "Recepção da clínica", "width": 1200, "height": 800,
        "mime_type": "image/png", "byte_size": len(PNG),
    }
    value.update(changes)
    return value


def test_first_party_candidate_is_draft_only_not_publish_approved() -> None:
    result = SiteAssetCandidateValidator().validate(redesign_lead(), [observation()])
    assert not result.rejected
    asset = result.accepted[0]
    assert asset.rights_status == "likely_business_owned"
    assert asset.approval_status == "approved_for_draft"
    assert asset.approval_status != "approved_for_publish"


def test_social_reference_is_never_automatically_approved_or_downloaded() -> None:
    item = observation(
        source_type="business_social_reference", source_url="https://instagram.com/p/example",
        discovered_from="https://instagram.com/business", mime_type="image/jpeg",
    )
    result = SiteAssetCandidateValidator().validate(
        {**redesign_lead(), "opportunity_type": "first_website"}, [item],
    )
    assert not result.accepted
    assert "reference-only" in result.rejected[0].reason


def test_stock_like_candidate_keeps_unknown_rights_and_candidate_approval() -> None:
    item = observation(source_type="licensed_stock")
    asset = SiteAssetCandidateValidator().validate(redesign_lead(), [item]).accepted[0]
    assert (asset.rights_status, asset.approval_status) == ("unknown", "candidate")


@pytest.mark.parametrize("url", [
    "file:///tmp/photo.png", "javascript:alert(1)", "/relative.png",
    "https://user:password@clinica.example/photo.png",
    "https://clinica.example/photo.png?token=secret",
])
def test_unsafe_asset_urls_are_rejected(url: str) -> None:
    result = SiteAssetCandidateValidator().validate(redesign_lead(), [observation(source_url=url)])
    assert not result.accepted


@pytest.mark.parametrize("changes", [
    {"mime_type": "image/svg+xml"},
    {"mime_type": "application/octet-stream"},
    {"byte_size": 8 * 1024 * 1024 + 1},
    {"key": "../hero"},
])
def test_unsafe_mime_size_svg_and_filename_are_rejected(changes: dict[str, object]) -> None:
    result = SiteAssetCandidateValidator().validate(redesign_lead(), [observation(**changes)])
    assert not result.accepted and result.rejected


def test_competitor_and_identity_mismatch_are_rejected() -> None:
    candidates = [
        observation(key="competitor", discovered_from="https://competitor.example"),
        observation(key="mismatch", business_identity_match=False),
    ]
    result = SiteAssetCandidateValidator().validate(redesign_lead(), candidates)
    assert not result.accepted
    assert {item.reason for item in result.rejected} == {
        "asset was not discovered from the current business website", "business identity mismatch",
    }


def test_ingestion_uses_controlled_filename_and_deterministic_checksum(tmp_path: Path) -> None:
    asset = SiteAssetCandidateValidator().validate(redesign_lead(), [observation()]).accepted[0]
    service = SiteAssetIngestionService(lambda _: DownloadedImage(PNG, "image/png"))
    first = service.ingest(asset, tmp_path / "staging" / "assets")
    second = service.ingest(asset, tmp_path / "other" / "assets")
    assert first.local_file == "assets/hero.png"
    assert first.checksum == second.checksum
    assert (tmp_path / "staging" / first.local_file).read_bytes() == PNG


def test_ingestion_rechecks_mime_size_and_magic(tmp_path: Path) -> None:
    asset = SiteAssetCandidateValidator().validate(redesign_lead(), [observation()]).accepted[0]
    with pytest.raises(ValidationError, match="MIME"):
        SiteAssetIngestionService(lambda _: DownloadedImage(PNG, "image/jpeg")).ingest(asset, tmp_path)
    with pytest.raises(ValidationError, match="does not match"):
        SiteAssetIngestionService(lambda _: DownloadedImage(b"not png", "image/png")).ingest(asset, tmp_path)
    with pytest.raises(ValidationError, match="8 MiB"):
        SiteAssetIngestionService(
            lambda _: DownloadedImage(b"\x89PNG\r\n\x1a\n" + b"x" * (8 * 1024 * 1024), "image/png")
        ).ingest(asset, tmp_path)


def test_approved_assets_are_copied_locally_rendered_and_manifested(tmp_path: Path) -> None:
    raw = [observation(), observation(
        key="gallery", source_url="https://clinica.example/gallery.png",
        alt_text=None, width=900, height=700,
    )]
    validated = SiteAssetCandidateValidator().validate(redesign_lead(), raw).accepted
    staging = tmp_path / "staging"
    ingestor = SiteAssetIngestionService(lambda _: DownloadedImage(PNG, "image/png"))
    ingested = tuple(ingestor.ingest(asset, staging / "assets") for asset in validated)
    result = SiteGenerationService(tmp_path / "sites").generate(
        lead(), research(), assets=ingested, asset_source_root=staging,
    )
    site = Path(result.site_path or "")
    html = (site / "index.html").read_text()
    assert 'src="assets/hero.png"' in html and 'width="1200" height="800"' in html
    assert 'src="assets/gallery.png"' in html and 'alt=""' in html and 'loading="lazy"' in html
    assert "https://cdn.clinica.example" not in html and "https://clinica.example/gallery.png" not in html
    manifest = json.loads((site / "site-manifest.json").read_text())
    assert manifest["assets"][0]["checksum"] == ingested[0].checksum
    assert manifest["assets"][0]["source_url"] == raw[0]["source_url"]
    assert manifest["assets"][0]["approval_status"] == "approved_for_draft"


def test_unapproved_asset_is_not_rendered_or_hotlinked(tmp_path: Path) -> None:
    candidate = SiteAssetCandidateValidator().validate(
        redesign_lead(), [observation(source_type="licensed_stock")],
    ).accepted[0]
    result = SiteGenerationService(tmp_path / "sites").generate(
        lead(), research(), assets=(candidate,), asset_source_root=tmp_path,
    )
    html = Path(result.site_path or "").joinpath("index.html").read_text()
    assert candidate.source_url not in html
    assert 'src="assets/hero-visual.svg"' in html


def test_visual_copy_uses_facts_without_invented_claims(tmp_path: Path) -> None:
    result = SiteGenerationService(tmp_path / "sites").generate(lead(), research())
    html = Path(result.site_path or "").joinpath("index.html").read_text()
    assert "4.9" in html and "180 avaliações" in html and "Catanduva, SP" in html
    assert "depoimento" not in html.casefold()
    for invented in ("anos de experiência", "especialista", "certificado", "clareamento", "implante"):
        assert invented not in html.casefold()
