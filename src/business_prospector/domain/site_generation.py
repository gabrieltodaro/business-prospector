from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import ValidationError
from .first_website import FirstWebsiteMarketReport
from .models import validate_http_url
from .normalization import slugify

SITE_STRATEGY_VERSION = "2.0"


def _optional_text(value: Any, field: str, maximum: int = 500) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{field} must be a non-empty string up to {maximum} characters")
    return value.strip()


@dataclass(frozen=True, slots=True)
class WebsiteStrategy:
    primary_goal: str
    primary_cta: str
    sections: tuple[str, ...]
    trust_strategy: str
    contact_strategy: str
    mobile_priorities: tuple[str, ...]
    content_assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_goal": self.primary_goal,
            "primary_cta": self.primary_cta,
            "sections": list(self.sections),
            "trust_strategy": self.trust_strategy,
            "contact_strategy": self.contact_strategy,
            "mobile_priorities": list(self.mobile_priorities),
            "content_assumptions": list(self.content_assumptions),
        }


@dataclass(frozen=True, slots=True)
class FirstWebsiteSiteBrief:
    lead_slug: str
    business_name: str
    category: str
    city: str
    address: str | None
    phone: str | None
    whatsapp: str | None
    whatsapp_confirmed: bool
    instagram: str | None
    maps_url: str | None
    rating: float
    review_count: int
    opportunity_type: str
    status: str
    batch_id: str | None
    external_place_id: str | None
    market_research: FirstWebsiteMarketReport
    strategy: WebsiteStrategy
    missing_information: tuple[str, ...]

    @classmethod
    def from_inputs(cls, lead: dict[str, Any], research: dict[str, Any]) -> "FirstWebsiteSiteBrief":
        if not isinstance(lead, dict):
            raise ValidationError("lead must be an object")
        if lead.get("opportunity_type") != "first_website":
            raise ValidationError("lead must be a first_website opportunity")
        if lead.get("status") != "qualified":
            raise ValidationError("lead must have qualified status")
        name = _optional_text(lead.get("name"), "name", 200)
        category = _optional_text(lead.get("category"), "category", 200)
        city = _optional_text(lead.get("city"), "city", 200)
        if not name or not category or not city:
            raise ValidationError("name, category and city are required")
        rating, reviews = lead.get("rating"), lead.get("review_count")
        if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not 0 <= rating <= 5:
            raise ValidationError("rating must be between 0 and 5")
        if isinstance(reviews, bool) or not isinstance(reviews, int) or reviews < 0:
            raise ValidationError("review_count cannot be negative")
        report = FirstWebsiteMarketReport.from_dict(research)
        if report.status != "complete" or len(report.benchmarks) < 2:
            raise ValidationError("complete market research with at least 2 benchmarks is required")
        address = _optional_text(lead.get("address"), "address")
        phone = _optional_text(lead.get("phone"), "phone", 100)
        whatsapp = _optional_text(lead.get("whatsapp"), "whatsapp", 100)
        confirmed = lead.get("whatsapp_confirmed") is True and whatsapp is not None
        instagram = _optional_text(lead.get("instagram"), "instagram")
        maps_url = _optional_text(lead.get("maps_url"), "maps_url")
        validate_http_url(instagram, "instagram")
        validate_http_url(maps_url, "maps_url")
        slug = _optional_text(lead.get("slug"), "slug", 240) or slugify(f"{name}-{city}")
        try:
            safe_slug = slugify(slug)
        except ValueError as exc:
            raise ValidationError("lead slug is unsafe") from exc
        if slug != safe_slug or slug in {"", ".", ".."}:
            raise ValidationError("lead slug is unsafe")
        missing = tuple(field for field, value in (
            ("address", address), ("phone", phone), ("confirmed_whatsapp", whatsapp if confirmed else None),
            ("instagram", instagram), ("maps_url", maps_url), ("services_or_treatments", None),
            ("professional_biography", None), ("opening_hours", None),
        ) if value is None)
        primary_cta = "Conversar pelo WhatsApp" if confirmed else ("Entrar em contato" if phone else "Ver localização")
        contact_strategy = "confirmed_whatsapp" if confirmed else ("public_phone" if phone else "public_location")
        strategy = WebsiteStrategy(
            primary_goal="Facilitar o primeiro contato com informações públicas verificadas",
            primary_cta=primary_cta,
            sections=("hero", "introduction", "services_placeholder", "reputation", "contact"),
            trust_strategy="Exibir somente reputação pública e dados verificáveis",
            contact_strategy=contact_strategy,
            mobile_priorities=("CTA visível", "leitura rápida", "contato com poucos toques"),
            content_assumptions=("Textos institucionais genéricos não representam credenciais clínicas"),
        )
        return cls(
            slug, name, category, city, address, phone, whatsapp, confirmed, instagram, maps_url,
            float(rating), reviews, "first_website", "qualified",
            _optional_text(lead.get("batch_id"), "batch_id", 100),
            _optional_text(lead.get("external_place_id"), "external_place_id", 300),
            report, strategy, missing,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead_slug": self.lead_slug, "business_name": self.business_name,
            "category": self.category, "city": self.city, "address": self.address,
            "phone": self.phone, "whatsapp": self.whatsapp if self.whatsapp_confirmed else None,
            "whatsapp_confirmed": self.whatsapp_confirmed, "instagram": self.instagram,
            "maps_url": self.maps_url, "rating": self.rating, "review_count": self.review_count,
            "opportunity_type": self.opportunity_type, "status": self.status,
            "batch_id": self.batch_id, "external_place_id": self.external_place_id,
            "benchmark_market": self.market_research.benchmark_market,
            "benchmarks_used": len(self.market_research.benchmarks),
            "common_features": [item.to_dict() for item in self.market_research.common_features],
            "facts": [fact for item in self.market_research.benchmarks for fact in item.facts],
            "inferences": list(self.market_research.inferences),
            "recommendations": list(self.market_research.recommendations),
            "confidence": self.market_research.confidence,
            "strategy": self.strategy.to_dict(), "missing_information": list(self.missing_information),
        }
