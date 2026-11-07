"""Bounded public DNS and pinned HTTPS, with no proxy, redirect or HTTP fallback."""
from __future__ import annotations

import concurrent.futures
import http.client
import socket
import ssl
import threading
import time

from business_prospector.application.preview_verification import PublicResponse, VerificationFailure

# getaddrinfo has no portable timeout. A bounded shared pool prevents unbounded
# threads when libc DNS stalls. Future timeout bounds the caller, not libc itself.
_DNS_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='preview-dns')
_DNS_SLOTS = threading.BoundedSemaphore(2)


class SystemDnsResolver:
    def resolve(self, hostname: str, timeout: float) -> tuple[str, ...]:
        if not _DNS_SLOTS.acquire(blocking=False):
            raise VerificationFailure('timeout', 'dns_resolver_busy')
        future = _DNS_POOL.submit(socket.getaddrinfo, hostname, 443, 0, socket.SOCK_STREAM)
        future.add_done_callback(lambda _: _DNS_SLOTS.release())
        try:
            records = future.result(timeout=timeout)
            addresses = tuple(sorted({record[4][0] for record in records}))
            if len(addresses) > 8:
                raise VerificationFailure('dns_failure', 'dns_address_limit')
            return addresses
        except concurrent.futures.TimeoutError:
            raise VerificationFailure('timeout', 'dns_timeout') from None
        except socket.gaierror:
            raise VerificationFailure('dns_failure', 'dns_resolution') from None


class PinnedHttpsReader:
    def get(self, hostname: str, address: str, path: str, limit: int, timeout: float) -> PublicResponse:
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(hostname, timeout=timeout, context=context)
        deadline = time.monotonic() + timeout
        active_socket = None
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            if active_socket is not None:
                try:
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        # Socket timeouts alone allow slow headers/body to extend an operation
        # indefinitely. Closing the active socket enforces the total deadline.
        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            active_socket = socket.create_connection((address, 443), timeout=timeout)
            if expired.is_set():
                raise TimeoutError
            active_socket = context.wrap_socket(active_socket, server_hostname=hostname,
                                                do_handshake_on_connect=False)
            active_socket.settimeout(max(0.001, deadline - time.monotonic()))
            active_socket.do_handshake()
            connection.sock = active_socket
            connection.request('GET', path, headers={'Host': hostname, 'Accept-Encoding': 'identity',
                                                     'Cache-Control': 'no-cache', 'User-Agent': 'business-prospector/preview-verifier'})
            response = connection.getresponse()
            chunks = bytearray()
            while len(chunks) < limit:
                if response.isclosed():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                active_socket.settimeout(remaining)
                chunk = response.read1(min(65536, limit - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            if expired.is_set():
                raise TimeoutError
            return PublicResponse(response.status, response.getheader('Content-Type', ''), bytes(chunks))
        except ssl.SSLError:
            if expired.is_set():
                raise VerificationFailure('timeout', 'https_timeout') from None
            raise VerificationFailure('tls_failure', 'tls_certificate_or_handshake') from None
        except (TimeoutError, socket.timeout):
            raise VerificationFailure('timeout', 'https_timeout') from None
        except (OSError, http.client.HTTPException):
            if expired.is_set():
                raise VerificationFailure('timeout', 'https_timeout') from None
            raise VerificationFailure('http_failure', 'https_connection') from None
        finally:
            timer.cancel()
            connection.close()
            if active_socket is not None:
                active_socket.close()
