import json
import math
from datetime import date, datetime, timezone

import pytest

from transfercar import queries, route_map
from transfercar.pipeline import MemoryFetcher, collect

AT = datetime(2026, 9, 15, tzinfo=timezone.utc)
SCOPE = {"pickup": "custom:queenstown", "limit": 1}


def test_snapshot_aggregation_lines_and_unknown_locations(samples):
    rows = samples[0]["listings"] + samples[1]["listings"]
    routes = route_map.aggregate_snapshot(rows)
    assert sum(r["quantity"] for r in routes) == 152
    data = route_map.geometry(routes)
    assert len(data["lines"]) == len(data["arrows"]) == 152
    assert not data["missing"]
    assert sum(line["represented_quantity"] for line in data["lines"]) == 152
    unknown = {"pickup": "Unmapped depot", "dropoff": "Picton", "quantity": 3, "listing_count": 1}
    missing = route_map.geometry([unknown])
    assert missing["missing"] == [unknown]
    assert not missing["lines"]


def test_scaled_lines_preserve_exact_quantity_and_arrow_direction():
    routes = [{"pickup": "Queenstown", "dropoff": "Picton", "quantity": 12.5, "listing_count": 2}]
    data = route_map.geometry(routes, units_per_line=5)
    assert len(data["lines"]) == 3
    assert [line["represented_quantity"] for line in data["lines"]] == [5, 5, 2.5]
    path = data["lines"][0]["path"]
    polygon = data["arrows"][0]["polygon"]
    tip = polygon[0]
    base = [(polygon[1][i] + polygon[2][i]) / 2 for i in (0, 1)]
    index = int((len(path) - 1) * 0.72)
    assert sum((tip[i] - base[i]) * (path[index][i] - path[index - 1][i]) for i in (0, 1)) > 0


def test_bidirectional_and_self_routes_are_valid():
    a, b = [168.66, -45.03], [174.0, -41.29]
    forward = route_map.curved_path(a, b, 0, 1)
    reverse = route_map.curved_path(b, a, 0, 1)
    assert forward[0] == pytest.approx(a)
    assert forward[-1] == pytest.approx(b)
    assert forward[len(forward) // 2] != reverse[len(reverse) // 2]
    loop = route_map.curved_path(a, a, 0, 1)
    assert all(math.isfinite(v) for point in route_map.arrowhead(loop) for v in point)


def test_filters_and_automatic_line_scale():
    routes = [{"pickup": "Queenstown", "dropoff": "Picton", "quantity": 100, "listing_count": 2}]
    assert route_map.filter_routes(routes, ["Auckland"]) == []
    assert route_map.filter_routes(routes, ["Queenstown"], ["Picton"]) == routes
    data = route_map.geometry(routes, max_lines=20)
    assert len(data["lines"]) <= 20
    assert data["units_per_line"] > 1
    assert sum(r["represented_quantity"] for r in data["lines"]) == 100


def test_layer_units_are_literal_strings_not_accessor_expressions():
    spec = json.loads(route_map.deck({"lines": [], "arrows": [], "nodes": []}).to_json())
    assert spec["layers"][0]["widthUnits"] == "pixels"
    assert spec["layers"][2]["radiusUnits"] == "pixels"


@pytest.mark.integration
def test_period_average_includes_absent_routes_and_empty_days(conn, small_pages):
    collect(conn, MemoryFetcher(small_pages, AT, SCOPE), SCOPE, started_at=AT)
    # Later same-day empty snapshot replaces the earlier one for daily aggregation.
    empty = [{"listings": [], "offset": 1, "limit": 1, "count": 0, "sum": 0}]
    later = AT.replace(hour=1)
    collect(conn, MemoryFetcher(empty, later, SCOPE), SCOPE, started_at=later)
    tomorrow = AT.replace(day=16)
    collect(conn, MemoryFetcher(small_pages, tomorrow, SCOPE), SCOPE, started_at=tomorrow)
    routes = queries.route_averages(
        conn, "transfercar", SCOPE, date(2026, 9, 15), date(2026, 9, 17)
    )
    assert {r["complete_days"] for r in routes} == {2}  # day 17 missing, not part of denominator
    assert sum(r["quantity"] for r in routes) == 16  # (0 + 32) / 2
    assert queries.route_averages(conn, "demo", SCOPE, date(2026, 9, 15), date(2026, 9, 17)) == []
