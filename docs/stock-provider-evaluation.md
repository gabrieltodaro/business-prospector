# Stock provider evaluation — November 7, 2026

Selected **Pixabay** for individual, human-requested website compositions. Its local
hosting model fits our immutable reviewed assets; Pexels remains optional.

| Requirement | Pixabay | Unsplash |
|---|---|---|
| Public key availability | API docs currently offer login/signup to obtain a key. | Developer registration and new demo applications remain documented. |
| Free access | Default 100 requests/60 seconds; mandatory 24-hour cache, human requests only, no systematic downloads. Standard image endpoint suffices; full-resolution access needs approval. | Demo: 50 requests/hour for testing/personal use. Public applications should apply for Production and demonstrate compliance. |
| Commercial previews | Content License allows commercial compositions, subject to exclusions. | General license allows commercial use; API obligations also apply. |
| Attribution | License credit optional; API requests source identification in search results. We show provider/photographer credits in both review and generated pages. | API requires photographer/Unsplash links with referral parameters. |
| Tracking | No separate download-event callback is documented. | Must call the returned download endpoint when selecting an image for use. |
| Hosting | Temporary search hotlinks allowed; permanent hotlinks prohibited. Download selected images to own hosting. | API images must remain hotlinked, including final uses. This conflicts with our local deployment inventory. |

Sources: [Pixabay API](https://pixabay.com/api/docs/),
[Pixabay Content License and terms](https://pixabay.com/service/terms/),
[Unsplash documentation](https://unsplash.com/documentation),
[Unsplash API guidelines](https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines),
[Unsplash production access](https://help.unsplash.com/en/articles/3887917-when-should-i-apply-for-a-higher-rate-limit),
[Unsplash license](https://unsplash.com/license).

This checks published access instructions, not account-specific key issuance: no
account was created, terms accepted, key requested or authenticated API call made.
Configure `PIXABAY_API_KEY` and optionally `BUSINESS_PROSPECTOR_STOCK_PROVIDER=pixabay`
in the authorized runtime before use. See [workflow/configuration](premium-generation.md#explicit-mcp-workflow).

The suitability decision assumes an original website composition, not standalone
photo resale or a stock library. Review must exclude commercial logos/brands,
misleading endorsements and unsuitable identifiable people, and establish any
necessary third-party permissions. Pixabay does not guarantee those permissions.
Photos stay explicitly illustrative and receive only draft approval on ingestion.
Commercial approval and publication still require the existing separate checks.

No database migration or deployment is required for this code change. Existing
reviewed Pexels assets and provenance remain usable; new provider selection applies
to searches/downloads. No automatic provider failover occurs.
