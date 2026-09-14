"""All history queries isolate source + scope and exclude incomplete batches."""

from psycopg.types.json import Jsonb


def scopes(conn, source):
    return [
        r["scope"]
        for r in conn.execute(
            """SELECT scope FROM transfercar.ingestion_runs WHERE source=%s
               GROUP BY scope
               ORDER BY max(started_at) FILTER (WHERE status='succeeded') DESC NULLS LAST,
                        max(started_at) DESC""",
            (source,),
        ).fetchall()
    ]


def runs(conn, source, scope, start, end):
    return conn.execute(
        """
        SELECT run_id, started_at, finished_at, status, record_count, page_count,
               expected_count, reported_sum, observed_sum, attempt, error
        FROM transfercar.ingestion_runs
        WHERE source=%s AND scope=%s
          AND (started_at AT TIME ZONE 'Pacific/Auckland')::date BETWEEN %s AND %s
        ORDER BY started_at DESC, run_id DESC
    """,
        (source, Jsonb(scope), start, end),
    ).fetchall()


def daily(conn, source, scope, start, end):
    # LEFT JOIN preserves missing days as NULL; successful empty batches remain zero.
    return conn.execute(
        """
        SELECT days.day::date AS day, m.run_id, m.started_at, m.record_count,
               m.observed_sum, m.route_count
        FROM generate_series(%s::date::timestamp, %s::date::timestamp, interval '1 day') days(day)
        LEFT JOIN transfercar.daily_metrics m
          ON m.observation_day=days.day::date AND m.source=%s AND m.scope=%s
        ORDER BY day
    """,
        (start, end, source, Jsonb(scope)),
    ).fetchall()


def snapshot(conn, run_id):
    return conn.execute(
        """
        SELECT o.* FROM transfercar.listing_observations o
        JOIN transfercar.ingestion_runs r USING (run_id)
        WHERE o.run_id=%s AND r.status='succeeded'
        ORDER BY o.pickup_date, o.listing_id
    """,
        (run_id,),
    ).fetchall()


def history(conn, source, scope, listing_id, start, end):
    # Missing observations are explicit NULLs; never carry forward previous inventory.
    return conn.execute(
        """
        SELECT days.day::date AS day, d.run_id, o.listing_id, o.observed_at, o.nb_listings,
               o.status_name, o.price_per_free_day, o.free_days,
               o.pickup_date, o.dropoff_date
        FROM generate_series(%s::date::timestamp, %s::date::timestamp, interval '1 day') days(day)
        LEFT JOIN transfercar.daily_runs d
          ON d.observation_day=days.day::date AND d.source=%s AND d.scope=%s
        LEFT JOIN transfercar.listing_observations o
          ON o.run_id=d.run_id AND o.listing_id=%s
        ORDER BY day
    """,
        (start, end, source, Jsonb(scope), listing_id),
    ).fetchall()


def latest_link_observations(conn, source, scope):
    """Latest successful run covering this geographic scope, independent of UI dates.

    An unfiltered run may supersede an older city run. Pagination and sorting settings
    do not change coverage; featured selection does. Never link synthetic demo rows.
    """
    if source != "transfercar":
        return None, []
    latest = conn.execute(
        """
        SELECT run_id, started_at, finished_at FROM transfercar.ingestion_runs
        WHERE source=%s AND status='succeeded'
          AND COALESCE(scope->>'featured', '0') = %s
          AND (NULLIF(scope->>'pickup', '') IS NULL OR scope->>'pickup'=%s)
          AND (NULLIF(scope->>'dropoff', '') IS NULL OR scope->>'dropoff'=%s)
        ORDER BY started_at DESC, run_id DESC LIMIT 1
        """,
        (source, str(scope.get("featured", 0)), scope.get("pickup"), scope.get("dropoff")),
    ).fetchone()
    if latest is None:
        return None, []
    rows = conn.execute(
        """SELECT listing_id, pickup_location, dropoff_location
           FROM transfercar.listing_observations WHERE run_id=%s""",
        (latest["run_id"],),
    ).fetchall()
    return latest, rows


def route_averages(conn, source, scope, start, end):
    """Common denominator includes successful empty days and route-absent days.

    Missing/incomplete days are excluded. One batch per NZ day prevents double counting.
    """
    return conn.execute(
        """
        WITH chosen AS (
            SELECT run_id FROM transfercar.daily_runs
            WHERE source=%s AND scope=%s AND observation_day BETWEEN %s AND %s
        ), coverage AS (SELECT count(*) AS days FROM chosen)
        SELECT o.pickup_location AS pickup, o.dropoff_location AS dropoff,
               sum(o.nb_listings)::numeric / c.days AS quantity,
               count(*)::numeric / c.days AS listing_count,
               count(DISTINCT o.listing_id) AS distinct_listings,
               count(DISTINCT o.run_id) AS days_present, c.days AS complete_days
        FROM transfercar.listing_observations o JOIN chosen USING (run_id)
        CROSS JOIN coverage c
        GROUP BY o.pickup_location, o.dropoff_location, c.days
        ORDER BY quantity DESC, pickup, dropoff
        """,
        (source, Jsonb(scope), start, end),
    ).fetchall()
