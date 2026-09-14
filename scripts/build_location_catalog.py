"""Rebuild the reviewed NZ reference points from the GeoNames NZ.zip download.

Usage: python scripts/build_location_catalog.py .local/geo/NZ.zip
No fuzzy geocoding or address-level accuracy is implied.
"""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

REVIEWED_IDS = {
    "Auckland": 2193733,
    "Auckland City": 2193733,
    "Auckland Airport": 6232134,
    "Christchurch": 2192362,
    "Christchurch Airport": 6220393,
    "Coutts Island (Christchurch)": 2192068,
    "Dunedin": 2191562,
    "Dunedin Airport": 6212232,
    "Gisborne": 2206854,
    "Greymouth": 2206895,
    "Hamilton": 2190324,
    "Islington (Christchurch)": 6220343,
    "Lower Hutt": 2188164,
    "Manurewa (Auckland)": 6232064,
    "Nelson Airport": 2207510,
    "North Shore (Auckland)": 2185964,
    "Palmerston North": 2185018,
    "Picton": 6243776,
    "Pokeno": 2184459,
    "Queenstown": 6204696,
    "Queenstown Airport": 6206225,
    "Rotorua": 6241325,
    "Wellington Airport": 6244688,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as archive:
        records = {
            int(fields[0]): fields
            for fields in (
                line.split("\t") for line in archive.read("NZ.txt").decode().splitlines()
            )
        }
    locations = {}
    for alias, geoname_id in REVIEWED_IDS.items():
        row = records[geoname_id]
        locations[alias] = {
            "latitude": float(row[4]),
            "longitude": float(row[5]),
            "reference_name": row[1],
            "geoname_id": geoname_id,
            "precision": "airport reference" if row[7] == "AIRP" else "locality reference",
            "source_url": f"https://www.geonames.org/{geoname_id}/",
        }
    result = {
        "source": "GeoNames",
        "source_url": "https://download.geonames.org/export/dump/NZ.zip",
        "license": "CC BY 4.0",
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "locations": locations,
    }
    path = Path(__file__).resolve().parents[1] / "src/transfercar/data/nz_locations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(locations)} reviewed locations")


if __name__ == "__main__":
    main()
