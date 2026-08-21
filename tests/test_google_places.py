from __future__ import annotations

import json
import socket
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.ports import SearchQuery
from business_prospector.application.prospecting import ProspectingService
from business_prospector.domain.models import WebsiteAssessment
from business_prospector.infrastructure.google_places import (
    FIELD_MASK,
    GooglePlacesBusinessDiscoveryProvider,
    GooglePlacesConfigurationError,
    GooglePlacesError,
    GooglePlacesResponseError,
)
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


class Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class StubOpener:
    def __init__(self, *payloads: object) -> None:
        self.payloads = list(payloads)
        self.requests: list[object] = []

    def __call__(self, request: object, **_: object) -> Response:
        self.requests.append(request)
        payload = self.payloads.pop(0)
        if isinstance(payload, BaseException):
            raise payload
        return Response(payload)


def provider(opener: StubOpener, key: str = "test-secret") -> GooglePlacesBusinessDiscoveryProvider:
    return GooglePlacesBusinessDiscoveryProvider(key, opener=opener)


def place(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": "place-123",
        "displayName": {"text": "Clínica Sorriso", "languageCode": "pt-BR"},
        "formattedAddress": "Rua Brasil, 10, Catanduva - SP, Brasil",
        "googleMapsUri": "https://maps.google.com/?cid=123",
        "primaryType": "dentist",
        "rating": 4.8,
        "userRatingCount": 87,
        "websiteUri": "https://sorriso.example.com",
        "nationalPhoneNumber": "(17) 3522-1000",
    }
    result.update(changes)
    return result


def test_successful_text_search_maps_domain_fields() -> None:
    opener = StubOpener({"places": [place()]})
    candidates = provider(opener).search(SearchQuery("dentistas", "Catanduva, SP", 10))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.name == "Clínica Sorriso"
    assert candidate.category == "dentist"
    assert candidate.city == "Catanduva, SP"
    assert candidate.rating == 4.8
    assert candidate.review_count == 87
    assert candidate.website_url == "https://sorriso.example.com"
    assert candidate.external_place_id == "place-123"
    assert candidate.address == "Rua Brasil, 10, Catanduva - SP, Brasil"
    assert candidate.maps_url == "https://maps.google.com/?cid=123"
    assert candidate.phone == "(17) 3522-1000"
    assert candidate.source == "google_places_new"

    request = opener.requests[0]
    body = json.loads(request.data)
    assert body == {
        "textQuery": "dentistas em Catanduva, SP, Brasil",
        "languageCode": "pt-BR",
        "regionCode": "BR",
        "pageSize": 10,
    }
    assert request.get_header("X-goog-fieldmask") == FIELD_MASK
    assert "*" not in FIELD_MASK
    assert "test-secret" not in request.full_url


def test_empty_results_are_not_an_error() -> None:
    assert provider(StubOpener({})).search(SearchQuery("psicólogos", "Catanduva", 5)) == []


def test_missing_api_key_has_safe_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(GooglePlacesConfigurationError, match="not configured") as caught:
        GooglePlacesBusinessDiscoveryProvider().search(SearchQuery("dentistas", "Catanduva", 1))
    assert "GOOGLE_MAPS_API_KEY" not in str(caught.value)


@pytest.mark.parametrize("payload", [[], {"places": {}}, {"places": [None]}, {"places": [{}]}])
def test_malformed_payload_is_rejected(payload: object) -> None:
    with pytest.raises(GooglePlacesResponseError, match="unexpected response"):
        provider(StubOpener(payload)).search(SearchQuery("dentistas", "Catanduva", 1))


@pytest.mark.parametrize(
    ("status", "message"),
    [(400, "rejected"), (401, "authorization"), (403, "authorization"), (429, "quota"), (503, "unavailable")],
)
def test_http_errors_are_safe(status: int, message: str) -> None:
    secret = "must-never-leak"
    error = HTTPError("https://places.googleapis.com", status, secret, {}, BytesIO(secret.encode()))
    with pytest.raises(GooglePlacesError, match=message) as caught:
        provider(StubOpener(error), secret).search(SearchQuery("dentistas", "Catanduva", 1))
    assert secret not in str(caught.value)


@pytest.mark.parametrize("error", [TimeoutError(), socket.timeout(), URLError("DNS secret")])
def test_network_errors_are_safe(error: BaseException) -> None:
    with pytest.raises(GooglePlacesError) as caught:
        provider(StubOpener(error)).search(SearchQuery("dentistas", "Catanduva", 1))
    assert "test-secret" not in str(caught.value)


def test_pagination_stops_at_requested_limit() -> None:
    first = {"places": [place(id=f"first-{i}") for i in range(20)], "nextPageToken": "page-2"}
    second = {"places": [place(id=f"second-{i}") for i in range(5)], "nextPageToken": "unused"}
    opener = StubOpener(first, second)
    results = provider(opener).search(SearchQuery("dentistas", "Catanduva", 25))
    assert len(results) == 25
    assert len(opener.requests) == 2
    assert json.loads(opener.requests[1].data)["pageToken"] == "page-2"
    assert json.loads(opener.requests[1].data)["pageSize"] == 5


class AlwaysProblematicAssessment:
    def assess(self, candidate: object) -> WebsiteAssessment:
        return WebsiteAssessment(layout=True, mobile=True, reason="controlled test")


def test_google_candidate_composes_with_existing_filtering_and_place_id_dedup(tmp_path: Path) -> None:
    discovery = provider(StubOpener({"places": [place()]}))
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    config = ProspectingConfig(max_businesses=1, target_leads=1)
    service = ProspectingService(discovery, AlwaysProblematicAssessment(), repository, config)
    first = service.prospect("dentistas", "Catanduva")
    assert first.inspected == 1
    assert first.leads[0].external_place_id == "place-123"

    second_discovery = provider(StubOpener({"places": [place(websiteUri="https://changed.example.com")]}))
    second = ProspectingService(second_discovery, AlwaysProblematicAssessment(), repository, config)
    result = second.prospect("dentistas", "Catanduva")
    assert result.duplicates == 1
    assert result.leads == []


def test_google_candidate_uses_existing_reputation_filter(tmp_path: Path) -> None:
    discovery = provider(StubOpener({"places": [place(rating=4.0, userRatingCount=10)]}))
    service = ProspectingService(
        discovery,
        AlwaysProblematicAssessment(),
        SQLiteLeadRepository(tmp_path / "leads.db"),
        ProspectingConfig(max_businesses=1, target_leads=1),
    )
    result = service.prospect("dentistas", "Catanduva")
    assert result.rejected_reputation == 1
    assert result.leads == []
