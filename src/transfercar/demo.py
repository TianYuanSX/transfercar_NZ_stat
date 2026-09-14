"""Sample-derived synthetic history: always stored under the separate demo source."""

import copy
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from transfercar.pipeline import CollectionError, MemoryFetcher, collect

NZ = ZoneInfo("Pacific/Auckland")


def seed(conn, sample_dir: Path, start=None):
    start = start or (datetime.now(NZ).date() - timedelta(days=6))
    original = []
    for name in ("queenstown-page-1.json", "queenstown-page-2.json"):
        original.extend(json.loads((sample_dir / name).read_text())["listings"])
    scope = {
        "pickup": "custom:queenstown",
        "limit": 10,
        "featured": 0,
        "sort": "pickup_date",
        "direction": "asc",
    }
    results = []
    for index in range(7):
        day = start + timedelta(days=index)
        observed_at = datetime.combine(day, time(8, 0), NZ)
        rows = copy.deepcopy(original[: len(original) - index])
        for row in rows:
            row["nb_listings"] = max(1, row["nb_listings"] - index)
        pages = [
            {
                "listings": rows[offset : offset + 10],
                "offset": offset // 10 + 1,
                "limit": 10,
                "count": len(rows),
                "sum": sum(r["nb_listings"] for r in rows),
            }
            for offset in range(0, len(rows), 10)
        ]
        if index == 3:
            pages = pages[:1]  # Explicit demonstration of a missing/incomplete day.
        try:
            results.append(
                collect(
                    conn,
                    MemoryFetcher(pages, observed_at, scope),
                    scope,
                    source="demo",
                    started_at=observed_at,
                    run_id=uuid5(NAMESPACE_URL, f"transfercar-demo-v1:{day.isoformat()}"),
                )
            )
        except CollectionError:
            if index != 3:
                raise
            results.append({"day": day.isoformat(), "status": "intentional_demo_gap"})
    return results
