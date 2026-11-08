# Art-direction validation — November 7, 2026

Local development only, branch `openclaw-port`. No Mac Mini, operational data,
live stock/Places requests, publication, DNS changes or outreach.

## Verification

- Full test suite: **789 passed in 19.57 seconds** on Python 3.14.8 in an isolated uv environment.
  Thirty-one added regression cases cover
  planning/fallback, pixel payloads, rejection, byte changes, native MCP image
  handoff, client sampling/denial, benchmark provenance, context binding, schema
  restrictions, current-artifact checks under lock, bounded revision loops,
  transaction rollback and commercial-approval invalidation.
- Existing qualification, lifecycle, SQLite, cPanel and deployment tests remain in
  the full suite. Qualification thresholds did not change. Benchmark ranking now
  balances reputation with review volume; its stable-order expectation was updated.
- Wheel built/installed in a disposable environment: imports/resources pass;
  **41 MCP tools**, including 11 new design operations; SQLite schema remains **8**.
- Python syntax, embedded browser JavaScript and `git diff --check` checked.

## Browser matrix and visual evidence

`scripts/validate_art_direction.py` creates six synthetic businesses through the
normal benchmark, qualification, planning, curation and persisted-generation use
cases: two dental clinics, two restaurants and two salons. One clinic deliberately
has sparse content. Same-category variants exercise different typography, density,
section emphasis/order and hero composition. All fixture identities are distinct;
no deduplication or lifecycle protections are bypassed.

Actual Chromium captures at 1440×1000 and 390×844 pass the in-pipeline deterministic
checks. Additional browser validation at 1440, 390 and 320 pixels covers **18
site/viewport combinations**: no overflow, missing images, broken anchors, browser
errors, external requests or axe WCAG A/AA violations; mobile navigation works,
touch targets pass, reduced motion is honored and measured layout shift is zero.
This is Chromium evidence, not cross-browser or assistive-technology certification.

The development agent inspected actual local stock pixels and page screenshots:

- Dental tool still life `7800563` was rejected: sharp instruments, excessive empty
  space and awkward cropping conflict with a welcoming preventive-care direction.
  Matching category metadata did not override rejection. Both dental drafts omit it.
- Pasta `1279330` and salon craft `3993460` were accepted for explicitly illustrative
  use against their synthetic directions; attribution/disclosures remain visible.
- Restaurant variants render a full-width food hero versus a split image-led hero.
  Salon variants differ in hero composition, type, palette and section hierarchy.
  The sparse clinic retains factual typography without invented services/history.
- A real screenshot review rejected the second restaurant's hierarchy: the menu
  followed reputation, location and hours. The review also identified a vague CTA.
  The supported revision path moved the menu directly after the hero and changed
  the CTA to “Reservar mesa”, retaining the verified booking URL. Desktop/mobile
  screenshots were recaptured and visually inspected. The previous artifact was
  archived; its review becomes stale for the new checksum.
- The subsequent judgment records those two improvements, but leaves distinctive
  positioning and content strength **uncertain**. No commercial approval was granted.

Revision evidence:

- Before: `b7a098ccf11d49f23bcd9c8edc39aefe7d342fecd12458026c9761961f6b8de0`
- After: `3978faa017241726b40b7373217f8e2e24788f4726222fcd4785f8ac6af67c31`

Local run artifacts: `/tmp/business-prospector-art-direction-v1/`, including
`validation.json`, `visual-revision.json`, private receipts, before/after screenshots
and `final-accessibility`. These are development outputs, not shipped public assets.

## What this demonstrates—and what it does not

The automated loop is tested with injected visual evaluators, including failure,
no-progress and stale-review paths. The actual image/page review exercised the
client-handoff application path with development-agent visual judgments. The
reproducible matrix replays recorded photo observations bound to exact local bytes;
it does **not** claim to invoke a live model each time. MCP sampling transport is
covered by protocol tests; Oliver's installed runtime/model was not accessed or
verified. Live benchmark browsing was not performed; benchmark vision contracts
are tested with synthetic selections and captures.

The [reference file](design-reference-assessments.json) separates the user's
human-reviewed negative example from development-agent photo judgments. No new
positive human approvals are invented. The red-background customer photograph
was described by the user, not retrieved; the actual rejected local photo is the
blue dental-tool still life. Technical passes and differentiated compositions do
not establish that business owners will adopt the designs. Good source facts,
capable vision/creative judgment and human review remain necessary.

Reproduce in an isolated directory with the existing local demonstration photos:

```sh
PYTHONPATH=src python scripts/validate_art_direction.py \
  --output /new/isolated/design-validation \
  --stock-directory /explicit/local/photos
python scripts/validate_premium_sites.py \
  --sites /new/isolated/design-validation/sites \
  --output /new/isolated/design-validation/browser \
  --axe-script /explicit/local/axe.min.js
```

Optional dependencies: `.[visual]`, an available Chromium executable, and a local
axe-core script for the supplementary accessibility run. Omitting the photo directory
produces no-photo drafts; it does not demonstrate photo acceptance/rejection.
