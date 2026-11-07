import socket
import ssl
from pathlib import Path

import pytest

from business_prospector.application.artifacts import capture_artifact
from business_prospector.application.preview_verification import (
    PublicPreviewVerifier, PublicResponse, VerificationFailure,
)
from business_prospector.infrastructure.preview_verification import SystemDnsResolver, PinnedHttpsReader
from test_cpanel_deployment import site


class FakeDns:
    def __init__(self, addresses=('8.8.8.8',), failure=None):
        self.addresses, self.failure = addresses, failure
        self.calls = []

    def resolve(self, hostname, timeout):
        self.calls.append((hostname, timeout))
        if self.failure:
            raise self.failure
        return self.addresses


class FakeHttps:
    def __init__(self, artifact, *, failure=None, status=200, mime=None, stale=None):
        self.artifact, self.failure, self.status, self.mime, self.stale = artifact, failure, status, mime, stale
        self.calls = []

    def get(self, hostname, address, path, limit, timeout):
        self.calls.append((hostname, address, path, limit, timeout))
        if self.failure:
            raise self.failure
        relative = 'index.html' if path == '/' else path.lstrip('/')
        content = next(item.content for item in self.artifact.files if item.path == relative)
        mime = 'text/html' if relative == 'index.html' else 'text/css' if relative == 'styles.css' else 'image/svg+xml'
        return PublicResponse(self.status, self.mime or mime, self.stale if self.stale is not None else content)


def test_all_addresses_and_every_file_including_landing_page_verified(tmp_path):
    artifact = capture_artifact(site(tmp_path))
    dns = FakeDns(('8.8.8.8', '1.1.1.1'))
    http = FakeHttps(artifact)
    result = PublicPreviewVerifier(dns, http).verify('https://preview.example.test', artifact)
    assert result.state == 'published' and result.files_verified == len(artifact.files) * 2
    assert {call[2] for call in http.calls} == {'/', '/index.html', '/styles.css', '/assets/hero.svg'}
    assert all(call[0] == 'preview.example.test' and 0 < call[4] <= 30 for call in http.calls)


@pytest.mark.parametrize('addresses,expected,code', [
    ((), (), 'dns_no_addresses'), (('127.0.0.1',), (), 'dns_non_public_address'),
    (('224.0.0.1',), (), 'dns_non_public_address'),
    (('169.254.169.254',), (), 'dns_non_public_address'), (('::1',), (), 'dns_non_public_address'),
    (('8.8.8.8',), ('1.1.1.1',), 'dns_destination_mismatch'),
    (('not-an-ip',), (), 'dns_invalid_address'),
])
def test_dns_failures_block_https(tmp_path, addresses, expected, code):
    artifact = capture_artifact(site(tmp_path))
    http = FakeHttps(artifact)
    result = PublicPreviewVerifier(FakeDns(addresses), http, expected_addresses=expected).verify('https://preview.example.test', artifact)
    assert result.state == 'dns_failure' and result.error_code == code
    assert not http.calls


@pytest.mark.parametrize('kwargs,state,code', [
    ({'status': 500}, 'http_failure', 'http_status'),
    ({'status': 301}, 'http_failure', 'unexpected_redirect'),
    ({'status': 302}, 'http_failure', 'unexpected_redirect'),
    ({'mime': 'text/plain'}, 'http_failure', 'content_type'),
    ({'stale': b'hosting error page'}, 'content_mismatch', 'approved_bytes_mismatch'),
    ({'stale': b''}, 'content_mismatch', 'approved_bytes_mismatch'),
    ({'failure': VerificationFailure('tls_failure', 'tls_certificate_or_handshake')}, 'tls_failure', 'tls_certificate_or_handshake'),
    ({'failure': VerificationFailure('timeout', 'https_timeout')}, 'timeout', 'https_timeout'),
    ({'failure': VerificationFailure('http_failure', 'https_connection')}, 'http_failure', 'https_connection'),
])
def test_http_200_is_not_sufficient_and_failures_have_actions(tmp_path, kwargs, state, code):
    artifact = capture_artifact(site(tmp_path))
    result = PublicPreviewVerifier(FakeDns(), FakeHttps(artifact, **kwargs)).verify('https://preview.example.test', artifact)
    assert result.state == state and result.error_code == code and result.corrective_action


@pytest.mark.parametrize('url', ['http://preview.test', 'https://user:pass@preview.test', 'https://preview.test:444',
                               'https://preview.test/other', 'https://preview.test?x=y'])
def test_only_https_origin_is_accepted(tmp_path, url):
    from business_prospector.domain.exceptions import ValidationError
    artifact = capture_artifact(site(tmp_path))
    with pytest.raises(ValidationError):
        PublicPreviewVerifier(FakeDns(), FakeHttps(artifact)).verify(url, artifact)


def test_dns_resolution_errors_are_sanitized(monkeypatch):
    def fail(*args):
        raise socket.gaierror('private hostname')
    monkeypatch.setattr(socket, 'getaddrinfo', fail)
    with pytest.raises(VerificationFailure) as caught:
        SystemDnsResolver().resolve('preview.example.test', 1)
    assert caught.value.state == 'dns_failure' and 'private' not in str(caught.value)


@pytest.mark.parametrize('error,state', [(ssl.SSLCertVerificationError('private'), 'tls_failure'),
                                        (TimeoutError('private'), 'timeout'), (OSError('private'), 'http_failure')])
def test_https_transport_failure_classification(monkeypatch, error, state):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(socket, 'create_connection', fail)
    with pytest.raises(VerificationFailure) as caught:
        PinnedHttpsReader().get('preview.example.test', '8.8.8.8', '/', 100, 1)
    assert caught.value.state == state and 'private' not in str(caught.value)


def test_dns_timeout_is_bounded_without_sleep(monkeypatch):
    import threading
    import time
    release = threading.Event()
    entered = threading.Event()
    def stalled(*args):
        entered.set()
        release.wait(2)
        return []
    monkeypatch.setattr(socket, 'getaddrinfo', stalled)
    started = time.monotonic()
    try:
        with pytest.raises(VerificationFailure) as caught:
            SystemDnsResolver().resolve('preview.example.test', 0.02)
        assert caught.value.state == 'timeout'
        assert time.monotonic() - started < 1
    finally:
        release.set()


def test_real_tls_rejects_untrusted_certificate_and_accepts_trusted_hostname(tmp_path, monkeypatch):
    import subprocess
    import threading
    certificate, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=preview.example.test', '-addext', 'subjectAltName=DNS:preview.example.test',
                    '-keyout', str(key), '-out', str(certificate)], check=True, capture_output=True)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, key)
    default_context = ssl.create_default_context
    original_connect = socket.create_connection
    for trusted, hostname, expected in [(False, 'preview.example.test', 'tls_failure'),
                                         (True, 'wrong.example.test', 'tls_failure'),
                                         (True, 'preview.example.test', 'success')]:
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        address = listener.getsockname()
        errors = []
        def serve():
            try:
                sock, _ = listener.accept()
                with sock, server_context.wrap_socket(sock, server_side=True) as secure:
                    request = secure.recv(4096)
                    assert b'Authorization:' not in request
                    secure.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok')
            except ssl.SSLError:
                pass  # Expected when client rejects this synthetic certificate.
            except BaseException as exc:
                errors.append(exc)
            finally:
                listener.close()
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        destinations = []
        def connect(destination, **kwargs):
            destinations.append(destination)
            return original_connect(address, **kwargs)
        monkeypatch.setattr(socket, 'create_connection', connect)
        monkeypatch.setattr(ssl, 'create_default_context', lambda: default_context(cafile=str(certificate)) if trusted else default_context())
        if expected == 'success':
            assert PinnedHttpsReader().get(hostname, '8.8.8.8', '/', 3, 2).body == b'ok'
        else:
            with pytest.raises(VerificationFailure) as caught:
                PinnedHttpsReader().get(hostname, '8.8.8.8', '/', 3, 2)
            assert caught.value.state == expected
        thread.join(3)
        assert not thread.is_alive() and not errors
        assert destinations == [('8.8.8.8', 443)]
