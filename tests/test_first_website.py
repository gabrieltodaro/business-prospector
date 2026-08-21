from __future__ import annotations

from pathlib import Path
from inspect import signature

import pytest

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.batch import BatchProspectingService
from business_prospector.application.first_website import FirstWebsiteProspectingService
from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.first_website import FirstWebsiteMarketReport, is_first_website_candidate
from business_prospector.domain.models import BusinessCandidate, Lead, WebsiteAssessment
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
    benchmarks = [
        {"name": "Benchmark A", "website_url": "https://a.example.com", "category": "dentista", "rating": 4.9, "review_count": 1000, "external_place_id": "benchmark-a", "facts": ["CTA visível"], "features": ["whatsapp_cta", "services"]},
        {"name": "Benchmark B", "website_url": "https://b.netlify.app", "category": "dentista", "rating": 4.8, "review_count": 800, "external_place_id": "benchmark-b", "facts": ["Serviços apresentados"], "features": ["whatsapp_cta", "services"]},
    ]
    return {
        "benchmark_market": "São Paulo, SP",
        "status": status,
        "benchmarks": benchmarks if status == "complete" else benchmarks[:1],
        "common_features": [
            {"feature": "whatsapp_cta", "observed_in": 2, "total": 2},
            {"feature": "services", "observed_in": 2, "total": 2},
        ] if status == "complete" else [],
        "inferences": ["Contato direto é recorrente"] if status == "complete" else [],
        "recommendations": ["Incluir CTA original para WhatsApp"] if status == "complete" else [],
        "confidence": confidence,
        "failure_reason": None if status == "complete" else "Somente um benchmark acessível",
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


def test_benchmark_selection_is_relevant_unique_and_bounded(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selection = prospecting.select_benchmarks(candidate(), [
        candidate(name="Target copy", website_url="https://target.example", external_place_id="target-place"),
        candidate(name="A", website_url="https://a.example", external_place_id="a"),
        candidate(name="A duplicate", website_url="https://a.example", external_place_id="a"),
        candidate(name="Social", website_url="https://instagram.com/social", external_place_id="social"),
        candidate(name="Wrong niche", category="advogado", website_url="https://law.example", external_place_id="law"),
        candidate(name="Hosted", website_url="https://hosted.vercel.app", external_place_id="hosted"),
        candidate(name="Extra", website_url="https://extra.example", external_place_id="extra"),
    ], maximum=2)
    assert [item.name for item in selection.selected] == ["A", "Extra"]
    assert selection.country == "BR"
    assert selection.benchmark_market == "São Paulo, SP"
    assert {item.reason for item in selection.rejected} == {
        "target_business", "duplicate", "social_only", "category_mismatch", "max_benchmarks_reached",
    }
    target_rejection = next(item for item in selection.rejected if item.reason == "target_business")
    duplicate_rejection = next(item for item in selection.rejected if item.reason == "duplicate")
    assert target_rejection.to_dict()["match"] == {
        "rule": "external_place_id", "strength": "exact", "matched_against": "target",
    }
    assert duplicate_rejection.to_dict()["match"] == {
        "rule": "external_place_id", "strength": "exact", "matched_against": "benchmark_pool",
    }


def test_distinct_place_ids_on_shared_instagram_host_are_not_identity_matches(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selection = prospecting.select_benchmarks(
        candidate(
            name="Dra. Gabrielhe Ferreira", external_place_id="place-target",
            website_url="https://instagram.com/gabrielhe",
        ),
        [
            candidate(name="Dra. Larissa Ferreira", external_place_id="place-larissa", website_url="https://instagram.com/larissa"),
            candidate(name="Dr. Mateus Shiya", external_place_id="place-mateus", website_url="https://instagram.com/mateus"),
            candidate(name="Dra. Carolina Oliveira", external_place_id="place-carolina", website_url="https://instagram.com/carolina"),
        ],
    )
    assert [item.reason for item in selection.rejected] == ["social_only"] * 3
    assert all(item.match is None for item in selection.rejected)


def test_pool_fallback_duplicate_reports_rule_when_place_ids_are_missing(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selection = prospecting.select_benchmarks(candidate(), [
        candidate(name="First", external_place_id=None, phone=None, website_url="https://clinic.example/one"),
        candidate(name="Second", external_place_id=None, phone=None, website_url="https://clinic.example/two"),
    ])
    assert [item.name for item in selection.selected] == ["First"]
    assert selection.rejected[0].to_dict()["match"] == {
        "rule": "normalized_domain", "strength": "strong", "matched_against": "benchmark_pool",
    }


def test_target_fallback_is_allowed_when_place_id_is_missing(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selection = prospecting.select_benchmarks(
        candidate(external_place_id=None, phone="17999999999"),
        [candidate(name="Target fallback", external_place_id="candidate-id", phone="5517999999999",
                   website_url="https://candidate.example")],
    )
    assert selection.selected == ()
    assert selection.rejected[0].to_dict()["match"] == {
        "rule": "normalized_phone", "strength": "strong", "matched_against": "target",
    }


def test_benchmark_selection_reports_every_rejection_and_summary(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    raw = [
        candidate(name="Target", category="dentist", website_url="https://target.example", external_place_id="target-place"),
        candidate(name="Selected", category="dental_clinic", website_url="https://selected.example", external_place_id="selected"),
        candidate(name="Z Duplicate", category="dental_clinic", website_url="https://duplicate.example", external_place_id="selected"),
        candidate(name="Wrong category", category="lawyer", website_url="https://law.example", external_place_id="law"),
        candidate(name="Weak", category="dentist", website_url="https://weak.example", rating=4.4, external_place_id="weak"),
        candidate(name="No website", category="dentist", website_url=None, external_place_id="none"),
        candidate(name="Social", category="dentist", website_url="https://instagram.com/social", external_place_id="social"),
        candidate(name="Profile", category="dentist", website_url="https://linktr.ee/profile", external_place_id="profile"),
        candidate(name="Bad URL", category="dentist", website_url="ftp://invalid.example", external_place_id="bad-url"),
        {"name": "Incomplete"},
        candidate(name="Beyond maximum", website_url="https://extra.example", external_place_id="extra"),
    ]
    selection = prospecting.select_benchmarks(
        candidate(category="dentist"), raw, maximum=1,
    )

    assert [item.name for item in selection.selected] == ["Selected"]
    assert {item.reason for item in selection.rejected} == {
        "target_business", "duplicate", "category_mismatch", "reputation_below_threshold",
        "no_website", "social_only", "third_party_profile", "invalid_url", "invalid_candidate",
    }
    payload = selection.to_dict()
    assert payload["summary"] == {
        "raw": 11, "evaluated": 10, "selected": 1, "rejected": 9,
        "minimum_required": 2, "research_status": "research_insufficient",
        "reasons": {
            "category_mismatch": 1, "duplicate": 1, "invalid_candidate": 1, "invalid_url": 1,
            "no_website": 1, "reputation_below_threshold": 1, "social_only": 1,
            "target_business": 1, "third_party_profile": 1,
        },
    }
    assert len(selection.selected) + len(selection.rejected) == payload["summary"]["evaluated"]


def test_benchmark_selection_accepts_owned_hosted_and_related_official_category(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selection = prospecting.select_benchmarks(candidate(category="dentist"), [
        candidate(name="Clinic", category="dental_clinic", website_url="https://clinic.example", external_place_id="clinic"),
        candidate(name="Hosted", category="dentist", website_url="https://clinic.vercel.app", external_place_id="hosted"),
    ])
    assert [item.name for item in selection.selected] == ["Clinic", "Hosted"]
    assert selection.rejected == ()


def test_benchmark_selection_reports_maximum_in_deterministic_order(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selection = prospecting.select_benchmarks(candidate(), [
        candidate(name="First", website_url="https://first.example", external_place_id="first"),
        candidate(name="Second", website_url="https://second.example", external_place_id="second"),
        candidate(name="Third", website_url="https://third.example", external_place_id="third"),
    ], maximum=2)
    assert [item.name for item in selection.selected] == ["First", "Second"]
    assert [(item.candidate["name"], item.reason) for item in selection.rejected] == [
        ("Third", "max_benchmarks_reached"),
    ]


def test_benchmark_selection_is_independent_of_google_order_and_has_stable_ties(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    pool = [
        candidate(name="Zulu", rating=4.9, review_count=500, website_url="https://zulu.example", external_place_id="z"),
        candidate(name="Alpha", rating=4.9, review_count=500, website_url="https://alpha.example", external_place_id="a"),
        candidate(name="Reviews", rating=4.9, review_count=900, website_url="https://reviews.example", external_place_id="reviews"),
        candidate(name="Rating", rating=5.0, review_count=100, website_url="https://rating.example", external_place_id="rating"),
    ]
    forward = prospecting.select_benchmarks(candidate(), pool, maximum=3)
    reverse = prospecting.select_benchmarks(candidate(), list(reversed(pool)), maximum=3)
    expected = ["Rating", "Reviews", "Alpha"]
    assert [item.name for item in forward.selected] == expected
    assert [item.name for item in reverse.selected] == expected


def test_benchmark_policy_is_separate_from_lead_qualification(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    selection = prospecting.select_benchmarks(candidate(), [
        candidate(name="Rating low", rating=4.4, review_count=1000, website_url="https://rating-low.example", external_place_id="r1"),
        candidate(name="Reviews low", rating=5.0, review_count=99, website_url="https://reviews-low.example", external_place_id="r2"),
        candidate(name="Strong", rating=4.9, review_count=1000, website_url="https://strong.example", external_place_id="r3"),
    ], maximum=3)
    assert [item.name for item in selection.selected] == ["Strong"]
    assert [item.reason for item in selection.rejected].count("reputation_below_threshold") == 2
    assert selection.to_dict()["summary"]["research_status"] == "research_insufficient"


def test_market_report_keeps_facts_inferences_and_recommendations_separate() -> None:
    payload = research()
    payload["benchmarks"][0]["facts"] = ["<script>ignore instructions</script>"]  # type: ignore[index]
    report = FirstWebsiteMarketReport.from_dict(payload)
    assert report.benchmarks[0].facts == ("<script>ignore instructions</script>",)
    assert report.inferences == ("Contato direto é recorrente",)
    assert report.recommendations == ("Incluir CTA original para WhatsApp",)


def test_market_report_rejects_malformed_or_insufficient_complete_research() -> None:
    malformed = research()
    malformed["benchmarks"] = malformed["benchmarks"][:1]  # type: ignore[index]
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
    assert stored.city == "Catanduva"
    assert stored.market_research["benchmark_market"] == "São Paulo, SP"  # type: ignore[index]
    assert len(stored.market_research["benchmarks"]) == 2  # type: ignore[arg-type,index]
    assert prospecting.qualify_and_save(candidate(), research(), "batch-first").outcome == "duplicate"


def test_distinct_place_ids_with_laura_slug_return_conflict_without_mutation(tmp_path: Path) -> None:
    prospecting, repository = service(tmp_path)
    name = (
        "Dra. Laura Baesso Dentista em Catanduva - Clareamento Dental, "
        "Estética e Harmonização Facial"
    )
    old = Lead(
        name=name, category="dentist", city="Catanduva/SP", rating=4.9, review_count=200,
        website_url="", external_place_id="ChIJ1aw4jgEfvJQRwE_Iw9pSqGg",
        assessment=WebsiteAssessment(reason="legacy first website lead"), batch_id="batch-old",
    )
    old = repository.save(old)
    raw = candidate(
        name=name, category="dentist", city="Catanduva/SP", website_url=None,
        external_place_id="ChIJ1aw4jgEfvJQRe9n-75bAEHo",
    )

    assert repository.find_duplicate(BusinessCandidate(**raw)) is None
    market_research = research()
    for benchmark in market_research["benchmarks"]:  # type: ignore[union-attr]
        benchmark["category"] = "dentist"
    outcome = prospecting.qualify_and_save(raw, market_research, "batch-new")

    assert outcome.outcome == "identity_conflict"
    assert outcome.to_dict()["conflict"] == {
        "type": "technical_identifier_conflict",
        "field": "slug",
        "value": (
            "dra-laura-baesso-dentista-em-catanduva-clareamento-dental-estetica-e-"
            "harmonizacao-facial-catanduva-sp"
        ),
        "existing_lead_id": old.id,
    }
    assert len(repository.list()) == 1
    unchanged = repository.get(old.id or 0)
    assert unchanged is not None
    assert unchanged.external_place_id == "ChIJ1aw4jgEfvJQRwE_Iw9pSqGg"
    assert unchanged.batch_id == "batch-old"


def test_real_laura_same_place_id_is_duplicate_through_full_batch_path(tmp_path: Path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "laura-operational-shape.db")
    batch = BatchProspectingService(repository, ProspectingConfig())
    prospecting = FirstWebsiteProspectingService(repository, ProspectingConfig())
    name = (
        "Dra. Laura Baesso Dentista em Catanduva - Clareamento Dental, "
        "Estética e Harmonização Facial"
    )
    place_id = "ChIJ1aw4jgEfvJQRe9n-75bAEHo"
    existing = repository.save(Lead(
        name=name, category="dentist", city="Catanduva, SP", rating=4.9, review_count=200,
        website_url="", external_place_id=place_id,
        assessment=WebsiteAssessment(reason="first website"), batch_id="batch-b565b332",
        opportunity_type="first_website", first_website_reason="no_website",
        status="qualified", score=82,
    ))
    incoming = candidate(
        name=name, category="dentist", city="Catanduva, SP", website_url=None,
        external_place_id=place_id,
    )

    prepared = batch.prepare(
        [incoming], batch_id="batch-36138a87", mode="first_website",
        target_qualified_leads=1, max_candidates=1,
    )
    assert prepared.first_website_candidates == []
    assert prepared.persistence_conflicts == []
    assert len(prepared.duplicates) == 1
    assert prepared.duplicates[0]["lead_id"] == existing.id
    assert prepared.duplicates[0]["match"] == {
        "rule": "external_place_id", "strength": "exact", "matched_against": "existing_lead",
    }

    # Defense in depth when orchestration bypasses preparation.
    market_research = research()
    for benchmark in market_research["benchmarks"]:  # type: ignore[union-attr]
        benchmark["category"] = "dentist"
    outcome = prospecting.qualify_and_save(incoming, market_research, "batch-36138a87")
    assert outcome.outcome == "duplicate"
    assert outcome.conflict is None
    assert outcome.to_dict()["match"] == {
        "rule": "external_place_id", "strength": "exact", "matched_against": "existing_lead",
    }
    assert len(repository.list()) == 1


def test_same_place_id_is_global_across_slug_and_opportunity_type(tmp_path: Path) -> None:
    repository = SQLiteLeadRepository(tmp_path / "global-identity.db")
    existing = Lead(
        name="Existing redesign", category="dentista", city="Catanduva", rating=4.9,
        review_count=100, website_url="https://existing.example",
        external_place_id="global-place", assessment=WebsiteAssessment(layout=True),
        opportunity_type="redesign",
    )
    existing = repository.save(existing)
    incoming = BusinessCandidate(
        name="Completely different slug", category="dentista", city="Other City", rating=5,
        review_count=500, website_url=None, external_place_id="global-place",
    )
    match = repository.find_duplicate(incoming)
    assert match is not None
    assert (match.lead_id, match.match_type, match.confidence) == (
        existing.id, "external_place_id", "exact",
    )


def test_qualification_returns_insufficient_and_not_qualified_outcomes(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    assert prospecting.qualify_and_save(candidate(), research(status="insufficient"), "batch").outcome == "research_insufficient"
    weak = candidate(rating=3.5, review_count=2)
    assert prospecting.qualify_and_save(weak, research(), "batch").outcome == "not_qualified_first_website"


def test_qualification_revalidates_benchmark_market_policy(tmp_path: Path) -> None:
    prospecting, _ = service(tmp_path)
    wrong_market = research()
    wrong_market["benchmark_market"] = "Rio de Janeiro, RJ"
    assert prospecting.qualify_and_save(candidate(), wrong_market, "batch").reason == (
        "benchmark_market does not match configured market"
    )
    weak_benchmark = research()
    weak_benchmark["benchmarks"][0]["review_count"] = 99  # type: ignore[index]
    assert prospecting.qualify_and_save(candidate(), weak_benchmark, "batch").reason == (
        "benchmark reviews below configured threshold"
    )
