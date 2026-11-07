# Premium engine validation — November 7, 2026

Implementation and verification stayed on the local development machine,
`openclaw-port`. No Mac Mini, production database, paid Places requests, live
HostGator deployment, email or DNS changes were involved.

## Automated verification

- Complete suite: **689 passed in 18.91 seconds** (54 additional cases over 635).
- Python 3.14.8, isolated uv environment: `pytest>=8,<10`, `mcp>=1.2,<2`.
- New regression coverage: all five deterministic hero modes; same-business research
  variation; portrait crop guard; long/hostile listing names; absent-fact omission;
  typography-only inventory and snapshots; three synthetic demos; provider-neutral
  stock search; cuisine/relevance/orientation filters; caching/expiry/cooldown;
  malformed responses and HTTP redaction; fixed-origin downloads/no redirects;
  explicit review and lead-bound receipts; expiry, path and image-signature rejection;
  inventory rollback; local library/generation integration; commercial approval
  invalidation; stock provenance tampering; MCP discovery/fallback; scoped launcher
  credential recovery without logging values.
- Existing lifecycle, refresh, benchmark, asset integrity, approval receipts,
  deployment authorization, cPanel containment and deployment verification tests pass.
- Syntax: 92 Python sources/tests/validation script; launcher `sh -n`; `git diff --check`.
- Built and installed the wheel in a disposable directory. Installed imports,
  packaged resources and MCP discovery pass: **30 tools**, SQLite **v8**.

Full test command:

```sh
uv run --no-project --python /opt/homebrew/bin/python3.14 \
  --with 'pytest>=8,<10' --with 'mcp>=1.2,<2' python -m pytest --tb=short
```

## Browser and visual evidence

Generated clinic, restaurant and salon examples from synthetic qualified records
using the normal selection/review/asset/generation operations. Public Pexels photos
were downloaded individually for this local visual exercise. API transport tests
use injected responses, not an authenticated live Pexels account.

The clinic uses an editorial split and conceptual instruments; the restaurant uses
full-width cuisine photography and a two-column menu; the salon uses asymmetric
portrait imagery and editorial service typography. Manual screenshot review led to
shorter supporting copy, a cleaner clinic photograph and reduced name repetition.
All examples retain independent Gapps.Tech/synthetic-business disclosures, explicit
stock credits/disclosures and `noindex,nofollow,noarchive`.

Chromium rendered each example at **1440×1000, 390×844 and 320×760** (nine cases):

- Zero horizontal overflow, broken images, broken fragment links or page errors.
- Main navigation, menu and CTA targets meet the tested 44px height check.
- All mobile hero CTAs are visible within the first viewport (bottom at most 517px).
- Mobile menu opens; reduced-motion disables entrance animation.
- **Zero axe-core 4.10.3 violations** under WCAG 2 A/AA and 2.1 AA rule tags.
- No external browser requests. Resource transfers range from **173,903 to 395,678
  bytes**; measured layout-shift score is **0** in these local test loads.
- Desktop/mobile full-page and hero screenshots captured and manually inspected.

[Local screenshot gallery and machine-readable browser results](/Users/gabrieltodaro/.codex/visualizations/2026/11/07/01a1b456-a73a-7aa3-a228-5c196e3b8332/premium-generation/index.html)

Browser automation is reproducible with `scripts/validate_premium_sites.py` and the
[demo instructions](premium-generation.md#reproducible-visual-validation). These are
local Chromium measurements, not production speed benchmarks or a complete manual
accessibility certification. Safari/Firefox, authenticated provider availability and
real hosting remain untested. The implementation requires no schema migration.
