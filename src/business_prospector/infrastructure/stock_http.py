"""Shared bounded stock transport and persistent search cache; never logs requests."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from business_prospector.domain.exceptions import ValidationError


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


class StockSearchCache:
    def __init__(self, root: Path, clock: Callable[[], float] = time.time) -> None:
        self._cache, self._clock = root, clock

    def _cache_path(self, name: str) -> Path:
        if self._cache.is_symlink():
            raise ValidationError('stock cache cannot be a symlink')
        self._cache.mkdir(parents=True, exist_ok=True)
        path = self._cache / name
        if path.is_symlink():
            raise ValidationError('stock cache entry cannot be a symlink')
        return path

    def get(self, query: str, fetch: Callable[[], dict], field: str) -> dict:
        path = self._cache_path(hashlib.sha256(query.encode()).hexdigest() + '.json')
        cooldown = self._cache_path('cooldown.json')
        now = self._clock()
        payload = None
        if path.exists() and path.stat().st_size <= 1024 * 1024:
            try:
                cached = json.loads(path.read_text())
                if 0 <= now - cached['stored_at'] < 86400:
                    candidate = cached['payload']
                    if isinstance(candidate, dict) and isinstance(candidate.get(field), list) and len(candidate[field]) <= 15:
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
                payload = fetch()
                if not isinstance(payload, dict) or not isinstance(payload.get(field), list) or len(payload[field]) > 15:
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
        return payload
