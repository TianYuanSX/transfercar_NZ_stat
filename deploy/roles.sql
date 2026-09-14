-- Optional roles for a migration owner to apply after transfercar migrate.
-- These roles cannot log in. Create separate login users through your DB admin
-- and grant the corresponding role. Do not grant either role to anon/authenticated.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='transfercar_reader') THEN
        CREATE ROLE transfercar_reader NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='transfercar_writer') THEN
        CREATE ROLE transfercar_writer NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA transfercar TO transfercar_reader, transfercar_writer;
GRANT SELECT ON transfercar.ingestion_runs, transfercar.listings,
    transfercar.listing_observations, transfercar.daily_runs,
    transfercar.daily_metrics, transfercar.schema_migrations TO transfercar_reader;
GRANT SELECT, INSERT, UPDATE ON transfercar.ingestion_runs,
    transfercar.listings, transfercar.listing_observations TO transfercar_writer;
GRANT SELECT, INSERT ON transfercar.raw_responses TO transfercar_writer;
GRANT SELECT ON transfercar.schema_migrations TO transfercar_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA transfercar TO transfercar_writer;
