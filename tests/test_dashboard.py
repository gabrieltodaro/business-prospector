from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

from business_prospector.dashboard import DashboardApplication, create_handler
from business_prospector.domain.models import Lead, WebsiteAssessment
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


STATIC_DIR = Path(__file__).parents[1] / "src" / "business_prospector" / "dashboard_static"


def saved_lead(repository: SQLiteLeadRepository) -> Lead:
    return repository.save(
        Lead(
            name='<img src=x onerror="alert(1)">',
            category="dentista",
            city="Catanduva",
            rating=4.8,
            review_count=81,
            website_url="https://example.com",
            phone="(17) 99999-1234",
            assessment=WebsiteAssessment(layout=True, mobile=True, reason="<script>bad()</script>"),
            score=82,
            status="qualified",
        )
    )


@contextmanager
def running_server(application: DashboardApplication) -> Iterator[tuple[str, int]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(application, STATIC_DIR))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield str(host), int(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def call(
    address: tuple[str, int], method: str, path: str, payload: object | None = None
) -> tuple[int, dict[str, str], bytes]:
    headers: dict[str, str] = {}
    body: bytes | None = None
    if payload is not None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection(*address, timeout=2)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


@pytest.fixture
def application(tmp_path: Path) -> DashboardApplication:
    repository = SQLiteLeadRepository(tmp_path / "dashboard.db")
    saved_lead(repository)
    return DashboardApplication(repository)


def test_lists_filters_and_returns_security_headers(application: DashboardApplication) -> None:
    with running_server(application) as address:
        status, headers, body = call(address, "GET", "/api/leads?city=cat&min_score=80")
    payload = json.loads(body)
    assert status == 200
    assert payload["leads"][0]["name"] == '<img src=x onerror="alert(1)">'
    assert payload["leads"][0]["assessment"]["reason"] == "<script>bad()</script>"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in headers["Content-Security-Policy"]


def test_status_only_update_persists_valid_pipeline_status(application: DashboardApplication) -> None:
    lead_id = application.repository.list()[0].id
    assert lead_id is not None
    with running_server(application) as address:
        status, _, body = call(address, "PATCH", f"/api/leads/{lead_id}/status", {"status": "contacted"})
        statuses_code, _, statuses_body = call(address, "GET", "/api/statuses")
    assert status == 200
    assert json.loads(body)["lead"]["status"] == "contacted"
    assert application.repository.get(lead_id).status == "contacted"  # type: ignore[union-attr]
    assert statuses_code == 200
    assert json.loads(statuses_body)["statuses"] == [
        "new", "qualified", "needs_review", "contacted", "proposal", "closed", "discarded"
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "owned"},
        {"status": "closed", "score": 100},
        ["closed"],
        b"{not-json",
    ],
)
def test_rejects_invalid_or_arbitrary_status_updates(
    application: DashboardApplication, payload: object
) -> None:
    lead_id = application.repository.list()[0].id
    assert lead_id is not None
    with running_server(application) as address:
        status, _, _ = call(address, "PATCH", f"/api/leads/{lead_id}/status", payload)
    assert status == 400
    assert application.repository.get(lead_id).status == "qualified"  # type: ignore[union-attr]


def test_missing_records_and_mutating_methods_are_restricted(application: DashboardApplication) -> None:
    with running_server(application) as address:
        missing, _, _ = call(address, "GET", "/api/leads/99999")
        deleted, headers, _ = call(address, "DELETE", "/api/leads/1")
    assert missing == 404
    assert deleted == 405
    assert headers["Allow"] == "GET, PATCH"


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard.db",
        "/config/default.json",
        "/.git/config",
        "/../pyproject.toml",
        "/service-env/ai.openclaw.gateway.env",
    ],
)
def test_static_allowlist_cannot_expose_project_or_secret_files(
    application: DashboardApplication, path: str
) -> None:
    with running_server(application) as address:
        status, _, _ = call(address, "GET", path)
    assert status == 404


def test_repository_errors_do_not_leak_details(
    application: DashboardApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_list(limit: int = 100) -> list[Lead]:
        raise OSError("secret filesystem detail")

    monkeypatch.setattr(application.repository, "list", broken_list)
    with running_server(application) as address:
        status, _, body = call(address, "GET", "/api/leads")
    assert status == 500
    assert json.loads(body) == {"error": "dashboard data is unavailable"}
    assert b"secret filesystem detail" not in body


def test_frontend_uses_safe_dom_and_status_only_requests() -> None:
    source = (STATIC_DIR / "app.js").read_text()
    assert "innerHTML" not in source
    assert "localStorage" not in source
    assert "textContent" in source
    assert "['http:','https:'].includes(url.protocol)" in source
    assert "body:JSON.stringify({status})" in source
    assert "lead.status=previous" in source
    assert "calculate_score" not in source
    assert "website_assessment" in source
    assert "(criterion.facts||[]).join" in source
    assert "Primeiro Site" in source
    assert "opportunity_type" in source
    assert "market_research" in source
    assert "research.benchmark_market" in source
    assert "research.benchmarks||research.competitors||[]" in source
    assert "(benchmark.facts||[]).join" in source
    assert "innerHTML" not in source
