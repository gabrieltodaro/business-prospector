from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class WebsitePresence(StrEnum):
    OWN_WEBSITE = "own_website"
    HOSTED_WEBSITE = "hosted_website"
    NO_WEBSITE = "no_website"
    SOCIAL_ONLY = "social_only"
    THIRD_PARTY_PROFILE = "third_party_profile"
    INVALID_URL = "invalid_url"


SOCIAL_PROFILE_DOMAINS = frozenset({
    "instagram.com",
    "facebook.com",
    "fb.com",
    "tiktok.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
})

THIRD_PARTY_PROFILE_DOMAINS = frozenset({
    "linktr.ee",
    "beacons.ai",
    "bio.site",
    "solo.to",
    "taplink.cc",
})

HOSTED_WEBSITE_DOMAINS = frozenset({
    "netlify.app",
    "vercel.app",
    "wixsite.com",
    "wordpress.com",
    "web.app",
    "github.io",
})


@dataclass(frozen=True, slots=True)
class WebsitePresenceClassification:
    presence: WebsitePresence
    hostname: str | None = None


def _matches_domain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def classify_website_presence(value: str | None) -> WebsitePresenceClassification:
    if value is None or not value.strip():
        return WebsitePresenceClassification(WebsitePresence.NO_WEBSITE)
    try:
        parsed = urlsplit(value.strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return WebsitePresenceClassification(WebsitePresence.INVALID_URL)
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return WebsitePresenceClassification(WebsitePresence.INVALID_URL)
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if any(_matches_domain(hostname, domain) for domain in SOCIAL_PROFILE_DOMAINS):
        return WebsitePresenceClassification(WebsitePresence.SOCIAL_ONLY, hostname)
    if any(_matches_domain(hostname, domain) for domain in THIRD_PARTY_PROFILE_DOMAINS):
        return WebsitePresenceClassification(WebsitePresence.THIRD_PARTY_PROFILE, hostname)
    if any(hostname != domain and hostname.endswith(f".{domain}") for domain in HOSTED_WEBSITE_DOMAINS):
        return WebsitePresenceClassification(WebsitePresence.HOSTED_WEBSITE, hostname)
    return WebsitePresenceClassification(WebsitePresence.OWN_WEBSITE, hostname)
