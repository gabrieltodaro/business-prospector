import json
import sqlite3
from pathlib import Path

import pytest

from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


def lead(name: str = "Clinica Teste", website: str = "https://www.example.com") -> Lead:
    return Lead(
        name=name, category="dentista", city="Catanduva", rating=4.9, review_count=120,
        website_url=website, phone="(17) 99999-1234",
        assessment=WebsiteAssessment(True, True, True, False, False, False, "site fraco"), score=80,
    )


@pytest.fixture
def repository(tmp_path: Path) -> SQLiteLeadRepository:
    return SQLiteLeadRepository(tmp_path / "prospector.db")


def test_save_get_update_and_list(repository: SQLiteLeadRepository) -> None:
    first = repository.save(lead("Lead B", "https://b.example.com"))
    second = lead("Lead A", "https://a.example.com")
    second.score = 90
    second = repository.save(second)
    assert repository.get(first.id or 0).name == "Lead B"  # type: ignore[union-attr]
    updated = repository.update(first.id or 0, {"email": "contato@example.com"})
    assert updated.email == "contato@example.com"
    assert [item.id for item in repository.list()] == [second.id, first.id]


@pytest.mark.parametrize(
    ("candidate", "match_type", "confidence"),
    [
        (BusinessCandidate("Outro", "dentista", "Outra", 5, 1, external_place_id="place-1"), "external_place_id", "exact"),
        (BusinessCandidate("Outro", "dentista", "Outra", 5, 1, website_url="http://example.com/x"), "normalized_domain", "likely"),
        (BusinessCandidate("Outro", "dentista", "Outra", 5, 1, phone="+55 17 99999-1234"), "normalized_phone", "likely"),
        (BusinessCandidate("Clínica Teste", "dentista", "CATANDUVA", 5, 1), "normalized_name_city", "possible"),
    ],
)
def test_layered_deduplication(
    repository: SQLiteLeadRepository, candidate: BusinessCandidate, match_type: str, confidence: str
) -> None:
    original = lead()
    original.external_place_id = "place-1"
    repository.save(original)
    match = repository.find_duplicate(candidate)
    assert match is not None
    assert (match.match_type, match.confidence) == (match_type, confidence)


@pytest.mark.parametrize("fallback", ["domain", "phone", "name_city", "address"])
def test_different_stable_place_ids_are_not_repository_duplicates(
    repository: SQLiteLeadRepository, fallback: str,
) -> None:
    original = lead()
    original.external_place_id = "place-A"
    original.address = "Rua Brasil, 10"
    repository.save(original)
    values: dict[str, object] = {
        "name": "Other", "city": "Other", "website_url": "https://other.example",
        "phone": "5517888888888", "address": "Rua Other, 20",
    }
    if fallback == "domain":
        values["website_url"] = "https://example.com/path"
    elif fallback == "phone":
        values["phone"] = "5517999991234"
    elif fallback == "name_city":
        values.update(name="Clinica Teste", city="Catanduva")
    else:
        values["address"] = "RUA BRASIL, 10"
    candidate = BusinessCandidate(
        category="dentista", rating=5, review_count=1, external_place_id="place-B", **values,
    )
    assert repository.find_duplicate(candidate) is None


def test_repository_fallback_matches_record_without_stable_place_id(
    repository: SQLiteLeadRepository,
) -> None:
    repository.save(lead())
    candidate = BusinessCandidate(
        "Other", "dentista", "Other", 5, 1,
        website_url="https://example.com/path", external_place_id="place-B",
    )
    match = repository.find_duplicate(candidate)
    assert match is not None
    assert match.match_type == "normalized_domain"


def test_fallback_identity_works_in_both_missing_place_id_directions(
    repository: SQLiteLeadRepository,
) -> None:
    existing_without_id = repository.save(lead("Without ID", "https://without-id.example"))
    candidate_with_id = BusinessCandidate(
        "Other", "dentista", "Other", 5, 1,
        website_url="https://without-id.example/path", external_place_id="place-new",
    )
    match = repository.find_duplicate(candidate_with_id)
    assert match is not None and match.lead_id == existing_without_id.id

    existing_with_id = lead("With ID", "https://with-id.example")
    existing_with_id.external_place_id = "place-existing"
    existing_with_id = repository.save(existing_with_id)
    candidate_without_id = BusinessCandidate(
        "Other Two", "dentista", "Other", 5, 1,
        website_url="https://with-id.example/path",
    )
    match = repository.find_duplicate(candidate_without_id)
    assert match is not None and match.lead_id == existing_with_id.id


def test_slug_conflict_is_technical_and_does_not_change_business_identity(
    repository: SQLiteLeadRepository,
) -> None:
    original = lead("Same Name")
    original.external_place_id = "place-A"
    original = repository.save(original)
    candidate = BusinessCandidate(
        "Same Name", "dentista", "Catanduva", 5, 100,
        website_url="https://different.example", external_place_id="place-B",
    )
    assert repository.find_duplicate(candidate) is None
    conflict = repository.find_slug_conflict(original.slug or "")
    assert conflict is not None
    assert conflict.to_dict() == {
        "type": "technical_identifier_conflict",
        "field": "slug",
        "value": original.slug,
        "existing_lead_id": original.id,
    }


def test_schema_v1_migrates_without_losing_leads(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    repository = SQLiteLeadRepository(database)
    original = repository.save(lead())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 1")

    migrated = SQLiteLeadRepository(database)
    updated = migrated.update(original.id or 0, {"status": "proposal"})

    assert updated.name == original.name
    assert updated.status == "proposal"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(leads)")}
    assert "ix_leads_name_city" in indexes


def test_schema_v2_adds_evidence_columns_and_preserves_legacy_rows(tmp_path: Path) -> None:
    database = tmp_path / "v2.db"
    repository = SQLiteLeadRepository(database)
    original = repository.save(lead("Legacy"))
    from business_prospector.infrastructure.sqlite_repository import LEAD_COLUMNS
    columns = ", ".join(LEAD_COLUMNS)
    with sqlite3.connect(database) as connection:
        connection.execute(f"CREATE TABLE leads_v2 AS SELECT {columns} FROM leads")
        connection.execute("DROP TABLE leads")
        connection.execute("ALTER TABLE leads_v2 RENAME TO leads")
        connection.execute("PRAGMA user_version = 2")

    migrated = SQLiteLeadRepository(database).get(original.id or 0)
    assert migrated is not None
    assert migrated.name == "Legacy"
    assert migrated.website_assessment is None
    assert migrated.batch_id is None


def test_schema_v3_defaults_existing_leads_to_redesign(tmp_path: Path) -> None:
    database = tmp_path / "v3.db"
    repository = SQLiteLeadRepository(database)
    original = repository.save(lead("Existing redesign"))
    from business_prospector.infrastructure.sqlite_repository import LEAD_COLUMNS
    v3_columns = LEAD_COLUMNS + (
        "website_assessment_json", "assessment_status", "assessment_checked_at", "batch_id",
    )
    columns = ", ".join(v3_columns)
    with sqlite3.connect(database) as connection:
        connection.execute(f"CREATE TABLE leads_v3 AS SELECT {columns} FROM leads")
        connection.execute("DROP TABLE leads")
        connection.execute("ALTER TABLE leads_v3 RENAME TO leads")
        connection.execute("PRAGMA user_version = 3")

    migrated = SQLiteLeadRepository(database).get(original.id or 0)
    assert migrated is not None
    assert migrated.opportunity_type == "redesign"
    assert migrated.market_research is None


def test_schema_v4_adds_site_ready_without_mutating_existing_statuses(tmp_path: Path) -> None:
    from business_prospector.infrastructure.sqlite_repository import ALL_LEAD_COLUMNS, SCHEMA

    database = tmp_path / "v4.db"
    repository = SQLiteLeadRepository(database)
    original = repository.save(lead("Existing qualified"))
    columns = ", ".join(ALL_LEAD_COLUMNS)
    old_schema = SCHEMA.replace(",'site_ready'", "")
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE leads RENAME TO leads_current")
        connection.executescript(old_schema)
        connection.execute(
            f"INSERT INTO leads ({columns}) SELECT {columns} FROM leads_current"
        )
        connection.execute("DROP TABLE leads_current")
        connection.execute("PRAGMA user_version = 4")

    migrated = SQLiteLeadRepository(database)
    assert migrated.get(original.id or 0).status == "qualified"  # type: ignore[union-attr]
    updated = migrated.update(original.id or 0, {"status": "site_ready"})
    assert updated.status == "site_ready"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5


def test_legacy_competitor_research_rows_load_as_benchmarks_without_migration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-research.db"
    repository = SQLiteLeadRepository(database)
    stored = repository.save(lead("Legacy first website"))
    legacy = {
        "status": "complete",
        "competitors": [
            {"name": "A", "website_url": "https://a.example", "facts": ["fact a"], "features": ["cta"]},
            {"name": "B", "website_url": "https://b.example", "facts": ["fact b"], "features": ["cta"]},
        ],
        "common_features": [{"feature": "cta", "observed_in": 2, "total": 2}],
        "inferences": ["legacy inference"],
        "recommendations": ["legacy recommendation"],
        "confidence": "medium",
        "failure_reason": None,
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE leads SET opportunity_type = 'first_website', first_website_reason = 'no_website', "
            "market_research_json = ?, market_research_status = 'complete', market_research_checked_at = ? "
            "WHERE id = ?",
            (json.dumps(legacy), "2026-01-01T00:00:00+00:00", stored.id),
        )
    loaded = repository.get(stored.id or 0)
    assert loaded is not None
    assert loaded.market_research["benchmark_market"] is None  # type: ignore[index]
    assert [item["name"] for item in loaded.market_research["benchmarks"]] == ["A", "B"]  # type: ignore[index,union-attr]
