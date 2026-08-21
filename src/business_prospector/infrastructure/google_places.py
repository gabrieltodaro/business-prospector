from __future__ import annotations

import json
import os
import socket
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from business_prospector.application.ports import SearchQuery
from business_prospector.domain.exceptions import ProspectorError
from business_prospector.domain.models import BusinessCandidate

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.googleMapsUri",
        "places.primaryType",
        "places.rating",
        "places.userRatingCount",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "nextPageToken",
    )
)


class GooglePlacesError(ProspectorError):
    """Safe, credential-free failure returned by Places API (New)."""


class GooglePlacesConfigurationError(GooglePlacesError):
    """Raised when Places API credentials are unavailable."""


class GooglePlacesResponseError(GooglePlacesError):
    """Raised when Google returns data that cannot be mapped safely."""


UrlOpen = Callable[..., Any]


class GooglePlacesBusinessDiscoveryProvider:
    """Discover public business metadata through Places API (New) Text Search."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 10.0,
        opener: UrlOpen = urlopen,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("GOOGLE_MAPS_API_KEY")
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def search(self, query: SearchQuery) -> list[BusinessCandidate]:
        if not self.configured:
            raise GooglePlacesConfigurationError("Google Places API is not configured.")
        if query.limit < 1:
            return []

        candidates: list[BusinessCandidate] = []
        page_token: str | None = None
        while len(candidates) < query.limit:
            page_size = min(20, query.limit - len(candidates))
            payload: dict[str, object] = {
                "textQuery": f"{query.niche} em {query.city}, Brasil",
                "languageCode": "pt-BR",
                "regionCode": "BR",
                "pageSize": page_size,
            }
            if page_token:
                payload["pageToken"] = page_token

            response = self._post(payload)
            places = response.get("places", [])
            if not isinstance(places, list):
                raise GooglePlacesResponseError("Google Places returned an unexpected response.")
            candidates.extend(self._map_place(place, query) for place in places)
            next_token = response.get("nextPageToken")
            if next_token is None or next_token == "":
                break
            if not isinstance(next_token, str):
                raise GooglePlacesResponseError("Google Places returned an unexpected response.")
            page_token = next_token
        return candidates[: query.limit]

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            TEXT_SEARCH_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key or "",
                "X-Goog-FieldMask": FIELD_MASK,
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            raise self._http_error(exc.code) from None
        except (TimeoutError, socket.timeout) as exc:
            raise GooglePlacesError("Google Places request timed out.") from exc
        except (URLError, OSError) as exc:
            raise GooglePlacesError("Google Places network request failed.") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GooglePlacesResponseError("Google Places returned an unexpected response.") from exc
        if not isinstance(decoded, dict):
            raise GooglePlacesResponseError("Google Places returned an unexpected response.")
        return decoded

    @staticmethod
    def _http_error(status: int) -> GooglePlacesError:
        if status == 400:
            return GooglePlacesError("Google Places rejected the search request.")
        if status in {401, 403}:
            return GooglePlacesError("Google Places authentication or authorization failed.")
        if status == 429:
            return GooglePlacesError("Google Places quota or rate limit was exceeded.")
        if 500 <= status <= 599:
            return GooglePlacesError("Google Places is temporarily unavailable.")
        return GooglePlacesError(f"Google Places request failed with HTTP status {status}.")

    @staticmethod
    def _map_place(place: object, query: SearchQuery) -> BusinessCandidate:
        if not isinstance(place, dict):
            raise GooglePlacesResponseError("Google Places returned an unexpected response.")
        display_name = place.get("displayName")
        name = display_name.get("text") if isinstance(display_name, dict) else None
        place_id = place.get("id")
        if not isinstance(name, str) or not name.strip() or not isinstance(place_id, str) or not place_id:
            raise GooglePlacesResponseError("Google Places returned an unexpected response.")

        rating = place.get("rating", 0.0)
        reviews = place.get("userRatingCount", 0)
        if not isinstance(rating, (int, float)) or isinstance(rating, bool):
            raise GooglePlacesResponseError("Google Places returned an unexpected response.")
        if not isinstance(reviews, int) or isinstance(reviews, bool):
            raise GooglePlacesResponseError("Google Places returned an unexpected response.")

        def optional_string(field: str) -> str | None:
            value = place.get(field)
            if value is None or value == "":
                return None
            if not isinstance(value, str):
                raise GooglePlacesResponseError("Google Places returned an unexpected response.")
            return value

        return BusinessCandidate(
            name=name.strip(),
            category=optional_string("primaryType") or query.niche,
            city=query.city,
            rating=float(rating),
            review_count=reviews,
            website_url=optional_string("websiteUri"),
            external_place_id=place_id,
            address=optional_string("formattedAddress"),
            maps_url=optional_string("googleMapsUri"),
            phone=optional_string("nationalPhoneNumber"),
            whatsapp_source="google_business_phone",
            source="google_places_new",
        )
