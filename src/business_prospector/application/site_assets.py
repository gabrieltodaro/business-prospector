from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.site_assets import (
    MAX_IMAGE_BYTES,
    SAFE_IMAGE_MIMES,
    AssetRejection,
    AssetValidationResult,
    SiteAsset,
)


def _same_origin(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    a, b = urlsplit(left), urlsplit(right)
    return a.scheme in {"http", "https"} and a.hostname == b.hostname


class SiteAssetCandidateValidator:
    def validate(
        self, lead: dict[str, Any], observations: list[dict[str, Any]],
    ) -> AssetValidationResult:
        if not isinstance(lead, dict) or lead.get("opportunity_type") not in {"redesign", "first_website"}:
            raise ValidationError("lead opportunity_type is required")
        if not isinstance(observations, list) or len(observations) > 30:
            raise ValidationError("asset observations must contain at most 30 items")
        accepted: list[SiteAsset] = []
        rejected: list[AssetRejection] = []
        seen: set[str] = set()
        for raw in observations:
            key = raw.get("key") if isinstance(raw, dict) and isinstance(raw.get("key"), str) else None
            try:
                asset = SiteAsset.from_observation(raw)
                if asset.key in seen:
                    raise ValidationError("duplicate asset key")
                seen.add(asset.key)
                if asset.mime_type not in SAFE_IMAGE_MIMES:
                    raise ValidationError("unsupported or unsafe image MIME type")
                if asset.byte_size and asset.byte_size > MAX_IMAGE_BYTES:
                    raise ValidationError("asset exceeds the 8 MiB limit")
                if asset.source_type == "business_social_reference":
                    rejected.append(AssetRejection(asset.key, "social assets are reference-only and never auto-approved"))
                    continue
                if asset.source_type == "existing_business_site":
                    if lead.get("opportunity_type") != "redesign":
                        raise ValidationError("existing-site assets require a redesign opportunity")
                    if not asset.business_identity_match:
                        raise ValidationError("business identity mismatch")
                    if not _same_origin(asset.discovered_from, lead.get("website_url")):
                        raise ValidationError("asset was not discovered from the current business website")
                    accepted.append(asset.classified(
                        rights_status="likely_business_owned", approval_status="approved_for_draft",
                    ))
                    continue
                if asset.source_type == "licensed_stock":
                    accepted.append(asset.classified(
                        rights_status="unknown", approval_status="candidate",
                    ))
                    continue
                if asset.source_type == "generated":
                    accepted.append(asset.classified(
                        rights_status="generated", approval_status="approved_for_draft",
                    ))
                    continue
                accepted.append(asset.classified(rights_status="unknown", approval_status="candidate"))
            except (ValidationError, TypeError, ValueError) as exc:
                rejected.append(AssetRejection(key, str(exc)))
        return AssetValidationResult(tuple(accepted), tuple(rejected))


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    content: bytes
    mime_type: str


class SiteAssetIngestionService:
    def __init__(self, fetch: Callable[[str], DownloadedImage]) -> None:
        self._fetch = fetch

    def ingest(self, asset: SiteAsset, assets_directory: Path) -> SiteAsset:
        if asset.approval_status != "approved_for_draft" or not asset.source_url:
            raise ValidationError("asset is not approved for draft ingestion")
        downloaded = self._fetch(asset.source_url)
        if downloaded.mime_type not in SAFE_IMAGE_MIMES or asset.mime_type != downloaded.mime_type:
            raise ValidationError("downloaded image MIME type does not match validated observation")
        if len(downloaded.content) > MAX_IMAGE_BYTES:
            raise ValidationError("downloaded asset exceeds the 8 MiB limit")
        signatures = {
            "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
            "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        }
        if not signatures[downloaded.mime_type](downloaded.content):
            raise ValidationError("downloaded content does not match its image MIME type")
        extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
        root = assets_directory.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / f"{asset.key}{extensions[downloaded.mime_type]}").resolve()
        if destination.parent != root:
            raise ValidationError("unsafe asset destination")
        checksum = hashlib.sha256(downloaded.content).hexdigest()
        with tempfile.NamedTemporaryFile(dir=root, prefix=f".{asset.key}-", delete=False) as temporary:
            temporary.write(downloaded.content)
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
        return asset.with_local_file(
            f"assets/{destination.name}", checksum, downloaded.mime_type, len(downloaded.content),
        )
