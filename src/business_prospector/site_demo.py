from __future__ import annotations

import argparse
import json
from pathlib import Path

from business_prospector.application.site_generation import SiteGenerationService
from business_prospector.package_resources import site_demo_fixture_resource


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an offline first-website fixture draft")
    parser.add_argument("--sites-root", type=Path, default=Path.cwd() / "sites")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    payload = json.loads(site_demo_fixture_resource().read_text(encoding="utf-8"))
    result = SiteGenerationService(args.sites_root).generate(
        payload["lead"], payload["research"], overwrite=args.overwrite,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
