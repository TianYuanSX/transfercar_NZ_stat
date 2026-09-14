# Transfercar NZ Stat

[![CI](https://github.com/TianYuanSX/transfercar_NZ_stat/actions/workflows/ci.yml/badge.svg)](https://github.com/TianYuanSX/transfercar_NZ_stat/actions/workflows/ci.yml)

A Python data pipeline and Streamlit dashboard for exploring New Zealand vehicle relocation listings over time. Each complete collection adds a historical snapshot to PostgreSQL, so changes in routes, prices, quantities, and listing status remain queryable. The database can run locally or on Supabase.

This project demonstrates relational data modelling, SQL migrations, idempotent ingestion, data quality checks, integration testing, and GitHub Actions workflows for collection, CI, container publishing, and deployment.

## Features

- **Historical observations:** retain each listing's state per successful batch, with raw responses and failed attempts available for inspection.
- **Nationwide collection:** omit pickup/dropoff filters to collect the public search results across New Zealand, or select a smaller scope.
- **Route map:** filter by observation date, batch, period, pickup, and dropoff. Parallel lines represent source quantity; arrows show travel direction. North-to-south routes are blue, south-to-north routes green, and local routes grey.
- **Historical analysis:** daily snapshots, period averages, listing history, pipeline status, and CSV downloads. Missing observations remain distinguishable from a successful collection with zero results.
- **Listing links:** tables include a clickable link for IDs still present in the latest complete live collection covering the selected scope.
- **Reproducible demo:** seven days of explicitly synthetic history, including an intentional incomplete day, stored separately from live observations.

## Repository layout

```text
apps/                      Streamlit dashboard entry point
src/transfercar/            Collector, CLI, database access, queries, and map logic
  migrations/              Versioned SQL migrations with checksum verification
  data/                    GeoNames location reference points and provenance
tests/                     Unit, PostgreSQL integration, and dashboard tests
samples/transfercar/        Two small API fixtures used by tests and the demo
deploy/                    Dockerfile, Compose, database roles, and deployment script
scripts/                   Location reference data maintenance
docs/                      Architecture, API findings, and deployment instructions
.github/workflows/         CI, collection, image publishing, and deployment
```

Local database files, credentials, editor settings, caches, and generated exports are excluded from version control. The API fixtures are partial development samples, not a complete historical dataset.

## Quick start

Use Python 3.10 and PostgreSQL 14 or newer. Python 3.10 is the tested runtime for the pinned dependencies, CI, and container image. Run these commands from the repository root:

```bash
git clone git@github.com:TianYuanSX/transfercar_NZ_stat.git
cd transfercar_NZ_stat
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .

docker compose -f deploy/compose.yaml up -d --wait db
cp .env.example .env
set -a
source .env
set +a

transfercar migrate
transfercar demo
streamlit run apps/dashboard.py --browser.gatherUsageStats=false
```

Open <http://localhost:8501> and select **Synthetic demo** in the sidebar. Select **Live observations** after collecting real data. The `.env` file must be loaded into the shell as shown above; the CLI does not load it automatically.

For an existing PostgreSQL instance, skip the Compose database step and set `DATABASE_URL` to its connection URI before running migrations. The bundled Compose database and its example password are for local development.

To run the dashboard in Docker after initializing the database:

```bash
docker compose -f deploy/compose.yaml --profile app up -d --build dashboard
```

Migrations are an explicit command and do not run as a side effect of starting the dashboard.

## Collect observations

```bash
# All pickup and dropoff locations in the public search results.
transfercar collect

# Optional filters using the source's location codes.
transfercar collect --pickup custom:queenstown
transfercar collect --dropoff custom:auckland
transfercar collect --pickup custom:queenstown --dropoff custom:auckland

# Reuse a UUID when retrying the same logical collection.
transfercar collect --run-id 11111111-1111-4111-8111-111111111111
```

A new collection creates a new batch. Replaying a successful batch UUID is a no-op; retrying a failed batch preserves the previous raw responses and starts a new attempt. Only fully validated batches publish listing observations.

For offline validation and imports:

```bash
# Expected to fail completeness validation: these fixtures contain only 2 of 11 pages.
transfercar validate samples/transfercar/queenstown-page-1.json samples/transfercar/queenstown-page-2.json

# Supply all pages in order and the actual original observation timestamp.
transfercar import --pickup custom:queenstown \
  --observed-at '<original ISO-8601 timestamp with timezone>' \
  /path/to/page-1.json /path/to/page-2.json /path/to/remaining-pages.json
```

## Data model

All application tables live in the private `transfercar` schema.

| Table or view | Grain | Purpose |
| --- | --- | --- |
| `ingestion_runs` | One logical collection | Scope, attempts, status, timestamps, and quality metrics |
| `raw_responses` | One page response per request attempt | Original response text, parameters, HTTP status, and checksum |
| `listings` | Source + listing ID | Stable identity and first/last successful observation times |
| `listing_observations` | Batch + listing ID | Historical locations, dates, prices, quantities, status, and inclusions |
| `daily_runs` / `daily_metrics` | Source + scope + NZ date | Last successful batch of each day and its aggregate metrics |

Changing fields belong in `listing_observations`, so an update to today's listing does not overwrite yesterday's state. Observation dates use the batch start time in `Pacific/Auckland`; rental pickup/dropoff dates are separate source fields. Period averages use the latest successful batch per day and exclude days without a complete collection.

See [architecture and data semantics](docs/architecture.md) for transaction, concurrency, retry, and historical query details.

## Supabase

Use a PostgreSQL connection URI from the project's **Connect** panel. This collector uses session advisory locks, so choose a direct connection or the **Session pooler**, rather than the Transaction pooler. The Session pooler also supports IPv4 connections. See the [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).

1. Set `DATABASE_URL` with TLS enabled and a URL-encoded password.
2. Run `transfercar migrate` as the migration owner.
3. Apply [deploy/roles.sql](deploy/roles.sql) and grant its reader/writer roles to separate database login accounts.
4. Use the writer connection for collection and `DASHBOARD_DATABASE_URL` for the dashboard's reader connection. The dashboard falls back to `DATABASE_URL` if its separate variable is unset.

Database connections are server-side. The application does not need Supabase API keys or exposure of the `transfercar` schema through the Data API.

## Tests and automation

Integration tests recreate the `transfercar` schema. Use a disposable database whose name ends with `_test`:

```bash
docker compose -f deploy/compose.yaml exec db createdb -U transfercar transfercar_test
export TEST_DATABASE_URL='postgresql://transfercar:local_dev_only@localhost:5432/transfercar_test'
ruff check .
ruff format --check .
pytest -q
docker build -f deploy/Dockerfile -t transfercar:local .
```

Without `TEST_DATABASE_URL`, database and dashboard integration tests are skipped. CI supplies a temporary PostgreSQL 16 service and runs the full suite. Tests cover pagination boundaries, duplicate IDs, retries, transaction rollback, NULL preservation, daily snapshot selection, route geometry, listing links, Streamlit interactions, and deployment rollback using simulated Docker/HTTP.

| Workflow | Trigger | Configuration |
| --- | --- | --- |
| [CI](.github/workflows/ci.yml) | Pull requests and pushes to `main` | No production credentials required |
| [Collect observations](.github/workflows/collect.yml) | Manual; daily at 19:17 UTC when enabled | `DATABASE_URL` Actions secret; repository variable `ENABLE_COLLECTION=true` for scheduled runs |
| [Publish application image](.github/workflows/image.yml) | Manual or a `v*` tag | Built-in `GITHUB_TOKEN`; publishes to GHCR after CI passes |
| [Deploy dashboard](.github/workflows/deploy.yml) | Manual, with a full commit SHA image tag | Configured Docker host and `production` environment secrets |

Enable scheduled collection after migrations and a successful manual run from the runner. The schedule is 07:17 or 08:17 the next day in New Zealand, depending on daylight saving; actual execution can be delayed. Workflow reruns reuse a deterministic collection UUID.

The deployment workflow applies migrations, checks database access, replaces the application container, and restores the previous container if startup or health checks fail. Supabase configuration and a dashboard hosting environment are separate setup steps; workflow files alone do not constitute a deployed service. See the [deployment guide](docs/deployment.md).

## Source behaviour and limitations

- Pagination uses the response's effective page size and total count. The source has returned the last page again for out-of-range requests, so the collector does not rely on receiving an empty page to stop.
- Duplicate IDs, changing pagination metadata, short pages, and page limits prevent publication. Multi-page reads still cannot guarantee an atomic snapshot of a changing source.
- `nb_listings` is labelled **source quantity** because its exact business unit is unverified. An absent listing does not prove it was booked, and a live link indicates recent observation rather than a real-time availability check.
- HTTP 401, 403, and 429 stop a batch. Network failures and 5xx responses have bounded retries. Source access can differ between local machines and hosted runners.
- Once-daily snapshots cannot recover changes between collection windows. Raw response retention and archival will need a policy as the dataset grows.
- Map coordinates are approximate city/airport reference points, not rental depot addresses. Unknown locations remain in tables and totals and are reported as unmapped. The basemap requires browser network access.

See [API findings](docs/api-discovery.md) for the evidence behind the parser and pagination rules.

## License and attribution

Project code is distributed under the existing [MIT license](LICENSE). Location reference data is derived from [GeoNames](https://www.geonames.org/) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with record IDs and provenance in `src/transfercar/data/nz_locations.json`. Map tiles are supplied by CARTO and OpenStreetMap. Source API fixtures are third-party listing data; the code license does not relicense that data.
