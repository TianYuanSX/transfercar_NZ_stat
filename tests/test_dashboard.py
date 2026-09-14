from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from transfercar.demo import seed


@pytest.mark.integration
def test_dashboard_demo_gap_and_snapshot(conn, monkeypatch):
    import os

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("DASHBOARD_DATABASE_URL", raising=False)
    root = Path(__file__).resolve().parents[1]
    seed(conn, root / "samples/transfercar")
    app = AppTest.from_file(str(root / "apps/dashboard.py"), default_timeout=30).run()
    assert not app.exception
    app.sidebar.selectbox[0].set_value("demo").run()
    assert not app.exception
    assert app.metric[0].value == "6"
    assert app.metric[1].value == "1"
    assert len(app.dataframe) >= 3
    assert app.title[0].value == "Transfercar Route Explorer"
    assert app.metric[3].label == "Routes"
    assert app.metric[4].value == "57"
    # Time filter changes map contents and correctly handles the intentional missing day.
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Pacific/Auckland")).date()
    app.select_slider[0].set_value(today - timedelta(days=3)).run()
    assert not app.exception
    assert any("No complete snapshot" in info.value for info in app.info)
    app.radio[0].set_value("Period average").run()
    assert not app.exception
    assert any(m.label == "Average daily source quantity" for m in app.metric)
    app.sidebar.date_input[0].set_value((today, today)).run()
    app.radio[0].set_value("Daily snapshot").run()
    assert not app.exception
    assert any(m.label == "Source quantity" and m.value == "57" for m in app.metric)
    listing_tables = [table.value for table in app.dataframe if "listing_id" in table.value]
    assert len(listing_tables) == 2
    assert all(table.columns[-1] == "web_link" for table in listing_tables)
    assert all(table.web_link.isna().all() for table in listing_tables)  # No live demo links.
