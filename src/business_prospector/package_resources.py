from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable


def resource(*parts: str) -> Traversable:
    item = files("business_prospector")
    for part in parts:
        item = item.joinpath(part)
    return item


def default_config_resource() -> Traversable:
    return resource("resources", "default.json")


def fake_dentists_resource() -> Traversable:
    return resource("resources", "dentists.json")


def dashboard_static_resource() -> Traversable:
    return resource("dashboard_static")
