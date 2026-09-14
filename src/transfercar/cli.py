import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

import psycopg

from transfercar import db
from transfercar.demo import seed
from transfercar.models import DataQualityError, Page, Pagination, timestamp
from transfercar.pipeline import CollectionError, FileFetcher, HTTPFetcher, collect


def main():
    parser = argparse.ArgumentParser(description="Transfercar historical data pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Apply checksum-verified SQL migrations")
    sub.add_parser("check-db", help="Check database connectivity and schema")
    demo = sub.add_parser("demo", help="Seed explicitly SYNTHETIC seven-day demo history")
    demo.add_argument("--samples", type=Path, default=Path("samples/transfercar"))
    validate = sub.add_parser("validate", help="Validate offline pages without a database")
    validate.add_argument("files", type=Path, nargs="+")
    for command in ("collect", "import"):
        p = sub.add_parser(command)
        p.add_argument("--pickup", help="Optional pickup code; omit for all pickup locations")
        p.add_argument("--dropoff", help="Optional dropoff code; omit for all dropoff locations")
        p.add_argument("--limit", type=int, default=100 if command == "collect" else 10)
        p.add_argument("--max-pages", type=int, default=100)
        p.add_argument("--run-id", type=UUID)
        if command == "import":
            p.add_argument("--observed-at", required=True, help="Original timestamp with timezone")
            p.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            pagination = Pagination()
            for n, path in enumerate(args.files, 1):
                pagination.add(Page.parse(path.read_text(), n))
            pagination.finish()
            print(json.dumps({"complete": True, "unique_ids": len(pagination.ids)}))
            return
        with db.connect() as conn:
            if args.command == "migrate":
                result = {"applied": db.migrate(conn)}
            elif args.command == "check-db":
                result = conn.execute(
                    "SELECT count(*) AS migrations FROM transfercar.schema_migrations"
                ).fetchone()
            elif args.command == "demo":
                result = seed(conn, args.samples)
            else:
                if not 1 <= args.limit <= 100 or args.max_pages < 1:
                    raise ValueError("limit must be 1..100; max-pages must be positive")
                scope = {
                    "limit": args.limit,
                    "featured": 0,
                    "sort": "pickup_date",
                    "direction": "asc",
                }
                if args.pickup:
                    scope["pickup"] = args.pickup
                if args.dropoff:
                    scope["dropoff"] = args.dropoff
                observed_at = (
                    timestamp(args.observed_at, "observed-at") if args.command == "import" else None
                )
                fetch = (
                    FileFetcher(args.files, scope, observed_at)
                    if args.command == "import"
                    else HTTPFetcher(scope)
                )
                try:
                    result = collect(
                        conn,
                        fetch,
                        scope,
                        run_id=args.run_id,
                        started_at=observed_at,
                        max_pages=args.max_pages,
                    )
                finally:
                    if isinstance(fetch, HTTPFetcher):
                        fetch.close()
            print(json.dumps(result, default=str, ensure_ascii=False))
    except (CollectionError, DataQualityError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except psycopg.Error:
        print("Database operation failed. Check connection, role and migrations.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
