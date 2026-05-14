from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.transfercar.co.nz/search"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Listing:
    listing_url: str
    pickup_when: str
    pickup_location: str
    dropoff_when: str
    dropoff_location: str
    vehicle_type: str
    deal: str
    included: str
    free_days: str
    paid_days_count: str
    paid_days_rate: str
    requested_by: str
    left: str


def build_search_url(pickup: str = "", dropoff: str = "", sort_col: str = "dates", view_by: str = "list") -> str:
    params = {
        "pickup": pickup,
        "dropoff": dropoff,
        "sort_col": sort_col,
        "view_by": view_by,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_location_block(block) -> tuple[str, str]:
    period_node = block.find("div")
    period = clean_text(period_node.get_text(" ", strip=True)) if period_node else ""
    full_text = clean_text(block.get_text(" ", strip=True))
    location = clean_text(full_text[len(period):]) if full_text.startswith(period) else clean_text(full_text.replace(period, "", 1))
    return period, location


def extract_date(period_text: str) -> str:
    return clean_text(re.sub(r"^(From|To)\s+", "", period_text, flags=re.IGNORECASE))


def normalize_date(date_text: str, year: int) -> str:
    value = clean_text(date_text)
    if not value:
        return ""

    for fmt in ("%d %b", "%d %B"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(year=year).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return value


def extract_first_int(text: str) -> str:
    match = re.search(r"(\d+)", text or "")
    return match.group(1) if match else ""


def parse_paid_days(text: str) -> tuple[str, str]:
    normalized = clean_text(text)
    if not normalized:
        return "", ""

    count = extract_first_int(normalized)
    rate_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*day", normalized, flags=re.IGNORECASE)
    rate = rate_match.group(1) if rate_match else ""
    return count, rate


def parse_left_count(text: str) -> str:
    # Examples: "Only 1 left", "5+ left" -> "1", "5"
    match = re.search(r"(\d+)\+?", text or "")
    return match.group(1) if match else ""


def parse_card(card, year: int) -> Listing:
    link = card.find("a", href=True)
    route_blocks = card.select(".route-location-name")
    pickup_when, pickup_location = ("", "")
    dropoff_when, dropoff_location = ("", "")
    if route_blocks:
        pickup_when, pickup_location = parse_location_block(route_blocks[0])
    if len(route_blocks) > 1:
        dropoff_when, dropoff_location = parse_location_block(route_blocks[1])

    included_node = card.select_one(".listing-included")
    included = clean_text(included_node.get_text(" ", strip=True)) if included_node else ""

    days_node = card.select_one(".listing-days")
    free_days_text = clean_text(days_node.select_one(".nb-days").get_text(" ", strip=True)) if days_node and days_node.select_one(".nb-days") else ""
    paid_days_text = clean_text(days_node.select_one(".paid-days").get_text(" ", strip=True)) if days_node and days_node.select_one(".paid-days") else ""
    free_days = extract_first_int(free_days_text)
    paid_days_count, paid_days_rate = parse_paid_days(paid_days_text)

    requested_node = card.select_one(".nb-requested strong")
    requested_by = clean_text(requested_node.get_text(" ", strip=True)) if requested_node else ""

    left_node = card.select_one(".listings-left strong")
    left_text = clean_text(left_node.get_text(" ", strip=True)) if left_node else ""
    left = parse_left_count(left_text)

    deal_node = card.select_one(".deal strong")
    vehicle_node = card.select_one(".vehicle-title")

    return Listing(
        listing_url=urljoin(BASE_URL, link["href"]) if link else "",
        pickup_when=normalize_date(extract_date(pickup_when), year),
        pickup_location=pickup_location,
        dropoff_when=normalize_date(extract_date(dropoff_when), year),
        dropoff_location=dropoff_location,
        vehicle_type=clean_text(vehicle_node.get_text(" ", strip=True)) if vehicle_node else "",
        deal=clean_text(deal_node.get_text(" ", strip=True)) if deal_node else "",
        included=included,
        free_days=free_days,
        paid_days_count=paid_days_count,
        paid_days_rate=paid_days_rate,
        requested_by=requested_by,
        left=left,
    )


def crawl_listings(start_url: str, max_pages: int | None = None, year: int | None = None) -> list[Listing]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    parse_year = year if year is not None else datetime.now().year

    listings: list[Listing] = []
    seen_urls: set[str] = set()
    current_url = start_url
    pages_visited = 0

    while current_url:
        pages_visited += 1
        html = fetch_html(session, current_url)
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".vehicle-list .tile-shadowed")

        for card in cards:
            listing = parse_card(card, parse_year)
            if not listing.listing_url or listing.listing_url in seen_urls:
                continue
            seen_urls.add(listing.listing_url)
            listings.append(listing)

        if max_pages is not None and pages_visited >= max_pages:
            break

        next_link = soup.select_one(".pagination li.next a[href]")
        current_url = urljoin(current_url, next_link["href"]) if next_link else ""

    return listings


def write_csv(listings: Iterable[Listing], output_path: str) -> None:
    rows = [asdict(listing) for listing in listings]
    fieldnames = list(rows[0].keys()) if rows else [field.name for field in Listing.__dataclass_fields__.values()]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl current Transfercar relocation listings and export them to CSV.")
    parser.add_argument("--pickup", default="", help="Pickup location filter")
    parser.add_argument("--dropoff", default="", help="Drop-off location filter")
    parser.add_argument("--sort-col", default="dates", help="Sort column used by the site")
    parser.add_argument("--view-by", default="list", help="View mode used by the site")
    parser.add_argument("--output", default="transfercar_listings.csv", help="CSV output file path")
    parser.add_argument("--max-pages", type=int, default=None, help="Safety limit for the number of pages to crawl")
    parser.add_argument("--year", type=int, default=datetime.now().year, help="Year used to normalize pickup/drop-off dates")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_url = build_search_url(
        pickup=args.pickup,
        dropoff=args.dropoff,
        sort_col=args.sort_col,
        view_by=args.view_by,
    )
    listings = crawl_listings(start_url, max_pages=args.max_pages, year=args.year)
    write_csv(listings, args.output)
    print(f"Saved {len(listings)} listings to {args.output}")


if __name__ == "__main__":
    main()