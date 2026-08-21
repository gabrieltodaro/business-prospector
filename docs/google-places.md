# Google Places discovery

`GooglePlacesBusinessDiscoveryProvider` uses only Places API (New) Text Search:

```text
POST https://places.googleapis.com/v1/places:searchText
X-Goog-Api-Key: value from GOOGLE_MAPS_API_KEY
X-Goog-FieldMask: places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.primaryType,places.rating,places.userRatingCount,places.websiteUri,places.nationalPhoneNumber,nextPageToken
```

The key is sent only in the header. It is never placed in the URL, returned by MCP, persisted, or logged. The request body uses `languageCode: pt-BR`, `regionCode: BR`, a bounded `pageSize`, and a generic query such as `dentistas em Catanduva, SP, Brasil`.

## Fields and cost

| Field | Purpose | Text Search SKU tier |
| --- | --- | --- |
| `places.id` | Strongest deduplication identifier | Essentials ID Only |
| `places.displayName` | Business name | Pro |
| `places.formattedAddress` | Lead metadata and fallback deduplication | Pro |
| `places.googleMapsUri` | Public source link | Pro |
| `places.primaryType` | Google business category | Pro |
| `places.rating` | Existing reputation filter and scoring | Enterprise |
| `places.userRatingCount` | Existing reputation filter and scoring | Enterprise |
| `places.websiteUri` | Required input for website assessment | Enterprise |
| `places.nationalPhoneNumber` | Existing contactability metadata | Enterprise |
| `nextPageToken` | Fetch only enough pages to satisfy the bounded limit | Essentials ID Only |

Because the mask requests rating, review count, website, and phone, the request triggers the **Text Search Enterprise SKU**. Removing only phone would not lower the tier while the other Enterprise fields remain. The MVP makes no Place Details call and requests no photos, hours, reviews, atmosphere, accessibility, or location data. Each additional page is a separate billable Text Search request, so the provider stops as soon as the requested limit is met.

Check current pricing before production volume at the official [Place Data Fields](https://developers.google.com/maps/documentation/places/web-service/data-fields) and [Places billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing) pages.

## Configuration and smoke test

The OpenClaw gateway process must receive `GOOGLE_MAPS_API_KEY`. Never write its value into this repository.

One controlled request, returning at most one candidate:

```bash
python -m business_prospector.google_places_smoke \
  --niche dentistas \
  --city 'Catanduva, SP' \
  --limit 1
```

Through OpenClaw/Oliver, first call `google_places_status`, then ask:

```text
Oliver, use business-prospector__prospect_places to search for 1 dentist in Catanduva, SP. Do not contact anyone and do not assess or save the result.
```

`prospect_places` performs real Google discovery only. Website assessment remains fixture-backed, so it deliberately returns `website_assessment: not_run` and saves no leads. `prospect_fake` remains the deterministic full offline pipeline.

## Troubleshooting

- `403`: confirm Places API (New) is enabled, billing is active, the key permits Places API (New), and the Mac Mini's key restrictions match the request environment.
- `429`: inspect the project's quota and billing limits, reduce request frequency, and avoid unnecessary pagination. The provider does not retry automatically.
- `Google Places API is not configured.`: make `GOOGLE_MAPS_API_KEY` available to the OpenClaw gateway process and restart the gateway.
