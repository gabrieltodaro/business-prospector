from pathlib import Path

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.prospecting import ProspectingService
from business_prospector.infrastructure.fake_providers import FakeBusinessDiscoveryProvider, FakeWebsiteAssessmentProvider
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "dentists.json"


def service(tmp_path: Path) -> ProspectingService:
    return ProspectingService(
        FakeBusinessDiscoveryProvider(FIXTURE),
        FakeWebsiteAssessmentProvider(FIXTURE),
        SQLiteLeadRepository(tmp_path / "prospector.db"),
        ProspectingConfig.from_path(ROOT / "config" / "default.json"),
    )


def test_fake_prospecting_end_to_end(tmp_path: Path) -> None:
    result = service(tmp_path).prospect("dentistas", "Catanduva")
    assert result.inspected == 6
    assert result.rejected_reputation == 2
    assert result.rejected_no_website == 1
    assert result.rejected_website == 1
    assert result.duplicates == 0
    assert [(item.name, item.score) for item in result.leads] == [
        ("Odonto Catanduva Prime", 98),
        ("Odonto Familia Catanduva", 85),
    ]


def test_second_run_detects_duplicates(tmp_path: Path) -> None:
    prospecting = service(tmp_path)
    assert len(prospecting.prospect("dentistas", "Catanduva").leads) == 2
    second = prospecting.prospect("dentistas", "Catanduva")
    assert second.duplicates == 2
    assert second.leads == []
