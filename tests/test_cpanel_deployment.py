from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from business_prospector.application.deployment import (
    DeploymentResult,
    DeploymentStatus,
    SalesPreviewDeploymentService,
    UnpublishResult,
    public_artifact_files,
)
from business_prospector.application.sales_preview import SalesPreviewLifecycleService
from business_prospector.domain.exceptions import ValidationError
from business_prospector.infrastructure.cpanel import (
    CPanelConnectionResult,
    CPanelConnectivityService,
    CPanelDeploymentConfig,
    CPanelError,
    CPanelUapiClient,
    HostGatorPreviewDeploymentProvider,
    HttpRequest,
    HttpResponse,
    UploadFile,
    cpanel_connection_test,
    cpanel_configuration_status,
)
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository

from test_sales_preview import generated_artifact, internal_lead

TOKEN = "unit-test-token-that-must-never-be-returned"


def environment(**changes: str) -> dict[str, str]:
    values = {
        "BUSINESS_PROSPECTOR_CPANEL_BASE_URL": "https://cpanel.example.test:2083",
        "BUSINESS_PROSPECTOR_CPANEL_USERNAME": "prospector",
        "BUSINESS_PROSPECTOR_CPANEL_API_TOKEN": TOKEN,
        "BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN": "gapps.test",
        "BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR": "public_html/sales-previews",
    }
    values.update(changes)
    return values


def config(**changes: str) -> CPanelDeploymentConfig:
    result = CPanelDeploymentConfig.from_environment(environment(**changes))
    assert result is not None
    return result


def envelope(data: Any = None, *, status: int = 1, errors: Any = None) -> bytes:
    return json.dumps({"result": {
        "status": status, "data": data, "errors": errors,
        "messages": None, "warnings": None, "metadata": {},
    }}).encode()


class FakeTransport:
    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        return self.responses.pop(0)


class FailingTransport:
    def __init__(self, error: CPanelError) -> None:
        self.error = error
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        raise self.error


def response(data: Any = None, *, status: int = 1, errors: Any = None) -> HttpResponse:
    return HttpResponse(200, envelope(data, status=status, errors=errors))


def documented_response(data: Any) -> HttpResponse:
    return HttpResponse(200, json.dumps({
        "apiversion": 3,
        "func": "list_domains",
        "module": "DomainInfo",
        "result": {
            "status": 1, "data": data, "errors": None, "messages": None,
            "metadata": None, "warnings": None,
        },
    }).encode(), "application/json")


def flattened_response(
    data: Any, *, status: int = 1, errors: Any = None, messages: Any = None,
) -> HttpResponse:
    return HttpResponse(200, json.dumps({
        "messages": messages,
        "status": status,
        "metadata": {},
        "errors": errors,
        "data": data,
        "warnings": None,
    }).encode(), "application/json")


def site(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<html lang="pt-BR"><header></header><main><h1>Teste</h1>'
        '<img src="assets/hero.svg" alt=""></main><footer></footer></html>',
        encoding="utf-8",
    )
    (root / "styles.css").write_text("@media(min-width:40rem){body{display:block}}", encoding="utf-8")
    (root / "assets" / "hero.svg").write_text("<svg></svg>", encoding="utf-8")
    (root / "site-manifest.json").write_text('{"private":"metadata"}', encoding="utf-8")
    (root / "README.md").write_text("internal", encoding="utf-8")
    return root


def test_configuration_status_requires_every_value_and_never_returns_secret() -> None:
    assert cpanel_configuration_status({}) == {"configured": False, "root_domain": None}
    incomplete = environment(BUSINESS_PROSPECTOR_CPANEL_API_TOKEN="")
    assert cpanel_configuration_status(incomplete) == {"configured": False, "root_domain": None}
    status = cpanel_configuration_status(environment())
    assert status == {"configured": True, "root_domain": "gapps.test"}
    assert TOKEN not in json.dumps(status)
    assert TOKEN not in repr(config())


@pytest.mark.parametrize("base_url", [
    "http://cpanel.example.test:2083", "https://user:pass@cpanel.example.test",
    "https://cpanel.example.test/path", "https://cpanel.example.test?token=bad",
])
def test_configuration_rejects_non_origin_or_non_https_base_url(base_url: str) -> None:
    with pytest.raises(ValidationError, match="HTTPS origin"):
        config(BUSINESS_PROSPECTOR_CPANEL_BASE_URL=base_url)


def test_client_uses_cpanel_token_header_and_closed_uapi_endpoint() -> None:
    transport = FakeTransport(response([]))
    CPanelUapiClient(config(), transport).domains_data()
    request = transport.requests[0]
    assert request.method == "GET"
    assert "/execute/DomainInfo/domains_data?" in request.url
    assert request.headers["Authorization"] == f"cpanel prospector:{TOKEN}"
    assert "password" not in request.headers["Authorization"].casefold()


@pytest.mark.parametrize(
    "http_response, code",
    [
        (HttpResponse(401, b"denied"), "authentication_failed"),
        (HttpResponse(403, b"denied"), "authentication_failed"),
        (HttpResponse(500, b"oops"), "http_error"),
        (HttpResponse(200, b"not-json"), "malformed_response"),
        (response(None, status=0, errors=[f"token {TOKEN} forbidden"]), "forbidden_operation"),
    ],
)
def test_client_normalizes_errors_and_redacts_token(
    http_response: HttpResponse, code: str,
) -> None:
    client = CPanelUapiClient(config(), FakeTransport(http_response))
    with pytest.raises(CPanelError) as caught:
        client.domains_data()
    assert caught.value.code == code
    assert TOKEN not in str(caught.value)


def test_client_normalizes_documented_and_flattened_success() -> None:
    wrapped = CPanelUapiClient(config(), FakeTransport(response([{"domain": "one.test"}])))
    flattened = CPanelUapiClient(
        config(), FakeTransport(flattened_response([{"domain": "two.test"}])),
    )
    assert wrapped.domains_data() == [{"domain": "one.test"}]
    assert flattened.domains_data() == [{"domain": "two.test"}]


@pytest.mark.parametrize("http_response", [response(None), flattened_response(None)])
def test_client_accepts_null_data_in_both_uapi_forms(http_response: HttpResponse) -> None:
    assert CPanelUapiClient(config(), FakeTransport(http_response)).add_subdomain(
        "preview", "gapps.test", "public_html/sales-previews/preview",
    ) is None


@pytest.mark.parametrize(
    "http_response",
    [
        response(None, status=0, errors=["operation failed"]),
        flattened_response(None, status=0, errors=["operation failed"]),
    ],
)
def test_client_handles_failed_status_in_both_uapi_forms(
    http_response: HttpResponse,
) -> None:
    with pytest.raises(CPanelError) as caught:
        CPanelUapiClient(config(), FakeTransport(http_response)).domains_data()
    assert caught.value.code == "uapi_error"


@pytest.mark.parametrize("payload", [{}, {"foo": "bar"}, [], "ok"])
def test_client_rejects_non_uapi_json_shapes(payload: Any) -> None:
    transport = FakeTransport(HttpResponse(200, json.dumps(payload).encode(), "application/json"))
    with pytest.raises(CPanelError) as caught:
        CPanelUapiClient(config(), transport).domains_data()
    assert caught.value.code == "malformed_response"


def test_flattened_failure_redacts_all_infrastructure_values() -> None:
    sensitive_error = (
        f"denied {TOKEN} prospector https://cpanel.example.test:2083"
    )
    client = CPanelUapiClient(
        config(), FakeTransport(flattened_response(None, status=0, errors=[sensitive_error])),
    )
    with pytest.raises(CPanelError) as caught:
        client.domains_data()
    serialized = str(caught.value)
    for value in (TOKEN, "prospector", "https://cpanel.example.test:2083"):
        assert value not in serialized


@pytest.mark.parametrize(
    "method_name, arguments, data",
    [
        ("domains_data", (), [{"domain": "domain.example"}]),
        ("list_files", ("public_html/previews",), {"files": [], "dirs": []}),
        ("add_subdomain", ("preview", "gapps.test", "public_html/previews/preview"), None),
        ("rename_file", ("public_html/staging", "public_html/preview"), None),
        ("delete_file", ("public_html/staging",), None),
        ("installed_ssl_hosts", (), [{"domains": ["preview.gapps.test"]}]),
    ],
)
def test_flattened_shape_is_shared_by_deployment_client_operations(
    method_name: str, arguments: tuple[str, ...], data: Any,
) -> None:
    client = CPanelUapiClient(config(), FakeTransport(flattened_response(data)))
    assert getattr(client, method_name)(*arguments) == data


def test_file_upload_uses_the_same_flattened_response_normalization() -> None:
    data = {"succeeded": 1, "failed": 0, "uploads": []}
    client = CPanelUapiClient(config(), FakeTransport(flattened_response(data)))
    result = client.upload_files(
        "public_html/previews", [UploadFile("index.html", b"safe", "text/html")],
    )
    assert result == data


@pytest.mark.parametrize(
    "domain_data, expected_present",
    [
        ({
            "main_domain": "gapps.test",
            "addon_domains": ["customer.example"],
            "sub_domains": [],
        }, True),
        ({
            "main_domain": "one.example",
            "addon_domains": [],
            "sub_domains": ["two.example"],
            "parked_domains": [],
        }, False),
    ],
)
def test_connectivity_service_returns_only_safe_domain_summary(
    domain_data: Any, expected_present: bool,
) -> None:
    transport = FakeTransport(documented_response(domain_data))
    result = CPanelConnectivityService(
        config(), CPanelUapiClient(config(), transport),
    ).test().to_dict()
    assert result == {
        "configured": True,
        "reachable": True,
        "authenticated": True,
        "root_domain": "gapps.test",
        "root_domain_present": expected_present,
        "domain_count": 2,
        "error_code": None,
        "response_shape": None,
    }
    serialized = json.dumps(result)
    for private_value in (TOKEN, "prospector", "cpanel.example.test", "customer.example"):
        assert private_value not in serialized
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.url.endswith("/execute/DomainInfo/list_domains")
    assert not any(operation in request.url for operation in (
        "addsubdomain", "upload_files", "rename_file", "delete_file",
    ))


def test_connectivity_service_accepts_flattened_hosting_response_without_leaking_domains() -> None:
    domain_data = {
        "main_domain": "temporary.example",
        "addon_domains": ["customer.example"],
        "sub_domains": [],
        "parked_domains": [],
    }
    result = cpanel_connection_test(
        environment(), FakeTransport(flattened_response(domain_data)),
    ).to_dict()
    assert result == {
        "configured": True,
        "reachable": True,
        "authenticated": True,
        "root_domain": "gapps.test",
        "root_domain_present": False,
        "domain_count": 2,
        "error_code": None,
        "response_shape": None,
    }
    serialized = json.dumps(result)
    assert "temporary.example" not in serialized
    assert "customer.example" not in serialized


@pytest.mark.parametrize(
    "transport, expected",
    [
        (
            FakeTransport(HttpResponse(401, b"denied")),
            (True, False, "authentication_failed"),
        ),
        (
            FailingTransport(CPanelError("timeout", "cPanel request failed: timeout")),
            (False, None, "timeout"),
        ),
        (
            FailingTransport(CPanelError("network_failure", "cPanel request failed: network failure")),
            (False, None, "network_failure"),
        ),
        (
            FakeTransport(HttpResponse(200, b"not-json")),
            (True, None, "malformed_response"),
        ),
        (
            FakeTransport(response(None, status=0, errors=[f"token {TOKEN} forbidden"])),
            (True, True, "forbidden_operation"),
        ),
        (
            FakeTransport(response(None, status=0, errors=["unexpected operation failure"])),
            (True, True, "uapi_error"),
        ),
    ],
)
def test_connectivity_service_returns_safe_structured_failures(
    transport: FakeTransport | FailingTransport,
    expected: tuple[bool, bool | None, str],
) -> None:
    result = cpanel_connection_test(environment(), transport).to_dict()
    assert (result["reachable"], result["authenticated"], result["error_code"]) == expected
    serialized = json.dumps(result)
    assert TOKEN not in serialized
    assert "prospector" not in serialized
    assert "cpanel.example.test" not in serialized
    assert len(transport.requests) == 1


def test_connectivity_test_requires_complete_configuration_without_request() -> None:
    transport = FakeTransport()
    result = cpanel_connection_test({}, transport).to_dict()
    assert result == {
        "configured": False,
        "reachable": False,
        "authenticated": None,
        "root_domain": None,
        "root_domain_present": None,
        "domain_count": None,
        "error_code": "not_configured",
        "response_shape": None,
    }
    assert not transport.requests


def test_empty_top_level_object_remains_malformed_with_safe_response_shape() -> None:
    raw: dict[str, object] = {}
    transport = FakeTransport(HttpResponse(
        200, json.dumps(raw).encode(), "application/json; charset=utf-8",
    ))
    result = cpanel_connection_test(environment(), transport).to_dict()
    assert result["error_code"] == "malformed_response"
    assert result["response_shape"] == {
        "http_status": 200,
        "content_type": "application/json",
        "json_parsed": True,
        "top_level_type": "object",
        "top_level_keys": [],
        "result_type": "null",
        "result_keys": [],
        "data_type": None,
    }
    serialized = json.dumps(result)
    assert TOKEN not in serialized


def test_unexpected_data_type_reports_shape_without_copying_value() -> None:
    transport = FakeTransport(documented_response("customer.example"))
    result = cpanel_connection_test(environment(), transport).to_dict()
    assert result["error_code"] == "malformed_response"
    assert result["response_shape"]["data_type"] == "string"
    assert "customer.example" not in json.dumps(result)


def test_cpanel_connection_mcp_tool_has_no_arguments_or_sqlite_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from business_prospector.mcp import server as mcp_server

    source_path = Path(__file__).parents[1] / "src/business_prospector/mcp/server.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "cpanel_connection_test"
    )
    assert function.args.args == []
    monkeypatch.setattr(
        mcp_server, "run_cpanel_connection_test",
        lambda: CPanelConnectionResult(True, True, True, "gapps.test", False, 2),
    )
    monkeypatch.setattr(
        mcp_server, "_repository",
        lambda: (_ for _ in ()).throw(AssertionError("SQLite must not be accessed")),
    )
    result = mcp_server.cpanel_connection_test()
    assert result["data"]["reachable"] is True


def test_domain_is_idempotent_when_document_root_matches() -> None:
    transport = FakeTransport(response([{
        "domain": "drlaura.gapps.test",
        "documentroot": "/home/prospector/public_html/sales-previews/drlaura",
    }]))
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    result = provider.ensure_subdomain("drlaura")
    assert result.status == "existing"
    assert len(transport.requests) == 1


def test_domain_creation_uses_current_subdomain_uapi_operation() -> None:
    transport = FakeTransport(response([]), response({}))
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    result = provider.ensure_subdomain("drlaura")
    assert result.status == "created"
    request = transport.requests[1]
    assert "/execute/SubDomain/addsubdomain?" in request.url
    assert "domain=drlaura" in request.url
    assert "rootdomain=gapps.test" in request.url
    assert "dir=public_html%2Fsales-previews%2Fdrlaura" in request.url


def test_existing_foreign_document_root_is_a_conflict() -> None:
    transport = FakeTransport(response([{
        "domain": "drlaura.gapps.test", "documentroot": "/home/user/public_html/unrelated",
    }]))
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    with pytest.raises(CPanelError) as caught:
        provider.ensure_subdomain("drlaura")
    assert caught.value.code == "document_root_conflict"


@pytest.mark.parametrize("slug", ["../laura", "Laura", "other.example", "-bad", "a" * 33])
def test_slug_and_foreign_domain_inputs_are_rejected(slug: str) -> None:
    provider = HostGatorPreviewDeploymentProvider(
        config(), CPanelUapiClient(config(), FakeTransport()),
    )
    with pytest.raises(ValidationError, match="slug"):
        provider.ensure_subdomain(slug)


def test_public_artifact_allowlist_excludes_manifest_and_readme(tmp_path: Path) -> None:
    root = site(tmp_path)
    relative = {path.relative_to(root).as_posix() for path in public_artifact_files(root)}
    assert relative == {"index.html", "styles.css", "assets/hero.svg"}


def test_public_artifact_rejects_symlink(tmp_path: Path) -> None:
    root = site(tmp_path)
    (root / "assets" / "escape").symlink_to(root / "site-manifest.json")
    with pytest.raises(ValidationError, match="symlink"):
        public_artifact_files(root)


def publish_transport(*, ssl_active: bool = False) -> FakeTransport:
    ssl = [{"domains": ["drlaura.gapps.test"]}] if ssl_active else []
    return FakeTransport(
        response({"dirs": [], "files": []}),
        response({"succeeded": 2, "failed": 0, "uploads": []}),
        response({"succeeded": 1, "failed": 0, "uploads": []}),
        response([]), response({}), response({}), response(ssl),
    )


def test_publish_uploads_staging_then_creates_domain_and_promotes(tmp_path: Path) -> None:
    transport = publish_transport()
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    result = provider.publish(site(tmp_path), "drlaura")
    assert result.deployment_status == "published"
    assert result.files_uploaded == 3
    assert result.domain_status == "created"
    assert result.ssl_status == "pending"
    assert result.preview_url == "https://drlaura.gapps.test"
    urls = [request.url for request in transport.requests]
    assert "/execute/Fileman/upload_files?" in urls[1]
    assert ".staging-drlaura-" in urls[1]
    assert "/execute/Fileman/rename_file?" in urls[-2]
    bodies = b"".join(request.body or b"" for request in transport.requests)
    assert b"site-manifest.json" not in bodies and b"README.md" not in bodies


def test_partial_upload_fails_and_attempts_only_staging_cleanup(tmp_path: Path) -> None:
    transport = FakeTransport(
        response({"dirs": [], "files": []}),
        response({"succeeded": 1, "failed": 1, "uploads": []}),
        response({}),
    )
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    with pytest.raises(CPanelError) as caught:
        provider.publish(site(tmp_path), "drlaura")
    assert caught.value.code == "partial_upload"
    assert "/execute/Fileman/delete_file?" in transport.requests[-1].url
    assert "sales-previews%2F.staging-drlaura-" in transport.requests[-1].url


def test_existing_final_directory_prevents_unrelated_overwrite(tmp_path: Path) -> None:
    transport = FakeTransport(response({"dirs": [{"file": "drlaura"}], "files": []}))
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    with pytest.raises(CPanelError) as caught:
        provider.publish(site(tmp_path), "drlaura")
    assert caught.value.code == "deployment_conflict"
    assert len(transport.requests) == 1


def test_status_is_read_only_and_reports_ssl_active() -> None:
    transport = FakeTransport(
        response([{
            "domain": "drlaura.gapps.test",
            "documentroot": "public_html/sales-previews/drlaura",
        }]),
        response({
            "files": [{"file": "index.html", "type": "file"}, {"file": "styles.css", "type": "file"}],
            "dirs": [{"file": "assets"}],
        }),
        response([{"domains": ["drlaura.gapps.test"]}]),
    )
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    result = provider.status("drlaura")
    assert result.deployment_status == "published" and result.ssl_status == "active"
    assert all(request.method == "GET" for request in transport.requests)


def test_unpublish_is_explicitly_unsupported_and_makes_no_request() -> None:
    transport = FakeTransport()
    provider = HostGatorPreviewDeploymentProvider(config(), CPanelUapiClient(config(), transport))
    result = provider.unpublish("drlaura")
    assert result.deployment_status == "unsupported"
    assert not transport.requests
    with pytest.raises(ValidationError):
        provider.unpublish("../gapps.test")


class FakeProvider:
    def __init__(self) -> None:
        self.publish_calls = 0

    def publish(self, site_path: Path, preview_slug: str) -> DeploymentResult:
        self.publish_calls += 1
        from business_prospector.application.deployment import artifact_checksum
        return DeploymentResult(
            "published", preview_slug, f"https://{preview_slug}.gapps.test", 3,
            "created", "pending", "deployment-test", artifact_checksum(site_path), (),
        )

    def status(self, preview_slug: str) -> DeploymentStatus:
        return DeploymentStatus(
            "published", preview_slug, f"https://{preview_slug}.gapps.test",
            True, True, True, "pending", (),
        )

    def unpublish(self, preview_slug: str) -> UnpublishResult:
        return UnpublishResult("unsupported", preview_slug, ("not implemented",))


def approved_service(tmp_path: Path, initial_status: str = "internal_website") -> tuple[
    SQLiteLeadRepository, Any, Path, FakeProvider, SalesPreviewDeploymentService,
]:
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    stored = internal_lead(repository)
    drafts, site_path = generated_artifact(tmp_path, stored)
    if initial_status == "sales_preview":
        SalesPreviewLifecycleService(repository, drafts).approve(
            stored.id or 0, content_review_acknowledged=True,
            asset_keys_approved_for_publish=[], approved_by="reviewer",
        )
    else:
        repository.update(stored.id or 0, {"status": initial_status})
    provider = FakeProvider()
    return repository, stored, site_path, provider, SalesPreviewDeploymentService(
        repository, drafts, provider,
    )


@pytest.mark.parametrize("lead_status", ["qualified", "internal_website"])
def test_only_sales_preview_can_publish(tmp_path: Path, lead_status: str) -> None:
    repository, stored, _, provider, service = approved_service(tmp_path, lead_status)
    with pytest.raises(ValidationError, match="approved Sales Preview"):
        service.publish(stored.id or 0, explicitly_authorized=True)
    assert provider.publish_calls == 0
    assert repository.get(stored.id or 0).status == lead_status  # type: ignore[union-attr]


def test_publish_requires_explicit_authorization_and_never_marks_contacted(tmp_path: Path) -> None:
    repository, stored, site_path, provider, service = approved_service(tmp_path, "sales_preview")
    with pytest.raises(ValidationError, match="explicit"):
        service.publish(stored.id or 0, explicitly_authorized=False)
    result = service.publish(stored.id or 0, explicitly_authorized=True)
    assert result.deployment_status == "published" and provider.publish_calls == 1
    assert repository.get(stored.id or 0).status == "sales_preview"  # type: ignore[union-attr]
    manifest = json.loads((site_path / "site-manifest.json").read_text())
    assert manifest["deployment"]["deployment_status"] == "published"
    assert manifest["deployment"]["artifact_checksum"] == result.artifact_checksum
    assert manifest["sales_preview"]["preview_status"] == "published"


def test_unchanged_publish_is_idempotent_without_second_provider_call(tmp_path: Path) -> None:
    _, stored, _, provider, service = approved_service(tmp_path, "sales_preview")
    first = service.publish(stored.id or 0, explicitly_authorized=True)
    second = service.publish(stored.id or 0, explicitly_authorized=True)
    assert first.deployment_id == second.deployment_id
    assert provider.publish_calls == 1
    assert "already published" in second.warnings[0]


def test_mcp_boundaries_do_not_accept_infrastructure_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = Path(__file__).parents[1] / "src/business_prospector/mcp/server.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "publish_sales_preview"
    )
    assert {argument.arg for argument in function.args.args} == {
        "lead_id", "explicitly_authorized",
    }
    monkeypatch.setenv("BUSINESS_PROSPECTOR_CPANEL_API_TOKEN", TOKEN)
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    output = cpanel_configuration_status()
    serialized = json.dumps(output)
    assert output == {"configured": True, "root_domain": "gapps.test"}
    assert TOKEN not in serialized and "prospector" not in serialized
