from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from .exceptions import ValidationError
from .normalization import normalize_address, normalize_domain, normalize_phone, normalize_text, slugify

ISSUE_FIELDS = (
    "layout",
    "mobile",
    "cta",
    "content",
    "social_proof",
    "platform",
)
PIPELINE_STATUSES = (
    "new",
    "qualified",
    "needs_review",
    "internal_website",
    "sales_preview",
    "contacted",
    "proposal",
    "closed",
    "discarded",
)
# `rejected` is retained for existing records; new dashboard movement uses
# `discarded`, which describes a commercial pipeline decision more accurately.
VALID_STATUSES = set(PIPELINE_STATUSES) | {"rejected", "site_ready"}
VALID_WHATSAPP_SOURCES = {"website_link", "google_business_phone", "manual", "unknown"}
OPPORTUNITY_TYPES = {"redesign", "first_website"}
ASSESSMENT_PERSISTENCE_STATUSES = {
    "assessed", "unavailable", "blocked", "timeout", "insufficient_evidence", "error",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_http_url(value: str | None, field_name: str) -> None:
    if not value:
        return
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError(f"{field_name} must be an absolute http(s) URL")


@dataclass(frozen=True, slots=True)
class WebsiteAssessment:
    layout: bool = False
    mobile: bool = False
    cta: bool = False
    content: bool = False
    social_proof: bool = False
    platform: bool = False
    reason: str = ""

    @property
    def issue_count(self) -> int:
        return sum(bool(getattr(self, name)) for name in ISSUE_FIELDS)


@dataclass(frozen=True, slots=True)
class BusinessCandidate:
    name: str
    category: str
    city: str
    rating: float
    review_count: int
    website_url: str | None = None
    external_place_id: str | None = None
    address: str | None = None
    maps_url: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    whatsapp_confirmed: bool = False
    whatsapp_source: str = "unknown"
    email: str | None = None
    instagram: str | None = None
    source: str = "fake"

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in (self.name, self.category, self.city)):
            raise ValidationError("candidate name, category and city must be strings")
        if not self.name.strip() or not self.category.strip() or not self.city.strip():
            raise ValidationError("candidate name, category and city are required")
        if isinstance(self.rating, bool) or not isinstance(self.rating, (int, float)) or not 0 <= self.rating <= 5:
            raise ValidationError("rating must be between 0 and 5")
        if isinstance(self.review_count, bool) or not isinstance(self.review_count, int) or self.review_count < 0:
            raise ValidationError("review_count cannot be negative")
        for field_name, value in (("website_url", self.website_url), ("maps_url", self.maps_url), ("instagram", self.instagram)):
            if value is not None and not isinstance(value, str):
                raise ValidationError(f"{field_name} must be a string")
        if self.whatsapp_confirmed and not self.whatsapp:
            raise ValidationError("confirmed WhatsApp requires a number")
        if self.whatsapp_source not in VALID_WHATSAPP_SOURCES:
            raise ValidationError(f"invalid whatsapp_source: {self.whatsapp_source}")
        validate_http_url(self.website_url, "website_url")
        validate_http_url(self.maps_url, "maps_url")
        validate_http_url(self.instagram, "instagram")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Lead:
    name: str
    category: str
    city: str
    rating: float
    review_count: int
    website_url: str
    assessment: WebsiteAssessment
    external_place_id: str | None = None
    slug: str | None = None
    address: str | None = None
    maps_url: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    whatsapp_confirmed: bool = False
    whatsapp_source: str = "unknown"
    email: str | None = None
    instagram: str | None = None
    score: int = 0
    status: str = "qualified"
    source: str = "manual"
    website_assessment: dict[str, Any] | None = None
    assessment_status: str | None = None
    assessment_checked_at: str | None = None
    batch_id: str | None = None
    opportunity_type: str = "redesign"
    first_website_reason: str | None = None
    market_research: dict[str, Any] | None = None
    market_research_status: str | None = None
    market_research_checked_at: str | None = None
    discovered_at: str = field(default_factory=utc_now)
    last_checked_at: str = field(default_factory=utc_now)
    id: int | None = None

    def __post_init__(self) -> None:
        self.slug = self.slug or slugify(f"{self.name}-{self.city}")
        self.validate()

    def validate(self) -> None:
        if not self.name.strip() or not self.city.strip():
            raise ValidationError("name and city are required")
        if not 0 <= self.rating <= 5:
            raise ValidationError("rating must be between 0 and 5")
        if self.review_count < 0:
            raise ValidationError("review_count cannot be negative")
        if self.status not in VALID_STATUSES:
            raise ValidationError(f"invalid status: {self.status}")
        if self.whatsapp_source not in VALID_WHATSAPP_SOURCES:
            raise ValidationError(f"invalid whatsapp_source: {self.whatsapp_source}")
        if self.whatsapp_confirmed and not self.whatsapp:
            raise ValidationError("confirmed WhatsApp requires a number")
        if self.assessment_status is not None and self.assessment_status not in ASSESSMENT_PERSISTENCE_STATUSES:
            raise ValidationError(f"invalid assessment_status: {self.assessment_status}")
        if self.website_assessment is not None and not isinstance(self.website_assessment, dict):
            raise ValidationError("website_assessment must be a validated object")
        if self.website_assessment is not None and (
            self.assessment_status is None or self.assessment_checked_at is None
        ):
            raise ValidationError("structured assessment requires status and checked_at")
        if self.batch_id is not None and (not self.batch_id.strip() or len(self.batch_id) > 100):
            raise ValidationError("batch_id must be a non-empty string up to 100 characters")
        if self.opportunity_type not in OPPORTUNITY_TYPES:
            raise ValidationError("invalid opportunity_type")
        if self.opportunity_type == "first_website" and not self.first_website_reason:
            raise ValidationError("first website opportunity requires a reason")
        if self.market_research is not None and (
            self.market_research_status is None or self.market_research_checked_at is None
        ):
            raise ValidationError("market research requires status and checked_at")
        validate_http_url(self.website_url, "website_url")
        validate_http_url(self.maps_url, "maps_url")
        validate_http_url(self.instagram, "instagram")

    @property
    def normalized_domain(self) -> str | None:
        return normalize_domain(self.website_url)

    @property
    def normalized_phone(self) -> str | None:
        return normalize_phone(self.whatsapp or self.phone)

    @property
    def normalized_name(self) -> str:
        return normalize_text(self.name)

    @property
    def normalized_city(self) -> str:
        return normalize_text(self.city)

    @property
    def normalized_address(self) -> str | None:
        return normalize_address(self.address)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["website_issue_count"] = self.assessment.issue_count
        return data
