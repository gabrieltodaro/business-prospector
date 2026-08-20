import pytest

from business_prospector.domain.exceptions import ValidationError
from business_prospector.domain.models import Lead, WebsiteAssessment


def test_rejects_non_http_website_url() -> None:
    with pytest.raises(ValidationError, match="website_url"):
        Lead(
            name="Teste", category="dentista", city="Catanduva", rating=4.8, review_count=50,
            website_url="javascript:alert(1)", assessment=WebsiteAssessment(layout=True, mobile=True),
        )


def test_inferred_phone_is_not_confirmed_whatsapp() -> None:
    lead = Lead(
        name="Teste", category="dentista", city="Catanduva", rating=4.8, review_count=50,
        website_url="https://example.com", assessment=WebsiteAssessment(layout=True, mobile=True),
        phone="17999991234", whatsapp_source="google_business_phone",
    )
    assert lead.whatsapp_confirmed is False
    assert lead.whatsapp is None

