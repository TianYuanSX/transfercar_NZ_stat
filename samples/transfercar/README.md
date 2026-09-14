# Listing response fixtures

These two small JSON responses were supplied from browser inspection during development. They support parser tests and an explicitly synthetic demo. They do not constitute a complete collection or a daily historical snapshot.

| Fixture | Provenance | Records | Metadata | Page quantity |
| --- | --- | --- | --- | --- |
| `queenstown-page-1.json` | Browser Network response; HTTP 200 reported | 10 | offset 1, limit 10, count 101, sum 403 | 95 |
| `queenstown-page-2.json` | Subsequent raw JSON attachment; page 2 inferred from context | 10 | offset 2, limit 10, count 101, sum 403 | 57 |

The first request URL was:

```text
https://www.transfercar.co.nz/api-endpoint/listings.json?pickup=custom%3Aqueenstown&page=1&limit=10&featured=0&sort=pickup_date&direction=asc
```

Both fixtures were received on 2026-09-14 according to the development environment's date. The exact original response times were not supplied; receipt dates must not be used as genuine collection timestamps. The second attachment did not separately include its request URL or status code.

The two files contain 20 distinct IDs and a combined `nb_listings` sum of 152. They cover only two of the eleven expected pages and were not taken as one atomic snapshot. Validating them as a complete batch is expected to fail.

The files contain public listing data, without request credentials. Tests use separately labelled synthetic complete scopes where necessary; the demo always writes to the `demo` source. See [API findings](../../docs/api-discovery.md) for pagination and field semantics.
