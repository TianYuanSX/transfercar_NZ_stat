-- Keep ingestion data outside Supabase's default exposed public schema.
CREATE SCHEMA IF NOT EXISTS transfercar;
REVOKE ALL ON SCHEMA transfercar FROM PUBLIC;

CREATE TABLE transfercar.ingestion_runs (
    run_id UUID PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('transfercar', 'demo')),
    scope JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'incomplete', 'failed')),
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    expected_count INTEGER,
    reported_sum INTEGER,
    record_count INTEGER NOT NULL DEFAULT 0,
    observed_sum INTEGER,
    page_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    parser_version TEXT NOT NULL,
    CHECK (status <> 'succeeded' OR
        (finished_at IS NOT NULL AND expected_count = record_count AND error IS NULL))
);

CREATE TABLE transfercar.raw_responses (
    response_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES transfercar.ingestion_runs(run_id),
    attempt INTEGER NOT NULL,
    page INTEGER NOT NULL,
    request_attempt INTEGER NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    http_status INTEGER NOT NULL,
    request_params JSONB NOT NULL,
    body TEXT NOT NULL,
    checksum TEXT NOT NULL,
    UNIQUE (run_id, attempt, page, request_attempt)
);

CREATE TABLE transfercar.listings (
    source TEXT NOT NULL,
    listing_id BIGINT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source, listing_id),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE TABLE transfercar.listing_observations (
    run_id UUID NOT NULL REFERENCES transfercar.ingestion_runs(run_id),
    source TEXT NOT NULL,
    listing_id BIGINT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    pickup_location TEXT NOT NULL,
    dropoff_location TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    pickup_date TIMESTAMPTZ NOT NULL,
    dropoff_date TIMESTAMPTZ NOT NULL,
    free_days INTEGER NOT NULL CHECK (free_days >= 0),
    price_per_free_day NUMERIC NOT NULL CHECK (price_per_free_day >= 0),
    paid_days INTEGER CHECK (paid_days >= 0),
    price_per_paid_day NUMERIC CHECK (price_per_paid_day >= 0),
    nb_listings INTEGER NOT NULL CHECK (nb_listings >= 0),
    status INTEGER NOT NULL,
    status_name TEXT NOT NULL,
    is_closed BOOLEAN NOT NULL,
    is_ghost_listing BOOLEAN NOT NULL,
    great_deal BOOLEAN NOT NULL,
    nb_pending_requests INTEGER NOT NULL CHECK (nb_pending_requests >= 0),
    inclusions JSONB NOT NULL,
    closed_times JSONB NOT NULL,
    image_path TEXT,
    resource_url TEXT,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, listing_id),
    FOREIGN KEY (source, listing_id) REFERENCES transfercar.listings(source, listing_id)
);

CREATE INDEX observations_history_idx
    ON transfercar.listing_observations(source, listing_id, observed_at DESC);
CREATE INDEX runs_history_idx
    ON transfercar.ingestion_runs(source, started_at DESC) WHERE status = 'succeeded';

-- A day's snapshot is its latest successful batch, never a union across batches.
CREATE VIEW transfercar.daily_runs AS
SELECT DISTINCT ON (source, scope, (started_at AT TIME ZONE 'Pacific/Auckland')::date)
    run_id, source, scope,
    (started_at AT TIME ZONE 'Pacific/Auckland')::date AS observation_day,
    started_at, finished_at, record_count, reported_sum, observed_sum
FROM transfercar.ingestion_runs
WHERE status = 'succeeded'
ORDER BY source, scope, (started_at AT TIME ZONE 'Pacific/Auckland')::date,
         started_at DESC, run_id DESC;

CREATE VIEW transfercar.daily_metrics AS
SELECT d.*, COALESCE(a.route_count, 0) AS route_count
FROM transfercar.daily_runs d
LEFT JOIN (
    SELECT run_id, count(DISTINCT (pickup_location, dropoff_location)) AS route_count
    FROM transfercar.listing_observations GROUP BY run_id
) a USING (run_id);

