"""Bounded Pexels adapter: fixed HTTPS origins, no redirects or secret-bearing URLs."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from business_prospector.application.site_assets import DownloadedImage
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.site_assets import MAX_IMAGE_BYTES
from business_prospector.domain.stock_photography import StockPhoto, StockSearchPlan

LICENSE_URL = 'https://www.pexels.com/license/'


class StockProviderUnavailable(ValidationError):
    def __init__(self, message: str, retry_after: float = 3600) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(url: str, headers: dict[str, str], maximum: int) -> tuple[bytes, str]:
    try:
        with build_opener(_NoRedirects()).open(Request(url, headers=headers), timeout=15) as response:
            data = response.read(maximum + 1)
            if len(data) > maximum:
                raise StockProviderUnavailable('stock response exceeds size limit')
            return data, response.headers.get_content_type()
    except HTTPError as exc:
        # Never expose response bodies, request headers or credentials in diagnostics.
        retry = 3600.0
        value = exc.headers.get('Retry-After', '') if exc.headers else ''
        try:
            retry = max(retry, float(value))
        except ValueError:
            try:
                retry = max(retry, parsedate_to_datetime(value).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                pass
        raise StockProviderUnavailable(f'stock provider HTTP {exc.code}; retry later', retry) from None
    except (URLError, OSError, TimeoutError):
        raise StockProviderUnavailable('stock provider unavailable; retry later') from None


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

    def _cache_path(self, name: str) -> Path:
        if self._cache.is_symlink():
            raise ValidationError('stock cache cannot be a symlink')
        self._cache.mkdir(parents=True, exist_ok=True)
        path = self._cache / name
        if path.is_symlink():
            raise ValidationError('stock cache entry cannot be a symlink')
        return path

    def search(self, plan: StockSearchPlan) -> tuple[StockPhoto, ...]:
        query = urlencode({'query': plan.query, 'orientation': plan.orientation, 'per_page': 15, 'locale': 'en-US'})
        path = self._cache_path(hashlib.sha256(query.encode()).hexdigest() + '.json')
        cooldown = self._cache_path('cooldown.json')
        now = self._clock()
        payload = None
        if path.exists() and path.stat().st_size <= 1024 * 1024:
            try:
                cached = json.loads(path.read_text())
                if 0 <= now - cached['stored_at'] < 86400:
                    candidate = cached['payload']
                    if isinstance(candidate, dict) and isinstance(candidate.get('photos'), list) and len(candidate['photos']) <= 15:
                        payload = candidate
            except (ValueError, KeyError, TypeError):
                pass
        if payload is None:
            if cooldown.exists() and cooldown.stat().st_size <= 1024:
                try:
                    retry_at = json.loads(cooldown.read_text()).get('retry_at', 0)
                except (ValueError, TypeError, AttributeError):
                    retry_at = now + 3600
                if not isinstance(retry_at, (int, float)) or now < retry_at:
                    raise StockProviderUnavailable('stock provider cooling down; use typography or retry later')
            try:
                raw, mime = self._request('https://api.pexels.com/v1/search?' + query, {'Authorization': self._key}, 1024 * 1024)
                if mime != 'application/json':
                    raise StockProviderUnavailable('invalid stock response type')
                payload = json.loads(raw)
                if not isinstance(payload, dict) or not isinstance(payload.get('photos'), list) or len(payload['photos']) > 15:
                    raise StockProviderUnavailable('invalid stock search response')
            except (StockProviderUnavailable, ValueError) as exc:
                # Across MCP calls, avoid hammering unavailable/rate-limited providers.
                cooldown.write_text(json.dumps({'retry_at': now + getattr(exc, 'retry_after', 3600)}))
                raise StockProviderUnavailable('stock search unavailable; use typography or retry later') from None
            temporary = path.with_suffix('.tmp')
            if temporary.is_symlink():
                raise ValidationError('stock cache entry cannot be a symlink')
            temporary.write_text(json.dumps({'stored_at': now, 'payload': payload}))
            temporary.replace(path)
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
