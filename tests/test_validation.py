import copy
import json

import pytest

from transfercar.models import DataQualityError, Page, Pagination, parse_listing


def test_real_samples_are_partial_not_complete(samples):
    pagination = Pagination()
    for i, sample in enumerate(samples, 1):
        pagination.add(Page.parse(json.dumps(sample), i))
    assert len(pagination.ids) == 20
    assert pagination.total_pages == 11
    with pytest.raises(DataQualityError, match="missing pages"):
        pagination.finish()


def test_nullable_prices_and_multiple_inclusions(samples):
    first = parse_listing(samples[0]["listings"][0])
    assert first["paid_days"] is None
    assert first["price_per_paid_day"] is None
    second = parse_listing(samples[1]["listings"][1])
    assert len(second["inclusions"]) == 2
    assert second["free_days"] == 6
    assert second["pickup_date"].tzinfo is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("nb_listings", -1),
        ("is_closed", "false"),
        ("price_per_free_day", "NaN"),
        ("pickup_date", "2026-09-15"),
        ("inclusions", None),
    ],
)
def test_invalid_semantics_rejected(samples, field, value):
    raw = copy.deepcopy(samples[0]["listings"][0])
    raw[field] = value
    with pytest.raises(DataQualityError):
        parse_listing(raw)


def test_repeated_page_detected_even_if_offset_and_timestamp_change(small_pages):
    pagination = Pagination()
    pagination.add(Page.parse(json.dumps(small_pages[0]), 1))
    repeated = copy.deepcopy(small_pages[0])
    repeated["offset"] = 2
    repeated["listings"][0]["pickup_date"] = "2026-09-15T03:00:00Z"
    with pytest.raises(DataQualityError, match="duplicate"):
        pagination.add(Page.parse(json.dumps(repeated), 2))


def test_changed_count_and_premature_short_page(small_pages):
    for change, message in (({"count": 3}, "metadata"), ({"listings": []}, "page length")):
        pagination = Pagination()
        pagination.add(Page.parse(json.dumps(small_pages[0]), 1))
        changed = {**small_pages[1], **change}
        with pytest.raises(DataQualityError, match=message):
            pagination.add(Page.parse(json.dumps(changed), 2))


def test_valid_empty_batch():
    pagination = Pagination()
    pagination.add(Page.parse('{"listings":[],"offset":1,"limit":10,"count":0,"sum":0}', 1))
    pagination.finish()
    assert pagination.total_pages == 1


def test_safety_cap_and_non_json(small_pages):
    with pytest.raises(DataQualityError, match="safety"):
        Pagination(max_pages=1).add(Page.parse(json.dumps(small_pages[0]), 1))
    with pytest.raises(DataQualityError, match="JSON"):
        Page.parse("<html>challenge</html>", 1)


def test_effective_response_limit_controls_last_page(samples):
    # Synthetic regression for the observed server cap: request 100, response 50.
    original = samples[0]["listings"][0]
    rows = [{**original, "id": n} for n in range(1, 102)]
    pagination = Pagination()
    for number, offset in enumerate(range(0, 101, 50), 1):
        body = {
            "listings": rows[offset : offset + 50],
            "offset": number,
            "limit": 50,
            "count": 101,
            "sum": 404,
        }
        pagination.add(Page.parse(json.dumps(body), number))
    pagination.finish()
    assert pagination.total_pages == 3
    assert len(pagination.ids) == 101


def test_repeated_terminal_page_is_outside_boundary(small_pages):
    pagination = Pagination()
    for number, page in enumerate(small_pages, 1):
        pagination.add(Page.parse(json.dumps(page), number))
    pagination.finish()
    repeated = {**small_pages[-1], "offset": 3}
    with pytest.raises(DataQualityError, match="boundary"):
        pagination.add(Page.parse(json.dumps(repeated), 3))
