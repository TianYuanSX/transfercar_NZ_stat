"""PostgreSQL persistence, atomic publication, and checksum-verified migrations."""

import hashlib
import json
import os
from datetime import datetime, timezone
from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from transfercar import __version__


def connect(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL first; see .env.example")
    return psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=15)


def migrate(conn) -> list[str]:
    applied = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(73821951)")
        conn.execute("CREATE SCHEMA IF NOT EXISTS transfercar")
        conn.execute("REVOKE ALL ON SCHEMA transfercar FROM PUBLIC")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transfercar.schema_migrations (
                name TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        for path in sorted(files("transfercar").joinpath("migrations").iterdir(), key=str):
            if not path.name.endswith(".sql"):
                continue
            body = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(body.encode()).hexdigest()
            old = conn.execute(
                "SELECT checksum FROM transfercar.schema_migrations WHERE name = %s",
                (path.name,),
            ).fetchone()
            if old:
                if old["checksum"] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}")
                continue
            conn.execute(body)
            conn.execute(
                "INSERT INTO transfercar.schema_migrations(name, checksum) VALUES (%s, %s)",
                (path.name, checksum),
            )
            applied.append(path.name)
    return applied


def scope_key(source: str, scope: dict) -> str:
    return source + ":" + json.dumps(scope, sort_keys=True, separators=(",", ":"))


def acquire(conn, key: str) -> bool:
    return conn.execute(
        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked", (key,)
    ).fetchone()["locked"]


def release(conn, key: str) -> None:
    conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,))


def start_run(conn, run_id, source: str, scope: dict, started_at: datetime) -> int | None:
    with conn.transaction():
        row = conn.execute(
            "SELECT * FROM transfercar.ingestion_runs WHERE run_id = %s FOR UPDATE", (run_id,)
        ).fetchone()
        if row:
            if row["source"] != source or row["scope"] != scope:
                raise ValueError("run_id already belongs to a different source/scope")
            if row["status"] == "succeeded":
                return None  # Published batches are immutable; replay is a no-op.
            conn.execute(
                """
                UPDATE transfercar.ingestion_runs
                SET status='running', attempt=attempt+1, started_at=%s, finished_at=NULL,
                    expected_count=NULL, reported_sum=NULL, observed_sum=NULL,
                    record_count=0, page_count=0, error=NULL, parser_version=%s
                WHERE run_id=%s
            """,
                (started_at, __version__, run_id),
            )
            return row["attempt"] + 1
        conn.execute(
            """
            INSERT INTO transfercar.ingestion_runs
                (run_id, source, scope, status, started_at, parser_version)
            VALUES (%s, %s, %s, 'running', %s, %s)
        """,
            (run_id, source, Jsonb(scope), started_at, __version__),
        )
        return 1


def archive(conn, run_id, attempt: int, page: int, response) -> None:
    conn.execute(
        """
        INSERT INTO transfercar.raw_responses
            (run_id, attempt, page, request_attempt, fetched_at, http_status,
             request_params, body, checksum)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """,
        (
            run_id,
            attempt,
            page,
            response.request_attempt,
            response.fetched_at,
            response.status,
            Jsonb(response.params),
            response.body,
            hashlib.sha256(response.body.encode()).hexdigest(),
        ),
    )


def publish(conn, run_id, source: str, rows: list[dict], pagination) -> None:
    pagination.finish()
    with conn.transaction():
        for row in rows:
            conn.execute(
                """
                INSERT INTO transfercar.listings
                    (source, listing_id, first_seen_at, last_seen_at)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (source, listing_id) DO UPDATE SET
                    first_seen_at = LEAST(transfercar.listings.first_seen_at,
                                          EXCLUDED.first_seen_at),
                    last_seen_at = GREATEST(transfercar.listings.last_seen_at,
                                            EXCLUDED.last_seen_at)
            """,
                (source, row["listing_id"], row["observed_at"], row["observed_at"]),
            )
        if rows:
            columns = ["run_id", "source", *rows[0].keys()]
            query = sql.SQL("INSERT INTO transfercar.listing_observations ({}) VALUES ({})").format(
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns),
            )
            values = []
            for row in rows:
                data = {"run_id": run_id, "source": source, **row}
                values.append(
                    [
                        Jsonb(data[k]) if k in ("inclusions", "closed_times") else data[k]
                        for k in columns
                    ]
                )
            with conn.cursor() as cur:
                cur.executemany(query, values)
        conn.execute(
            """
            UPDATE transfercar.ingestion_runs SET
                status='succeeded', finished_at=%s, record_count=%s, page_count=%s,
                expected_count=%s, reported_sum=%s, observed_sum=%s, error=NULL
            WHERE run_id=%s
        """,
            (
                datetime.now(timezone.utc),
                len(rows),
                pagination.pages,
                pagination.metadata[1],
                pagination.metadata[2],
                sum(row["nb_listings"] for row in rows),
                run_id,
            ),
        )


def fail(conn, run_id, status: str, error: str, pages: int) -> None:
    conn.execute(
        """
        UPDATE transfercar.ingestion_runs
        SET status=%s, error=%s, finished_at=%s, page_count=%s WHERE run_id=%s
    """,
        (status, error, datetime.now(timezone.utc), pages, run_id),
    )
