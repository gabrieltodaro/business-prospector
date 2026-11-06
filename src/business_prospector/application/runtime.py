"""Shared runtime paths; resolving a path never opens an operational database."""
from __future__ import annotations

import os
from pathlib import Path
from importlib.resources.abc import Traversable

from business_prospector.package_resources import default_config_resource


def data_directory() -> Path:
    configured = os.environ.get("BUSINESS_PROSPECTOR_DATA_DIR")
    return (Path(configured).expanduser() if configured else
            Path.home() / ".openclaw" / "data" / "business-prospector").resolve()


def database_path() -> Path:
    return data_directory() / "business-prospector.db"


def config_resource() -> Traversable:
    configured = os.environ.get("BUSINESS_PROSPECTOR_CONFIG")
    return Path(configured).expanduser().resolve() if configured else default_config_resource()
