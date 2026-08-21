from __future__ import annotations

import argparse
import json

from business_prospector.application.ports import SearchQuery
from business_prospector.domain.exceptions import ProspectorError
from business_prospector.infrastructure.google_places import GooglePlacesBusinessDiscoveryProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded Places API (New) discovery request.")
    parser.add_argument("--niche", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--limit", type=int, default=1, choices=range(1, 6), metavar="1-5")
    args = parser.parse_args()
    try:
        candidates = GooglePlacesBusinessDiscoveryProvider().search(
            SearchQuery(args.niche, args.city, args.limit)
        )
    except ProspectorError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "candidates": [item.to_dict() for item in candidates]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
