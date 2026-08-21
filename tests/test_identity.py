from business_prospector.domain.identity import match_business_identity
from business_prospector.domain.models import BusinessCandidate


def business(**changes: object) -> BusinessCandidate:
    data: dict[str, object] = {
        "name": "Clínica", "category": "dentist", "city": "Catanduva",
        "rating": 4.9, "review_count": 100,
    }
    data.update(changes)
    return BusinessCandidate(**data)  # type: ignore[arg-type]


def test_distinct_place_ids_cannot_be_overridden_by_any_fallback() -> None:
    left = business(
        external_place_id="A", website_url="https://same.example/path",
        phone="17999999999", address="Rua Um, 10",
    )
    right = business(
        external_place_id="B", website_url="https://same.example/other",
        phone="17999999999", address="Rua Um, 10",
    )
    assert match_business_identity(left, right) is None


def test_same_place_id_is_authoritative() -> None:
    match = match_business_identity(
        business(name="One", external_place_id="A"),
        business(name="Other", city="Other", external_place_id="A"),
    )
    assert match is not None
    assert (match.rule, match.strength) == ("external_place_id", "exact")


def test_fallbacks_are_allowed_when_stable_id_is_missing() -> None:
    cases = [
        (
            business(name="One", website_url="https://company.example/a", external_place_id="A"),
            business(name="Other", website_url="https://company.example/b"),
            "normalized_domain",
        ),
        (business(name="One", phone="17999999999"), business(name="Other", phone="5517999999999"), "normalized_phone"),
        (business(name="One", address="Rua Brasil, 10"), business(name="Other", address="RUA BRASIL, 10"), "normalized_address"),
        (business(name="Clínica São José"), business(name="Clinica Sao Jose"), "normalized_name_city"),
    ]
    assert [match_business_identity(left, right).rule for left, right, _ in cases] == [  # type: ignore[union-attr]
        expected for _, _, expected in cases
    ]


def test_shared_profile_hosts_are_not_business_identity() -> None:
    assert match_business_identity(
        business(name="Larissa", website_url="https://instagram.com/larissa"),
        business(name="Mateus", website_url="https://instagram.com/mateus"),
    ) is None
