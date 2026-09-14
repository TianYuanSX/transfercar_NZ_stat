# Architecture and data semantics

## Pipeline

The CLI fetches public listing pages, archives every HTTP response, validates the complete traversal, and publishes one batch to PostgreSQL. Streamlit queries successful batches through read-only transactions. GitHub Actions runs the same CLI; it does not commit collected records into the repository.

The application uses a private `transfercar` schema. SQL migrations are bundled with the Python package under `src/transfercar/migrations`, so the CLI works both from a checkout and inside the container.

## Identity and history

| Object | Key | Responsibility |
| --- | --- | --- |
| `ingestion_runs` | `run_id` | Source, exact request scope, attempt number, timestamps, status, and validation metrics |
| `raw_responses` | `response_id`; unique run/attempt/page/request attempt | Original text, request parameters, HTTP status, timestamp, and checksum |
| `listings` | `(source, listing_id)` | Stable identity and earliest/latest successful observation timestamps |
| `listing_observations` | `(run_id, listing_id)` | All parsed business fields as observed in that batch |
| `schema_migrations` | Migration filename | Applied SQL checksum and application timestamp |

Updating an entity's `last_seen_at` never overwrites its historical observations. New runs append observations even when business fields have not changed. This makes the meaning of a daily snapshot explicit without reconstructing state from change events.

Prices use PostgreSQL `NUMERIC`; missing optional values remain NULL. `inclusions` and `closed_times` use JSONB. The original response preserves unrecognised fields and the distinction between an absent key and an explicit JSON null. The API resource URL and human-readable listing URL have different purposes.

## Publication and recovery

1. Acquire session advisory locks for the logical run and source/scope. Concurrent collection of that run or scope is rejected.
2. Create a `running` record, or increment the attempt of an existing unsuccessful run. A previously successful UUID returns without fetching or publishing again.
3. Fetch and archive each request attempt before parsing its body. Transient retries also leave a raw response record when a response is available.
4. Validate page metadata, expected sizes, unique IDs, and traversal completeness. Stop at the computed final page or the independent safety limit.
5. In one transaction, upsert entity timestamps, insert observations, and mark the run `succeeded`. A database error rolls back all three changes.
6. On failure, retain the raw archive and mark the batch `failed` or `incomplete`. The dashboard continues to use complete batches.

A process killed before cleanup may leave a `running` record. Retrying with the same UUID starts another attempt after the previous connection has released its locks. Previous raw responses remain queryable, while the run record describes the current attempt.

HTTP 401/403/429 stop collection. Network errors and 5xx responses have at most three request attempts. Requests are paced by the collector. The source is mutable, so a traversal passing these checks still does not prove that all pages came from one atomic upstream snapshot.

Migration files are checksum-verified and applied transactionally under a migration lock. Add a new numbered file for schema changes; do not edit an applied migration. Collection requires a direct PostgreSQL connection or a Session pooler because its locks must stay on one server session.

## Time and aggregation

- The batch's `started_at`, converted to `Pacific/Auckland`, determines its observation day. Individual rows also retain the actual page fetch time. A batch spanning midnight belongs to its start day.
- `pickup_date` and `dropoff_date` are rental-related source values, not collection timestamps or verified publication dates.
- `daily_runs` chooses the last successful batch per source, exact scope, and NZ day. `daily_metrics` adds route counts. Different scopes are never unioned into one daily inventory.
- Daily snapshot mode can select a specific successful batch. Period average mode uses the last complete batch on each day.
- A missing route on a complete day contributes zero. A day without a complete collection is excluded from the average's denominator. A successful empty batch is a valid zero.
- The source field `nb_listings` is summed as **source quantity**. Its business unit has not been verified as individual vehicles. Disappearance from a snapshot is not evidence of a booking.

## Map and listing links

Route endpoints use reviewed GeoNames city/airport reference points. Each route has parallel curved paths scaled by source quantity and arrows from pickup to dropoff. Latitude determines colour: blue southbound, green northbound, grey at the same latitude or for local loops. Reverse routes use separate curves. A rendering budget raises the shared units-per-line scale when needed and reports it in the legend.

Unknown endpoints are reported and omitted from map geometry, while their records remain in tables and totals. These points represent localities or airports rather than exact depots. Provenance and the source archive checksum are stored in `src/transfercar/data/nz_locations.json`; update the catalog with `scripts/build_location_catalog.py` after reviewing new GeoNames IDs.

Web links use the newest successful live collection that covers the selected pickup/dropoff scope, regardless of the historical date currently displayed. A later nationwide batch may supersede an older city batch. Failed runs do not affect this check, and synthetic data never receives live links. The latest observed location names form the URL; no per-row detail-page request is made.

## Validation and operating boundaries

The test suite uses real partial fixtures plus explicitly synthetic complete scopes. Integration tests use a disposable PostgreSQL database ending in `_test`; they rebuild the application schema. Streamlit tests exercise the moved `apps/dashboard.py` entry point. Deployment tests simulate Docker and HTTP to verify control flow, rather than asserting that a production host exists.

Daily snapshots cannot recover intraday changes. Raw responses currently remain in PostgreSQL text columns; retention, backups, and object-storage archival should be configured as the dataset grows. Database migrations and app rollback are separate concerns: reverting a container does not revert a successful migration.
