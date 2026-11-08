# Premium website generation (engine 4.0)

The generator now composes concise commercial demonstrations from verified business
facts, benchmark evidence and explicitly reviewed local assets. It does not browse,
acquire stock or grant commercial approval during generation. Existing SQLite v8,
research receipts, lifecycle, revision archives, approval checksums and cPanel
publication/verification boundaries remain in place. No database migration is needed.

## Composition and content

`domain/site_strategy.py` selects sections, hierarchy, palette, typography and hero
composition deterministically. Dental, restaurant, salon and fitness policies share
components rather than separate page templates. Observed priorities can change the
same business's composition. Available image count and aspect ratio constrain the
choice: editorial split, full-width photography, asymmetric photography, image-led,
or minimal typography. Unsupported categories use the generic policy and do not
trigger speculative stock searches.

`WebsiteContentModel` separates the exact stored identity from a conservative display
name, concise marketing headline, location, supporting copy and conversion action.
Listing suffixes are trimmed for display only; the complete name remains in metadata
and the footer. Headlines never interpolate a raw listing name. Category copy makes
no claims about qualifications, treatments, history, results or actual facilities.

Biography, menu, services, team, credentials, hours, FAQ and differentiators require
reviewed target evidence. An absent biography no longer produces a filler section.
A lead without contact channels does not receive an empty contact section. Address
information appears in the location section, with a direct map action when available.
Restaurant menus, salon services, editorial introductions, compact reputation bands
and closing CTAs use different component treatments. The location block is not a
fabricated map. No maps, remote fonts, trackers or frontend JavaScript are loaded.

`preview.css` supplies four coherent palettes and three system-font pairings,
responsive grids, deliberate type scales and 44px-or-larger main navigation/CTA
hit areas. Entrance animation, hover feedback and desktop sticky section headings
support hierarchy; reduced-motion disables animation and smooth scrolling. No-photo
pages use typography, not an abstract hero illustration. Old generated fallback
illustrations are removed during an explicit revision, never by a background update.

## Provider decision and licensing

Reviewed November 7, 2026, using official documentation:

| Provider | API and license implications | Decision |
|---|---|---|
| **Pexels** | Free API, orientation filters and resized image sources. General license permits commercial website use and local downloads; API guidance asks for prominent Pexels links and photographer credit. Default API limits are 200/hour and 20,000/month. No standalone resale, stock-library redistribution, implied endorsement or offensive treatment of identifiable people. | Optional adapter for existing keys; new key issuance is paused according to the operator. |
| Unsplash | API requires hotlinked returned image URLs, photographer/Unsplash attribution and download-event tracking. General license and API obligations are distinct. | Not implemented: mandatory hotlinking conflicts with the existing local-file inventory/publication model. |
| Pixabay | API permits local downloads; permanent image hotlinking is prohibited. Requires 24-hour search caching, prohibits systematic mass downloads; default limit is 100 requests/60 seconds. Its content license also restricts standalone distribution and certain trademark/person uses. | Selected and implemented; compatible with locally hosted reviewed assets. |

References: [Pexels API](https://www.pexels.com/api/documentation/),
[Pexels license](https://www.pexels.com/legal-pages/license/),
[Pexels commercial-use guidance](https://help.pexels.com/hc/en-us/articles/360042295214-Can-I-use-the-photos-and-videos-for-a-commercial-project),
[Unsplash API and hotlinking](https://unsplash.com/documentation),
[Pixabay API](https://pixabay.com/api/docs/),
[Pixabay license](https://pixabay.com/service/license-summary/).

Provider credit is rendered beside each stock image and in a provider link in the
footer. Every stock image has a visible Portuguese illustrative-use disclosure;
no stock photo is labeled as the actual business, staff, customers or work. The
reviewer must assess relevance, context, logos/brands, identifiable people and
additional rights; an API result or a matching keyword is not proof of suitability.
This feature composes websites, not a stock gallery or a redistribution service.

## Explicit MCP workflow

Configure `PIXABAY_API_KEY` in the authorized runtime environment. Keep
`PEXELS_API_KEY` for optional Pexels use. `BUSINESS_PROSPECTOR_STOCK_PROVIDER` accepts
`auto` (default, prefers configured Pixabay, otherwise Pexels), `pixabay`, `pexels`,
or `none`. Explicit selection with no matching key uses typography; errors never
silently switch providers. Set `pexels` explicitly to retain it when both keys exist.
The launcher allowlists these variables in its existing service-env mechanism;
credentials never enter MCP arguments, artifacts or diagnostics. Changing providers
requires a new search before reviewing pending selections; existing reviewed local
assets retain their original provider and license. No database migration is needed.
No operational configuration was changed.

See the [current provider evaluation](stock-provider-evaluation.md) for API access,
licensing, hosting and account-verification limits.

1. For an individual human request (never a background/bulk job),
   `search_stock_photos(lead_id, reviewed_content=null)` derives a bounded query from
   category, benchmark gallery emphasis and reviewed cuisine/menu facts. Present the
   returned provider/photographer links with candidates. At most one API search is
   made (15 results examined, up to six retained), with no automatic pagination.
2. Inspect a candidate and its source/license. Call
   `approve_stock_photo_for_draft(lead_id, selection_id, photo_id, reviewed_by,
   review_confirmed=true)` only after explicit relevance, license and illustrative-use
   review. Selection receipts are lead-bound and expire after 24 hours. Callers cannot
   supply arbitrary download URLs or filesystem paths.
3. Pass the returned `asset_key` in `asset_keys` to `generate_first_website_draft`
   for a qualified lead, or `revise_first_website_draft` for an eligible unpublished
   draft. Only keys in the reviewed business-scoped library are accepted. Review of
   stock does not change lead status or alter an existing generated site.
4. Use the existing commercial content/asset approval, followed by separately
   authorized publication. Stock receives **draft approval only** during ingestion.
   A revised artifact loses its previous commercial approval, including when photos
   are removed. Reserved/published artifacts remain protected.

`StockPhotoProvider` is the application port. `PixabayStockPhotoProvider` and
`PexelsStockPhotoProvider` parse their own responses and share bounded transport,
24-hour disk caching and persistent failure cooldown. Pixabay caches only normalized
candidate metadata in `stock-cache/pixabay`; the legacy Pexels cache stays in
`stock-cache`. Transport rejects redirects, sanitizes errors and honors longer
`Retry-After` values. Pixabay's required query-string key is sent only to its API;
image downloads carry no credentials. Pixabay API and image requests identify the
application with `User-Agent: BusinessProspector/0.1.1`. Embedders can override the
adapter's `user_agent` constructor argument with a descriptive ASCII application
identifier; no runtime configuration is needed for the default. HTTP status codes
survive sanitized errors, cooldown persistence and the MCP `http_status` field.
A 403 means the request was refused; it does not establish that credentials are
invalid. Existing cooldowns without status metadata remain compatible and expire
normally; this update does not clear cooldowns or automatically retry requests.
Images are restricted to fixed provider origins, then validated for MIME, signature, size, checksum and safe inventory paths.
Immutable keys and atomic manifest replacement preserve existing assets on failure.
Generation consumes local bytes and retains all commercial approval boundaries.

Pixabay uses the standard `largeImageURL` (up to 1280 pixels), not restricted full-API
originals. Candidate dimensions account for this cap; unsuitable resolution/crops
use typography. Expired remote download URLs require another search/review; existing
approved local bytes remain intact. Matching tags are hints, never evidence that a
photo depicts the lead or that third-party rights are cleared.

Provider failures and unsupported categories use typography. Tests use injected
transports; no authenticated provider requests were made during this implementation.

## Outreach metadata

No email system was added and no messages were sent. The private site manifest and
local draft metadata expose `outreach_image_context`: `contains_illustrative_stock`,
`depicts_actual_business`, a suggested disclosure and per-image provenance. The
message explains that images are illustrative and can be replaced with photographs
and assets supplied by the owner. Provenance records provider ID, source and license
URLs, photographer, query, reviewer and review timestamp. It is not uploaded as a
public file; visible attribution remains in HTML.

## Reproducible visual validation

`python -m business_prospector.premium_demo --output /new/isolated/directory` creates
three synthetic businesses through benchmark selection, qualification and normal
persisted generation. The output must be a new directory. With
`--stock-directory /explicit/local/photos`, it additionally exercises search receipts,
human draft review and the local inventory through a supplied offline provider.
No live API or production database is used by this demo command.

The local photo directory contains these reviewed Pexels downloads (not committed):

- `7800563.jpg`: [dental instruments, Nadezhda Moryak](https://www.pexels.com/photo/different-kinds-of-dental-tools-7800563/).
- `1279330.jpg`: [pasta, Lisa Fotios](https://www.pexels.com/photo/selective-focus-photography-of-pasta-with-tomato-and-basil-1279330/).
- `3993460.jpg`: [hair-styling concept, cottonbro studio](https://www.pexels.com/photo/person-in-brown-long-sleeve-shirt-holding-silver-scissors-3993460/).

Only these public licensed photo files were downloaded for manual visual review;
no operational credentials were accessed. Businesses, reputation, addresses, services
and benchmark observations in the demo resource are explicitly synthetic. Photography
is real stock with its own provenance and is not represented as business evidence.

Run `scripts/validate_premium_sites.py --sites /isolated/sites --output /screenshots`
using a development environment with Playwright. Supply `--axe-script` with a local
axe-core script for WCAG A/AA checks. The script serves only the supplied static sites
on loopback and blocks all external browser requests. It captures desktop/mobile
screenshots and checks 1440, 390 and 320px widths, navigation, images, CTA targets,
overflow, reduced motion, resource transfer and layout shift. Real browser screenshots
were inspected and the copy/image selection refined; results are in the accompanying
[validation report](premium-generation-validation.md).

## Boundaries and limitations

- Candidate prefiltering uses category/cuisine vocabulary, captions and dimensions.
  The optional [art-direction workflow](art-direction.md) adds actual pixel assessment
  and distinct agent curation for internal drafts. Human commercial review remains
  essential; unavailable vision never grants visual acceptance.
- Pixabay and Pexels are implemented. Credentials, account quota and current provider availability
  must be verified in an authorized runtime before live API use.
- System fonts vary by operating system. Browser evidence covers Chromium, not a claim
  of manual screen-reader or Safari/Firefox certification.
- An explicit empty inventory is permitted only for typography pages; any unlisted
  file still fails artifact capture. Empty-asset snapshots retain the assets directory.
- New stock manifests require reviewed provenance. Older manually licensed stock
  lacking it must be reviewed again; no evidence is fabricated or auto-migrated.
- Search caches/receipts and reviewed inventories have no automatic pruning service.
  Filesystem operations recover from caught failures; they do not add a crash-recovery
  journal to the existing artifact lifecycle.
