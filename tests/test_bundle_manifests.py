from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AGENT_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def read_json(name: str) -> dict[str, object]:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_agent_plugins_manifest_has_runtime_detection_marker() -> None:
    manifest = read_json("plugin.json")
    assert manifest["$schema"] == AGENT_PLUGIN_SCHEMA
    assert manifest["name"] == "business-prospector"
    assert (ROOT / "plugin.json").parent == ROOT
    assert not (ROOT / ".claude-plugin" / "plugin.json").exists()


def test_agent_mcp_config_is_closed_and_uses_bundle_contract() -> None:
    config = read_json("mcp.json")
    assert set(config) == {"$schema", "mcpServers"}
    assert config["$schema"] == AGENT_MCP_SCHEMA
    servers = config["mcpServers"]
    assert isinstance(servers, dict)
    server = servers["business-prospector"]
    assert server["type"] == "stdio"
    assert server["command"] == "./bin/business-prospector-mcp"
    assert server["cwd"] == "${PLUGIN_ROOT}"
    assert server["env"]["BUSINESS_PROSPECTOR_DATA_DIR"] == "${PLUGIN_DATA}"
    assert "GOOGLE_MAPS_API_KEY" not in server["env"]


def test_openclaw_2026_7_1_claude_fallback_loads_same_server() -> None:
    config = read_json(".mcp.json")
    servers = config["mcpServers"]
    assert isinstance(servers, dict)
    server = servers["business-prospector"]
    assert server["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/business-prospector-mcp"
    assert "type" not in server
    assert "GOOGLE_MAPS_API_KEY" not in server["env"]


def test_bundle_mcp_commands_use_the_executable_launcher_not_python() -> None:
    launcher = ROOT / "bin" / "business-prospector-mcp"
    assert os.access(launcher, os.X_OK)

    agent_server = read_json("mcp.json")["mcpServers"]["business-prospector"]
    claude_server = read_json(".mcp.json")["mcpServers"]["business-prospector"]
    assert agent_server["command"] == "./bin/business-prospector-mcp"
    assert claude_server["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/business-prospector-mcp"
    for server in (agent_server, claude_server):
        command = server["command"].lower()
        assert "python" not in command
        assert server["args"] == []


def test_launcher_uses_explicit_python_without_developer_venv(tmp_path: Path) -> None:
    invocation = tmp_path / "python-invocation.txt"
    fake_python = tmp_path / "controlled-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_PYTHON_INVOCATION\"\n"
        "printf '%s\\n' 'business-prospector MCP runtime: ok'\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = dict(os.environ)
    env["BUSINESS_PROSPECTOR_PYTHON"] = str(fake_python)
    env["FAKE_PYTHON_INVOCATION"] = str(invocation)
    result = subprocess.run(
        [str(ROOT / "bin" / "business-prospector-mcp"), "--check"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "runtime: ok" in result.stdout
    arguments = invocation.read_text(encoding="utf-8").splitlines()
    assert arguments[0] == "-c"
    assert "import mcp, business_prospector" in arguments[1]


def test_launcher_recovers_only_google_key_from_openclaw_service_env(tmp_path: Path) -> None:
    service_env = tmp_path / ".openclaw" / "service-env" / "ai.openclaw.gateway.env"
    service_env.parent.mkdir(parents=True)
    service_env.write_text(
        "GOOGLE_MAPS_API_KEY='test-only'\n"
        "UNRELATED_PRIVATE_VALUE='must-not-be-forwarded'\n",
        encoding="utf-8",
    )
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "BUSINESS_PROSPECTOR_PYTHON": os.sys.executable,
    }
    result = subprocess.run(
        [str(ROOT / "bin" / "business-prospector-mcp"), "--check-google-places-env"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "business-prospector Google Places environment: configured"
    assert "test-only" not in result.stdout + result.stderr
    assert "UNRELATED_PRIVATE_VALUE" not in result.stdout + result.stderr


def test_launcher_recovers_allowlisted_cpanel_environment_without_printing_token(
    tmp_path: Path,
) -> None:
    service_env = tmp_path / ".openclaw" / "service-env" / "ai.openclaw.gateway.env"
    service_env.parent.mkdir(parents=True)
    service_env.write_text(
        "BUSINESS_PROSPECTOR_CPANEL_BASE_URL='https://cpanel.example.test:2083'\n"
        "BUSINESS_PROSPECTOR_CPANEL_USERNAME='prospector'\n"
        "BUSINESS_PROSPECTOR_CPANEL_API_TOKEN='test-token-must-not-print'\n"
        "BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN='gapps.test'\n"
        "BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR='public_html/sales-previews'\n"
        "UNRELATED_PRIVATE_VALUE='must-not-be-forwarded'\n",
        encoding="utf-8",
    )
    env = {
        "HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""),
        "BUSINESS_PROSPECTOR_PYTHON": os.sys.executable,
    }
    result = subprocess.run(
        [str(ROOT / "bin" / "business-prospector-mcp"), "--check-cpanel-env"],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    assert result.stdout.strip() == "business-prospector cPanel environment: configured"
    assert "test-token-must-not-print" not in output
    assert "UNRELATED_PRIVATE_VALUE" not in output


def test_manifests_do_not_claim_unsupported_ambient_env_interpolation() -> None:
    for name in (".mcp.json", "mcp.json"):
        raw = (ROOT / name).read_text(encoding="utf-8")
        assert "${GOOGLE_MAPS_API_KEY}" not in raw
        assert "CPANEL_API_TOKEN" not in raw


def test_openclaw_stdio_path_reaches_launcher_and_cpanel_status(tmp_path: Path) -> None:
    """Exercise the compatibility manifest -> launcher -> MCP tool boundary."""
    service_env = tmp_path / ".openclaw" / "service-env" / "ai.openclaw.gateway.env"
    service_env.parent.mkdir(parents=True)
    service_env.write_text(
        "BUSINESS_PROSPECTOR_CPANEL_BASE_URL='https://cpanel.example.test:2083'\n"
        "BUSINESS_PROSPECTOR_CPANEL_USERNAME='test-user'\n"
        "BUSINESS_PROSPECTOR_CPANEL_API_TOKEN='test-only-token'\n"
        "BUSINESS_PROSPECTOR_PREVIEW_ROOT_DOMAIN='preview.example.test'\n"
        "BUSINESS_PROSPECTOR_PREVIEW_BASE_DIR='public_html/previews'\n",
        encoding="utf-8",
    )
    server = read_json(".mcp.json")["mcpServers"]["business-prospector"]
    command = server["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
    cwd = server["cwd"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "BUSINESS_PROSPECTOR_PYTHON": os.sys.executable,
        "BUSINESS_PROSPECTOR_CONFIG": str(ROOT / "config" / "default.json"),
        "BUSINESS_PROSPECTOR_DATA_DIR": str(tmp_path / "data"),
    }

    async def call_status() -> dict[str, object] | None:
        parameters = StdioServerParameters(command=command, args=server["args"], cwd=cwd, env=env)
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("cpanel_status", {})
                return result.structuredContent

    result = asyncio.run(call_status())
    assert result is not None
    assert result["ok"] is True
    assert result["data"] == {
        "configured": True,
        "root_domain": "preview.example.test",
    }
