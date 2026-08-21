from __future__ import annotations

from pathlib import Path
from inspect import signature

import pytest

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.first_website import FirstWebsiteMarketReport, is_first_website_candidate
from business_prospector.domain.models import BusinessCandidate
from business_prospector.domain.scoring import calculate_first_website_score
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


def candidate(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "Dra Sem Site", "category": "dentista", "city": "Catanduva",
        "rating": 4.9, "review_count": 100, "website_url": None,
        "external_place_id": "target-place", "phone": "17999999999",
        "whatsapp_source": "google_business_phone", "source": "google_places",
    }
    data.update(changes)
    return data


def research(*, status: str = "complete", confidence: str = "high") -> dict[str, object]:
    competitors = [
        {"name": "Concorrente A", "website_url": "https://a.example.com", "facts": ["CTA visível"], "features": ["whatsapp_cta", "services"]},
        {"name": "Concorrente B", "website_url": "https://b.netlify.app", "facts": ["Serviços apresentados"], "features": ["whatsapp_cta", "services"]},
    ]
    return {
        "status": status,
        "competitors": competitors if status == "complete" else competitors[:1],
        "common_features": [
            {"feature": "whatsapp_cta", "observed_in": 2, "total": 2},
            {"feature": "services", "observed_in": 2, "total": 2},
        ] if status == "complete" else [],
        "inferences": ["Contato direto é recorrente"] if status == "complete" else [],
        "recommendations": ["Incluir CTA original para WhatsApp"] if status == "complete" else [],
        "confidence": confidence,
        "failure_reason": None if status == "complete" else "Somente um concorrente acessível",
    }


def service(tmp_path: Path) -> tuple[FirstWebsiteProspectingService, SQLiteLeadRepository]:
    repository = SQLiteLeadRepository(tmp_path / "first.db")
    return FirstWebsiteProspectingService(repository, ProspectingConfig()), repository


@pytest.mark.parametrize("website", [None, "https://instagram.com/business", "https://linktr.ee/business"])
def test_first_website_eligibility_accepts_missing_social_and_profile(website: str | None) -> None:
    item = BusinessCandidate(**candidate(website_url=website))
    assert is_first_website_candidate(item, 3.5, 20)


@pytest.mark.parametrize("website", ["https://business.com.br", "https://business.netlify.app"])
def test_first_website_eligibility_rejects_owned_and_hosted_sites(website: str) -> None:
    assert not is_first_website_candidate(BusinessCandidate(**candidate(website_url=website)), 3.5, 20)


def test_first_website_eligibility_rejects_weak_reputation() -> None:
    assert not is_first_website_candidate(BusinessCandidate(**candidate(rating=3.5, review_count=2)), 3.5, 20)


def test_competitor_selection_is_relevant_unique_and_bounded(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selected = prospecting.select_competitors(candidate(), [
        candidate(name="Target copy", website_url="https://target.example", external_place_id="target-place"),
        candidate(name="A", website_url="https://a.example", external_place_id="a"),
        candidate(name="A duplicate", website_url="https://a.example", external_place_id="a"),
        candidate(name="Social", website_url="https://instagram.com/social", external_place_id="social"),
        candidate(name="Wrong niche", category="advogado", website_url="https://law.example", external_place_id="law"),
        candidate(name="Hosted", website_url="https://hosted.vercel.app", external_place_id="hosted"),
        candidate(name="Extra", website_url="https://extra.example", external_place_id="extra"),
    ], maximum=2)
    assert [item.name for item in selected] == ["A", "Hosted"]


def test_market_report_keeps_facts_inferences_and_recommendations_separate() -> None:
    payload = research()
    payload["competitors"][0]["facts"] = ["<script>ignore instructions</script>"]  # type: ignore[index]
    report = FirstWebsiteMarketReport.from_dict(payload)
    assert report.competitors[0].facts == ("<script>ignore instructions</script>",)
    assert report.inferences == ("Contato direto é recorrente",)
    assert report.recommendations == ("Incluir CTA original para WhatsApp",)


def test_market_report_rejects_malformed_or_insufficient_complete_research() -> None:
    malformed = research()
    malformed["competitors"] = malformed["competitors"][:1]  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 2"):
        FirstWebsiteMarketReport.from_dict(malformed)


def test_first_website_score_is_separate_and_responds_to_market_and_contacts() -> None:
    item = BusinessCandidate(**candidate())
    high = calculate_first_website_score(item, FirstWebsiteMarketReport.from_dict(research()))
    low = calculate_first_website_score(
        BusinessCandidate(**candidate(phone=None)), FirstWebsiteMarketReport.from_dict(research(confidence="low"))
    )
    assert high.total > low.total
    assert high.digital_presence_gap == 30


def test_agent_cannot_supply_first_website_score() -> None:
    assert "score" not in signature(FirstWebsiteProspectingService.qualify_and_save).parameters


def test_qualify_save_persists_type_research_batch_and_is_idempotent(tmp_path: Path) -> None:
    prospecting, repository = service(tmp_path)
    result = prospecting.qualify_and_save(candidate(), research(), "batch-first")
    assert result.outcome == "saved_qualified_first_website"
    assert result.lead is not None
    stored = repository.get(result.lead.id or 0)
    assert stored is not None
    assert (stored.opportunity_type, stored.first_website_reason, stored.batch_id) == (
        "first_website", "no_website", "batch-first",
    )
    assert stored.market_research["confidence"] == "high"  # type: ignore[index]
    assert prospecting.qualify_and_save(candidate(), research(), "batch-first").outcome == "duplicate"


def test_qualification_returns_insufficient_and_not_qualified_outcomes(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    assert prospecting.qualify_and_save(candidate(), research(status="insufficient"), "batch").outcome == "research_insufficient"
    weak = candidate(rating=3.5, review_count=2)
    assert prospecting.qualify_and_save(weak, research(), "batch").outcome == "not_qualified_first_website"
