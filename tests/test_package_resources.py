from __future__ import annotations

import tomllib
from pathlib import Path

from business_prospector import dashboard
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository
from business_prospector.package_resources import (
    dashboard_static_resource,
    default_config_resource,
    fake_dentists_resource,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_defaults_match_bundle_and_test_sources() -> None:
    assert default_config_resource().read_text(encoding="utf-8") == (
        ROOT / "config" / "default.json"
    ).read_text(encoding="utf-8")
    assert fake_dentists_resource().read_text(encoding="utf-8") == (
        ROOT / "tests" / "fixtures" / "dentists.json"
    ).read_text(encoding="utf-8")


def test_dashboard_demo_does_not_resolve_resources_from_installed_module_path(
    tmp_path: Path, monkeypatch
) -> None:
    installed_module = (
        tmp_path
        / "runtime"
        / "lib"
        / "python3.14"
        / "site-packages"
        / "business_prospector"
        / "dashboard.py"
    )
    monkeypatch.setattr(dashboard, "__file__", str(installed_module))
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "demo.db"

    dashboard._seed_demo(database)

    assert len(SQLiteLeadRepository(database).list()) == 2


def test_read_only_resources_are_declared_as_package_data() -> None:
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "tool"
    ]["setuptools"]["package-data"]["business_prospector"]
    assert "resources/*.json" in package_data
    assert dashboard_static_resource().joinpath("index.html").is_file()
