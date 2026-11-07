"""Pixabay photos for individual human selections, downloaded to reviewed local assets."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode, urlsplit

from business_prospector.application.site_assets import DownloadedImage
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.site_assets import MAX_IMAGE_BYTES
from business_prospector.domain.stock_photography import StockPhoto, StockSearchPlan
from .stock_http import StockProviderUnavailable, StockSearchCache, _request

LICENSE_URL = 'https://pixabay.com/service/license-summary/'


def _pixabay_url(value: str, *, image: bool = False) -> str:
    parsed = urlsplit(value)
    allowed = {'pixabay.com', 'cdn.pixabay.com'} if image else {'pixabay.com'}
    if (parsed.scheme != 'https' or parsed.hostname not in allowed
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or (image and not parsed.path.startswith('/get/' if parsed.hostname == 'pixabay.com' else '/photo/'))):
        raise ValidationError('unexpected Pixabay image or page URL')
    return value


def _photo(item: dict) -> StockPhoto:
    if item['type'] != 'photo' or type(item['id']) is not int or item['id'] < 1:
        raise ValidationError('invalid Pixabay photo identity')
    if type(item['user_id']) is not int or item['user_id'] < 1:
        raise ValidationError('invalid Pixabay contributor identity')
    # Metadata dimensions describe the original; the standard API download is capped at 1280.
    width, height = item['imageWidth'], item['imageHeight']
    if any(type(v) is not int or not 1 <= v <= 100000 for v in (width, height)):
        raise ValidationError('invalid Pixabay dimensions')
    scale = min(1, 1280 / max(width, height))
    return StockPhoto('pixabay', str(item['id']), _pixabay_url(item['pageURL']),
        _pixabay_url(item['largeImageURL'], image=True), item['user'],
        'https://pixabay.com/users/' + quote(item['user'], safe='') + '-' + str(item['user_id']) + '/',
        LICENSE_URL, round(width * scale), round(height * scale), item['tags'])


class PixabayStockPhotoProvider:
    display_name = 'Pixabay'
    attribution_url = 'https://pixabay.com'

    def __init__(self, api_key: str, cache_root: Path, *,
                 request: Callable[[str, dict[str, str], int], tuple[bytes, str]] = _request,
                 clock: Callable[[], float] = time.time) -> None:
        if not api_key or any(c.isspace() for c in api_key):
            raise ValidationError('Pixabay API key is not configured')
        self._key, self._request = api_key, request
        self._cache = StockSearchCache(cache_root, clock)

    def search(self, plan: StockSearchPlan) -> tuple[StockPhoto, ...]:
        if not 1 <= len(plan.query) <= 100 or plan.orientation not in {'landscape', 'portrait', 'square'}:
            raise ValidationError('unsupported Pixabay search plan')
        query = urlencode({'q': plan.query, 'orientation': {'landscape': 'horizontal', 'portrait': 'vertical', 'square': 'all'}[plan.orientation],
            'image_type': 'photo', 'safesearch': 'true', 'lang': 'en', 'per_page': 15,
            'min_width': 800, 'min_height': 800})

        def fetch() -> dict:
            # Pixabay requires the key in its API query. Never persist/log this URL or raw response.
            raw, mime = self._request('https://pixabay.com/api/?' + urlencode({'key': self._key}) + '&' + query, {}, 1024 * 1024)
            if mime != 'application/json':
                raise StockProviderUnavailable('invalid stock response type')
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get('hits'), list) or len(payload['hits']) > 15:
                raise StockProviderUnavailable('invalid stock search response')
            photos = []
            for item in payload['hits']:
                try:
                    photos.append(_photo(item).to_dict())
                except (KeyError, TypeError, ValueError, ValidationError):
                    continue
            return {'photos': photos}

        payload = self._cache.get(query, fetch, 'photos')
        photos = []
        for item in payload['photos']:
            try:
                photo = StockPhoto(**item)
                if photo.provider != 'pixabay' or photo.license_url != LICENSE_URL:
                    continue
                _pixabay_url(photo.source_page)
                _pixabay_url(photo.photographer_url)
                _pixabay_url(photo.download_url, image=True)
                if photo.matches(plan):
                    photos.append(photo)
            except (TypeError, ValueError, ValidationError):
                continue
        return tuple(sorted(photos, key=lambda p: (abs(p.width / p.height - plan.aspect_ratio), p.photo_id)))[:6]

    def download(self, photo: StockPhoto) -> DownloadedImage:
        if photo.provider != 'pixabay' or photo.license_url != LICENSE_URL:
            raise ValidationError('wrong stock provider or license')
        url = _pixabay_url(photo.download_url, image=True)
        content, mime = self._request(url, {}, MAX_IMAGE_BYTES)
        return DownloadedImage(content, mime)
