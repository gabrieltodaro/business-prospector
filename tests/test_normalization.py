import pytest

from business_prospector.domain.normalization import normalize_domain, normalize_phone, slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Example.COM/path?q=1", "example.com"),
        ("example.com/contato", "example.com"),
        (None, None),
    ],
)
def test_normalize_domain(raw: str | None, expected: str | None) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(17) 99999-1234", "5517999991234"),
        ("+55 17 3522-1000", "551735221000"),
        ("", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


def test_slugify_removes_accents_and_punctuation() -> None:
    assert slugify("Clínica São José — Catanduva/SP") == "clinica-sao-jose-catanduva-sp"

