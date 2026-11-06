from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from business_prospector.application.artifacts import (
    artifact_checksum, public_artifact_files, artifact_snapshot,
)
from business_prospector.application.ports import LeadRepository
from business_prospector.application.site_generation import SiteDraftService
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
        manifest_path = draft.site_path / "site-manifest.json"
        with artifact_snapshot(draft.site_path) as (artifact, snapshot):
            manifest = json.loads(artifact.manifest_bytes)
            preview = manifest.get("sales_preview")
            if not isinstance(preview, dict) or preview.get("preview_status") not in {"approved_not_published", "published"}:
                raise ValidationError("Sales Preview approval metadata is required")
            preview_slug = preview.get("preview_slug")
            if not isinstance(preview_slug, str) or not preview_slug:
                raise ValidationError("approved preview slug is required")
            existing = manifest.get("deployment")
            if existing is not None and not isinstance(existing, dict):
                raise ValidationError("invalid deployment metadata")
            if isinstance(existing, dict) and existing.get("deployment_status") == "published":
                if existing.get("artifact_checksum") != artifact.checksum:
                    raise ValidationError("published artifact changed; safe replacement is not supported yet")
            if preview.get("approved_artifact") != artifact.identity():
                raise ValidationError("stale or missing artifact approval; review and approve this revision again")
            from .sales_preview import SalesPreviewLifecycleService
            readiness = SalesPreviewLifecycleService(
                self._repository, SiteDraftService(snapshot.parent),
            ).readiness(lead, content_review_acknowledged=preview.get("content_review_acknowledged") is True)
            if not readiness.ready:
                raise ValidationError("Sales Preview is not ready: " + "; ".join(readiness.blocking_reasons))
            if isinstance(existing, dict) and existing.get("deployment_status") == "published":
                return DeploymentResult(
                    "published", preview_slug, str(existing.get("preview_url") or ""),
                    int(existing.get("files_uploaded") or 0), str(existing.get("domain_status") or "existing"),
                    str(existing.get("ssl_status") or "unknown"), str(existing.get("deployment_id") or ""),
                    artifact.checksum, ("unchanged artifact was already published",),
                    str(existing.get("deployment_mode") or "direct_first_publish"),
                    str(existing.get("cleanup") or "manual_required"),
                    tuple(item for item in existing.get("uploaded_files", []) if isinstance(item, str)),
                )
            # The provider sees an isolated copy of the approved bytes, never the editable draft.
            result = self._provider.publish(snapshot, preview_slug)
            if result.artifact_checksum != artifact.checksum:
                raise ValidationError("provider result does not match approved artifact")
        published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest["deployment"] = {
            **result.to_dict(), "published_at": published_at, "last_checked_at": None,
        }
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
