"""Public listing links derived from the latest comparable complete observation."""

from urllib.parse import quote


def public_listing_url(listing_id: int, pickup: str, dropoff: str) -> str:
    origin = quote(pickup.replace(" ", "_"), safe="")
    destination = quote(dropoff.replace(" ", "_"), safe="")
    return f"https://www.transfercar.co.nz/relocation/{origin}/{destination}/{listing_id}"


def link_lookup(observations):
    return {
        row["listing_id"]: public_listing_url(
            row["listing_id"], row["pickup_location"], row["dropoff_location"]
        )
        for row in observations
    }


def append_web_links(data, links):
    """Append the final column without manufacturing IDs for missing observations."""
    if "listing_id" not in data.columns:
        return data
    result = data.drop(columns=["web_link"], errors="ignore").copy()
    urls = result["listing_id"].map(links)
    result["web_link"] = urls.astype(object).where(urls.notna(), None)
    return result
