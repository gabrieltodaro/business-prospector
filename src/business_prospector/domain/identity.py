from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .normalization import normalize_address, normalize_domain, normalize_phone, normalize_text
from .website_presence import WebsitePresence, classify_website_presence


class BusinessIdentity(Protocol):
    name: str
    city: str
    website_url: str | None
    phone: str | None
    whatsapp: str | None
    address: str | None
    external_place_id: str | None


@dataclass(frozen=True, slots=True)
class IdentityMatch:
    rule: str
    strength: str

    def to_dict(self, matched_against: str) -> dict[str, str]:
        return {
            "rule": self.rule,
            "strength": self.strength,
            "matched_against": matched_against,
        }


def identity_domain(item: BusinessIdentity) -> str | None:
    presence = classify_website_presence(item.website_url).presence
    if presence not in {WebsitePresence.OWN_WEBSITE, WebsitePresence.HOSTED_WEBSITE}:
        return None
    return normalize_domain(item.website_url)


def match_business_identity(left: BusinessIdentity, right: BusinessIdentity) -> IdentityMatch | None:
    """Match two businesses without allowing fallbacks to contradict stable Place IDs."""
    left_place_id = left.external_place_id
    right_place_id = right.external_place_id
    if left_place_id and right_place_id:
        return IdentityMatch("external_place_id", "exact") if left_place_id == right_place_id else None

    left_domain = identity_domain(left)
    right_domain = identity_domain(right)
    if left_domain and left_domain == right_domain:
        return IdentityMatch("normalized_domain", "strong")

    left_phone = normalize_phone(left.whatsapp or left.phone)
    right_phone = normalize_phone(right.whatsapp or right.phone)
    if left_phone and left_phone == right_phone:
        return IdentityMatch("normalized_phone", "strong")

    left_address = normalize_address(left.address)
    right_address = normalize_address(right.address)
    if left_address and left_address == right_address:
        return IdentityMatch("normalized_address", "strong")

    left_name_city = (normalize_text(left.name), normalize_text(left.city))
    right_name_city = (normalize_text(right.name), normalize_text(right.city))
    if all(left_name_city) and left_name_city == right_name_city:
        return IdentityMatch("normalized_name_city", "possible")
    return None
