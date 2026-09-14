from datetime import date, datetime, timezone
from uuid import UUID

import pandas as pd
import pytest

from transfercar import listing_links, queries
from transfercar.pipeline import CollectionError, MemoryFetcher, collect


def test_public_url_uses_location_slugs_and_encodes_path_segments():
    assert listing_links.public_listing_url(665951, "Christchurch Airport", "Auckland") == (
        "https://www.transfercar.co.nz/relocation/Christchurch_Airport/Auckland/665951"
    )
    assert listing_links.public_listing_url(
        673562, "Queenstown Airport", "Manurewa (Auckland)"
    ) == (
        "https://www.transfercar.co.nz/relocation/Queenstown_Airport/Manurewa_%28Auckland%29/673562"
    )
    assert "/A%2FB/C_%26_D/1" in listing_links.public_listing_url(1, "A/B", "C & D")


def test_link_column_is_last_and_only_current_observed_ids_link():
    data = pd.DataFrame({"listing_id": [1, 2, None], "quantity": [3, 4, None]})
    linked = listing_links.append_web_links(data, {1: "https://example.com/1"})
    assert list(linked.columns) == ["listing_id", "quantity", "web_link"]
    assert linked.web_link.tolist() == ["https://example.com/1", None, None]
    assert "web_link" not in data


@pytest.mark.integration
def test_latest_covering_snapshot_controls_links_outside_selected_history(conn, small_pages):
    city = {"pickup": "custom:queenstown", "limit": 1}
    all_locations = {"limit": 100, "featured": 0}
    observed = datetime(2026, 9, 15, tzinfo=timezone.utc)
    first = collect(conn, MemoryFetcher(small_pages, observed, city), city, started_at=observed)
    latest, rows = queries.latest_link_observations(conn, "transfercar", city)
    assert latest["run_id"] == UUID(first["run_id"])
    assert len(rows) == 2
    # A city run is not sufficient to establish current availability across all NZ.
    assert queries.latest_link_observations(conn, "transfercar", all_locations) == (None, [])

    # A later full-country empty snapshot supersedes the old city observation.
    tomorrow = observed.replace(day=16)
    empty = [{"listings": [], "offset": 1, "limit": 50, "count": 0, "sum": 0}]
    second = collect(
        conn, MemoryFetcher(empty, tomorrow, all_locations), all_locations, started_at=tomorrow
    )
    latest, rows = queries.latest_link_observations(conn, "transfercar", city)
    assert latest["run_id"] == UUID(second["run_id"])
    assert rows == []
    historical = queries.snapshot(conn, UUID(first["run_id"]))
    linked = listing_links.append_web_links(
        pd.DataFrame(historical), listing_links.link_lookup(rows)
    )
    assert linked.web_link.isna().all()
    assert len(historical) == 2  # Link availability never rewrites history.

    # A newer incomplete attempt must not replace the latest complete result.
    with pytest.raises(CollectionError):
        collect(
            conn,
            MemoryFetcher(small_pages[:1], tomorrow, all_locations),
            all_locations,
            started_at=observed.replace(day=17),
        )
    assert queries.latest_link_observations(conn, "transfercar", city)[0]["run_id"] == UUID(
        second["run_id"]
    )
    assert queries.latest_link_observations(conn, "demo", city) == (None, [])
    history = queries.history(
        conn,
        "transfercar",
        city,
        small_pages[0]["listings"][0]["id"],
        date(2026, 9, 15),
        date(2026, 9, 16),
    )
    assert history[0]["listing_id"] is not None
    assert history[1]["listing_id"] is None
