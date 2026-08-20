from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from business_prospector.application.config import ProspectingConfig
from business_prospector.application.prospecting import ProspectingService
from business_prospector.infrastructure.fake_providers import FakeBusinessDiscoveryProvider, FakeWebsiteAssessmentProvider
from business_prospector.infrastructure.sqlite_repository import SQLiteLeadRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline fake prospecting pipeline")
    parser.add_argument("--niche", default="dentistas")
    parser.add_argument("--city", default="Catanduva")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "dentists.json"
    database = args.database or Path(tempfile.mkdtemp(prefix="business-prospector-")) / "prospector.db"
    service = ProspectingService(
        FakeBusinessDiscoveryProvider(fixture),
        FakeWebsiteAssessmentProvider(fixture),
        SQLiteLeadRepository(database),
        ProspectingConfig.from_path(root / "config" / "default.json"),
    )
    json.dump(service.prospect(args.niche, args.city).to_dict(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

