from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


import socket
import pytest


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Never let boundary tests use operational storage or external networking."""
    monkeypatch.setenv("BUSINESS_PROSPECTOR_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("BUSINESS_PROSPECTOR_CONFIG", str(ROOT / "config" / "default.json"))
    for name, value in {
        "GOOGLE_MAPS_API_KEY": "test-only",
        "BUSINESS_PROSPECTOR_PREVIEW_EXPECTED_IPS": "",
        "BUSINESS_PROSPECTOR_CPANEL_BASE_URL": "https://cpanel.example.test:2083",
        "BUSINESS_PROSPECTOR_CPANEL_USERNAME": "test-user",
        "BUSINESS_PROSPECTOR_CPANEL_API_TOKEN": "test-only",
        "BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN": "example.test",
        "BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR": "public_html/previews",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.delenv("BUSINESS_PROSPECTOR_STOCK_PROVIDER", raising=False)
    original = socket.socket.connect

    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("external networking is forbidden in tests")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    original_resolver = socket.getaddrinfo
    def resolve(host, *args, **kwargs):
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("external DNS is forbidden in tests")
        return original_resolver(host, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
