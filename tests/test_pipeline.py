import copy
from datetime import date, datetime, timezone
from uuid import uuid4

import httpx
import pytest

from transfercar import db, queries
from transfercar.pipeline import CollectionError, HTTPFetcher, MemoryFetcher, collect

SCOPE = {"pickup": "custom:queenstown", "limit": 1}
AT = datetime(2026, 9, 15, 0, tzinfo=timezone.utc)


@pytest.mark.integration
def test_immutable_replay_history_and_atomic_failure(conn, small_pages):
    run_id = uuid4()
    fetch = MemoryFetcher(small_pages, AT, SCOPE)
    collect(conn, fetch, SCOPE, run_id=run_id, started_at=AT)
    assert collect(conn, fetch, SCOPE, run_id=run_id)["status"] == "already_succeeded"
    assert (
        conn.execute("SELECT count(*) AS n FROM transfercar.listing_observations").fetchone()["n"]
        == 2
    )
    assert db.migrate(conn) == []

    tomorrow = AT.replace(day=16)
    changed = copy.deepcopy(small_pages)
    changed[0]["listings"][0]["nb_listings"] = 1
    collect(conn, MemoryFetcher(changed, tomorrow, SCOPE), SCOPE, started_at=tomorrow)
    rows = conn.execute(
        """
        SELECT nb_listings FROM transfercar.listing_observations
        WHERE listing_id=%s ORDER BY observed_at
    """,
        (small_pages[0]["listings"][0]["id"],),
    ).fetchall()
    assert [r["nb_listings"] for r in rows] == [4, 1]
    failed_id = uuid4()
    with pytest.raises(CollectionError, match="incomplete"):
        collect(conn, MemoryFetcher(small_pages[:1], AT, SCOPE), SCOPE, run_id=failed_id)
    assert queries.snapshot(conn, failed_id) == []
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM transfercar.raw_responses WHERE run_id=%s", (failed_id,)
        ).fetchone()["n"]
        == 1
    )
    # Retry same logical batch, preserve failed raw attempt, publish once.
    collect(conn, fetch, SCOPE, run_id=failed_id, started_at=AT)
    assert (
        conn.execute(
            "SELECT attempt FROM transfercar.ingestion_runs WHERE run_id=%s", (failed_id,)
        ).fetchone()["attempt"]
        == 2
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM transfercar.raw_responses WHERE run_id=%s", (failed_id,)
        ).fetchone()["n"]
        == 3
    )


@pytest.mark.integration
def test_date_view_latest_batch_nz_timezone_and_missing_vs_zero(conn, small_pages):
    # 13:00 UTC is next day in NZ before DST. A later successful run wins.
    start = datetime(2026, 9, 14, 13, tzinfo=timezone.utc)
    collect(conn, MemoryFetcher(small_pages, start, SCOPE), SCOPE, started_at=start)
    later = start.replace(hour=14)
    empty = [{"listings": [], "offset": 1, "limit": 1, "count": 0, "sum": 0}]
    result = collect(conn, MemoryFetcher(empty, later, SCOPE), SCOPE, started_at=later)
    failed_at = start.replace(hour=15)
    with pytest.raises(CollectionError):
        collect(conn, MemoryFetcher(small_pages[:1], failed_at, SCOPE), SCOPE, started_at=failed_at)
    rows = queries.daily(conn, "transfercar", SCOPE, date(2026, 9, 14), date(2026, 9, 16))
    assert [r["record_count"] for r in rows] == [None, 0, None]
    assert str(rows[1]["run_id"]) == result["run_id"]
    assert (
        queries.daily(conn, "demo", SCOPE, date(2026, 9, 15), date(2026, 9, 15))[0]["run_id"]
        is None
    )


@pytest.mark.integration
def test_publish_rollback_does_not_leave_entities(conn, small_pages, monkeypatch):
    original = db.publish

    def broken(connection, run_id, source, rows, pagination):
        # Force a DB constraint failure after entity upserts; everything must roll back.
        rows[1]["free_days"] = -1
        original(connection, run_id, source, rows, pagination)

    monkeypatch.setattr(db, "publish", broken)
    with pytest.raises(CollectionError, match="failed"):
        collect(conn, MemoryFetcher(small_pages, AT, SCOPE), SCOPE, started_at=AT)
    assert conn.execute("SELECT count(*) AS n FROM transfercar.listings").fetchone()["n"] == 0
    assert (
        conn.execute("SELECT count(*) AS n FROM transfercar.listing_observations").fetchone()["n"]
        == 0
    )


@pytest.mark.integration
def test_never_requests_repeated_out_of_range_page(conn, small_pages):
    requested = []
    fetch = MemoryFetcher(small_pages, AT, SCOPE)

    def tracked(page, archive):
        requested.append(page)
        return fetch(page, archive)

    collect(conn, tracked, SCOPE, started_at=AT)
    assert requested == [1, 2]


def test_http_403_archived_once_without_retry():
    fetch = HTTPFetcher(SCOPE)
    fetch.client.close()
    fetch.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, text="<html>challenge</html>")
        )
    )
    archive = []
    try:
        with pytest.raises(CollectionError, match="403"):
            fetch(1, archive.append)
        assert len(archive) == 1
        assert archive[0].status == 403
    finally:
        fetch.close()
