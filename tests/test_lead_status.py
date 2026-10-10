from __future__ import annotations

import pytest

from business_prospector.application.lead_status import LeadStatusService, can_transition
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import Lead, WebsiteAssessment
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


def stored_lead(repository: SQLiteLeadRepository, status: str) -> Lead:
    return repository.save(Lead(
        name=f"Lead {status}", slug=f"lead-{status.replace('_', '-')}",
        category="dentist", city="Catanduva, SP", rating=4.9, review_count=20,
        website_url="https://example.test",
        assessment=WebsiteAssessment(reason="fixture"), status=status,
    ))


@pytest.mark.parametrize(("source", "target"), [
    ("new", "qualified"),
    ("new", "needs_review"),
    ("needs_review", "qualified"),
    ("qualified", "internal_website"),
    ("sales_preview", "contacted"),
    ("contacted", "proposal"),
    ("proposal", "closed"),
    ("qualified", "discarded"),
    ("discarded", "needs_review"),
])
def test_explicit_pipeline_graph_allows_normal_review_and_discard_paths(
    source: str, target: str,
) -> None:
    assert can_transition(source, target)


@pytest.mark.parametrize(("source", "target"), [
    ("qualified", "contacted"),
    ("qualified", "proposal"),
    ("qualified", "closed"),
    ("internal_website", "contacted"),
    ("new", "closed"),
    ("closed", "proposal"),
    ("proposal", "qualified"),
    ("contacted", "internal_website"),
])
def test_explicit_pipeline_graph_blocks_skips_and_arbitrary_regressions(
    source: str, target: str,
) -> None:
    assert not can_transition(source, target)


def test_generic_status_service_cannot_reach_sales_preview(tmp_path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    lead = stored_lead(repository, "internal_website")
    with pytest.raises(ValidationError, match="explicit approval"):
        LeadStatusService(repository).change(lead.id or 0, "sales_preview")
    assert repository.get(lead.id or 0).status == "internal_website"  # type: ignore[union-attr]


def test_service_blocks_invalid_transition_without_mutation(tmp_path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "leads.db")
    lead = stored_lead(repository, "qualified")
    with pytest.raises(ValidationError, match="qualified -> contacted"):
        LeadStatusService(repository).change(lead.id or 0, "contacted")
    assert repository.get(lead.id or 0).status == "qualified"  # type: ignore[union-attr]
