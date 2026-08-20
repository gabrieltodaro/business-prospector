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

