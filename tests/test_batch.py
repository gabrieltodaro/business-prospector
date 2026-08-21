from __future__ import annotations

from pathlib import Path

from business_prospector.application.batch import BatchProspectingService
from business_prospector.application.config import ProspectingConfig
from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment
from business_prospector.dashboard import DashboardApplication
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


def candidate(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Clinica Real",
        "category": "dentista",
        "city": "Catanduva",
        "rating": 4.9,
        "review_count": 120,
        "website_url": "https://example.com",
        "external_place_id": "place-real",
        "phone": "1712345678",
        "whatsapp_source": "google_business_phone",
        "source": "google_places",
    }
    payload.update(changes)
    return payload


def report(*, issues: int = 2, status: str = "assessed", unknown: bool = False) -> dict[str, object]:
    names = ["mobile", "cta", "content", "social_proof", "layout", "platform", "broken_elements"]
    criteria = {}
    for index, name in enumerate(names):
        outcome = "unknown" if unknown and name == "mobile" else ("issue" if index < issues else "no_issue")
        criteria[name] = {
            "outcome": outcome,
            "facts": [] if outcome == "unknown" else [f"Observed {name}"],
            "inference": f"Opportunity in {name}" if outcome == "issue" else None,
        }
    return {
        "website_url": "https://example.com",
        "status": status,
        "failure_reason": None if status == "assessed" else "controlled browser failure",
        "criteria": criteria,
    }


def service(tmp_path: Path) -> tuple[BatchProspectingService, SQLiteLeadRepository]:
    repository = SQLiteLeadRepository(tmp_path / "batch.db")
    return BatchProspectingService(repository, ProspectingConfig()), repository


def existing_lead(raw: dict[str, object]) -> Lead:
    return Lead(
        name=str(raw["name"]), category=str(raw["category"]), city=str(raw["city"]),
        rating=float(raw["rating"]), review_count=int(raw["review_count"]),
        website_url=str(raw["website_url"]), external_place_id=raw.get("external_place_id"),
        phone=raw.get("phone"), assessment=WebsiteAssessment(layout=True, mobile=True),
    )


def test_prepare_classifies_reputation_websites_deferred_and_invalid(tmp_path: Path) -> None:
    batch, _ = service(tmp_path)
    result = batch.prepare([
        candidate(),
        candidate(name="Low reviews", external_place_id="low", review_count=2),
        candidate(name="Deferred", external_place_id="none", website_url=None, rating=3.5, review_count=0),
        candidate(name="Too low", external_place_id="too-low", website_url=None, rating=3.4),
        {"name": "missing required fields"},
    ], target_qualified_leads=2, max_candidates=5)
    assert [item.name for item in result.website_candidates] == ["Clinica Real"]
    assert [(item.candidate.name, item.reason) for item in result.deferred_first_website] == [
        ("Deferred", "no_website")
    ]
    assert {item.name for item in result.rejected_reputation} == {"Low reviews", "Too low"}
    assert len(result.invalid) == 1
    assert result.target_qualified_leads == 2


def test_prepare_defers_social_and_profile_urls_but_keeps_hosted_sites(tmp_path: Path) -> None:
    batch, _ = service(tmp_path)
    result = batch.prepare([
        candidate(name="Instagram", external_place_id="ig", website_url="https://www.instagram.com/business/?igsh=x"),
        candidate(name="Linktree", external_place_id="linktree", website_url="https://linktr.ee/business"),
        candidate(name="Hosted", external_place_id="hosted", website_url="https://business.netlify.app"),
    ])
    assert [item.candidate.name for item in result.deferred_first_website] == ["Instagram", "Linktree"]
    assert [item.reason for item in result.deferred_first_website] == ["social_only", "third_party_profile"]
    assert [item.name for item in result.website_candidates] == ["Hosted"]


def test_social_only_candidate_never_enters_website_assessment_work(tmp_path: Path) -> None:
    batch, _ = service(tmp_path)
    result = batch.prepare([
        candidate(website_url="https://instagram.com/business", rating=5.0, review_count=196)
    ])
    assert result.website_candidates == []
    assert result.deferred_first_website[0].reason == "social_only"


def test_prepare_detects_place_id_and_fallback_duplicates(tmp_path: Path) -> None:
    batch, repository = service(tmp_path)
    repository.save(existing_lead(candidate()))
    result = batch.prepare([
        candidate(name="Other", website_url="https://other.example", external_place_id="place-real"),
        candidate(name="Domain duplicate", external_place_id="other-place"),
    ])
    assert [item["match_type"] for item in result.duplicates] == ["external_place_id", "normalized_domain"]
    assert result.website_candidates == []


def test_qualify_save_persists_score_batch_and_structured_evidence(tmp_path: Path) -> None:
    batch, repository = service(tmp_path)
    outcome = batch.qualify_and_save(candidate(), report(), "batch-controlled")
    assert outcome.outcome == "saved_qualified"
    assert outcome.lead is not None
    assert outcome.lead.score == 66
    stored = repository.get(outcome.lead.id or 0)
    assert stored is not None
    assert stored.batch_id == "batch-controlled"
    assert stored.assessment_status == "assessed"
    assert stored.assessment_checked_at is not None
    assert stored.website_assessment["criteria"]["mobile"]["facts"] == ["Observed mobile"]  # type: ignore[index]
    api_payload = DashboardApplication(repository).get_lead(stored.id or 0).to_dict()
    assert api_payload["website_assessment"]["criteria"]["cta"]["outcome"] == "issue"  # type: ignore[index]


def test_qualification_outcomes_are_explicit(tmp_path: Path) -> None:
    batch, _ = service(tmp_path)
    assert batch.qualify_and_save(candidate(), report(issues=1), "batch").outcome == "not_qualified_website"
    assert batch.qualify_and_save(candidate(), report(unknown=True), "batch").outcome == "assessment_insufficient"
    assert batch.qualify_and_save(candidate(), report(status="timeout"), "batch").outcome == "assessment_failed"
    assert batch.qualify_and_save(candidate(website_url=None), report(), "batch").outcome == "deferred_first_website"
    social = batch.qualify_and_save(
        candidate(website_url="https://instagram.com/business"), report(), "batch"
    )
    assert (social.outcome, social.reason) == ("deferred_first_website", "social_only")


def test_duplicate_recheck_makes_save_idempotent(tmp_path: Path) -> None:
    batch, _ = service(tmp_path)
    assert batch.qualify_and_save(candidate(), report(), "batch").outcome == "saved_qualified"
    assert batch.qualify_and_save(candidate(), report(), "batch").outcome == "duplicate"


def test_public_contacts_affect_score_without_confirming_inferred_whatsapp(tmp_path: Path) -> None:
    batch, _ = service(tmp_path)
    phone = batch.qualify_and_save(candidate(), report(), "batch-phone")
    assert phone.lead is not None and phone.lead.score == 66

    confirmed_candidate = candidate(name="Confirmed", external_place_id="confirmed", website_url="https://confirmed.example")
    confirmed_report = report()
    confirmed_report["website_url"] = "https://confirmed.example"
    confirmed = batch.qualify_and_save(
        confirmed_candidate, confirmed_report, "batch-confirmed",
        {"whatsapp": "5517999999999", "whatsapp_confirmed": True, "whatsapp_source": "website_link"},
    )
    assert confirmed.lead is not None and confirmed.lead.score == 71
    assert phone.lead.whatsapp_confirmed is False


def test_untrusted_evidence_round_trips_as_inert_text(tmp_path: Path) -> None:
    batch, repository = service(tmp_path)
    malicious = report()
    malicious["criteria"]["mobile"]["facts"] = ["<script>alert(1)</script>"]  # type: ignore[index]
    outcome = batch.qualify_and_save(candidate(), malicious, "batch-xss")
    stored = repository.get(outcome.lead.id or 0)  # type: ignore[union-attr]
    assert stored.website_assessment["criteria"]["mobile"]["facts"] == ["<script>alert(1)</script>"]  # type: ignore[index,union-attr]


def test_invalid_batch_and_contact_evidence_are_not_saved(tmp_path: Path) -> None:
    batch, repository = service(tmp_path)
    assert batch.qualify_and_save(candidate(), report(), "").outcome == "invalid"
    outcome = batch.qualify_and_save(
        candidate(), report(), "batch",
        {"whatsapp": "5517999999999", "whatsapp_confirmed": True, "whatsapp_source": "google_business_phone"},
    )
    assert outcome.outcome == "invalid"
    assert repository.list() == []
