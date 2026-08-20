from business_prospector.domain.models import Lead, WebsiteAssessment
from business_prospector.domain.scoring import calculate_score


def make_lead(**changes: object) -> Lead:
    values = {
        "name": "Clinica Teste",
        "category": "dentista",
        "city": "Catanduva",
        "rating": 4.9,
        "review_count": 200,
        "website_url": "https://example.com",
        "assessment": WebsiteAssessment(True, True, True, True, False, False, "quatro problemas"),
        "whatsapp": "5517999991234",
        "whatsapp_confirmed": True,
        "whatsapp_source": "website_link",
    }
    values.update(changes)
    return Lead(**values)  # type: ignore[arg-type]


def test_score_is_deterministic_and_bounded() -> None:
    score = calculate_score(make_lead())
    assert score.total == 98
    assert score.business_quality == 38
    assert score.website_opportunity == 40
    assert score.contactability == 20


def test_contact_priority_changes_contactability_only() -> None:
    phone_only = make_lead(whatsapp=None, whatsapp_confirmed=False, phone="17999991234")
    email_only = make_lead(whatsapp=None, whatsapp_confirmed=False, phone=None, email="oi@example.com")
    assert calculate_score(phone_only).contactability == 15
    assert calculate_score(email_only).contactability == 11

