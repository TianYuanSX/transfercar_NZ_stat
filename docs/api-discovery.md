# Transfercar API findings

These findings combine browser-provided fixtures and implementation-time checks. They describe observed behaviour, not a published API contract. The small committed fixtures have no precise original observation timestamp and are not imported as complete live history.

## Listing endpoint

```text
GET https://www.transfercar.co.nz/api-endpoint/listings.json
    ?page=1&limit=100&featured=0&sort=pickup_date&direction=asc
```

Omitting pickup and dropoff filters returns the public New Zealand search results. Optional examples are `pickup=custom:queenstown` and `dropoff=custom:auckland`. The meaning of `featured=0` is unverified; it is retained from the observed browser request.

The search page is HTML and loads listings separately. Its `sort=earliest_pickup_date` parameter differs from the observed JSON endpoint's `sort=pickup_date`; page URL parameters should not be assumed equivalent to API parameters. The `_links` host `api.transfercar.co.nz` is also distinct from the browser's endpoint.

## Pagination evidence

| Observation | Result |
| --- | --- |
| Queenstown fixture page 1 | 10 records, `offset=1`, `limit=10`, `count=101`, `sum=403` |
| Queenstown fixture page 2 | 10 different records, `offset=2`, same limit/count/sum |
| Browser-reported pages 11 and 12 | Both contained listing 673562; only `offset` changed |
| Online request with `limit=100` | Server used an effective `limit=50` |
| Complete Queenstown traversal | 3 pages, 101 unique listing IDs, summed `nb_listings=403` |
| Complete unfiltered traversal | 4 pages, 170 unique IDs, summed `nb_listings=753`, 31 routes, 21 location names |

The complete traversals were observed during local implementation on 2026-09-14; these counts are historical examples, not current availability. Other attempts encountered duplicate IDs across page boundaries and were correctly left incomplete. Requests using `sort=id` and `sort=dropoff_date` did not establish those sort orders as supported.

The collector uses the response's effective limit to compute the expected final page. It checks stable metadata, expected page sizes, unique IDs, and total count, with a separate page ceiling. It never keeps requesting pages until an empty array appears. `SUM(nb_listings)` is stored alongside the source's `sum` for diagnosis; the business unit remains unverified.

Browser-reported pages 11 and 12 were pasted through Markdown escaping. They are evidence for a boundary regression scenario, not raw JSON fixtures. Tests constructing this scenario are explicitly synthetic.

## Important fields

| Source field | Interpretation in this project |
| --- | --- |
| `id` | Source listing identity, not an individual vehicle identifier |
| `pickup_location`, `dropoff_location` | Original names; a search code may cover more than one named location |
| `vehicle_type` | Source description, retained without inventing a vehicle identity |
| `pickup_date`, `dropoff_date` | Source timestamp values, distinct from observation time |
| `nb_listings`, `count`, `sum` | Source quantity and pagination metadata; not verified vehicle inventory |
| `free_days`, `price_per_free_day` | Independent fields; the name does not guarantee a zero price |
| `paid_days`, `price_per_paid_day` | Optional values; absent values stay NULL |
| `status`, `status_name`, `is_closed` | Observed state, without inferring an unsupported lifecycle |
| `nb_pending_requests` | Reported pending requests, not completed bookings |
| `inclusions`, `closed_times` | Original structured values stored as JSONB |
| `image_path`, `_links.self.href` | Original image/API URLs; images are not downloaded |

There is no top-level currency field in the fixtures. Currency references inside an inclusion description do not establish the currency of every price. Early pages have uniform pickup timestamps while the final page has a future timestamp; source dates must not be repurposed as listing creation or collection times. Allowed rental days must not be derived from the timestamp difference.

## Public listing links

The human-readable URL format is:

```text
https://www.transfercar.co.nz/relocation/{pickup}/{dropoff}/{listing_id}
```

Replace spaces in each location name with underscores, then URL-encode each path segment. Ordinary GET requests returned matching page titles for both examples during implementation:

- [Christchurch Airport to Auckland, 665951](https://www.transfercar.co.nz/relocation/Christchurch_Airport/Auckland/665951)
- [Queenstown Airport to Manurewa (Auckland), 673562](https://www.transfercar.co.nz/relocation/Queenstown_Airport/Manurewa_%28Auckland%29/673562)

The dashboard only creates links for IDs in a recent complete live scope covering the selection. This is an observation-based indication, not a real-time booking availability check.

## Access and fixtures

Early urllib/curl requests received Cloudflare 403 responses; later public HTTPX requests succeeded. The cause of the difference was not isolated, so hosted runner access needs its own manual validation. The collector stops on 401/403/429 and does not attempt to bypass challenges.

The [fixture notes](../samples/transfercar/README.md) document provenance. Only the two small listing response samples are committed; complete local response archives and database files are excluded.
