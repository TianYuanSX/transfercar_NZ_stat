# Transfercar CSV scraper

This small Python script crawls the current relocation listings from Transfercar and exports them to CSV.

## Daily CI/CD on GitHub

This repository includes a GitHub Actions workflow at `.github/workflows/daily-transfercar-scrape.yml`.

- It runs every day at `00:10 UTC`.
- It can also be triggered manually from the **Actions** tab.
- It generates `data/transfercar_listings_daily.csv`.
- It uploads the CSV as a workflow artifact.
- It auto-commits and pushes the CSV when data changes.

### One-time setup

1. Create a GitHub repository and push this project.
2. In GitHub, open **Settings** -> **Actions** -> **General**.
3. Under **Workflow permissions**, select **Read and write permissions**.
4. Save settings.

After that, the daily task will run automatically.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python scrape_transfercar.py --output transfercar_listings.csv
```

Optional filters are supported:

```bash
python scrape_transfercar.py --pickup Auckland --dropoff Christchurch --output filtered.csv
```

The script follows pagination automatically and stops when there are no more result pages.