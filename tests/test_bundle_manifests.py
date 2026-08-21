from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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


def test_launcher_uses_explicit_python_without_developer_venv() -> None:
    env = dict(os.environ)
    env["BUSINESS_PROSPECTOR_PYTHON"] = os.sys.executable
    result = subprocess.run(
        [str(ROOT / "bin" / "business-prospector-mcp"), "--check"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "runtime: ok" in result.stdout


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


def test_manifests_do_not_claim_unsupported_ambient_env_interpolation() -> None:
    for name in (".mcp.json", "mcp.json"):
        raw = (ROOT / name).read_text(encoding="utf-8")
        assert "${GOOGLE_MAPS_API_KEY}" not in raw
