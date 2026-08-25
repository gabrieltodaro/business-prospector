from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from business_prospector.application.ports import LeadRepository
from business_prospector.application.site_generation import SiteDraftService, validate_generated_site
from business_prospector.domain.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    deployment_status: str
    preview_slug: str
    preview_url: str
    files_uploaded: int
    domain_status: str
    ssl_status: str
    deployment_id: str
    artifact_checksum: str
    warnings: tuple[str, ...] = ()
    deployment_mode: str = "direct_first_publish"
    cleanup: str = "manual_required"
    uploaded_files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_status": self.deployment_status,
            "preview_slug": self.preview_slug,
            "preview_url": self.preview_url,
            "files_uploaded": self.files_uploaded,
            "domain_status": self.domain_status,
            "ssl_status": self.ssl_status,
            "deployment_id": self.deployment_id,
            "artifact_checksum": self.artifact_checksum,
            "warnings": list(self.warnings),
            "deployment_mode": self.deployment_mode,
            "cleanup": self.cleanup,
            "uploaded_files": list(self.uploaded_files),
        }


@dataclass(frozen=True, slots=True)
class DeploymentStatus:
    deployment_status: str
    preview_slug: str
    preview_url: str
    domain_configured: bool
    document_root_matches: bool
    expected_files_present: bool
    ssl_status: str
    warnings: tuple[str, ...] = ()
    public_files: tuple[str, ...] = ()
    staging_residual_present: bool | None = None
    document_root_present: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_status": self.deployment_status,
            "preview_slug": self.preview_slug,
            "preview_url": self.preview_url,
            "domain_configured": self.domain_configured,
            "document_root_matches": self.document_root_matches,
            "expected_files_present": self.expected_files_present,
            "ssl_status": self.ssl_status,
            "warnings": list(self.warnings),
            "public_files": list(self.public_files),
            "staging_residual_present": self.staging_residual_present,
            "document_root_present": self.document_root_present,
        }


@dataclass(frozen=True, slots=True)
class UnpublishResult:
    deployment_status: str
    preview_slug: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_status": self.deployment_status,
            "preview_slug": self.preview_slug,
            "warnings": list(self.warnings),
        }


class PreviewDeploymentProvider(Protocol):
    def publish(self, site_path: Path, preview_slug: str) -> DeploymentResult: ...
    def unpublish(self, preview_slug: str) -> UnpublishResult: ...
    def status(self, preview_slug: str) -> DeploymentStatus: ...


def public_artifact_files(site_path: Path) -> tuple[Path, ...]:
    root = site_path.expanduser().resolve()
    validate_generated_site(root)
    allowed: list[Path] = [root / "index.html", root / "styles.css"]
    assets = root / "assets"
    if not assets.is_dir() or assets.is_symlink():
        raise ValidationError("generated site assets directory is invalid")
    for candidate in sorted(assets.rglob("*")):
        if candidate.is_symlink():
            raise ValidationError("generated site contains a symlink")
        if candidate.is_file():
            resolved = candidate.resolve()
            try:
                resolved.relative_to(assets.resolve())
            except ValueError as exc:
                raise ValidationError("generated site asset escapes controlled root") from exc
            allowed.append(resolved)
    if len(allowed) > 100:
        raise ValidationError("generated site contains too many public files")
    if sum(path.stat().st_size for path in allowed) > 25 * 1024 * 1024:
        raise ValidationError("generated site exceeds public upload size limit")
    return tuple(allowed)


def artifact_checksum(site_path: Path) -> str:
    root = site_path.resolve()
    digest = hashlib.sha256()
    for path in public_artifact_files(root):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


class SalesPreviewDeploymentService:
    def __init__(
        self, repository: LeadRepository, drafts: SiteDraftService,
        provider: PreviewDeploymentProvider,
    ) -> None:
        self._repository = repository
        self._drafts = drafts
        self._provider = provider

    def publish(self, lead_id: int, *, explicitly_authorized: bool) -> DeploymentResult:
        if explicitly_authorized is not True:
            raise ValidationError("explicit publication authorization is required")
        lead = self._repository.get(lead_id)
        if lead is None:
            raise ValidationError("persisted lead not found")
        if lead.status != "sales_preview":
            raise ValidationError("lead must be an approved Sales Preview before publication")
        draft = self._drafts.inspect(lead.slug or "")
        if not draft.exists or draft.site_path is None:
            raise ValidationError("valid approved site artifact is required")
        validate_generated_site(draft.site_path)
        manifest_path = draft.site_path / "site-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValidationError("approved site manifest is invalid") from exc
        preview = manifest.get("sales_preview")
        if not isinstance(preview, dict) or preview.get("preview_status") != "approved_not_published":
            existing = manifest.get("deployment")
            if not isinstance(existing, dict) or existing.get("deployment_status") != "published":
                raise ValidationError("Sales Preview approval metadata is required")
        preview_slug = preview.get("preview_slug") if isinstance(preview, dict) else None
        if not isinstance(preview_slug, str) or not preview_slug:
            raise ValidationError("approved preview slug is required")
        assets = manifest.get("assets")
        if not isinstance(assets, list) or not assets or any(
            not isinstance(asset, dict) or asset.get("approval_status") != "approved_for_publish"
            or asset.get("rights_status") in {"unknown", "do_not_use"}
            for asset in assets
        ):
            raise ValidationError("all rendered assets must be approved for publish")
        checksum = artifact_checksum(draft.site_path)
        existing = manifest.get("deployment")
        if isinstance(existing, dict) and existing.get("deployment_status") == "published":
            if existing.get("artifact_checksum") != checksum:
                raise ValidationError("published artifact changed; safe replacement is not supported yet")
            return DeploymentResult(
                "published", preview_slug, str(existing.get("preview_url") or ""),
                int(existing.get("files_uploaded") or 0), str(existing.get("domain_status") or "existing"),
                str(existing.get("ssl_status") or "unknown"), str(existing.get("deployment_id") or ""),
                checksum, ("unchanged artifact was already published",),
                str(existing.get("deployment_mode") or "direct_first_publish"),
                str(existing.get("cleanup") or "manual_required"),
                tuple(
                    item for item in existing.get("uploaded_files", [])
                    if isinstance(item, str)
                ),
            )
        result = self._provider.publish(draft.site_path, preview_slug)
        published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest["deployment"] = {
            **result.to_dict(), "published_at": published_at, "last_checked_at": None,
        }
        if isinstance(preview, dict):
            preview["preview_status"] = "published"
            preview["preview_url"] = result.preview_url
        self._write_manifest(manifest_path, manifest)
        return result

    def status(self, lead_id: int) -> DeploymentStatus:
        lead = self._repository.get(lead_id)
        if lead is None:
            raise ValidationError("persisted lead not found")
        draft = self._drafts.inspect(lead.slug or "")
        if not draft.exists or draft.site_path is None:
            raise ValidationError("valid site artifact is required")
        manifest = json.loads((draft.site_path / "site-manifest.json").read_text(encoding="utf-8"))
        preview = manifest.get("sales_preview")
        preview_slug = preview.get("preview_slug") if isinstance(preview, dict) else None
        if not isinstance(preview_slug, str) or not preview_slug:
            raise ValidationError("Sales Preview metadata is required")
        return self._provider.status(preview_slug)

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".manifest-", delete=False,
        ) as temporary:
            json.dump(manifest, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
