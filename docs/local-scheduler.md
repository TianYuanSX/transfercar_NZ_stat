# Daily collection on a Linux host

Use the host's cron service when public source requests work from that host.
Collection writes directly to the Supabase writer connection. GitHub Actions
can continue to run CI and publish images independently.

## Prerequisites

- A running Cronie service, Bash, `flock`, and GNU `timeout`.
- The checkout and installed dependencies in its `.venv` directory.
- Applied database migrations and a writer login.
- A private `.local/supabase-runtime.env` containing `DATABASE_URL`.

The environment file contains shell assignments and is sourced by the script.
Use a quoted PostgreSQL URI with a URL-encoded password and TLS enabled. Keep the
file readable only by its owner (`chmod 600 .local/supabase-runtime.env`). It is
excluded from Git. Administrator credentials are not used for collection.

## Schedule

Add the following to the account's crontab with `crontab -e`, replacing the
checkout path. Preserve any existing tasks. Do not put database credentials in
the crontab.

```cron
CRON_TZ=Pacific/Auckland
17 7 * * * /bin/bash /absolute/path/to/repository/scripts/collect_daily.sh
```

This runs at **07:17 New Zealand local time** every day, including during daylight
saving. Quote a checkout path containing spaces. `CRON_TZ` applies to subsequent
entries, so restore any earlier timezone setting if other jobs follow this block.
See the [Cronie crontab reference](https://man7.org/linux/man-pages/man5/crontab.5.html).

The host must be running and connected to the network at the scheduled time.
Closing a terminal does not stop cron. Plain cron does not catch up a collection
missed while the host was off; run the script manually after recovery if needed.
Keep GitHub's `ENABLE_COLLECTION=false` while this host supplies the daily batch.

## Execution and recovery

```bash
# The same entry point used by cron; safe to invoke from any working directory.
bash scripts/collect_daily.sh

# Inspect the installed schedule.
crontab -l
```

The script loads the runtime connection, changes to the project root, and uses
the project's Python directly without depending on an interactive shell. A local
file lock prevents overlapping launches, and the collector also takes database
locks. Execution is limited to 20 minutes, with a further 30 seconds before forced
termination if needed.

Every NZ date maps to a deterministic batch UUID for the all-location scope.
Repeating the script after success returns `already_succeeded` without another
fetch or duplicate observations. Repeating an unsuccessful batch on the same day
creates a new attempt with the same UUID and keeps its earlier raw responses.
Retries are manual; HTTP 403 and incomplete traversals are recorded as failures.

Logs append to `.local/logs/collection/YYYY-MM-DD.log`, including the batch UUID,
collector result, and exit code. Exit code 0 indicates success or an overlap
skip; 124 indicates the execution time limit. Inspect the log and the dashboard's
Pipeline runs table when a collection fails. A forcibly interrupted process may
leave a `running` record until that logical batch is retried.

To pause the local schedule, remove or comment out only its cron entry using
`crontab -e`. Do not use `crontab -r` if other tasks exist. Moving the checkout
requires updating its absolute path in the crontab.
