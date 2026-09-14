"""Strict validation of observed fields; unknown fields remain in the raw archive."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


class DataQualityError(ValueError):
    pass


def integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise DataQualityError(f"{name}: expected integer >= {minimum}")
    return value


def timestamp(value: Any, name: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise DataQualityError(f"{name}: expected timestamp with timezone") from exc


def money(value: Any, name: str) -> Decimal:
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
            raise ValueError
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError
        return amount
    except (InvalidOperation, ValueError) as exc:
        raise DataQualityError(f"{name}: expected nonnegative finite amount") from exc


def parse_listing(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise DataQualityError("listing must be an object")
    result = {"listing_id": integer(raw.get("id"), "id", 1)}
    for key in ("pickup_location", "dropoff_location", "vehicle_type", "status_name"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise DataQualityError(f"{key}: expected nonempty string")
        result[key] = raw[key]
    for key in ("pickup_date", "dropoff_date"):
        result[key] = timestamp(raw.get(key), key)
    for key in ("free_days", "nb_listings", "nb_pending_requests"):
        result[key] = integer(raw.get(key), key)
    if type(raw.get("status")) is not int:
        raise DataQualityError("status: expected integer")
    result["status"] = raw["status"]
    result["price_per_free_day"] = money(raw.get("price_per_free_day"), "price_per_free_day")
    result["paid_days"] = (
        integer(raw["paid_days"], "paid_days") if raw.get("paid_days") is not None else None
    )
    result["price_per_paid_day"] = (
        money(raw["price_per_paid_day"], "price_per_paid_day")
        if raw.get("price_per_paid_day") is not None
        else None
    )
    for key in ("is_closed", "is_ghost_listing", "great_deal"):
        if type(raw.get(key)) is not bool:
            raise DataQualityError(f"{key}: expected boolean")
        result[key] = raw[key]
    for key in ("inclusions", "closed_times"):
        if not isinstance(raw.get(key), list):
            raise DataQualityError(f"{key}: expected array")
        result[key] = raw[key]
    for item in raw["inclusions"]:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) for k in ("type", "description")
        ):
            raise DataQualityError("inclusions: expected type/description objects")
    for value in raw["closed_times"]:
        timestamp(value, "closed_times")
    result["image_path"] = raw.get("image_path")
    try:
        result["resource_url"] = raw.get("_links", {}).get("self", {}).get("href")
    except AttributeError as exc:
        raise DataQualityError("_links: expected nested objects") from exc
    for key in ("image_path", "resource_url"):
        if result[key] is not None and not isinstance(result[key], str):
            raise DataQualityError(f"{key}: expected string or null")
    result["content_hash"] = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result


@dataclass
class Page:
    number: int
    limit: int
    count: int
    reported_sum: int
    rows: list[dict]

    @classmethod
    def parse(cls, body: str, requested_page: int) -> "Page":
        try:
            raw = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise DataQualityError("response is not valid JSON") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("listings"), list):
            raise DataQualityError("response must contain a listings array")
        number = integer(raw.get("offset"), "offset", 1)
        if number != requested_page:
            raise DataQualityError("response offset differs from requested page")
        return cls(
            number,
            integer(raw.get("limit"), "limit", 1),
            integer(raw.get("count"), "count"),
            integer(raw.get("sum"), "sum"),
            [parse_listing(row) for row in raw["listings"]],
        )


class Pagination:
    """Never wait for an empty page: this API repeats its final page."""

    def __init__(self, max_pages: int = 100):
        self.max_pages = max_pages
        self.pages = 0
        self.total_pages = 0
        self.metadata = None
        self.ids: set[int] = set()

    def add(self, page: Page) -> None:
        if page.number != self.pages + 1:
            raise DataQualityError("pages must be contiguous starting at 1")
        metadata = (page.limit, page.count, page.reported_sum)
        if self.metadata is None:
            self.metadata = metadata
            self.total_pages = max(1, (page.count + page.limit - 1) // page.limit)
            if self.total_pages > self.max_pages:
                raise DataQualityError("expected page count exceeds safety limit")
        elif metadata != self.metadata:
            raise DataQualityError("pagination metadata changed during collection")
        if page.number > self.total_pages:
            raise DataQualityError("page beyond expected boundary")
        ids = {row["listing_id"] for row in page.rows}
        if len(ids) != len(page.rows) or self.ids.intersection(ids):
            raise DataQualityError("duplicate listing IDs within or across pages")
        expected = min(page.limit, max(0, page.count - (page.number - 1) * page.limit))
        if len(page.rows) != expected:
            raise DataQualityError("page length differs from expected count")
        self.ids.update(ids)
        self.pages += 1

    def finish(self) -> None:
        if not self.metadata or self.pages != self.total_pages:
            raise DataQualityError("missing pages: batch is incomplete")
        if len(self.ids) != self.metadata[1]:
            raise DataQualityError("unique ID count differs from reported count")
