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
  python main.py --from 2024-01-01 --to 2024-06-30   # pull a specific date range
  python main.py --schedule            # run monthly on the 1st of each month
  python main.py --dry-run             # show what would be pulled, don't save

Incremental pulls
-----------------
Every record saved is hashed into data/{parliament}/{data_type}/.seen_keys.
Re-running over an already-covered range skips records pulled before and only
appends new ones (per-run files + a cumulative {data_type}_master.csv).
Without --from, each run automatically resumes from where the last successful
run started (tracked in data/{parliament}/manifest.json), so routine re-runs
stay fast.
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timezone  # timezone required — do not remove
from pathlib import Path
from typing import Dict, List, Optional

import schedule

from config import PARLIAMENTS
from scrapers import (
    NIAssemblyScraper,
    UKParliamentScraper,
    ScottishParliamentScraper,
    WelshParliamentScraper,
)
from utils.storage import save_results, load_manifest, write_manifest

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_LOG_DATE = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("main")


def _setup_logging(run_label: str = "all") -> Path:
    """Configure console + file logging.  File name encodes the run type and timestamp."""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    log_path = logs_dir / f"run_{run_label}_{run_ts}.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE))
    root.addHandler(ch)

    # File handler — captures everything the console shows
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE))
    root.addHandler(fh)

    return log_path

SCRAPERS = {
    "ni": ("ni_assembly", NIAssemblyScraper),
    "uk": ("uk_parliament", UKParliamentScraper),
    "scotland": ("scottish_parliament", ScottishParliamentScraper),
    "wales": ("welsh_parliament", WelshParliamentScraper),
}

# Parliaments don't hold plenary sessions or divisions every day, so 0 records
# for these types during a narrow incremental pull is completely normal.
_NORMAL_EMPTY = {"plenary_business", "votes_on_division"}

# Data types that are known to return 0 records (or partial fields) for reasons
# outside the scraper's control. A 0-count for these appears in the run summary
# as an expected limitation, not a failure needing attention.
#
# (Welsh votes and Scottish plenary were previously listed here but are now
# fetched — Welsh via the Senedd Votes export, Scottish via browser-driven
# Official Report search + PDF parsing. Scottish plenary can still be sparse for
# very recent windows because Session 7 has barely sat since the May 2026
# election, but that is handled as a _NORMAL_EMPTY 0, not a hard limitation.)
KNOWN_LIMITATIONS = {
    ("Welsh Parliament (Senedd)", "register_of_interests"):
        "Senedd publishes the consolidated Register of Interests only as an "
        "end-of-term PDF; the current Senedd's is not yet published, so this "
        "returns 0 records until then (in-term interests live on per-member "
        "profile pages, not scraped here)",
}


def _assess_members(records: List[Dict]) -> List[str]:
    """Check completeness of raw member dicts (name/party/id fields, not _make_record shape)."""
    if not records:
        return ["no members returned"]
    n = len(records)
    issues = []
    empty_name  = sum(1 for r in records if not str(r.get("name", "")).strip())
    empty_party = sum(1 for r in records if not str(r.get("party", "")).strip())
    empty_id    = sum(1 for r in records if not str(r.get("id", "")).strip())
    if empty_name  > n // 2: issues.append(f"{empty_name}/{n} name fields empty")
    if empty_party == n:     issues.append("ALL party fields empty")
    if empty_id    == n:     issues.append("ALL id fields empty")
    return issues


def _assess(records: List[Dict]) -> List[str]:
    """Field-completeness check mirroring test_scrape.py's _assess()."""
    if not records:
        return ["no records returned — may simply be no data in the pulled date range"]
    n = len(records)
    issues = []
    empty_text = sum(1 for r in records if not str(r.get("text", "")).strip())
    empty_date = sum(1 for r in records if not str(r.get("date", "")).strip())
    empty_name = sum(1 for r in records if not (r.get("member") or {}).get("name", "").strip())
    if empty_text == n:
        issues.append("ALL text fields empty")
    elif empty_text > n // 2:
        issues.append(f"{empty_text}/{n} text fields empty")
    if empty_date > n // 2:
        issues.append(f"{empty_date}/{n} date fields empty")
    if empty_name > n // 2:
        issues.append(f"{empty_name}/{n} member name fields empty")
    return issues


def run_parliament(parliament_key: str, scraper_class, from_date: Optional[str] = None,
                   to_date: Optional[str] = None,
                   dry_run: bool = False):
    """Pull one parliament.

    Returns ``(results, dedup_stats)`` where *results* maps data_type → records
    and *dedup_stats* maps data_type → {"new": N, "skipped": N}.
    Returns ``(None, {})`` on failure or when the parliament is disabled.
    """
    cfg_key, _ = SCRAPERS[parliament_key]
    cfg = PARLIAMENTS[cfg_key]
    if not cfg.get("enabled", True):
        logger.info(f"Skipping {cfg['name']} (disabled in config)")
        return None, {}

    logger.info(f"{'[DRY RUN] ' if dry_run else ''}Starting pull for {cfg['name']}")
    scraper = scraper_class()

    manifest = load_manifest(cfg["name"])
    effective_from = from_date or manifest.get("last_pulled_from")
    run_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        results = scraper.fetch_all(from_date=effective_from, to_date=to_date)
    except Exception as e:
        logger.error(f"Pull failed for {cfg['name']}: {e}", exc_info=True)
        return None, {}

    if dry_run:
        for dtype, records in results.items():
            logger.info(f"  [DRY RUN] {dtype}: {len(records)} records (not saved)")
        return results, {}

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dedup_stats: Dict[str, Dict[str, int]] = {}
    for dtype, records in results.items():
        paths = save_results(cfg["name"], dtype, records, run_date=run_date)
        dedup_stats[dtype] = {"new": paths.get("new", 0), "skipped": paths.get("skipped", 0)}

    manifest["last_pulled_at"] = datetime.now(timezone.utc).isoformat()
    # Advance the resume point so the next default run is incremental:
    # an open-ended pull resumes from the day this one started; a bounded
    # (--to) pull only advances to its end date, so the gap between the
    # range end and today isn't silently skipped next time.
    manifest["last_pulled_from"] = min(to_date, run_start) if to_date else run_start
    manifest["runs"] = manifest.get("runs", []) + [{
        "date": run_date,
        "from_date": effective_from,
        "to_date": to_date,
        "counts": {dtype: len(records) for dtype, records in results.items()},
    }]
    write_manifest(cfg["name"], manifest)
    logger.info(f"Completed pull for {cfg['name']}")
    return results, dedup_stats


def _summarise(all_results: Dict[str, Dict[str, List[Dict]]],
               elapsed_by_parliament: Dict[str, float], total_elapsed: float,
               all_dedup_stats: Optional[Dict[str, Dict[str, Dict[str, int]]]] = None):
    """Log a test_scrape-style summary table so the run log ends with a reviewable digest."""
    W = 100
    lines = ["", "=" * W,
             f"RUN SUMMARY  ({total_elapsed / 60:.1f} min total)",
             "=" * W,
             f"{'Parliament':<30} {'Data Type':<25} {'Fetched':>8} {'New':>7} {'Skipped':>8}  Issues"]
    lines.append("-" * W)

    total_fetched = total_new = total_skipped = 0
    attention = []
    expected = []
    for parl_name, results in all_results.items():
        dedup = (all_dedup_stats or {}).get(parl_name, {})
        for dtype, records in results.items():
            n = len(records)
            stats = dedup.get(dtype, {})
            n_new = stats.get("new", 0)
            n_skipped = stats.get("skipped", 0)
            total_fetched += n
            total_new += n_new
            total_skipped += n_skipped

            # Determine issues
            issues = _assess_members(records) if dtype == "members" else _assess(records)
            note = KNOWN_LIMITATIONS.get((parl_name, dtype))

            # 0 plenary/votes records is normal (no sessions every day) — don't alarm
            if not records and dtype in _NORMAL_EMPTY and not note:
                issue_str = "no sessions/divisions in date range"
                lines.append(f"{parl_name:<30} {dtype:<25} {n:>8} {n_new:>7} {n_skipped:>8}  {issue_str}")
                continue

            issue_str = " | ".join(issues) if issues else ""
            if issues and note:
                issue_str += "  [expected]"
                expected.append((parl_name, dtype, note))
            elif issues:
                attention.append((parl_name, dtype, issue_str))
            lines.append(f"{parl_name:<30} {dtype:<25} {n:>8} {n_new:>7} {n_skipped:>8}  {issue_str}")
        lines.append(
            f"{'':<30} {'(elapsed)':<25} {elapsed_by_parliament.get(parl_name, 0) / 60:>7.1f}m"
        )
        lines.append("-" * W)

    lines.append(f"TOTAL: {total_fetched:,} fetched  |  {total_new:,} new  |  {total_skipped:,} skipped")

    if attention:
        lines.append("")
        lines.append("Issues that need attention:")
        for parl_name, dtype, issue_str in attention:
            lines.append(f"  {parl_name} / {dtype}: {issue_str}")

    if expected:
        lines.append("")
        lines.append("Known structural limitations (expected):")
        for parl_name, dtype, note in expected:
            lines.append(f"  {parl_name} / {dtype}: {note}")

    lines.append("=" * W)
    logger.info("\n".join(lines))


def run_all(from_date: Optional[str] = None, to_date: Optional[str] = None,
            parliament_filter: Optional[str] = None, dry_run: bool = False):
    keys = [parliament_filter] if parliament_filter else list(SCRAPERS.keys())
    for key in keys:
        if key not in SCRAPERS:
            logger.error(f"Unknown parliament key '{key}'. Choose from: {', '.join(SCRAPERS)}")
            sys.exit(1)

    t0 = time.time()
    all_results: Dict[str, Dict[str, List[Dict]]] = {}
    all_dedup_stats: Dict[str, Dict[str, Dict[str, int]]] = {}
    elapsed_by_parliament: Dict[str, float] = {}
    for key in keys:
        cfg_key, cls = SCRAPERS[key]
        parl_name = PARLIAMENTS[cfg_key]["name"]
        p0 = time.time()
        results, dedup_stats = run_parliament(key, cls, from_date=from_date, to_date=to_date,
                                              dry_run=dry_run)
        elapsed_by_parliament[parl_name] = time.time() - p0
        if results is not None:
            all_results[parl_name] = results
            all_dedup_stats[parl_name] = dedup_stats

    _summarise(all_results, elapsed_by_parliament, time.time() - t0, all_dedup_stats)


def scheduled_job():
    logger.info("=== Scheduled monthly pull starting ===")
    run_all()
    logger.info("=== Scheduled monthly pull complete ===")


def _monthly_check():
    # The schedule library has no native monthly interval — run daily and
    # fire only on the 1st of the month.
    if datetime.now(timezone.utc).day == 1:
        scheduled_job()


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
        "--to", dest="to_date", metavar="YYYY-MM-DD",
        help="Fetch data up to and including this date (default: today)",
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

    for arg_name, value in [("--from", args.from_date), ("--to", args.to_date)]:
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                parser.error(f"{arg_name} must be in YYYY-MM-DD format (got {value!r})")
    if args.from_date and args.to_date and args.to_date < args.from_date:
        parser.error(f"--to ({args.to_date}) is before --from ({args.from_date})")

    run_label = "scheduled" if args.schedule else (args.parliament or "all")
    log_path = _setup_logging(run_label)
    logger.info(f"Log file: {log_path.resolve()}")

    if args.schedule:
        logger.info("Scheduler mode: will pull on the 1st of each month at 02:00 UTC")
        schedule.every().day.at("02:00").do(_monthly_check)
        # Also run immediately on startup
        scheduled_job()
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_all(
            from_date=args.from_date,
            to_date=args.to_date,
            parliament_filter=args.parliament,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
