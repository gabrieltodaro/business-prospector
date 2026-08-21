from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import sqlite3
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from importlib.resources.abc import Traversable
from urllib.parse import parse_qs, urlsplit

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.lead_status import LeadStatusService
from business_prospector.application.prospecting import ProspectingService
from business_prospector.domain.exceptions import LeadNotFoundError, ProspectorError, ValidationError
from business_prospector.domain.models import PIPELINE_STATUSES, Lead
from business_prospector.infrastructure.fake_providers import (
    FakeBusinessDiscoveryProvider,
    FakeWebsiteAssessmentProvider,
)
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.package_resources import (
    dashboard_static_resource,
    default_config_resource,
    fake_dentists_resource,
)

LOGGER = logging.getLogger("business_prospector.dashboard")
MAX_REQUEST_BODY = 4096
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/styles.css": "styles.css",
    "/app.js": "app.js",
}


class DashboardApplication:
    def __init__(self, repository: SQLiteLeadRepository) -> None:
        self.repository = repository
        self.statuses = LeadStatusService(repository)

    def list_leads(self, filters: dict[str, str]) -> list[Lead]:
        leads = self.repository.list(1000)
        status = filters.get("status")
        city = filters.get("city", "").casefold().strip()
        category = filters.get("category", "").casefold().strip()
        raw_min_score = filters.get("min_score", "").strip()
        if status:
            if status not in PIPELINE_STATUSES and status != "rejected":
                raise ValidationError(f"invalid pipeline status: {status}")
            leads = [lead for lead in leads if lead.status == status]
        if city:
            leads = [lead for lead in leads if city in lead.city.casefold()]
        if category:
            leads = [lead for lead in leads if category in lead.category.casefold()]
        if raw_min_score:
            try:
                minimum = int(raw_min_score)
            except ValueError as exc:
                raise ValidationError("min_score must be an integer") from exc
            if not 0 <= minimum <= 100:
                raise ValidationError("min_score must be between 0 and 100")
            leads = [lead for lead in leads if lead.score >= minimum]
        return sorted(leads, key=lambda lead: (-lead.score, -lead.review_count, lead.name.casefold()))

    def get_lead(self, lead_id: int) -> Lead:
        lead = self.repository.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(f"lead not found: {lead_id}")
        return lead

    def change_status(self, lead_id: int, status: str) -> Lead:
        return self.statuses.change(lead_id, status)


def create_handler(application: DashboardApplication, static_dir: Traversable) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "BusinessProspectorDashboard"

        def end_headers(self) -> None:
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            super().end_headers()

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            try:
                if parsed.path == "/api/leads":
                    filters = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
                    return self._json(HTTPStatus.OK, {"leads": [lead.to_dict() for lead in application.list_leads(filters)]})
                if parsed.path == "/api/statuses":
                    return self._json(HTTPStatus.OK, {"statuses": list(application.statuses.allowed_statuses)})
                lead_id = self._lead_id(parsed.path)
                if lead_id is not None:
                    return self._json(HTTPStatus.OK, {"lead": application.get_lead(lead_id).to_dict()})
                if parsed.path in STATIC_FILES:
                    return self._static(STATIC_FILES[parsed.path])
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            except ValidationError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except LeadNotFoundError as exc:
                return self._error(HTTPStatus.NOT_FOUND, str(exc))
            except (sqlite3.Error, OSError) as exc:
                LOGGER.warning("dashboard read failed: %s", exc)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "dashboard data is unavailable")

        def do_PATCH(self) -> None:
            parsed = urlsplit(self.path)
            lead_id = self._status_lead_id(parsed.path)
            if lead_id is None:
                return self._method_or_not_found(parsed.path, "GET")
            try:
                payload = self._read_json()
                if set(payload) != {"status"} or not isinstance(payload.get("status"), str):
                    raise ValidationError("request must contain only a string status")
                lead = application.change_status(lead_id, payload["status"])
                return self._json(HTTPStatus.OK, {"lead": lead.to_dict()})
            except ValidationError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except LeadNotFoundError as exc:
                return self._error(HTTPStatus.NOT_FOUND, str(exc))
            except json.JSONDecodeError:
                return self._error(HTTPStatus.BAD_REQUEST, "invalid JSON")
            except (sqlite3.Error, OSError) as exc:
                LOGGER.warning("dashboard status update failed: %s", exc)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "status update failed")

        def do_POST(self) -> None:
            self._method_not_allowed("GET, PATCH")

        def do_PUT(self) -> None:
            self._method_not_allowed("GET, PATCH")

        def do_DELETE(self) -> None:
            self._method_not_allowed("GET, PATCH")

        def _read_json(self) -> dict[str, Any]:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ValidationError("Content-Type must be application/json")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ValidationError("Content-Length is required")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValidationError("invalid Content-Length") from exc
            if length < 1 or length > MAX_REQUEST_BODY:
                raise ValidationError("request body size is invalid")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValidationError("request JSON must be an object")
            return payload

        @staticmethod
        def _lead_id(path: str) -> int | None:
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "leads"] and parts[2].isdigit():
                return int(parts[2])
            return None

        @staticmethod
        def _status_lead_id(path: str) -> int | None:
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "leads"] and parts[3] == "status" and parts[2].isdigit():
                return int(parts[2])
            return None

        def _static(self, filename: str) -> None:
            path = static_dir / filename
            try:
                body = path.read_bytes()
            except OSError:
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: HTTPStatus, message: str) -> None:
            self._json(status, {"error": message})

        def _method_not_allowed(self, allow: str) -> None:
            body = json.dumps({"error": "method not allowed"}).encode()
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Allow", allow)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _method_or_not_found(self, path: str, allow: str) -> None:
            if path.startswith("/api/"):
                self._method_not_allowed(allow)
            else:
                self._error(HTTPStatus.NOT_FOUND, "not found")

        def log_message(self, format: str, *args: object) -> None:
            LOGGER.debug(format, *args)

    return DashboardHandler


def _default_database() -> Path:
    return Path.home() / ".openclaw" / "data" / "business-prospector" / "business-prospector.db"


def _seed_demo(database: Path) -> None:
    fixture = fake_dentists_resource()
    config = ProspectingConfig.from_resource(default_config_resource())
    ProspectingService(
        FakeBusinessDiscoveryProvider(fixture),
        FakeWebsiteAssessmentProvider(fixture),
        SQLiteLeadRepository(database),
        config,
    ).prospect("dentistas", "Catanduva")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Business Prospector Kanban dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host; keep localhost for this MVP")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, default=_default_database())
    parser.add_argument("--demo", action="store_true", help="Use a temporary database seeded from fake fixtures")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s %(message)s")

    temporary: tempfile.TemporaryDirectory[str] | None = None
    database = args.database.expanduser().resolve()
    if args.demo:
        temporary = tempfile.TemporaryDirectory(prefix="business-prospector-dashboard-")
        database = Path(temporary.name) / "demo.db"
        _seed_demo(database)

    repository = SQLiteLeadRepository(database)
    static_dir = dashboard_static_resource()
    server = ThreadingHTTPServer((args.host, args.port), create_handler(DashboardApplication(repository), static_dir))
    print(f"Business Prospector dashboard: http://{args.host}:{args.port}")
    print(f"SQLite source: {database}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if temporary is not None:
            temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
