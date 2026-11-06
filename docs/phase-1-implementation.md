# Phase 1 implementation report

Completed November 6, 2026, on `fix/business-prospector-phase-1`, based on
`696c7b536437ca1120dcb78c22f1bbfe96f61787`. Changes are prepared locally for review;
there was no commit, remote push, merge or deployment.

## Implementation summary

All seven requested corrections are implemented and verified offline.

| Task | Root cause | Implemented correction | Regression evidence | Status |
|---|---|---|---|---|
| 1. MCP lifecycle | `SiteDraftService` was referenced without import. | Import restored; readiness, approval, internal transition and deployment construction exercised with synthetic storage and providers. | Registered MCP dispatch, readiness results, approval acknowledgment, missing/present artifact and explicit publication authorization. | Complete |
| 2. Unified status lifecycle | MCP wrote status directly and performed separate field/score writes. | MCP delegates complete proposed edits to `LeadUpdateService`; both adapters use `LeadStatusService` and its existing graph. Validation and scoring precede a single repository write. | Invalid skips and compound edits leave rows unchanged; valid dashboard/MCP transitions and legacy source statuses agree. | Complete |
| 3. Qualification | Batch qualification skipped reputation; direct save trusted flags; generic edits could invalidate qualified records. The older provider workflow also accepted flag-only assessments. | Shared qualification checks enforce current policy, presence, matching structured evidence and issue counts. Candidate validation is reused for persisted lead field types. Provider prospecting now requires structured reports. | Rating 1.0/one review, booleans/fractional review counts, social URLs, unknown/missing evidence, wrong URLs and unsupported direct saves fail; valid cases succeed. | Complete |
| 4. Benchmark research | Distinct Place IDs could count the same website twice; observations/counts and report provenance were insufficiently checked. | Distinct normalized domains and IDs, nonempty observations, supported counts, deterministic aggregation, persisted selection receipts and target/reference matching. Generation requires the persisted lead's report. Two-to-three-reference policy retained. | Duplicate sites/IDs, empty facts/features, invented counts, changed target/reference, missing receipt and substituted generation research fail. Valid receipts persist and survive reopening. | Complete |
| 5. Runtime location | Dashboard ignored `BUSINESS_PROSPECTOR_DATA_DIR`. | Shared runtime path/config resolution; explicit dashboard `--database` still wins. | Temporary shared data-root check, actual CLI override and shared custom qualification policy. | Complete |
| 6. Approved revision | Approval metadata did not identify exact public bytes. | Versioned approval identity records file set, SHA-256 per file, byte sizes and aggregate checksum. Publication rechecks identity/readiness and passes an isolated snapshot. Explicit reapproval is available for unpublished revisions. | HTML/CSS/asset edits, additions/removal, missing approval identity and readiness changes block publication; unchanged artifacts publish idempotently. Source mutation during provider execution cannot change snapshot bytes. | Complete |
| 7. Upload inventory | Recursive asset enumeration admitted unlisted files; file bytes were reread during upload. | Explicit manifest inventory, passive image validation, bounded no-follow file reads, traversal/symlink rejection and immutable in-memory upload bytes before remote operations. | Fake transports receive zero requests for invalid inventories. Traversal, unsafe types, symlinks, forged checksums, SVG payloads and file/size limits are covered. | Complete |

## Changed implementation files

Paths below identify the implementation groups used by the table above.

- MCP and runtime: [src/business_prospector/mcp/server.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/mcp/server.py), [src/business_prospector/dashboard.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/dashboard.py), new [src/business_prospector/application/runtime.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/runtime.py).
- Status and qualification: [src/business_prospector/application/lead_status.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/lead_status.py), new [src/business_prospector/application/lead_update.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/lead_update.py), new [src/business_prospector/application/qualification.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/qualification.py), [src/business_prospector/application/batch.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/batch.py), [src/business_prospector/application/prospecting.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/prospecting.py), [src/business_prospector/domain/models.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/domain/models.py), [src/business_prospector/domain/website_assessment.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/domain/website_assessment.py), [src/business_prospector/infrastructure/fake_providers.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/infrastructure/fake_providers.py).
- Research and persistence: [src/business_prospector/domain/first_website.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/domain/first_website.py), [src/business_prospector/application/first_website.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/first_website.py), [src/business_prospector/application/ports.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/ports.py), [src/business_prospector/infrastructure/sqlite_repository.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/infrastructure/sqlite_repository.py), [src/business_prospector/application/site_generation.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/site_generation.py).
- Approval and publication: new [src/business_prospector/application/artifacts.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/artifacts.py), [src/business_prospector/application/sales_preview.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/sales_preview.py), [src/business_prospector/application/deployment.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/application/deployment.py), [src/business_prospector/infrastructure/cpanel.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/src/business_prospector/infrastructure/cpanel.py).
- Regression coverage: new [tests/test_phase1_boundaries.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/tests/test_phase1_boundaries.py) (54 cases), new [tests/test_artifact_integrity.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/tests/test_artifact_integrity.py) (31 cases); updated [tests/conftest.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/tests/conftest.py), [tests/test_cpanel_deployment.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/tests/test_cpanel_deployment.py), [tests/test_first_website.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/tests/test_first_website.py), [tests/test_google_places.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/tests/test_google_places.py), [tests/test_repository.py](/Users/gabrieltodaro/Developer/Gapps/business-prospector/tests/test_repository.py).
- Documentation: [README.md](/Users/gabrieltodaro/Developer/Gapps/business-prospector/README.md), this report, and the deployment, dashboard, first-website, site-generation and website-assessment guides.

## Executed validation

Final full suite: **417 executed, 417 passed, 0 failed, 0 errors, 0 skipped**.
Evidence: [JUnit XML](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-1-validation/pytest.xml) and [pytest output](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-1-validation/pytest.txt).

The original 332 cases remain present, with fixtures adjusted where the new contracts
require an inventory, selection receipt or structured provider evidence. There are
85 additional regression cases. Final pytest wall-clock output: 16.30 seconds.

The final focused run covered the new boundary/integrity tests and repository tests:
**103 passed**, zero failures or skips. An earlier full run passed 410 tests before the
additional migration, provider and input-bound regressions were added.

Runtime used: Python 3.14.8, pytest 9.2.0 and MCP 1.30.0. The environment was temporary;
no application dependency was added or changed.

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/uv run --no-project \
  --python /opt/homebrew/bin/python3.14 \
  --with 'pytest>=8,<10' --with 'mcp>=1.2,<2' \
  python -m pytest --tb=short --junitxml=/tmp/business-prospector-phase1-final.xml
```

Additional checks executed:

- Python AST syntax validation: all 68 Python files under source/tests passed.
- `node --check src/business_prospector/dashboard_static/app.js`: passed; this is the repository's JavaScript file.
- `git diff --check`: passed.
- Final source/test/documentation diff and untracked-file inventory reviewed; no production database, generated website, real credential or runtime output was added.

Tests set a fresh temporary data directory and explicit repository fixture config for
each case. Known runtime credential settings are overwritten with synthetic test values;
external socket connections are rejected, while loopback remains available for dashboard
HTTP tests. Existing launcher tests that exercise service-env loading use synthetic homes.
Google/cPanel behavior is supplied by fake providers/transports. No live Google request,
cPanel deployment, DNS change, message, legacy publisher, scheduler, production database
or production artifact operation was performed. The live OpenClaw configuration and
production secrets were not accessed or changed.

## Application boundaries and artifact lifecycle

Adapters delegate qualification and status policy to application services. Repository
methods remain a trusted persistence port, rather than a second business-rule engine.
Specialized generation, approval and publication operations retain their separate gates.

Selection is now a small persisted receipt, not a research cache. It records the target,
configured market and selected candidate metadata. New complete research must refer to
that receipt and match its references. Python counts observed features once per site and
sorts the resulting frequencies. Factual accuracy of observations still requires research;
a receipt proves association, not that an agent's observation is true.

`PublicArtifact` owns immutable byte strings and deterministic identity. Its explicit
inventory contains `index.html`, `styles.css`, and named manifest assets. Private README
and manifest data stay local. Approval validates a snapshot, then records its identity.
Publication captures another snapshot, compares identities, runs readiness and sends only
those validated bytes. The provider captures all bytes before its first remote request.
Per-file no-follow reads prevent asset/path symlink substitution during capture.

Limits remain 100 public files, 25 MiB total and 8 MiB per image. Allowed image types are
PNG, JPEG, WebP and restricted passive SVG. Unsafe SVG constructs and active embedded HTML
are rejected. No hosting provider, template, dependency or outreach feature was introduced.

## Compatibility and manual actions

| Area | Effect and action |
|---|---|
| SQLite | Schema v7 adds `benchmark_selections` and updates `user_version` on initialization. The v6 upgrade does not rewrite lead rows; existing earlier migrations remain tested. No operational database was opened or migrated during this work. No manual SQL migration is required for the new table. |
| Existing research | Legacy reports remain readable, including the older representation. New qualification requires a valid receipt. Historical rows are not automatically asserted to meet current policy. Existing valid complete research can still generate a draft when it matches the persisted report and passes current report validation. |
| Existing qualified rows | Qualification transitions and MCP edits retaining `qualified` revalidate evidence. Historical rows lacking structured assessments or selection receipts can fail these writes. They may still be read or moved to review. A reviewed evidence refresh is required before requalification; bulk backfill/evidence-replacement tooling is not added in this phase. No evidence is fabricated for historical production data. |
| Generated websites | Normal generated files with correct inventories/checksums remain compatible. Unlisted files, links, unsafe image types or incomplete inventories block approval/publication; correct or regenerate the draft and review it. |
| Previously approved previews | An unpublished preview without `approved_artifact` must be explicitly reviewed and approved again. Reapproval of an unpublished changed revision is supported. Already published sites are not modified; replacement/reapproval remains unsupported, and repeated publish calls lacking current integrity metadata fail closed. |
| MCP | `save_lead` requires matching structured evidence; flag-only calls fail. Prefer the structured batch qualification tool. Research callers carry the returned `selection_id`. Generic updates enforce the common graph and validate before writing. |
| Dashboard | Default storage honors the data-root environment variable; `--database` remains explicit. The same configured qualification policy and graph apply. No UI feature was added. |
| Deployment manifests | New approval metadata adds versioned file identities. Existing manifests are not silently upgraded or autoapproved. Provider results must report the approved checksum. |
| Assessment providers | Providers must return `WebsiteAssessmentReport`; old flag-only implementations cannot qualify leads. The bundled offline fake is updated and preserves expected scores. |

## Remaining risks and limits

**Blocking issues for Phase 1 or Phase 2 development:** none identified by the executed
verification within the authorized offline scope.

**Non-blocking limitations:**

- Live provider behavior, account permissions, DNS and TLS were intentionally not tested.
- No production inventory/backfill was performed, so the number of historical records or previews requiring manual review is unknown.
- File capture uses POSIX no-follow/descriptor APIs, verified on macOS. Windows support and other Python versions were not validated in this run.
- Approval and deployment metadata are trusted local files, not signed records resistant to an administrator who can rewrite both artifacts and approval metadata.
- A filesystem manifest write and SQLite status update are not a distributed transaction. Remote partial failures still require the existing manual cleanup; this phase adds no rollback or remote checksum read-back.
- Multi-process lifecycle updates/publications are not serialized. Snapshotting guarantees payload integrity, but simultaneous edits/approvals may still require reconciliation of local metadata. Automated concurrent publishing is outside the current operating model.

**Future improvements:** explicit historical evidence refresh tooling, serialized lifecycle
operations/recovery, receipt retention/TTL policy, separately authorized live provider
verification, and the research-driven generation work planned for Phase 2.

## Next-phase readiness

The project is ready to begin **Phase 2: Research-Driven Personalized Website Generation**
on this verified foundation. This is readiness for development, not approval for live
publication at scale. Phase 2 should preserve the receipt, qualification, approval and
immutable upload boundaries introduced here. No Phase 2 design or generation feature was
implemented as part of this change.
