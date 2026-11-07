"""Exact public artifact verification with injectable DNS and HTTPS boundaries."""
from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from pathlib import PurePosixPath
import math
from urllib.parse import quote, urlsplit

from business_prospector.application.artifacts import PublicArtifact
from business_prospector.domain.deployment import CORRECTIVE_ACTIONS, VerificationResult
from business_prospector.domain.exceptions import ValidationError


class VerificationFailure(Exception):
    def __init__(self, state: str, code: str) -> None:
        self.state, self.code = state, code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PublicResponse:
    status: int
    content_type: str
    body: bytes


class DnsResolver(Protocol):
    def resolve(self, hostname: str, timeout: float) -> tuple[str, ...]: ...


class HttpsReader(Protocol):
    def get(self, hostname: str, address: str, path: str, limit: int, timeout: float) -> PublicResponse: ...


class PublicPreviewVerifier:
    def __init__(self, resolver: DnsResolver, reader: HttpsReader, *,
                 expected_addresses: tuple[str, ...] = (), timeout: float = 30.0) -> None:
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValidationError('verification timeout must be between 0 and 120 seconds')
        self._resolver, self._reader = resolver, reader
        self._expected = frozenset(str(ipaddress.ip_address(item)) for item in expected_addresses)
        self._timeout = timeout

    def verify(self, url: str, artifact: PublicArtifact) -> VerificationResult:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in {None, 443} or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
            raise ValidationError('verification requires an authorized HTTPS preview origin')
        start = time.monotonic()
        verified = 0
        dns, tls = 'unknown', 'unknown'
        def remaining() -> float:
            value = self._timeout - (time.monotonic() - start)
            if value <= 0:
                raise VerificationFailure('timeout', 'verification_deadline')
            return value
        try:
            addresses = self._resolver.resolve(parsed.hostname, remaining())
            if len(addresses) > 8:
                raise VerificationFailure('dns_failure', 'dns_address_limit')
            if not addresses:
                raise VerificationFailure('dns_failure', 'dns_no_addresses')
            try:
                normalized = tuple(str(ipaddress.ip_address(item)) for item in addresses)
            except ValueError:
                raise VerificationFailure('dns_failure', 'dns_invalid_address') from None
            if any(not ipaddress.ip_address(item).is_global or ipaddress.ip_address(item).is_multicast or '%' in item for item in normalized):
                raise VerificationFailure('dns_failure', 'dns_non_public_address')
            if self._expected and not set(normalized) <= self._expected:
                raise VerificationFailure('dns_failure', 'dns_destination_mismatch')
            dns = 'verified'
            # Check every advertised address, pinning the socket to that address while
            # retaining the authorized hostname for certificate validation and Host.
            for address in normalized:
                for item in artifact.files:
                    paths = ('/', '/index.html') if item.path == 'index.html' else ('/' + quote(item.path, safe='/'),)
                    for path in paths:
                        response = self._reader.get(parsed.hostname, address, path, len(item.content) + 1, remaining())
                        tls = 'verified'
                        if response.status != 200:
                            raise VerificationFailure('http_failure', 'unexpected_redirect' if 300 <= response.status < 400 else 'http_status')
                        mime = response.content_type.partition(';')[0].strip().lower()
                        expected = ('text/html' if item.path == 'index.html' else 'text/css' if item.path == 'styles.css'
                                    else {'.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
                                          '.jpeg': 'image/jpeg', '.webp': 'image/webp'}[PurePosixPath(item.path).suffix.lower()])
                        if mime != expected:
                            raise VerificationFailure('http_failure', 'content_type')
                        if response.body != item.content:
                            raise VerificationFailure('content_mismatch', 'approved_bytes_mismatch')
                    verified += 1
            remaining()
            return VerificationResult('published', datetime.now(timezone.utc).isoformat(), verified, dns, tls)
        except VerificationFailure as exc:
            return VerificationResult(exc.state, datetime.now(timezone.utc).isoformat(), verified, dns,
                                      'failed' if exc.state == 'tls_failure' else tls,
                                      exc.code, CORRECTIVE_ACTIONS[exc.state])
