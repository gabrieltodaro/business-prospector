from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from business_prospector.application.deployment import (
    DeploymentResult,
    DeploymentStatus,
    public_artifact_files,
)
from business_prospector.application.site_generation import SiteDraftService
from business_prospector.domain.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class TechnicalDeploymentTarget:
    preview_slug: str
    fqdn: str
    document_root: str


class TechnicalDeploymentProvider(Protocol):
    def target(self, preview_slug: str) -> TechnicalDeploymentTarget: ...
    def publish(self, site_path: Path, preview_slug: str) -> DeploymentResult: ...
    def status(self, preview_slug: str) -> DeploymentStatus: ...


@dataclass(frozen=True, slots=True)
class TechnicalDeploymentPlan:
    site_slug: str
    target: TechnicalDeploymentTarget
    files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "technical_deployment": True,
            "deployment_purpose": "technical_test",
            "site_valid": True,
            "site_slug": self.site_slug,
            "preview_slug": self.target.preview_slug,
            "fqdn": self.target.fqdn,
            "document_root": self.target.document_root,
            "files": list(self.files),
            "configured": True,
            "would_write": True,
            "executed": False,
            "cleanup": "manual_required",
            "commercial_approval_changed": False,
            "lead_status_changed": False,
        }


class TechnicalDeploymentSmokeService:
    """Administrative infrastructure test, intentionally outside commercial lifecycle."""

    def __init__(
        self, drafts: SiteDraftService, provider: TechnicalDeploymentProvider,
    ) -> None:
        self._drafts = drafts
        self._provider = provider

    def plan(self, site_slug: str, preview_slug: str) -> TechnicalDeploymentPlan:
        draft = self._drafts.inspect(site_slug)
        if not draft.exists or draft.site_path is None:
            raise ValidationError("valid controlled site artifact is required")
        public_files = public_artifact_files(draft.site_path)
        root = draft.site_path.resolve()
        files = tuple(path.relative_to(root).as_posix() for path in public_files)
        return TechnicalDeploymentPlan(site_slug, self._provider.target(preview_slug), files)

    def execute(
        self, site_slug: str, preview_slug: str, *, explicitly_authorized: bool,
        confirmation: str | None,
    ) -> dict[str, Any]:
        if explicitly_authorized is not True:
            raise ValidationError("technical deployment requires --execute")
        if confirmation != preview_slug:
            raise ValidationError("technical deployment confirmation must match preview slug")
        plan = self.plan(site_slug, preview_slug)
        draft = self._drafts.inspect(site_slug)
        assert draft.site_path is not None
        result = self._provider.publish(draft.site_path, preview_slug)
        return {
            **plan.to_dict(),
            "executed": True,
            "result": result.to_dict(),
        }

    def status(self, preview_slug: str) -> dict[str, Any]:
        target = self._provider.target(preview_slug)
        result = self._provider.status(preview_slug)
        return {
            "technical_deployment": True,
            "deployment_purpose": "technical_test",
            "preview_slug": target.preview_slug,
            "fqdn": target.fqdn,
            "document_root": target.document_root,
            "cleanup": "manual_required",
            "read_only": True,
            "result": result.to_dict(),
        }
