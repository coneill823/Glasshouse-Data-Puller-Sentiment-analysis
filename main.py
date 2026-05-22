#!/usr/bin/env python3
"""
Glasshouse Parliamentary Data Puller
=====================================
Pulls Register of Interests, Questions, Plenary Business, and Votes on Division
for MPs / MLAs / MSPs / MSs from:
  - NI Assembly (Stormont)
  - UK Parliament (Westminster)
  - Scottish Parliament (Holyrood)
  - Welsh Parliament / Senedd

Usage
-----
  python main.py                        # pull all parliaments, all history
  python main.py --parliament ni        # pull NI Assembly only
  python main.py --from 2024-01-01     # pull from a specific date
  python main.py --schedule            # run monthly on the 1st of each month
  python main.py --dry-run             # show what would be pulled, don't save
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import schedule
import time

from config import PARLIAMENTS
from scrapers import (
    NIAssemblyScraper,
    UKParliamentScraper,
    ScottishParliamentScraper,
    WelshParliamentScraper,
)
from utils.storage import save_results, load_manifest, write_manifest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

SCRAPERS = {
    "ni": ("ni_assembly", NIAssemblyScraper),
    "uk": ("uk_parliament", UKParliamentScraper),
    "scotland": ("scottish_parliament", ScottishParliamentScraper),
    "wales": ("welsh_parliament", WelshParliamentScraper),
}

DATA_TYPES = [
    "register_of_interests",
    "questions",
    "plenary_business",
    "votes_on_division",
]


def run_parliament(parliament_key: str, scraper_class, from_date: Optional[str] = None,
                   dry_run: bool = False):
    cfg_key, _ = SCRAPERS[parliament_key]
    cfg = PARLIAMENTS[cfg_key]
    if not cfg.get("enabled", True):
        logger.info(f"Skipping {cfg['name']} (disabled in config)")
        return

    logger.info(f"{'[DRY RUN] ' if dry_run else ''}Starting pull for {cfg['name']}")
    scraper = scraper_class()

    manifest = load_manifest(cfg["name"])
    effective_from = from_date or manifest.get("last_pulled_from")

    try:
        results = scraper.fetch_all(from_date=effective_from)
    except Exception as e:
        logger.error(f"Pull failed for {cfg['name']}: {e}", exc_info=True)
        return

    if dry_run:
        for dtype, records in results.items():
            logger.info(f"  [DRY RUN] {dtype}: {len(records)} records (not saved)")
        return

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    saved_paths = {}
    for dtype, records in results.items():
        paths = save_results(cfg["name"], dtype, records, run_date=run_date)
        saved_paths[dtype] = paths

    manifest["last_pulled_at"] = datetime.now(timezone.utc).isoformat()
    manifest["last_pulled_from"] = effective_from
    manifest["runs"] = manifest.get("runs", []) + [{
        "date": run_date,
        "counts": {dtype: len(records) for dtype, records in results.items()},
    }]
    write_manifest(cfg["name"], manifest)
    logger.info(f"Completed pull for {cfg['name']}")


def run_all(from_date: Optional[str] = None, parliament_filter: Optional[str] = None,
            dry_run: bool = False):
    keys = [parliament_filter] if parliament_filter else list(SCRAPERS.keys())
    for key in keys:
        if key not in SCRAPERS:
            logger.error(f"Unknown parliament key '{key}'. Choose from: {', '.join(SCRAPERS)}")
            sys.exit(1)
        cfg_key, cls = SCRAPERS[key]
        run_parliament(key, cls, from_date=from_date, dry_run=dry_run)


def scheduled_job():
    logger.info("=== Scheduled monthly pull starting ===")
    run_all()
    logger.info("=== Scheduled monthly pull complete ===")


def main():
    parser = argparse.ArgumentParser(
        description="Pull MP/MLA/MSP/MS data from NI Assembly, UK Parliament, Scottish Parliament, and Senedd"
    )
    parser.add_argument(
        "--parliament", "-p",
        choices=list(SCRAPERS.keys()),
        help="Pull a single parliament only (ni | uk | scotland | wales)",
    )
    parser.add_argument(
        "--from", dest="from_date", metavar="YYYY-MM-DD",
        help="Fetch data from this date onwards (default: all history / since last pull)",
    )
    parser.add_argument(
        "--schedule", action="store_true",
        help="Run in scheduler mode: pull on the 1st of every month",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be pulled without saving any files",
    )
    args = parser.parse_args()

    if args.schedule:
        logger.info("Scheduler mode: will pull on the 1st of each month at 02:00 UTC")
        schedule.every().month.at("02:00").do(scheduled_job)
        # Also run immediately on startup
        scheduled_job()
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_all(
            from_date=args.from_date,
            parliament_filter=args.parliament,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
