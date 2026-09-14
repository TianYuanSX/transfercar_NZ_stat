import copy
import json
import os
from pathlib import Path

import pytest

from transfercar import db


@pytest.fixture
def samples():
    base = Path(__file__).resolve().parents[1] / "samples/transfercar"
    return [json.loads((base / f"queenstown-page-{n}.json").read_text()) for n in (1, 2)]


@pytest.fixture
def small_pages(samples):
    """Explicitly synthetic COMPLETE two-row scope derived from real samples."""
    rows = copy.deepcopy(samples[0]["listings"][:2])
    return [
        {
            "listings": [row],
            "offset": i,
            "limit": 1,
            "count": 2,
            "sum": sum(r["nb_listings"] for r in rows),
        }
        for i, row in enumerate(rows, 1)
    ]


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; integration tests require disposable PostgreSQL")
    with db.connect(url) as connection:
        # Refuse schema teardown outside a clearly named, dedicated test database.
        name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        if not name.endswith("_test"):
            raise RuntimeError("Test database name must end with _test")
        connection.execute("DROP SCHEMA IF EXISTS transfercar CASCADE")
        db.migrate(connection)
        yield connection
        connection.execute("DROP SCHEMA transfercar CASCADE")
