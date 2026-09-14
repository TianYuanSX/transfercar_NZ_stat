"""Collectors share an archive/validate/publish path for live and offline data."""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from transfercar import db
from transfercar.models import DataQualityError, Page, Pagination

ENDPOINT = "https://www.transfercar.co.nz/api-endpoint/listings.json"


class CollectionError(RuntimeError):
    pass


@dataclass
class Response:
    body: str
    status: int
    fetched_at: datetime
    params: dict
    request_attempt: int = 1


class HTTPFetcher:
    def __init__(self, scope: dict, delay: float = 2.0):
        self.scope = scope
        self.delay = max(1.0, delay)
        self.client = httpx.Client(
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": "TransfercarHistoryPortfolio/0.1", "Accept": "application/json"},
        )

    def close(self):
        self.client.close()

    def __call__(self, page: int, archive):
        params = {**self.scope, "page": page}
        if page > 1:
            time.sleep(self.delay)
        for attempt in range(1, 4):
            try:
                raw = self.client.get(ENDPOINT, params=params)
            except httpx.RequestError:
                if attempt == 3:
                    raise CollectionError("Network request failed after 3 attempts") from None
                time.sleep(attempt * 2)
                continue
            response = Response(
                raw.text, raw.status_code, datetime.now(timezone.utc), params, attempt
            )
            archive(response)
            if raw.status_code == 200:
                return response
            if raw.status_code in (401, 403):
                raise CollectionError(f"HTTP {raw.status_code}: access denied; no automatic retry")
            if raw.status_code == 429:
                raise CollectionError("HTTP 429: rate limited; stop this batch")
            if raw.status_code >= 500 and attempt < 3:
                time.sleep(attempt * 2)
                continue
            raise CollectionError(f"HTTP {raw.status_code}: collection stopped")


class FileFetcher:
    """Original observations require caller-supplied collection time and scope."""

    def __init__(self, paths: list[Path], scope: dict, observed_at: datetime):
        self.paths = paths
        self.scope = scope
        self.observed_at = observed_at

    def __call__(self, page: int, archive):
        if page > len(self.paths):
            raise DataQualityError("offline files do not contain all expected pages")
        response = Response(
            self.paths[page - 1].read_text(),
            200,
            self.observed_at,
            {**self.scope, "page": page},
        )
        archive(response)
        return response


class MemoryFetcher:
    """For explicitly synthetic demos and isolated tests."""

    def __init__(self, payloads: list[dict], observed_at: datetime, scope: dict):
        self.payloads = payloads
        self.observed_at = observed_at
        self.scope = scope

    def __call__(self, page: int, archive):
        if page > len(self.payloads):
            raise DataQualityError("missing synthetic page")
        response = Response(
            json.dumps(self.payloads[page - 1]),
            200,
            self.observed_at,
            {**self.scope, "page": page},
        )
        archive(response)
        return response


def collect(
    conn,
    fetch,
    scope: dict,
    *,
    source: str = "transfercar",
    run_id: UUID | None = None,
    started_at: datetime | None = None,
    max_pages: int = 100,
) -> dict:
    run_id = run_id or uuid4()
    started_at = started_at or datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        raise ValueError("started_at must include timezone")
    # Lock both logical run and source/scope, including across independent runners.
    keys = ["run:" + str(run_id), db.scope_key(source, scope)]
    held = []
    try:
        for key in keys:
            if not db.acquire(conn, key):
                raise CollectionError("Another collector is running for this run or scope")
            held.append(key)
        attempt = db.start_run(conn, run_id, source, scope, started_at)
        if attempt is None:
            return {"run_id": str(run_id), "status": "already_succeeded"}
        pagination = Pagination(max_pages)
        rows = []
        try:
            page_number = 1
            while True:
                response = fetch(
                    page_number,
                    lambda r, p=page_number: db.archive(conn, run_id, attempt, p, r),
                )
                page = Page.parse(response.body, page_number)
                pagination.add(page)
                rows.extend({**row, "observed_at": response.fetched_at} for row in page.rows)
                conn.execute(
                    """
                    UPDATE transfercar.ingestion_runs
                    SET page_count=%s, expected_count=%s, reported_sum=%s WHERE run_id=%s
                """,
                    (pagination.pages, page.count, page.reported_sum, run_id),
                )
                if page_number == pagination.total_pages:
                    break
                page_number += 1
            db.publish(conn, run_id, source, rows, pagination)
        except Exception as exc:
            status = "incomplete" if isinstance(exc, DataQualityError) else "failed"
            # Never save database/connection exceptions containing credentials or row values.
            error = (
                str(exc)
                if isinstance(exc, (DataQualityError, CollectionError))
                else type(exc).__name__
            )
            db.fail(conn, run_id, status, error, pagination.pages)
            raise CollectionError(f"Run {run_id} {status}: {error}") from None
        return {
            "run_id": str(run_id),
            "status": "succeeded",
            "records": len(rows),
            "pages": pagination.pages,
        }
    finally:
        for key in reversed(held):
            db.release(conn, key)
