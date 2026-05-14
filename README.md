# Transfercar NZ Stat

This small Python script crawls the current relocation listings from Transfercar and exports them to CSV.

## Daily CI/CD on GitHub

This repository includes a GitHub Actions workflow at `.github/workflows/daily-transfercar-scrape.yml`.

- It runs every day at `00:10 UTC`.
- It can also be triggered manually from the **Actions** tab.
- It generates and maintains 3 CSV files under `data/`.
- It uploads the CSV files as workflow artifacts.
- It auto-commits and pushes CSV changes when data changes.
- It is designed to run directly on the `main` branch of `transfercar_NZ_stat`.

### Will it run directly?

Yes, with two conditions:

1. The repository exists on GitHub with the workflow file committed to `main`.
2. In GitHub, **Actions** permissions allow read and write access so the workflow can push updated CSV files back to the repository.

### Data files and update strategy

- `data/transfercar_listings_daily.csv`
: Latest full snapshot from the current run.
- `data/transfercar_listings_history.csv`
: Historical table with one row per `snapshot_date + listing_url` (append-or-update).
- `data/transfercar_listings_state.csv`
: URL-indexed state table (upsert) for the latest known status.

`transfercar_listings_state.csv` includes:

- `left_initial`
: The earliest known or maximum known initial capacity for this listing URL. In implementation, it keeps the maximum seen value across runs.
- `left_latest`
: The latest observed `left` value from the current update.

Upsert rule:

1. Use `listing_url` as the index key.
2. If URL does not exist, create a new row and initialize both `left_initial` and `left_latest`.
3. If URL exists, update current fields and refresh `left_latest`; keep `left_initial` as max(existing, current).

### One-time setup

1. Create a GitHub repository named `transfercar_NZ_stat` and push this project.
2. In GitHub, open **Settings** -> **Actions** -> **General**.
3. Under **Workflow permissions**, select **Read and write permissions**.
4. Save settings.

After that, the daily task will run automatically.

## Install

```bash
pip install -r requirements.txt
```

## Python virtual environment

Recommended: create and use a local virtual environment in the project root.

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# run the scraper
python scrape_transfercar.py --max-pages 1
```

If you prefer not to activate, you can run the bundled Python directly:

```bash
.venv/bin/python scrape_transfercar.py --max-pages 1
```

Note: `.venv` is recommended to be ignored by Git (the repository already includes `.venv` in `.gitignore`).

## Run

```bash
python scrape_transfercar.py --output transfercar_listings.csv
```

Default run also updates history/state files:

- `data/transfercar_listings_history.csv`
- `data/transfercar_listings_state.csv`

Optional filters are supported:

```bash
python scrape_transfercar.py --pickup Auckland --dropoff Christchurch --output filtered.csv
```

The script follows pagination automatically and stops when there are no more result pages.

## Troubleshooting

**Script hangs or runs very slowly:** This was caused by a pagination bug on the Transfercar website where the "next" link on the last page points back to itself, creating an infinite loop. As of the latest version, this is fixed by detecting duplicate URLs and stopping pagination. If you experience this, please ensure you're running the latest version from the `main` branch.