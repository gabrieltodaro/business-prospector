from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from business_prospector.application.ports import LeadRepository
from business_prospector.application.deployment import PreviewDeploymentProvider
from business_prospector.application.site_generation import SiteDraftService, validate_generated_site
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import Lead
from business_prospector.domain.normalization import normalize_text

LEGACY_INTERNAL_STATUS = "site_ready"
INTERNAL_STATUSES = {"internal_website", LEGACY_INTERNAL_STATUS}
RESERVED_PREVIEW_SLUGS = {
    "admin", "api", "app", "dashboard", "gapps", "help", "mail", "site", "sites",
    "support", "www",
}
VISIBLE_BLOCKERS = (
    "conteúdo a validar", "conteudo a validar", "em preparação", "em preparacao",
    "identidade visual em definição", "identidade visual em definicao", "lorem ipsum",
    "placeholder", "todo:", "tbd",
)


def propose_sales_preview_slug(
    business_name: str, identity: str, existing: set[str] | None = None,
) -> str:
    if not isinstance(business_name, str) or not business_name.strip():
        raise ValidationError("business name is required for preview slug")
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalize_text(business_name))
    tokens = normalized.split()
    if not tokens:
        raise ValidationError("business name cannot produce a preview slug")
    honorifics = {"dra": "dr", "doutora": "dr", "dr": "dr", "doutor": "dr"}
    if tokens[0] in honorifics and len(tokens) > 1:
        base = honorifics[tokens[0]] + tokens[1]
    else:
        ignored = {"de", "da", "do", "das", "dos", "e", "ltda", "me", "eireli"}
        meaningful = [token for token in tokens if token not in ignored]
        base = "".join((meaningful or tokens)[:2])
    base = base[:24].strip("-") or "preview"
    occupied = existing or set()
    if base in RESERVED_PREVIEW_SLUGS or base in occupied:
        digest = hashlib.sha256((identity or business_name).encode("utf-8")).hexdigest()[:6]
        base = f"{base[:24]}-{digest}"
    return base[:32]


@dataclass(frozen=True, slots=True)
class SalesPreviewReadiness:
    ready: bool
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    artifact_valid: bool
    assets_publishable: bool
    asset_count: int
    assets_not_approved: tuple[str, ...]
    missing_information_count: int
    proposed_preview_slug: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready, "blocking_reasons": list(self.blocking_reasons),
            "warnings": list(self.warnings), "artifact_valid": self.artifact_valid,
            "assets_publishable": self.assets_publishable, "asset_count": self.asset_count,
            "assets_not_approved": list(self.assets_not_approved),
            "missing_information_count": self.missing_information_count,
            "proposed_preview_slug": self.proposed_preview_slug,
        }


@dataclass(frozen=True, slots=True)
class SalesPreviewApproval:
    lead: Lead
    readiness: SalesPreviewReadiness
    preview_slug: str
    approved_at: str
    approved_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead": self.lead.to_dict(), "readiness": self.readiness.to_dict(),
            "preview_slug": self.preview_slug, "preview_status": "approved_not_published",
            "preview_url": None, "approved_at": self.approved_at, "approved_by": self.approved_by,
        }


class SalesPreviewLifecycleService:
    def __init__(self, repository: LeadRepository, drafts: SiteDraftService) -> None:
        self._repository = repository
        self._drafts = drafts

    def readiness(
        self, lead: Lead, *, content_review_acknowledged: bool = False,
        publish_asset_keys: set[str] | None = None,
    ) -> SalesPreviewReadiness:
        blockers: list[str] = []
        warnings: list[str] = []
        publish_keys = publish_asset_keys or set()
        info = self._drafts.inspect(lead.slug or "")
        if not info.exists or info.site_path is None:
            return SalesPreviewReadiness(
                False, ("valid generated site is required",), (), False, False, 0, (), 0, None,
            )
        try:
            validate_generated_site(info.site_path)
            manifest = json.loads((info.site_path / "site-manifest.json").read_text(encoding="utf-8"))
            identity = manifest.get("lead_identity")
            if not isinstance(identity, dict) or identity.get("slug") != lead.slug:
                blockers.append("artifact identity does not match lead")
            manifest_place = identity.get("external_place_id") if isinstance(identity, dict) else None
            if manifest_place and lead.external_place_id and manifest_place != lead.external_place_id:
                blockers.append("artifact business identity does not match lead")
            if manifest.get("opportunity_type") != lead.opportunity_type:
                blockers.append("artifact opportunity type does not match lead")
            html = (info.site_path / "index.html").read_text(encoding="utf-8").casefold()
            for marker in VISIBLE_BLOCKERS:
                if marker in html:
                    blockers.append(f"visible internal placeholder: {marker}")
            css = (info.site_path / "styles.css").read_text(encoding="utf-8")
            if "@media" not in css or not manifest.get("strategy_version"):
                blockers.append("responsive generation metadata is missing")
            assets = manifest.get("assets")
            if not isinstance(assets, list) or not assets:
                blockers.append("manifest must contain rendered assets")
                assets = []
            not_approved: list[str] = []
            assets_have_blockers = False
            for raw in assets:
                if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
                    blockers.append("asset metadata is malformed")
                    assets_have_blockers = True
                    continue
                key = raw["key"]
                approval = "approved_for_publish" if key in publish_keys else raw.get("approval_status")
                rights = raw.get("rights_status")
                if rights in {"unknown", "do_not_use"} or raw.get("approval_status") == "rejected":
                    blockers.append(f"asset {key} has unacceptable publication rights")
                    assets_have_blockers = True
                elif approval != "approved_for_publish":
                    not_approved.append(key)
                local_file = raw.get("local_file")
                if not isinstance(local_file, str) or self._drafts.resolve_file(
                    lead.slug or "", tuple(local_file.split("/")),
                ) is None:
                    blockers.append(f"asset {key} is missing or unsafe")
                    assets_have_blockers = True
            if not_approved:
                blockers.extend(f"asset {key} is not approved for publish" for key in not_approved)
            missing = manifest.get("missing_information")
            missing_count = len(missing) if isinstance(missing, list) else 0
            if missing_count:
                warnings.append(f"{missing_count} missing-information items require human review")
            if not content_review_acknowledged:
                blockers.append("visible business content review must be acknowledged")
            preview_slug = propose_sales_preview_slug(
                lead.name, lead.external_place_id or lead.slug or lead.name,
            )
            unique_blockers = tuple(dict.fromkeys(blockers))
            return SalesPreviewReadiness(
                not unique_blockers, unique_blockers, tuple(warnings), True,
                not not_approved and not assets_have_blockers,
                len(assets), tuple(not_approved), missing_count, preview_slug,
            )
        except (ValidationError, ValueError, OSError, json.JSONDecodeError):
            return SalesPreviewReadiness(
                False, ("site manifest or generated artifact is invalid",), (), False, False,
                0, (), 0, None,
            )

    def approve(
        self, lead_id: int, *, content_review_acknowledged: bool,
        asset_keys_approved_for_publish: list[str], approved_by: str,
    ) -> SalesPreviewApproval:
        lead = self._repository.get(lead_id)
        if lead is None:
            raise ValidationError("persisted lead not found")
        if lead.status not in INTERNAL_STATUSES:
            raise ValidationError("lead must be in Internal Website before approval")
        if content_review_acknowledged is not True:
            raise ValidationError("content review acknowledgement is required")
        if not isinstance(approved_by, str) or not approved_by.strip() or len(approved_by) > 100:
            raise ValidationError("approved_by is required")
        keys = set(asset_keys_approved_for_publish)
        if len(keys) != len(asset_keys_approved_for_publish) or not all(
            isinstance(key, str) and key for key in keys
        ):
            raise ValidationError("asset approval keys are invalid")
        readiness = self.readiness(
            lead, content_review_acknowledged=True, publish_asset_keys=keys,
        )
        if not readiness.ready:
            raise ValidationError("sales preview is not ready: " + "; ".join(readiness.blocking_reasons))
        info = self._drafts.inspect(lead.slug or "")
        assert info.site_path is not None
        manifest_path = info.site_path / "site-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_keys = {item["key"] for item in manifest["assets"]}
        unknown = keys - manifest_keys
        if unknown:
            raise ValidationError("unknown asset approval keys: " + ", ".join(sorted(unknown)))
        for asset in manifest["assets"]:
            if asset["key"] in keys:
                asset["approval_status"] = "approved_for_publish"
        approved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        preview_slug = readiness.proposed_preview_slug or propose_sales_preview_slug(
            lead.name, lead.external_place_id or lead.slug or lead.name,
        )
        manifest["sales_preview"] = {
            "preview_slug": preview_slug, "preview_status": "approved_not_published",
            "preview_url": None, "approved_at": approved_at, "approved_by": approved_by,
            "content_review_acknowledged": True,
        }
        self._write_manifest(manifest_path, manifest)
        updated = self._repository.update(lead_id, {"status": "sales_preview"})
        final_readiness = self.readiness(updated, content_review_acknowledged=True)
        return SalesPreviewApproval(updated, final_readiness, preview_slug, approved_at, approved_by.strip())

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".manifest-", delete=False,
        ) as temporary:
            json.dump(manifest, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
