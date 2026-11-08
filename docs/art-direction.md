# Art direction and visual evaluation

This pipeline adds model/agent creative judgment to the existing deterministic
business, rights, lifecycle and publication boundaries. It does not certify
commercial quality. An internal draft can be revised without asking a human to
approve individual design choices; commercial approval remains a separate action.

## Boundaries and data

- `domain/art_direction.py`: validated `ArtDirectionPlan`, evidence references,
  bounded composition choices and visual assessment schema. Copy and positioning
  reference target facts; benchmark observations cannot become target evidence.
- `application/art_direction.py`: benchmark analysis, planning, pixel evaluation,
  agent curation, artifact-bound page review, supported revisions and bounded cycles.
  `VisualEvaluator`, `PageCapture` and `DesignReceiptStore` are injected boundaries.
- `infrastructure/mcp_vision.py`: uses the authorized client's negotiated MCP
  sampling capability. There is no API key, provider SDK or hardcoded model.
- `infrastructure/visual_browser.py`: captures an immutable public-file inventory
  through loopback Chromium with external requests/service workers blocked. Checks
  overflow, images, headings, language, anchors, repeated body copy, CTA visibility,
  touch targets and mobile navigation. These are a subset of accessibility checks;
  they do not replace axe, screen-reader testing or visual judgment.
- `infrastructure/design_store.py`: append-only private receipts and pixel evidence
  in `<data-directory>/design-reviews`. UUID paths, bounded no-follow reads and image
  hashes protect references. Jobs expire after 24 hours. No SQLite migration.
  Evidence remains private and is excluded from the deployment allowlist.

Benchmark selection defaults to three and retains configured category/reputation
eligibility. Ranking uses a review-volume-adjusted rating:
`(rating * reviews + minimum_rating * minimum_reviews) / (reviews + minimum_reviews)`
(with weight at least 1), then review count and stable identity ties. A well-established
4.9 can outrank a sparse 5.0. Visual analysis additionally requires all three selected
businesses to be in the configured benchmark market and desktop/mobile captures of
all three source URLs. Source URLs, screenshots, hashes, eight design dimensions and
evaluator identity are retained separately from business reputation. Website quality
is assessed from pixels, not inferred from review counts. Client browser provenance
is a trust boundary: the server cannot independently prove the URL shown by supplied
screenshots without browsing that external site itself.

For an existing internal draft, `analyze_benchmark_design(selection_id=...)` can
use a new three-reference selection bound to the same target without replacing
stored business research or bypassing research-refresh lifecycle rules.

Old two-benchmark reports remain readable. They cannot be labeled complete
three-reference visual research. Existing eligible qualified leads can use the
supported research-refresh operation; no missing selection/evidence is fabricated.

## MCP workflow

1. Select three benchmarks with `select_first_website_benchmarks`; use the configured
   market. Save/refresh valid research through the existing use cases.
2. `analyze_benchmark_design(lead_id, screenshots, reviewed_content?)`: submit six
   `{source_url, viewport: desktop|mobile, png_base64}` objects captured using the
   authorized browser. Each PNG is bounded to approximately 4 MiB. The response is
   either an assessment receipt or a vision-unavailable job.
3. `create_art_direction_plan(lead_id, reviewed_content?, benchmark_review_ids?,
   proposed_plan?)`: obtain evidence, plan schema and an immutable plan ID. The
   client can submit an original plan with evidence-backed copy. Without a model,
   the explicit deterministic fallback uses literal known facts and typography.
   `research_status` discloses missing visual references.
4. `search_stock_photos_for_plan(plan_id, query, orientation?)`: art-directed search
   phrases retain category, resolution, orientation and provider safety filters.
   `evaluate_stock_photo(plan_id, selection_id, photo_id)` sends actual downloaded
   bytes to vision and checks eight criteria plus focal point/rejection reasons.
5. `curate_stock_photo_for_draft(review_id)`: requires a fully accepted photo review,
   current context and unchanged image bytes on download. Creates
   `agent_curated_draft` with `review_kind=agent_curation` and assessment ID. It does
   not impersonate a human, grant third-party rights or authorize publication.
   Include the returned key/focal point in a new plan and preserve benchmark IDs.
6. `run_visual_design_cycle(plan_id, asset_keys?, max_iterations=3)` generates and
   reviews at most three candidates. It stops on unavailable vision/capture, full
   review pass, repeated plans, unchanged/no supported patch or non-improving
   criterion pass count. Results include review history and unresolved feedback.
   Explicit alternatives: `generate_art_directed_website`, `review_website_design`
   and `revise_website_design`.
7. Show desktop/mobile evidence and unresolved issues to the human. Use existing
   commercial approval/publication operations only after their authorization.
   `ready_for_human_review` is not publication approval or a quality certificate.

Supported review patches: typography, palette, density, hero composition, image
placement, responsive ordering, focal point, section order/emphasis/omission,
evidence-backed headline/supporting copy and CTA label. Revisions revalidate the
entire plan; cannot introduce arbitrary CSS, URLs, credentials, rights, lifecycle
changes or new unsupported section kinds. CTA destinations remain verified existing
business contact channels. New photo selection uses the separate curation workflow.

## Vision and browser configuration

Install development/runtime dependencies only in the authorized environment:
`pip install -e '.[visual]'`. Supply a Chromium installation through Playwright or
`BUSINESS_PROSPECTOR_CHROMIUM_EXECUTABLE=/absolute/path/to/chromium`.
No running OpenClaw process or Mac Mini was changed by this implementation.

MCP sampling depends on the client advertising support and selecting an authorized
vision-capable model. The server requests actual image inputs, at most 3,500 output
tokens and a 60-second sampling timeout. Denial/unavailability is an explicit
fallback, never a visual pass. Client consent behavior belongs to the host; this
integration cannot assume Oliver's installed client supports unattended sampling.
See the official [MCP sampling specification](https://modelcontextprotocol.io/specification/2025-06-18/client/sampling).

Clients without sampling can call `get_visual_evaluation_job(job_id)` to receive
native MCP image content and exact assessment instructions. After inspecting **all**
images with an authorized vision-capable model, call
`submit_visual_evaluation(job_id, assessment, evaluator)`. This is agent judgment,
not human approval. Without either vision route, generate an explicitly unreviewed
no-image draft and report the dependency; never submit fabricated visual evidence.

Job and photo evidence are byte-bound. Page reviews bind the public artifact checksum
and exact plan; generation rechecks the expected checksum under the existing site
lock, rejecting concurrent edits. Lead facts are checked again before generation.
Revisions preserve previous artifacts through the existing recovery/archive path,
reset stale commercial approvals and refuse reserved/published artifacts.

## Limits and validation

Evidence-reference validation is structural: it cannot prove that arbitrary creative
prose semantically follows its cited facts. Model instructions, screenshot critique
against business evidence and final human content review remain necessary. An agent
can provide bad judgment; schema validation does not turn it into good judgment.
Typography choices are controlled system-font stacks, not a full brand-identity
system. The renderer remains constrained intentionally, but planning and critique
can change composition, story order, copy, density and photographic direction.

See [validation results](art-direction-validation.md) and
[reference observations](design-reference-assessments.json). The human reference is
the user's negative design review. Positive current photo judgments are explicitly
attributed to the development agent; they are not invented human endorsements.
Private screenshots/receipts have no automatic retention cleanup; operators should
retain evidence needed for active reviews and manage archived evidence explicitly.
