#!/usr/bin/env python3
"""Install the MCP dependency set into a stable OpenClaw-owned virtualenv."""
from __future__ import annotations

import argparse
import os
import subprocess
import venv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path.home() / ".openclaw" / "venvs" / "business-prospector",
        help="Persistent virtualenv path outside the plugin checkout",
    )
    args = parser.parse_args()

    plugin_root = Path(__file__).resolve().parents[1]
    runtime_dir = args.runtime_dir.expanduser().resolve()
    runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True, upgrade_deps=False).create(runtime_dir)
    python = runtime_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(plugin_root)],
        check=True,
    )
    subprocess.run(
        [str(python), "-c", "import mcp, business_prospector"],
        check=True,
    )
    print(f"OpenClaw MCP runtime ready: {python}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

