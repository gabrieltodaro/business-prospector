# Phase 2: research-driven personalized previews

Implemented locally on November 6, 2026. Phase 2 is intentionally **uncommitted**, on `feature/business-prospector-phase-2`. No push, merge, publication, production access, lead contact, paid discovery or external AI request was performed.

## A. Phase 1 completion

- Verified branch: `fix/business-prospector-phase-1`.
- Commit: `3181abef0e799f3dadbc779412a9d11116b99371`.
- Exact message: `fix: secure prospecting and website lifecycle`.
- Before committing: implementation report, complete tracked/untracked implementation, intended file inventory, diff review, `git diff --check`, and complete suite: **417 passed, 0 failed, 0 skipped** in 17.21 seconds.
- Included 34 reviewed source, test and documentation files, listed below. No operational credentials, runtime database, generated site or unrelated file was staged.
- Phase 2 branched directly from this commit. Phase 1 history was not amended. Neither branch was pushed or merged.
- `docs/phase-1-implementation.md` remains the historical implementation report; this report records its subsequent verification and commit.

## B. Implementation and architectural decisions

The pipeline is now:

```text
persisted qualified lead + validated benchmark report + reviewed target facts
  -> pure deterministic design strategy
  -> structured website content model
  -> reusable static HTML components + packaged CSS
  -> bounded local asset validation + Phase 1 artifact inventory
  -> recoverable installation + persisted internal draft status
```

### Research and strategy

Previously, recommendations and common features were stored but the generator selected essentially the same structure. `domain/site_strategy.py` now derives sections, order, navigation, contact action, palette and hero composition from validated observations and a small category policy. `domain/first_website.py` adds optional `design_priorities`: at most eight distinct feature names, all present in benchmark observations. Old reports default to an empty list.

Only recognized feature identifiers affect rendering. Each section scores the number of supporting benchmark observations, plus ten per selected supported priority; category order resolves ties deterministically. Dentist, restaurant and generic policies supply a small set of reasonable defaults. Observed optional sections are included only when corresponding target facts exist. Unsupported or absent information is omitted, with a recorded rationale. No competitor prose, imagery, logos or distinctive layout is copied.

Free-text `recommendations` and `inferences` remain advisory research data. They are deliberately not interpreted as instructions or factual copy. Use `design_priorities` for executable, observation-backed recommendations. The bounded feature mapping supports services/treatments, menu, hours, biography/about, credentials, team, differentiators, FAQs/patient information, location, gallery, reputation and contact/booking/reservation/ordering patterns. Unknown feature names do not drive the strategy.

`WebsiteStrategy.decisions` records the decision, rationale, contributing features and evidence references such as `research.benchmarks[0].features:services` and `business.sources:brief`. Category defaults and original theme choices have explicit policy rationales. Repeated inputs yield the same strategy and public bytes; private generation timestamps and revision archive names are intentionally variable.

Tests: structural changes for identical businesses with different research, priority ordering/navigation, forged typed reports, contradictory counts, unsupported priorities, unsupported prose isolation, policy selection, theme variation and determinism.

### Reviewed business facts and content model

Previously, optional services, biography and opening hours were always missing. `domain/site_content.py` adds immutable, bounded, target-bound reviewed facts and source records. Existing lead name, category, address/city, phone, confirmed WhatsApp, Instagram, map and reputation fields are reused. `domain/site_generation.py` extends the existing brief; `domain/website_content_model.py` creates renderer-ready sections and contact actions.

Supported optional facts are services, menu entries, opening hours, biography, team, credentials, differentiators, FAQ pairs, booking/ordering URLs and approved palette/typography selections. Every fact needs an allowed source, reviewer and timestamp. Benchmark and generic-industry sources cannot substantiate target facts. Missing fields are omitted or replaced with clearly generic contact guidance, never invented marketing claims. Booking/order calls to action require both a reviewed URL and a relevant observed pattern. Unconfirmed WhatsApp never becomes a WhatsApp link.

“Verified” here means explicitly reviewed, source-backed input: the application validates the evidence contract and target identity. It does not independently prove that a human assertion or source is truthful. Existing persisted lead facts retain their established discovery/manual-source trust boundary. Google attribution requires the Google Places source; synthetic demonstration ratings are explicitly fictional.

Tests: source/target mismatch, missing facts, unsupported source kinds, unknown evidence references, malformed input, escaping, URL restrictions, channel selection, rating attribution and backward-compatible inputs.

### Adaptive renderer and visual system

Previously, a single large HTML string and category copy produced the same main sections. `application/site_renderer.py` composes hero, verified lists, about, reputation, FAQ, gallery, location and contact sections. `resources/preview.css` provides three original palettes, two typography modes and two hero compositions. Category/strategy selects the defaults; reviewed brand choices can override the bounded palette/type selections.

System fonts, local assets, responsive grids, native mobile navigation/FAQ controls, focus indicators, skip navigation, reduced-motion support and conservative typography avoid runtime frontend dependencies. All untrusted text/attributes are escaped. There are no embedded third-party widgets, remote fonts, image generators or frontend framework. The package configuration includes CSS resources.

Every newly generated page displays the independent Gapps.Tech demonstration disclosure at top and footer, with `noindex,nofollow,noarchive`. Internal drafts and commercially approved previews are distinguished in private metadata and lifecycle status. Commercial approval never changes the disclosure to imply prospect endorsement.

Tests: deterministic HTML/CSS and hashes, semantic/artifact validation, HTML escaping, local images, section availability, synthetic disclosure and noindex. Browser results are recorded below.

### Approved local assets

Previously, provenance and rights validation existed separately from the normal persisted generation tool. `infrastructure/local_site_assets.py` connects a reviewed business-scoped local inventory to generation through the `ReviewedSiteAssetLibrary` application port. MCP accepts only reviewed asset keys, never arbitrary file paths or approval declarations. `domain/site_assets.py` restores validated reviewed inventory entries. `application/artifacts.py` reuses Phase 1 bounded no-follow reads, signatures, MIME checks and checksums.

The library is `<data_dir>/reviewed-assets/<lead_slug>/asset-manifest.json`, with exact `lead_identity` and existing serialized `SiteAsset` entries. Each selected asset must already be approved for draft or publication, have permitted provenance/rights, and match its local SHA-256, MIME and byte size. Files remain below that business's `assets/` directory. The trusted local inventory must be prepared by an authorized reviewer using the existing asset classification/ingestion structures; no new automatic approval or asset acquisition service is introduced.

Unsafe paths, symlinks, unsupported formats/signatures, altered bytes, cross-business inventories and unsuitable rights are rejected. Limits remain 8 MiB per image, 100 public files and 25 MiB per artifact. Up to 30 asset entries are accepted. Assets approved only for draft still require explicit publication review. Without an approved image the existing authored SVG fallback is used, tinted with the selected original palette; it is not represented as a business photograph.

Tests: library integration/provenance, type/signature, checksum/size mismatch, symlinks/traversal, wrong business, missing keys, unapproved assets, rights and social-reference rejection, and unchanged Phase 1 inventory compatibility.

### Safe draft revisions

Previously, overwriting an artifact was awkward in the lifecycle and could remove a valid draft before successful replacement. `PersistedSiteGenerationWorkflow.revise` now accepts an existing internal draft or an approved, unpublished preview directly, including legacy `site_ready`; no artificial requalification is needed. Redesign remains unsupported.

Generation completes in a staging directory. HTML, images and the exact Phase 1 public inventory are validated before installation. `application/draft_revision.py` moves the old artifact into `<data_dir>/site-revisions/<slug>/<unique_archive_id>` outside the public site root, then installs the replacement. A caught rendering, validation, installation or database failure preserves/restores the prior valid artifact. Old revisions are retained after success; no cleanup policy deletes them automatically.

The private manifest records revision number, current artifact identity and previous artifact checksum. Changed public bytes produce a distinct identity. Every successful revision clears approval/deployment metadata, marks `preview_kind=internal_draft`, and returns the lead to `internal_website`. This conservatively requires fresh approval even if a rerender happens to produce identical public bytes. Both publication markers are checked; already-published artifacts are blocked at workflow and low-level generation boundaries. Malformed existing publication metadata fails closed.

`site_operation_lock` serializes generation/revision, approval and publication for one slug with POSIX `flock`. The workflow checks for changed lead data before its final status update. Phase 1 immutable receipts, restricted public inventory and snapshot publication checks remain authoritative. No remote replacement or deployment rollback is added.

Tests: revision success and archive retention, four failure/recovery stages, identity checks, distinct changed-byte hashes, stale approval rejection/reapproval, published guards, malformed metadata, fact/asset reuse, explicit clearing, lock serialization and unsupported redesign.

### MCP and dashboard integration

`generate_first_website_draft(lead, research, overwrite=false, reviewed_content=null, asset_keys=null)` remains compatible with prior calls and reloads the authoritative persisted lead by `lead.id`. Supplied research must equal the validated persisted report.

New `revise_first_website_draft(lead_id, reviewed_content=null, asset_keys=null)` reuses persisted research. On revision, omitted/null content and assets retain the previous reviewed values. An explicit empty object clears optional facts; an empty asset-key list removes selected images and restores the authored fallback. A nonempty content payload replaces the complete reviewed content model, not individual fields.

The result includes strategy, artifact identity, revision number and previous archive path. `SiteDraftService` exposes safe strategy/revision metadata to the existing dashboard. Existing local preview, readiness, approval and publication routes remain in place; no new dashboard, editor or CMS was introduced. The generation tool never grants commercial approval.

Tests: initial MCP generation with authoritative lead identity, revision tool, dashboard metadata visibility, lifecycle recovery and existing approval/deployment tests with fake providers.

## Reviewed content example

Use the exact slug/place ID of the persisted lead. All values below are synthetic.

```json
{
  "target": {"slug": "clinica-exemplo-demo-vila-exemplo-sp", "external_place_id": "synthetic-place"},
  "reviewed_by": "Synthetic reviewer",
  "reviewed_at": "2026-11-06T12:00:00+00:00",
  "sources": [{"id": "brief", "kind": "business_provided", "reference": "Synthetic demonstration brief"}],
  "facts": {
    "services": {"value": ["Avaliação odontológica"], "source_ids": ["brief"]},
    "opening_hours": {"value": ["Segunda a sexta, 09h–17h"], "source_ids": ["brief"]},
    "booking_url": {"value": "https://booking.example/clinica-demo", "source_ids": ["brief"]}
  }
}
```

Allowed source kinds: `business_provided`, `business_website`, `public_business_profile`, `professional_register`. URL-backed sources and booking/order destinations require HTTP(S) without embedded credentials or supported secret-query patterns. These URLs are data, not fetched during generation. Do not put sensitive information into a reviewed content payload.

## C. Demonstration artifacts

`personalized_demo.py` and `resources/personalized_site_demos.json` run the persisted selection/qualification/generation pipeline with synthetic fixtures and an isolated SQLite database. There are no live discovery, research, booking or image requests. The CLI requires a new explicit destination and refuses existing directories:

```bash
PYTHONPATH=src python -m business_prospector.personalized_demo --output /tmp/new-personalized-demo-run
```

| Synthetic business | Research and facts | Visible outcome |
| --- | --- | --- |
| Clínica Horizonte Demo, dentist | Services, patient-information FAQ, location and booking patterns; reviewed services, biography and booking URL | Services then FAQ; sage palette; focused hero; appointment CTA; unprovided credentials omitted |
| Mesa de Oliva Demo, restaurant | Menu, hours, location and reservations; reviewed menu/prices, opening hours, biography and reservation URL | Menu then hours; terracotta palette; editorial hero; reservation CTA |

Both include conspicuous fictional-data labeling. The same-business/different-research regression separately demonstrates that variation is caused by research, not merely by industry labels.

Durable local artifacts and screenshots:

- [Dental HTML](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-demonstrations/sites/clinica-horizonte-demo-vila-exemplo-sp/index.html)
- [Restaurant HTML](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-demonstrations/sites/mesa-de-oliva-demo-vila-exemplo-sp/index.html)
- [Dental desktop](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-demonstrations/clinica-horizonte-demo-vila-exemplo-sp-desktop.png) / [mobile](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-demonstrations/clinica-horizonte-demo-vila-exemplo-sp-mobile.png)
- [Restaurant desktop](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-demonstrations/mesa-de-oliva-demo-vila-exemplo-sp-desktop.png) / [mobile](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-demonstrations/mesa-de-oliva-demo-vila-exemplo-sp-mobile.png)

Generated sites and the synthetic runtime database are outside Git. Only reusable synthetic fixture data and demo source are part of the implementation.

## D. Verification

Final results are recorded in the validation evidence directory linked below. Python 3.14.8, isolated uv tool dependencies, no project runtime secrets. Tests use temporary data directories/fake providers; test sockets are restricted to loopback.

- Focused regression run: **88 passed**, zero failures/skips.
- Complete suite: **474 passed**, zero failures/skips in 16.81 seconds; 57 additional cases above the 417-test Phase 1 baseline.
- Python syntax: all 77 repository Python sources/tests compiled in memory, without bytecode files.
- JavaScript syntax: `node --check src/business_prospector/dashboard_static/app.js`.
- `git diff --check`: passed. No Phase 2 files staged.
- Both demonstration artifacts pass generated-site validation and Phase 1 inventory/signature validation. Their stored revision identities match recaptured bytes.
- Chrome/Playwright: both sites at 1440×1000 desktop and 390×844 mobile, plus mobile menu screenshots. Images loaded, anchor targets existed, mobile menus opened, no horizontal overflow or page errors, no external requests. Final screenshots were visually inspected. The checks do not constitute a full accessibility certification or cross-browser/device matrix.
- Fifteen palette text/button contrast pairs passed (minimum checked ratio 5.62:1); no claim of a comprehensive WCAG audit.

Evidence: [validation directory](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-validation) and [browser checks](/Users/gabrieltodaro/.codex/visualizations/2026/11/06/01a1b163-880d-7d21-bf59-80bd987acbb0/phase-2-demonstrations/visual-checks.json).

## E. Compatibility and reapproval

| Surface | Impact |
| --- | --- |
| SQLite | Schema stays v7. No Phase 2 migration or production DB access. Reviewed facts/revisions live in private site manifests and controlled local inventories. |
| Existing research | Optional `design_priorities` defaults to empty; existing valid reports remain usable. Contradictory evidence remains invalid. Refreshing persisted research is not part of the revision operation. |
| Existing generated sites | Unmodified until an explicit revision. Generation uses version 3.0.0, strategy 3.0. Legacy manifests without revision metadata start at revision 1 when replaced; old artifacts are archived. |
| Existing approved previews | Remain governed by their Phase 1 receipt. Revising an unpublished preview invalidates approval and requires explicit reapproval. Already-published artifacts cannot be revised. Older previews lacking immutable receipts still require Phase 1 reapproval. |
| Deployment manifests | Public inventory/checksum version remains 1. New private fields do not enter public upload inventory. No deployment manifest or remote artifact was changed. |
| MCP | Existing generation arguments remain valid; optional reviewed facts/asset keys and a new revision tool are additive. Responses add strategy/revision/integrity metadata. |
| Dashboard | Existing preview and approval routes continue. Safe draft metadata includes strategy/revision/preview kind. Revision is exposed through MCP, not a new dashboard editor. |
| Runtime | CSS is packaged with Python resources. No new production dependency. Existing macOS/Linux POSIX filesystem assumptions now also include `flock`. |

No automatic reapproval or migration of existing websites is performed. Old websites do not acquire the new disclosure/noindex merely by upgrading code; inspect/revise an unpublished old draft before selecting it for a Phase 3 personalized preview.

## F. Remaining risks

**Blocking implementation issues:** none identified by the completed offline checks. This is not authorization or certification to publish.

**Non-blocking limitations:**

- Human-reviewed facts, asset rights and benchmark observations remain a trust boundary. Schema validation cannot verify truth or legal rights, and timestamps do not guarantee freshness.
- Three small category policies and a bounded feature vocabulary deliberately limit breadth. Unknown features do not produce arbitrary new sections. Generated copy remains conservative; no fabricated credentials or testimonials fill gaps.
- File installation and SQLite status updates are recoverable for caught failures, but are not one crash-atomic cross-system transaction. A process kill/power failure between renames or DB steps may require manual reconciliation from retained archives. Status updates outside these locked operations are not a general database compare-and-swap transaction.
- Local revision archives have no automatic retention/pruning policy. There is no public deployment rollback or remote replacement.
- Reviewed asset inventories are trusted local operator inputs; no new review UI is provided. Signature/MIME checks are not a general-purpose image decoder or malware scanner.
- Visual checks cover current local Chrome and two viewport sizes. No screen-reader, Safari/Firefox, older-browser or real-device certification was performed. Noindex is a crawler request, not access control.
- Real hosting, DNS, TLS, remote path protections and public checksum verification were not exercised. External links in synthetic demos use reserved demonstration destinations and were not clicked.

**Future improvements:** evidence freshness/review tooling, controlled research refresh, broader policies justified by real users, additional accessibility/browser checks, crash-recovery journal and explicit archive retention. Outreach, autonomous workers, extra hosting providers, image-generation APIs and a visual editor remain out of scope.

## G. Phase 3 readiness

The application is ready for a separately authorized **controlled preview deployment and public verification** exercise. Before publishing the first real personalized preview:

1. Select a real qualified `first_website` lead with a valid persisted research report and verify its identity/contact data. Review the source-backed business facts and each asset's provenance/rights.
2. Generate/revise the local draft; review strategy rationale, missing information, desktop/mobile content, disclosure, noindex, links and asset rendering. Obtain explicit content and publication-rights approval for the exact final bytes through the existing lifecycle.
3. Confirm the intended preview slug and hosting configuration, destination isolation, DNS/TLS and the provider's production controls within a separately authorized deployment phase. Do not infer that synthetic tests validate the real environment.
4. Explicitly authorize one controlled publication through the existing deployment service. Recheck the immutable receipt immediately before upload. The current task does not authorize that action.
5. Verify the public HTTPS URL, restricted file inventory/checksums, disclosure/noindex, rendering and asset paths; record results. Keep lead contact/outreach separate and unauthorized until expressly requested.

Phase 3 publication authorization, real-business review and real-environment verification remain outstanding. No real preview has been published by this work.

## Phase 1 committed file inventory

- `README.md`
- `docs/cpanel-deployment.md`
- `docs/dashboard.md`
- `docs/first-website.md`
- `docs/phase-1-implementation.md`
- `docs/site-generation.md`
- `docs/website-assessment.md`
- `src/business_prospector/application/artifacts.py`
- `src/business_prospector/application/batch.py`
- `src/business_prospector/application/deployment.py`
- `src/business_prospector/application/first_website.py`
- `src/business_prospector/application/lead_status.py`
- `src/business_prospector/application/lead_update.py`
- `src/business_prospector/application/ports.py`
- `src/business_prospector/application/prospecting.py`
- `src/business_prospector/application/qualification.py`
- `src/business_prospector/application/runtime.py`
- `src/business_prospector/application/sales_preview.py`
- `src/business_prospector/application/site_generation.py`
- `src/business_prospector/dashboard.py`
- `src/business_prospector/domain/first_website.py`
- `src/business_prospector/domain/models.py`
- `src/business_prospector/domain/website_assessment.py`
- `src/business_prospector/infrastructure/cpanel.py`
- `src/business_prospector/infrastructure/fake_providers.py`
- `src/business_prospector/infrastructure/sqlite_repository.py`
- `src/business_prospector/mcp/server.py`
- `tests/conftest.py`
- `tests/test_artifact_integrity.py`
- `tests/test_cpanel_deployment.py`
- `tests/test_first_website.py`
- `tests/test_google_places.py`
- `tests/test_phase1_boundaries.py`
- `tests/test_repository.py`

## Phase 2 changed file inventory

- `README.md`
- `docs/dashboard.md`
- `docs/first-website.md`
- `docs/phase-2-implementation.md`
- `docs/site-generation.md`
- `pyproject.toml`
- `src/business_prospector/application/artifacts.py`
- `src/business_prospector/application/deployment.py`
- `src/business_prospector/application/draft_revision.py`
- `src/business_prospector/application/ports.py`
- `src/business_prospector/application/sales_preview.py`
- `src/business_prospector/application/site_generation.py`
- `src/business_prospector/application/site_renderer.py`
- `src/business_prospector/domain/first_website.py`
- `src/business_prospector/domain/site_assets.py`
- `src/business_prospector/domain/site_content.py`
- `src/business_prospector/domain/site_generation.py`
- `src/business_prospector/domain/site_strategy.py`
- `src/business_prospector/domain/website_content_model.py`
- `src/business_prospector/infrastructure/local_site_assets.py`
- `src/business_prospector/mcp/server.py`
- `src/business_prospector/personalized_demo.py`
- `src/business_prospector/resources/personalized_site_demos.json`
- `src/business_prospector/resources/preview.css`
- `tests/test_draft_revisions.py`
- `tests/test_personalized_generation.py`
- `tests/test_sales_preview.py`
