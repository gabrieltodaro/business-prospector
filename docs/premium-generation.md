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
| **Pexels** | Free API, orientation filters and resized image sources. General license permits commercial website use and local downloads; API guidance asks for prominent Pexels links and photographer credit. Default API limits are 200/hour and 20,000/month. No standalone resale, stock-library redistribution, implied endorsement or offensive treatment of identifiable people. | Primary adapter. Compatible with local, immutable, reviewed website assets. |
| Unsplash | API requires hotlinked returned image URLs, photographer/Unsplash attribution and download-event tracking. General license and API obligations are distinct. | Not implemented: mandatory hotlinking conflicts with the existing local-file inventory/publication model. |
| Pixabay | API permits local downloads; permanent image hotlinking is prohibited. Requires 24-hour search caching, prohibits systematic mass downloads; default limit is 100 requests/60 seconds. Its content license also restricts standalone distribution and certain trademark/person uses. | Viable alternative behind the provider port; not implemented or silently substituted. |

References: [Pexels API](https://www.pexels.com/api/documentation/),
[Pexels license](https://www.pexels.com/legal-pages/license/),
[Pexels commercial-use guidance](https://help.pexels.com/hc/en-us/articles/360042295214-Can-I-use-the-photos-and-videos-for-a-commercial-project),
[Unsplash API and hotlinking](https://unsplash.com/documentation),
[Pixabay API](https://pixabay.com/api/docs/),
[Pixabay license](https://pixabay.com/service/license-summary/).

Pexels credit is rendered beside each stock image and in a provider link in the
footer. Every stock image has a visible Portuguese illustrative-use disclosure;
no stock photo is labeled as the actual business, staff, customers or work. The
reviewer must assess relevance, context, logos/brands, identifiable people and
additional rights; an API result or a matching keyword is not proof of suitability.
This feature composes websites, not a stock gallery or a redistribution service.

## Explicit MCP workflow

Configure `PEXELS_API_KEY` in the authorized runtime environment. The existing
launcher can recover this single additional allowlisted variable from its normal
service-env mechanism; no credential is logged, passed in tool arguments or stored
in manifests. No paid service is mandatory. Missing configuration uses typography.
No operational configuration was changed while implementing this feature.

1. `search_stock_photos(lead_id, reviewed_content=null)` derives a bounded query from
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

`StockPhotoProvider` is the application port. `PexelsStockPhotoProvider` owns HTTP,
provider-specific parsing, a 24-hour disk search cache and persisted failure cooldown.
It honors longer `Retry-After` values, does not automatically retry, bounds request
size/time, rejects redirects, and limits downloads to the fixed Pexels image origin.
Only API requests receive the authorization header. Image MIME, signature, size,
checksum, inventory and no-follow path checks remain mandatory. The inventory update
uses immutable unique asset keys and atomic manifest replacement; failure preserves
previous entries and removes the new image. Generation still consumes local bytes.

Provider errors, irrelevant results and unsupported categories leave generation
available through typography. API search/download behavior is tested with injected
transports; no authenticated Pexels API request was made in this implementation run.

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

- Matching uses category/cuisine vocabulary, caption keywords and dimensions, not
  semantic image recognition. Human review remains essential; unknown niches receive
  typography. Query taxonomies can be extended without changing the renderer/provider.
- Only Pexels is implemented. Credentials, account quota and current provider availability
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
