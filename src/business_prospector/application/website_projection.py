from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from business_prospector.application.site_generation import SiteDraftService
from business_prospector.domain.models import Lead


_PREVIEW_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class WebsiteDeploymentProjection:
    website_stage: str | None
    approval_status: str | None
    preview_slug: str | None
    approved_at: str | None
    approved_by: str | None
    deployment_status: str | None
    preview_url: str | None
    deployment_mode: str | None
    published_at: str | None
    last_known_ssl_status: str | None
    files_uploaded: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "website_stage": self.website_stage,
            "approval_status": self.approval_status,
            "preview_slug": self.preview_slug,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "deployment_status": self.deployment_status,
            "preview_url": self.preview_url,
            "deployment_mode": self.deployment_mode,
            "published_at": self.published_at,
            "last_known_ssl_status": self.last_known_ssl_status,
            "files_uploaded": self.files_uploaded,
        }


class WebsiteDeploymentProjectionService:
    """Build a safe local read model without contacting the deployment provider."""

    def __init__(self, drafts: SiteDraftService) -> None:
        self._drafts = drafts

    def project(self, lead: Lead) -> WebsiteDeploymentProjection:
        info = self._drafts.inspect(lead.slug or "")
        if not info.exists or info.site_path is None:
            return WebsiteDeploymentProjection(*(None,) * 11)
        try:
            manifest = json.loads(
                (info.site_path / "site-manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return WebsiteDeploymentProjection(*(None,) * 11)
        preview = manifest.get("sales_preview")
        deployment = manifest.get("deployment")
        preview = preview if isinstance(preview, dict) else {}
        deployment = deployment if isinstance(deployment, dict) else {}

        approval_status = _safe_choice(
            preview.get("preview_status"), {"approved_not_published", "published"},
        )
        deployment_status = _safe_choice(deployment.get("deployment_status"), {"published"})
        if deployment_status == "published":
            stage = "published_sales_preview"
        elif approval_status in {"approved_not_published", "published"}:
            stage = "sales_preview"
        else:
            stage = "internal_website"

        slug = preview.get("preview_slug")
        safe_slug = slug if isinstance(slug, str) and _PREVIEW_SLUG.fullmatch(slug) else None
        preview_url = _safe_public_url(
            deployment.get("preview_url") or preview.get("preview_url")
        )
        files_uploaded = deployment.get("files_uploaded")
        safe_file_count = (
            files_uploaded
            if isinstance(files_uploaded, int) and not isinstance(files_uploaded, bool)
            and 0 <= files_uploaded <= 100
            else None
        )
        return WebsiteDeploymentProjection(
            stage,
            approval_status,
            safe_slug,
            _safe_text(preview.get("approved_at"), 64),
            _safe_text(preview.get("approved_by"), 100),
            deployment_status,
            preview_url,
            _safe_choice(deployment.get("deployment_mode"), {"direct_first_publish"}),
            _safe_text(deployment.get("published_at"), 64),
            _safe_choice(deployment.get("ssl_status"), {"active", "pending", "unknown"}),
            safe_file_count,
        )


def _safe_choice(value: Any, choices: set[str]) -> str | None:
    return value if isinstance(value, str) and value in choices else None


def _safe_text(value: Any, maximum: int) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= maximum else None


def _safe_public_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return value
