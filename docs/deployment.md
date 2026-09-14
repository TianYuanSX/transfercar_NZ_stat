# Deployment and recovery

The repository contains separate workflows for CI, collection, image publication, and dashboard deployment. Supabase stores the data; a separate host runs Streamlit. Complete each stage before enabling the next one.

## 1. GitHub and CI

Push the project to `main` and check the **CI** workflow. It installs the pinned dependencies, runs Ruff and tests against a temporary PostgreSQL 16 service, and builds `deploy/Dockerfile`. CI does not require Supabase credentials.

## 2. Supabase database

Use the project's Connect panel to obtain a direct PostgreSQL URI or a **Session pooler** URI. Session pooling supports IPv4 and retains the connection semantics required by advisory locks. Do not use the Transaction pooler for this collector. See [Supabase's connection documentation](https://supabase.com/docs/guides/database/connecting-to-postgres).

1. Configure the migration owner's `DATABASE_URL` locally, with TLS and a URL-encoded password.
2. Run `transfercar migrate` to create the private schema and migration ledger.
3. Apply `deploy/roles.sql` as an administrator. It creates the non-login roles `transfercar_reader` and `transfercar_writer`.
4. Create separate login accounts and grant the corresponding role. Keep the migration owner separate from everyday collection and dashboard use.
5. Verify the writer can collect and the reader can query the resulting history. The dashboard accepts `DASHBOARD_DATABASE_URL`; all its queries run in read-only transactions.

The application uses SQL connections, not Supabase API keys. Do not expose the `transfercar` schema through the Data API. Apply migration changes as new numbered files; previously applied checksums must remain unchanged. Configure production database backups separately.

## 3. GitHub Actions collection

In repository **Settings → Secrets and variables → Actions**, add the writer connection as the `DATABASE_URL` secret. See [GitHub's Actions secrets documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

Manually run **Collect observations** first. Confirm that the source is reachable from the runner and that a successful batch appears in PostgreSQL. Then set the repository variable `ENABLE_COLLECTION` to `true` to enable daily collection at 19:17 UTC. Set it to `false` to skip future scheduled jobs.

A workflow rerun derives the same UUID from the repository and `github.run_id`. A new run gets a new UUID. The collector uses the writer account and does not run migrations automatically.

If a hosted runner receives 403, the batch remains unsuccessful. Leave scheduling disabled until collection works from an appropriate execution environment. Browser access does not prove that hosted runner access will work.

## 4. Dashboard host

The prepared deployment path targets a Linux host with Bash, Docker, curl, flock, and SSH on port 22. The deployment user needs Docker access and write access to `/opt/transfercar`. Public HTTPS access requires a reverse proxy in front of the dashboard's localhost port.

Create two files on the host with mode 600, in Docker env-file format (no `export` and no shell quotes):

```text
# /opt/transfercar/app.env
DATABASE_URL=postgresql://<reader-login>:<encoded-password>@<session-pooler>:5432/postgres?sslmode=require
```

```text
# /opt/transfercar/migration.env
DATABASE_URL=postgresql://<migration-owner>:<encoded-password>@<compatible-endpoint>:5432/postgres?sslmode=require
```

Use the actual URI supplied for your database account and endpoint. The reader role also has access to the migration ledger for the database readiness check. If the image is private, authenticate the host to GHCR before deployment.

## 5. Publish and deploy

1. Run **Publish application image** manually or push a `v*` tag. The workflow runs CI before publishing a GHCR image tagged with the full commit SHA.
2. Create a GitHub `production` environment with `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, and `DEPLOY_KNOWN_HOSTS` secrets. Use a verified host key in `DEPLOY_KNOWN_HOSTS`; host verification stays enabled.
3. Manually run **Deploy dashboard** with `ghcr.io/tianyuansx/transfercar_nz_stat:<40-character-commit-sha>`.

The workflow sends `deploy/deploy.sh` to the host over SSH. The script takes a host lock, pulls the image, applies migrations with the owner connection, checks schema access with the reader connection, replaces the container, and polls its health endpoint. The container binds to `127.0.0.1:8501` on the host.

The same script can be run directly on the host:

```bash
bash deploy/deploy.sh ghcr.io/tianyuansx/transfercar_nz_stat:<40-character-commit-sha>
```

Replace the angle-bracket placeholder before running the command. This deployment briefly interrupts the application while replacing the container.

## Recovery

A migration error stops deployment before the old application is replaced. An application startup or health-check failure restores the previous container when one exists. A first deployment has no previous container to restore.

Successful database migrations are retained when the application rolls back. Subsequent migrations must therefore remain compatible with the previous application version. Destructive schema changes require a separately planned backup and recovery procedure.

Tests cover publication rollback, collection retries, idempotency, and simulated deployment success/failure paths. A configured remote host still needs a real deployment and recovery exercise before its behaviour is considered verified.
