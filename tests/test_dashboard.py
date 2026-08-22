from __future__ import annotations

import http.client
import json
import os
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

from business_prospector.dashboard import DashboardApplication, create_handler
from business_prospector.application.site_generation import SiteGenerationService
from business_prospector.domain.models import Lead, WebsiteAssessment
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.package_resources import site_demo_fixture_resource


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


def create_draft(application: DashboardApplication) -> tuple[Lead, Path]:
    stored = application.repository.list()[0]
    payload = json.loads(site_demo_fixture_resource().read_text(encoding="utf-8"))
    payload["lead"].update({
        "name": stored.name, "slug": stored.slug, "category": stored.category,
        "city": stored.city, "rating": stored.rating, "review_count": stored.review_count,
        "status": "qualified", "opportunity_type": "first_website",
    })
    result = SiteGenerationService(application.repository.database_path.parent / "sites").generate(
        payload["lead"], payload["research"],
    )
    return stored, Path(result.site_path or "")


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
        "new", "qualified", "needs_review", "site_ready", "contacted", "proposal", "closed", "discarded"
    ]


def test_drag_target_site_ready_persists_for_any_opportunity(application: DashboardApplication) -> None:
    lead_id = application.repository.list()[0].id
    assert lead_id is not None
    with running_server(application) as address:
        status, _, body = call(address, "PATCH", f"/api/leads/{lead_id}/status", {"status": "site_ready"})
    assert status == 200 and json.loads(body)["lead"]["status"] == "site_ready"
    assert application.repository.get(lead_id).opportunity_type == "redesign"  # type: ignore[union-attr]


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


def test_valid_draft_is_in_api_and_site_routes_serve_only_allowed_files(
    application: DashboardApplication,
) -> None:
    stored, site = create_draft(application)
    (site / "assets" / "mark.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    with running_server(application) as address:
        api_status, _, api_body = call(address, "GET", "/api/leads")
        index_status, index_headers, index_body = call(address, "GET", f"/sites/{stored.slug}/")
        css_status, css_headers, css_body = call(address, "GET", f"/sites/{stored.slug}/styles.css")
        asset_status, _, asset_body = call(address, "GET", f"/sites/{stored.slug}/assets/mark.svg")
        manifest_status, _, _ = call(address, "GET", f"/sites/{stored.slug}/site-manifest.json")
        listing_status, _, _ = call(address, "GET", f"/sites/{stored.slug}/assets/")
    draft = json.loads(api_body)["leads"][0]["site_draft"]
    assert api_status == 200 and draft["exists"] is True
    assert draft["site_url"] == f"/sites/{stored.slug}/" and "site_path" not in draft
    assert index_status == 200 and b'<html lang="pt-BR">' in index_body
    assert index_headers["Content-Type"].startswith("text/html")
    assert css_status == 200 and b"@media" in css_body
    assert css_headers["Content-Type"].startswith("text/css")
    assert asset_status == 200 and asset_body.startswith(b"<svg")
    assert manifest_status == 404 and listing_status == 404


@pytest.mark.parametrize("suffix", [
    "../dashboard.db", "%2e%2e/dashboard.db", "%2Fetc/passwd", "assets/%2e%2e/index.html",
    "dashboard.db", "config/default.json", ".env", "service-env/ai.openclaw.gateway.env",
])
def test_generated_site_route_rejects_traversal_and_non_generated_files(
    application: DashboardApplication, suffix: str,
) -> None:
    stored, _ = create_draft(application)
    with running_server(application) as address:
        status, _, body = call(address, "GET", f"/sites/{stored.slug}/{suffix}")
    assert status == 404 and b"dashboard.db" not in body


def test_generated_site_route_rejects_symlink_escape(application: DashboardApplication) -> None:
    stored, site = create_draft(application)
    outside = application.repository.database_path
    os.symlink(outside, site / "assets" / "database.db")
    with running_server(application) as address:
        status, _, _ = call(address, "GET", f"/sites/{stored.slug}/assets/database.db")
    assert status == 404


def test_missing_or_invalid_draft_has_no_site_action_metadata(application: DashboardApplication) -> None:
    stored = application.repository.list()[0]
    assert application.lead_payload(stored)["site_draft"]["exists"] is False
    _, site = create_draft(application)
    (site / "site-manifest.json").write_text("{}")
    payload = application.lead_payload(stored)
    assert payload["site_draft"]["exists"] is False
    assert payload["site_draft"]["site_url"] is None


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
    assert "site_ready','Site Pronto" in source
    assert "lead.site_draft?.exists" in source
    assert "Ver Site" in source
    assert "opportunity_type" in source
    assert "market_research" in source
    assert "research.benchmark_market" in source
    assert "research.benchmarks||research.competitors||[]" in source
    assert "(benchmark.facts||[]).join" in source
    assert "innerHTML" not in source
