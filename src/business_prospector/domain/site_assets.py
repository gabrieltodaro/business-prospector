from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .exceptions import ValidationError
from .normalization import slugify

ASSET_TYPES = {"photo", "logo", "icon", "illustration"}
SOURCE_TYPES = {
    "existing_business_site", "business_social_reference", "licensed_stock",
    "generated", "placeholder", "unknown",
}
RIGHTS_STATUSES = {"likely_business_owned", "licensed", "generated", "unknown", "do_not_use"}
APPROVAL_STATUSES = {"candidate", "approved_for_draft", "approved_for_publish", "rejected"}
SAFE_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _text(value: Any, field: str, maximum: int = 500, required: bool = True) -> str | None:
    if value in (None, "") and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{field} is invalid")
    return value.strip()


@dataclass(frozen=True, slots=True)
class SiteAsset:
    key: str
    asset_type: str
    source_type: str
    source_url: str | None
    discovered_from: str | None
    business_identity_match: bool
    rights_status: str
    approval_status: str
    alt_text: str | None
    width: int | None
    height: int | None
    mime_type: str | None
    byte_size: int | None
    local_file: str | None = None
    checksum: str | None = None
    notes: str | None = None

    @classmethod
    def from_observation(cls, payload: dict[str, Any]) -> "SiteAsset":
        if not isinstance(payload, dict):
            raise ValidationError("asset observation must be an object")
        key = _text(payload.get("key"), "asset key", 80)
        try:
            safe_key = slugify(key or "")
        except ValueError as exc:
            raise ValidationError("asset key is unsafe") from exc
        if key != safe_key:
            raise ValidationError("asset key is unsafe")
        asset_type, source_type = payload.get("asset_type"), payload.get("source_type")
        if asset_type not in ASSET_TYPES or source_type not in SOURCE_TYPES:
            raise ValidationError("asset type or source type is invalid")
        source_url = _text(payload.get("source_url"), "source_url", 2000, required=False)
        discovered = _text(payload.get("discovered_from"), "discovered_from", 2000, required=False)
        for field, value in (("source_url", source_url), ("discovered_from", discovered)):
            if value:
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValidationError(f"{field} must be an absolute HTTP(S) URL")
                if parsed.username or parsed.password:
                    raise ValidationError(f"{field} cannot contain credentials")
                sensitive = {"token", "key", "api_key", "signature", "x-amz-signature"}
                if any(name.casefold() in sensitive for name, _ in parse_qsl(parsed.query)):
                    raise ValidationError(f"{field} cannot contain secret query parameters")
        width, height, byte_size = payload.get("width"), payload.get("height"), payload.get("byte_size")
        for field, value in (("width", width), ("height", height), ("byte_size", byte_size)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValidationError(f"asset {field} must be a positive integer")
        mime = _text(payload.get("mime_type"), "mime_type", 100, required=False)
        return cls(
            key=key or "", asset_type=asset_type, source_type=source_type,
            source_url=source_url, discovered_from=discovered,
            business_identity_match=payload.get("business_identity_match") is True,
            rights_status="unknown", approval_status="candidate",
            alt_text=_text(payload.get("alt_text"), "alt_text", 300, required=False),
            width=width, height=height, mime_type=mime, byte_size=byte_size,
            notes=_text(payload.get("notes"), "notes", 500, required=False),
        )

    def classified(self, *, rights_status: str, approval_status: str) -> "SiteAsset":
        if rights_status not in RIGHTS_STATUSES or approval_status not in APPROVAL_STATUSES:
            raise ValidationError("invalid asset rights or approval status")
        return replace(self, rights_status=rights_status, approval_status=approval_status)

    def with_local_file(self, local_file: str, checksum: str, mime_type: str, byte_size: int) -> "SiteAsset":
        return replace(
            self, local_file=local_file, checksum=checksum, mime_type=mime_type, byte_size=byte_size,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "asset_type": self.asset_type, "source_type": self.source_type,
            "source_url": self.source_url, "discovered_from": self.discovered_from,
            "business_identity_match": self.business_identity_match,
            "rights_status": self.rights_status, "approval_status": self.approval_status,
            "alt_text": self.alt_text, "width": self.width, "height": self.height,
            "mime_type": self.mime_type, "byte_size": self.byte_size,
            "local_file": self.local_file, "checksum": self.checksum, "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class AssetRejection:
    key: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class AssetValidationResult:
    accepted: tuple[SiteAsset, ...]
    rejected: tuple[AssetRejection, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": [item.to_dict() for item in self.accepted],
            "rejected": [item.to_dict() for item in self.rejected],
        }
