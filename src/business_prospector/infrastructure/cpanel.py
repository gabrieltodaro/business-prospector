from __future__ import annotations

import json
import mimetypes
import os
import re
import socket
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from business_prospector.application.deployment import (
    DeploymentResult,
    DeploymentStatus,
    UnpublishResult,
    artifact_checksum,
    public_artifact_files,
)
from business_prospector.domain.exceptions import ValidationError

ENV_BASE_URL = "BUSINESS_PROSPECTOR_CPANEL_BASE_URL"
ENV_USERNAME = "BUSINESS_PROSPECTOR_CPANEL_USERNAME"
ENV_TOKEN = "BUSINESS_PROSPECTOR_CPANEL_API_TOKEN"
ENV_ROOT_DOMAIN = "BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN"
ENV_BASE_DIR = "BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR"
CPANEL_ENV_KEYS = (ENV_BASE_URL, ENV_USERNAME, ENV_TOKEN, ENV_ROOT_DOMAIN, ENV_BASE_DIR)
SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


class CPanelError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CPanelDeploymentConfig:
    base_url: str
    username: str
    api_token: str = field(repr=False)
    root_domain: str
    base_dir: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None,
    ) -> CPanelDeploymentConfig | None:
        env = os.environ if environment is None else environment
        values = {key: env.get(key, "").strip() for key in CPANEL_ENV_KEYS}
        if not any(values.values()):
            return None
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ValidationError("cPanel deployment configuration is incomplete")
        return cls(
            values[ENV_BASE_URL], values[ENV_USERNAME], values[ENV_TOKEN],
            values[ENV_ROOT_DOMAIN].casefold().rstrip("."), values[ENV_BASE_DIR],
        ).validated()

    def validated(self) -> CPanelDeploymentConfig:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
        ):
            raise ValidationError("cPanel base URL must be an HTTPS origin")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", self.username):
            raise ValidationError("cPanel username is invalid")
        if not self.api_token or any(char in self.api_token for char in "\r\n"):
            raise ValidationError("cPanel API token is invalid")
        if not DOMAIN_PATTERN.fullmatch(self.root_domain):
            raise ValidationError("preview root domain is invalid")
        normalized = _safe_remote_path(self.base_dir)
        if normalized != self.base_dir.strip("/"):
            raise ValidationError("preview base directory must be a normalized relative path")
        return self

    def safe_status(self) -> dict[str, Any]:
        return {"configured": True, "root_domain": self.root_domain}


def cpanel_configuration_status(environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    try:
        config = CPanelDeploymentConfig.from_environment(environment)
    except ValidationError:
        return {"configured": False, "root_domain": None}
    return config.safe_status() if config else {"configured": False, "root_domain": None}


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


class UrllibHttpTransport:
    def send(self, request: HttpRequest) -> HttpResponse:
        try:
            raw = Request(
                request.url, data=request.body, headers=dict(request.headers), method=request.method,
            )
            with urlopen(raw, timeout=request.timeout) as response:
                return HttpResponse(int(response.status), response.read())
        except HTTPError as exc:
            body = exc.read() if exc.fp else b""
            return HttpResponse(int(exc.code), body)
        except (URLError, TimeoutError, socket.timeout) as exc:
            reason = "timeout" if isinstance(exc, (TimeoutError, socket.timeout)) else "network failure"
            raise CPanelError("network_failure", f"cPanel request failed: {reason}") from None


@dataclass(frozen=True, slots=True)
class UploadFile:
    filename: str
    content: bytes
    content_type: str


class CPanelUapiClient:
    """Narrow cPanel UAPI v3 client. Module/function names are never caller supplied."""

    def __init__(
        self, config: CPanelDeploymentConfig, transport: HttpTransport | None = None,
    ) -> None:
        self._config = config.validated()
        self._transport = transport or UrllibHttpTransport()

    def domains_data(self) -> Any:
        return self._get("DomainInfo", "domains_data", {"format": "list"})

    def add_subdomain(self, slug: str, root_domain: str, document_root: str) -> Any:
        return self._get("SubDomain", "addsubdomain", {
            "domain": slug, "rootdomain": root_domain, "dir": document_root,
            "disallowdot": "1",
        })

    def list_files(self, directory: str) -> Any:
        return self._get("Fileman", "list_files", {
            "dir": directory, "show_hidden": "1", "types": "file|dir|link",
        })

    def upload_files(self, directory: str, files: Sequence[UploadFile]) -> Any:
        if not files:
            raise CPanelError("upload_failed", "at least one public file is required")
        boundary = "business-prospector-" + uuid.uuid4().hex
        body = bytearray()
        for index, upload in enumerate(files):
            if not _safe_filename(upload.filename):
                raise CPanelError("unsafe_path", "public upload filename is invalid")
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="file-{index}"; filename="{upload.filename}"\r\n'.encode()
            )
            body.extend(f"Content-Type: {upload.content_type}\r\n\r\n".encode())
            body.extend(upload.content)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        return self._request(
            "POST", "Fileman", "upload_files",
            {"dir": directory, "overwrite": "0", "permissions": "0644"},
            bytes(body), f"multipart/form-data; boundary={boundary}",
        )

    def rename_file(self, source: str, destination: str) -> Any:
        return self._get("Fileman", "rename_file", {
            "source": source, "destination": destination,
        })

    def delete_file(self, path: str) -> Any:
        return self._get("Fileman", "delete_file", {"path": path})

    def installed_ssl_hosts(self) -> Any:
        return self._get("SSL", "installed_hosts", {})

    def _get(self, module: str, function: str, parameters: Mapping[str, str]) -> Any:
        return self._request("GET", module, function, parameters, None, None)

    def _request(
        self, method: str, module: str, function: str, parameters: Mapping[str, str],
        body: bytes | None, content_type: str | None,
    ) -> Any:
        origin = self._config.base_url.rstrip("/")
        query = urlencode(parameters)
        url = f"{origin}/execute/{module}/{function}" + (f"?{query}" if query else "")
        headers = {
            "Accept": "application/json",
            "Authorization": f"cpanel {self._config.username}:{self._config.api_token}",
            "User-Agent": "business-prospector/0.1",
        }
        if content_type:
            headers["Content-Type"] = content_type
        response = self._transport.send(HttpRequest(
            method, url, headers, body, self._config.timeout_seconds,
        ))
        if response.status in {401, 403}:
            raise CPanelError("authentication_failed", "cPanel authentication or authorization failed")
        if not 200 <= response.status < 300:
            raise CPanelError("http_error", f"cPanel returned HTTP {response.status}")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CPanelError("malformed_response", "cPanel returned malformed JSON") from None
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise CPanelError("malformed_response", "cPanel returned an invalid UAPI envelope")
        if result.get("status") not in {1, True, "1"}:
            errors = result.get("errors")
            message = _safe_error_message(errors, self._config)
            code = _classify_uapi_error(message)
            raise CPanelError(code, message)
        return result.get("data")


@dataclass(frozen=True, slots=True)
class DomainEnsureResult:
    status: str
    fqdn: str
    document_root: str


class HostGatorPreviewDeploymentProvider:
    def __init__(self, config: CPanelDeploymentConfig, client: CPanelUapiClient) -> None:
        self._config = config.validated()
        self._client = client

    def publish(self, site_path: Path, preview_slug: str) -> DeploymentResult:
        slug = _safe_slug(preview_slug)
        files = public_artifact_files(site_path)
        checksum = artifact_checksum(site_path)
        deployment_id = checksum[:16]
        base_dir = _safe_remote_path(self._config.base_dir)
        final_dir = _safe_remote_path(f"{base_dir}/{slug}")
        staging_name = f".staging-{slug}-{deployment_id}"
        staging_dir = _safe_remote_path(f"{base_dir}/{staging_name}")
        if self._directory_exists(base_dir, slug):
            raise CPanelError(
                "deployment_conflict",
                "preview directory already exists; atomic replacement is not supported by UAPI",
            )
        uploaded = 0
        try:
            grouped: dict[str, list[UploadFile]] = {}
            root = site_path.resolve()
            for path in files:
                relative = path.relative_to(root)
                remote_parent = staging_dir
                if relative.parent != Path("."):
                    remote_parent = _safe_remote_path(
                        f"{staging_dir}/{relative.parent.as_posix()}"
                    )
                grouped.setdefault(remote_parent, []).append(UploadFile(
                    relative.name, path.read_bytes(),
                    mimetypes.guess_type(relative.name)[0] or "application/octet-stream",
                ))
            for directory, uploads in grouped.items():
                data = self._client.upload_files(directory, uploads)
                succeeded, failed = _upload_counts(data)
                uploaded += succeeded
                if failed or succeeded != len(uploads):
                    raise CPanelError("partial_upload", "cPanel did not store every public file")
            domain = self.ensure_subdomain(slug)
            self._client.rename_file(staging_dir, final_dir)
        except Exception:
            try:
                self._client.delete_file(staging_dir)
            except CPanelError:
                pass
            raise
        ssl_status = self._ssl_status(f"{slug}.{self._config.root_domain}")
        warnings = () if ssl_status == "active" else (
            "HTTPS certificate is not active yet; do not send this URL to a prospect",
        )
        return DeploymentResult(
            "published", slug, f"https://{slug}.{self._config.root_domain}", uploaded,
            domain.status, ssl_status, deployment_id, checksum, warnings,
        )

    def ensure_subdomain(self, preview_slug: str) -> DomainEnsureResult:
        slug = _safe_slug(preview_slug)
        fqdn = f"{slug}.{self._config.root_domain}"
        expected = _safe_remote_path(f"{self._config.base_dir}/{slug}")
        existing = self._find_domain(fqdn)
        if existing is not None:
            actual = _domain_document_root(existing)
            if not _document_roots_match(actual, expected):
                raise CPanelError(
                    "document_root_conflict",
                    "preview domain exists with a different document root",
                )
            return DomainEnsureResult("existing", fqdn, expected)
        self._client.add_subdomain(slug, self._config.root_domain, expected)
        return DomainEnsureResult("created", fqdn, expected)

    def status(self, preview_slug: str) -> DeploymentStatus:
        slug = _safe_slug(preview_slug)
        fqdn = f"{slug}.{self._config.root_domain}"
        expected = _safe_remote_path(f"{self._config.base_dir}/{slug}")
        domain = self._find_domain(fqdn)
        configured = domain is not None
        root_matches = configured and _document_roots_match(
            _domain_document_root(domain or {}), expected,
        )
        files_present = False
        warnings: list[str] = []
        if root_matches:
            try:
                listing = self._client.list_files(expected)
                names = _listed_file_names(listing)
                files_present = {"index.html", "styles.css"} <= names
            except CPanelError as exc:
                warnings.append(f"file status unavailable: {exc.code}")
        ssl_status = self._ssl_status(fqdn)
        if ssl_status != "active":
            warnings.append("HTTPS certificate is not active")
        state = "published" if configured and root_matches and files_present else "not_published"
        return DeploymentStatus(
            state, slug, f"https://{fqdn}", configured, bool(root_matches), files_present,
            ssl_status, tuple(warnings),
        )

    def unpublish(self, preview_slug: str) -> UnpublishResult:
        slug = _safe_slug(preview_slug)
        return UnpublishResult(
            "unsupported", slug,
            ("UAPI-only unpublish is disabled until domain and directory removal can be transactional",),
        )

    def _directory_exists(self, parent: str, name: str) -> bool:
        try:
            return name in _listed_directory_names(self._client.list_files(parent))
        except CPanelError as exc:
            if exc.code in {"not_found", "uapi_error"}:
                return False
            raise

    def _find_domain(self, fqdn: str) -> Mapping[str, Any] | None:
        for domain in _domain_records(self._client.domains_data()):
            if str(domain.get("domain") or domain.get("servername") or "").casefold() == fqdn:
                return domain
        return None

    def _ssl_status(self, fqdn: str) -> str:
        try:
            data = self._client.installed_ssl_hosts()
        except CPanelError:
            return "unknown"
        if not isinstance(data, list):
            return "unknown"
        for host in data:
            if not isinstance(host, dict):
                continue
            domains = set(str(item).casefold() for item in host.get("domains", []) if item)
            certificate = host.get("certificate")
            if isinstance(certificate, dict):
                domains.update(
                    str(item).casefold() for item in certificate.get("domains", []) if item
                )
            if fqdn in domains:
                return "active"
        return "pending"


def _safe_slug(value: str) -> str:
    if not isinstance(value, str) or not SLUG_PATTERN.fullmatch(value):
        raise ValidationError("preview slug is invalid")
    return value


def _safe_remote_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValidationError("remote preview path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError("remote preview path is invalid")
    return path.as_posix()


def _safe_filename(value: str) -> bool:
    return bool(value and value not in {".", ".."} and not any(
        char in value for char in "/\\\r\n\x00,;"
    ))


def _safe_error_message(errors: Any, config: CPanelDeploymentConfig) -> str:
    if isinstance(errors, list):
        raw = "; ".join(str(item) for item in errors if item)
    elif errors:
        raw = str(errors)
    else:
        raw = "cPanel UAPI operation failed"
    for secret in (config.api_token, config.username, config.base_url):
        if secret:
            raw = raw.replace(secret, "[redacted]")
    return raw[:500]


def _classify_uapi_error(message: str) -> str:
    lowered = message.casefold()
    if "already exists" in lowered:
        return "already_exists"
    if any(word in lowered for word in ("permission", "feature", "disabled", "forbidden", "not allowed")):
        return "forbidden_operation"
    if "not exist" in lowered or "not found" in lowered:
        return "not_found"
    return "uapi_error"


def _domain_records(data: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(data, list):
        return tuple(item for item in data if isinstance(item, dict))
    if not isinstance(data, dict):
        raise CPanelError("malformed_response", "cPanel domain data is malformed")
    records: list[Mapping[str, Any]] = []
    for value in data.values():
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            records.append(value)
    return tuple(records)


def _domain_document_root(domain: Mapping[str, Any]) -> str:
    return str(
        domain.get("documentroot") or domain.get("document_root") or domain.get("docroot") or ""
    )


def _document_roots_match(actual: str, expected: str) -> bool:
    clean_actual = actual.rstrip("/")
    clean_expected = expected.rstrip("/")
    return clean_actual == clean_expected or clean_actual.endswith("/" + clean_expected)


def _upload_counts(data: Any) -> tuple[int, int]:
    if not isinstance(data, dict):
        raise CPanelError("malformed_response", "cPanel upload result is malformed")
    try:
        return int(data.get("succeeded", 0)), int(data.get("failed", 0))
    except (TypeError, ValueError):
        raise CPanelError("malformed_response", "cPanel upload counts are malformed") from None


def _listed_file_names(data: Any) -> set[str]:
    if not isinstance(data, dict) or not isinstance(data.get("files", []), list):
        raise CPanelError("malformed_response", "cPanel file listing is malformed")
    return {
        str(item.get("file")) for item in data.get("files", [])
        if isinstance(item, dict) and item.get("type", "file") == "file" and item.get("file")
    }


def _listed_directory_names(data: Any) -> set[str]:
    if not isinstance(data, dict) or not isinstance(data.get("dirs", []), list):
        raise CPanelError("malformed_response", "cPanel directory listing is malformed")
    return {
        str(item.get("file")) for item in data.get("dirs", [])
        if isinstance(item, dict) and item.get("file")
    }
