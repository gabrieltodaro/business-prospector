from __future__ import annotations

import pytest

from business_prospector.domain.website_presence import WebsitePresence, classify_website_presence


@pytest.mark.parametrize("url", ["https://example.com", "https://www.clinica.com.br"])
def test_classifies_owned_websites(url: str) -> None:
    assert classify_website_presence(url).presence == WebsitePresence.OWN_WEBSITE


@pytest.mark.parametrize("url", [
    "https://business.netlify.app",
    "https://business.vercel.app",
    "https://business.wixsite.com/site",
    "https://business.wordpress.com",
])
def test_classifies_real_hosted_websites(url: str) -> None:
    assert classify_website_presence(url).presence == WebsitePresence.HOSTED_WEBSITE


@pytest.mark.parametrize("url", [
    "https://instagram.com/business",
    "https://www.instagram.com/business/?igsh=abc",
    "https://facebook.com/business",
    "https://m.facebook.com/business",
    "https://tiktok.com/@business",
    "https://linkedin.com/company/business",
    "https://x.com/business",
    "https://twitter.com/business",
    "https://YOUTUBE.COM/@business#about",
])
def test_classifies_social_profiles_by_parsed_hostname(url: str) -> None:
    assert classify_website_presence(url).presence == WebsitePresence.SOCIAL_ONLY


@pytest.mark.parametrize("url", ["https://linktr.ee/business", "https://LINKTR.EE/business?ref=x#bio"])
def test_classifies_third_party_profiles(url: str) -> None:
    assert classify_website_presence(url).presence == WebsitePresence.THIRD_PARTY_PROFILE


@pytest.mark.parametrize("url", [None, "", "  "])
def test_classifies_missing_website(url: str | None) -> None:
    assert classify_website_presence(url).presence == WebsitePresence.NO_WEBSITE


@pytest.mark.parametrize("url", ["not a URL", "javascript:alert(1)", "https://", "://broken"])
def test_classifies_malformed_or_unsupported_urls(url: str) -> None:
    assert classify_website_presence(url).presence == WebsitePresence.INVALID_URL


def test_hostname_matching_ignores_case_www_query_and_fragment() -> None:
    result = classify_website_presence("https://WWW.INSTAGRAM.COM/business?igsh=abc#profile")
    assert result.presence == WebsitePresence.SOCIAL_ONLY
    assert result.hostname == "instagram.com"
