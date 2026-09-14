"""Run with: streamlit run apps/dashboard.py"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
import streamlit as st

from transfercar import db, listing_links, queries, route_map

NZ = ZoneInfo("Pacific/Auckland")
st.set_page_config(page_title="Transfercar Route Explorer", page_icon="🚐", layout="wide")
st.title("Transfercar Route Explorer")
st.caption("Explore New Zealand relocation routes and historical availability.")


def frame(rows):
    data = pd.DataFrame(rows)
    for col in ("started_at", "finished_at", "observed_at", "pickup_date", "dropoff_date"):
        if col in data:
            data[col] = pd.to_datetime(data[col], utc=True).dt.tz_convert(NZ)
    if "run_id" in data:
        data["run_id"] = data["run_id"].map(lambda v: str(v) if v is not None else None)
    return data


def scope_label(scope):
    def label(code):
        return code.split(":", 1)[-1].replace("-", " ").title()

    pickup, dropoff = scope.get("pickup"), scope.get("dropoff")
    if not pickup and not dropoff:
        return "New Zealand · all pickup and dropoff locations"
    return (
        f"{label(pickup) if pickup else 'All pickups'} → "
        f"{label(dropoff) if dropoff else 'All dropoffs'}"
    )


def render_map(routes, mode, complete_days):
    if not routes:
        st.info("No routes match this selection.")
        return
    a, b, c = st.columns([2, 2, 1])
    pickups = a.multiselect("Pickup locations", sorted({r["pickup"] for r in routes}))
    dropoffs = b.multiselect("Dropoff locations", sorted({r["dropoff"] for r in routes}))
    units = c.selectbox("Source units per line", [1, 5, 10, 25], index=0)
    selected = route_map.filter_routes(routes, pickups, dropoffs)
    data = route_map.geometry(selected, units)
    quantity = sum(float(r["quantity"]) for r in selected)
    a, b, c = st.columns(3)
    a.metric("Routes", len(selected))
    b.metric(
        "Average daily source quantity" if mode == "Period average" else "Source quantity",
        f"{quantity:,.2f}" if mode == "Period average" else f"{quantity:,.0f}",
    )
    c.metric("Mapped locations", len(data["nodes"]))
    if mode == "Period average":
        st.caption(
            f"Average over {complete_days} complete observation days. "
            "A route absent on a complete day contributes zero; missing days are excluded."
        )
    st.caption("🔵 North → South   ·   🟢 South → North   ·   ⚪ Same latitude / local")
    st.pydeck_chart(route_map.deck(data), height=620, key="route_map")
    st.caption(
        f"Arrows point from pickup to dropoff. One line represents up to "
        f"{data['units_per_line']:g} source units; a partial line is lighter. "
        "Hover over a route for exact counts. More parallel lines indicate more availability."
    )
    st.caption(
        "Quantity is the sum of the source's nb_listings field, not verified vehicle stock. "
        "Curves show connections, not driving directions. Zoom in to separate nearby locations."
    )
    st.caption(
        "Location reference points: [GeoNames](https://www.geonames.org/), "
        "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). "
        "City/airport reference points are approximate, not rental depot addresses."
    )
    if data["missing"]:
        st.warning(
            f"{len(data['missing'])} routes have unrecognised locations and are not drawn. "
            "They remain included in the route table and totals."
        )
        st.dataframe(frame(data["missing"]), hide_index=True)
    st.dataframe(
        frame(selected).rename(
            columns={
                "pickup": "Pickup",
                "dropoff": "Dropoff",
                "quantity": "Source quantity",
                "listing_count": "Listing count",
            }
        ),
        hide_index=True,
    )


def render(conn):
    source = st.sidebar.selectbox(
        "Data source",
        ["transfercar", "demo"],
        format_func=lambda s: "Live observations" if s == "transfercar" else "Synthetic demo",
    )
    if source == "demo":
        st.warning("Synthetic demo: sample-derived history, not actual changes in availability.")
    available = queries.scopes(conn, source)
    if not available:
        st.info("No collection runs for this source yet. Select another data source.")
        return
    scope = st.sidebar.selectbox("Collection coverage", available, format_func=scope_label)
    today = datetime.now(NZ).date()
    period = st.sidebar.date_input(
        "Observation date range", (today - timedelta(days=6), today), max_value=today
    )
    st.sidebar.caption(
        "Dates use Pacific/Auckland time. This filters when data was observed, "
        "not the rental pickup window."
    )
    if len(period) != 2:
        st.info("Select both a start date and an end date.")
        return
    start, end = period
    if (end - start).days > 366:
        st.info("Select a range of no more than 366 days.")
        return
    daily = frame(queries.daily(conn, source, scope, start, end))
    records = queries.runs(conn, source, scope, start, end)
    successful = [r for r in records if r["status"] == "succeeded"]
    link_run, link_rows = queries.latest_link_observations(conn, source, scope)
    live_links = listing_links.link_lookup(link_rows)
    link_column = st.column_config.LinkColumn("Web link", display_text="View listing")
    link_note = (
        "Links are shown for IDs still present in the latest complete collection covering "
        f"this area ({link_run['started_at'].astimezone(NZ):%Y-%m-%d %H:%M %Z}). "
        "This is the latest observed state, not a real-time booking check."
        if link_run
        else "No current live links are available for this data source."
    )
    valid_days = int(daily["run_id"].notna().sum())
    a, b, c = st.columns(3)
    a.metric("Days with complete data", valid_days)
    b.metric("Days without complete data", len(daily) - valid_days)
    c.metric("Failed or unfinished runs", sum(r["status"] != "succeeded" for r in records))

    map_tab, snapshot_tab, trend_tab, history_tab, runs_tab = st.tabs(
        ["Route map", "Snapshot listings", "Daily trends", "Listing history", "Pipeline runs"]
    )
    selected_run = None
    snapshot_rows = []
    with map_tab:
        mode = st.radio("Map time view", ["Daily snapshot", "Period average"], horizontal=True)
        if mode == "Daily snapshot":
            dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            selected_day = st.select_slider(
                "Observation date", dates, value=end, format_func=lambda d: d.isoformat()
            )
            day_runs = [
                r for r in successful if r["started_at"].astimezone(NZ).date() == selected_day
            ]
            if not day_runs:
                st.info(
                    "No complete snapshot for this date. This is missing data, not zero supply."
                )
            else:
                selected_run = st.selectbox(
                    "Snapshot time · latest complete run first",
                    day_runs,
                    format_func=lambda r: f"{r['started_at'].astimezone(NZ):%H:%M:%S %Z}",
                )
                st.caption(
                    f"Observation window: {selected_run['started_at'].astimezone(NZ)} — "
                    f"{selected_run['finished_at'].astimezone(NZ)}"
                )
                snapshot_rows = queries.snapshot(conn, selected_run["run_id"])
                if not snapshot_rows:
                    st.success("This complete snapshot contains zero listings.")
                render_map(route_map.aggregate_snapshot(snapshot_rows), mode, 1)
        else:
            if not valid_days:
                st.info("No complete observation days in this range.")
            else:
                render_map(
                    queries.route_averages(conn, source, scope, start, end), mode, valid_days
                )

    with snapshot_tab:
        if selected_run is None:
            st.info("Select Daily snapshot in the Route map tab to inspect its listings.")
        elif snapshot_rows:
            snapshot = frame(snapshot_rows)
            origins = st.multiselect(
                "Filter listing pickups", sorted(snapshot.pickup_location.unique())
            )
            destinations = st.multiselect(
                "Filter listing dropoffs", sorted(snapshot.dropoff_location.unique())
            )
            if origins:
                snapshot = snapshot[snapshot.pickup_location.isin(origins)]
            if destinations:
                snapshot = snapshot[snapshot.dropoff_location.isin(destinations)]
            columns = [
                "listing_id",
                "pickup_location",
                "dropoff_location",
                "vehicle_type",
                "pickup_date",
                "dropoff_date",
                "nb_listings",
                "status_name",
                "free_days",
                "price_per_free_day",
                "paid_days",
                "price_per_paid_day",
                "inclusions",
                "observed_at",
            ]
            linked_snapshot = listing_links.append_web_links(snapshot[columns], live_links)
            st.dataframe(linked_snapshot, hide_index=True, column_config={"web_link": link_column})
            st.caption(link_note)
            st.download_button(
                "Download snapshot CSV",
                linked_snapshot.to_csv(index=False),
                file_name=f"transfercar-{selected_run['run_id']}.csv",
                mime="text/csv",
            )
            st.caption(
                "Price currency is not supplied by the listing API. Missing amounts remain blank."
            )
        else:
            st.success("This complete snapshot contains zero listings.")

    with trend_tab:
        if valid_days:
            st.bar_chart(daily.set_index("day")[["record_count"]], y_label="Listing count")
        st.caption(
            "Each day uses its last complete snapshot. Blank days are missing data; "
            "a successful empty collection is zero. Daily quantities are not added together."
        )
        st.dataframe(
            daily.rename(
                columns={
                    "record_count": "Listing count",
                    "observed_sum": "Source quantity",
                    "route_count": "Route count",
                }
            ),
            hide_index=True,
        )
    with history_tab:
        listing_id = st.number_input("Listing ID", min_value=1, value=670110, step=1)
        history = frame(queries.history(conn, source, scope, listing_id, start, end))
        history["Observation status"] = history.apply(
            lambda r: (
                "No complete collection"
                if pd.isna(r["run_id"])
                else ("Not observed" if pd.isna(r["observed_at"]) else "Observed")
            ),
            axis=1,
        )
        linked_history = listing_links.append_web_links(history, live_links)
        st.dataframe(linked_history, hide_index=True, column_config={"web_link": link_column})
        st.caption(link_note)
        st.caption(
            "Not observed does not mean booked. History uses the last complete batch each day."
        )
    with runs_tab:
        st.dataframe(frame(records), hide_index=True)
        st.caption(
            "A long-running batch may indicate an interrupted process. Retrying the same "
            "run ID preserves earlier raw attempts and prevents duplicate publication."
        )


url = os.environ.get("DASHBOARD_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not url:
    st.info("Database is not configured. Set the server-side connection and refresh.")
else:
    try:
        with db.connect(url) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.execute("SET LOCAL statement_timeout = '15s'")
                render(conn)
    except psycopg.Error:
        st.error(
            "Unable to read the database. Check connectivity, read permissions and migrations."
        )
