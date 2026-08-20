#!/usr/bin/env python3
"""Bundle entry point; keeps the src layout usable without installation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from business_prospector.mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()

