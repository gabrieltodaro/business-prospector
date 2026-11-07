"""Explicit replacement of research for an existing qualified first-website lead."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.first_website import FirstWebsiteMarketReport
from business_prospector.domain.models import Lead, utc_now
from .artifacts import read_local_manifest, site_operation_lock
from .config import ProspectingConfig
from .draft_revision import archive_draft
from .ports import LeadRepository
from .qualification import validate_qualified_lead


@dataclass(frozen=True, slots=True)
class ResearchRefreshResult:
    lead: Lead
    previous_artifact_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead": self.lead.to_dict(),
            "previous_artifact_path": str(self.previous_artifact_path) if self.previous_artifact_path else None,
        }


class ResearchRefreshService:
    def __init__(self, repository: LeadRepository, config: ProspectingConfig, sites_root: Path) -> None:
        self._repository = repository
        self._config = config
        self._sites_root = sites_root.expanduser().resolve()

    def refresh(self, lead_id: int, research: dict[str, Any]) -> ResearchRefreshResult:
        if type(lead_id) is not int or lead_id < 1:
            raise ValidationError("persisted lead id is required")
        report = FirstWebsiteMarketReport.from_dict(research)
        snapshot = self._repository.get_research_refresh_snapshot(lead_id)
        lead = snapshot.lead
        if lead.status != "qualified" or lead.opportunity_type != "first_website":
            raise ValidationError("research refresh requires a qualified first_website lead")
        proposed = replace(lead, market_research=report.to_dict(), market_research_status=report.status,
                           market_research_checked_at=utc_now())
        proposed.validate()
        validate_qualified_lead(proposed, self._config, self._repository)
        with site_operation_lock(self._sites_root, lead.slug or ""):
            if self._repository.get_deployment(lead_id) is not None:
                raise ValidationError("reserved deployment research cannot be refreshed")
            destination = self._sites_root / lead.slug
            self._validate_unpublished_draft(destination, lead)
            # Database commit happens inside the recoverable archive operation. A failed
            # transaction restores the original files and approval metadata byte for byte.
            with archive_draft(destination) as previous:
                updated = self._repository.replace_market_research(snapshot, report.to_dict())
            return ResearchRefreshResult(updated, previous)

    @staticmethod
    def _validate_unpublished_draft(destination: Path, lead: Lead) -> None:
        if destination.is_symlink():
            raise ValidationError("draft destination cannot be a symlink")
        if not destination.exists():
            return
        manifest = read_local_manifest(destination)
        if manifest.get("lead_identity") != {"slug": lead.slug, "external_place_id": lead.external_place_id}:
            raise ValidationError("research refresh must preserve draft identity")
        for key, status in (("deployment", "deployment_status"), ("sales_preview", "preview_status")):
            metadata = manifest.get(key)
            if metadata is not None and not isinstance(metadata, dict):
                raise ValidationError("invalid existing publication metadata")
            if metadata and (key == "deployment" or metadata.get(status) == "published"):
                raise ValidationError("published or reserved artifacts cannot be refreshed")
