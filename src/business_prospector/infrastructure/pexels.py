"""Bounded Pexels adapter: fixed HTTPS origins, no redirects or secret-bearing URLs."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlsplit

from business_prospector.application.site_assets import DownloadedImage
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.site_assets import MAX_IMAGE_BYTES
from business_prospector.domain.stock_photography import StockPhoto, StockSearchPlan

from .stock_http import StockProviderUnavailable, StockSearchCache, _NoRedirects, _request

LICENSE_URL = 'https://www.pexels.com/license/'


def _pexels_url(value: str, host: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or parsed.hostname != host or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise ValidationError('unexpected Pexels origin')
    return value


class PexelsStockPhotoProvider:
    display_name = "Pexels"
    attribution_url = "https://www.pexels.com"

    def __init__(self, api_key: str, cache_root: Path, *, request: Callable[[str, dict[str, str], int], tuple[bytes, str]] = _request, clock: Callable[[], float] = time.time) -> None:
        if not api_key or any(c in api_key for c in '\r\n'):
            raise ValidationError('Pexels API key is not configured')
        self._key, self._cache, self._request, self._clock = api_key, cache_root, request, clock

    def search(self, plan: StockSearchPlan) -> tuple[StockPhoto, ...]:
        query = urlencode({'query': plan.query, 'orientation': plan.orientation, 'per_page': 15, 'locale': 'en-US'})
        def fetch() -> dict:
            raw, mime = self._request('https://api.pexels.com/v1/search?' + query, {'Authorization': self._key}, 1024 * 1024)
            if mime != 'application/json':
                raise StockProviderUnavailable('invalid stock response type')
            return json.loads(raw)
        payload = StockSearchCache(self._cache, self._clock).get(query, fetch, 'photos')
        photos = []
        for item in payload.get('photos', [])[:15]:
            try:
                photo = StockPhoto('pexels', str(item['id']), _pexels_url(item['url'], 'www.pexels.com'),
                    _pexels_url(item['src']['large2x'], 'images.pexels.com'), item['photographer'],
                    _pexels_url(item['photographer_url'], 'www.pexels.com'), LICENSE_URL,
                    item['width'], item['height'], item['alt'])
                if photo.matches(plan):
                    photos.append(photo)
            except (KeyError, TypeError, ValueError, ValidationError):
                continue
        return tuple(sorted(photos, key=lambda p: (abs(p.width / p.height - plan.aspect_ratio), p.photo_id)))[:6]

    def download(self, photo: StockPhoto) -> DownloadedImage:
        if photo.provider != 'pexels':
            raise ValidationError('wrong stock provider')
        url = _pexels_url(photo.download_url, 'images.pexels.com')
        content, mime = self._request(url, {}, MAX_IMAGE_BYTES)
        return DownloadedImage(content, mime)
