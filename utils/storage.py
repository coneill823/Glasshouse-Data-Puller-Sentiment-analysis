"""
Handles persisting scraped records as JSON and CSV files.

Directory layout:
  data/{parliament_slug}/{data_type}/YYYY-MM-DD_{data_type}.json   ← new records from that run
  data/{parliament_slug}/{data_type}/YYYY-MM-DD_{data_type}.csv
  data/{parliament_slug}/{data_type}/{data_type}_master.csv        ← cumulative deduped dataset
  data/{parliament_slug}/{data_type}/.seen_keys                    ← dedup index (one hash per line)
  data/{parliament_slug}/manifest.json  ← tracks last-pulled timestamps

Every save is deduplicated against .seen_keys, so re-running a pull over an
already-covered date range only appends records that haven't been seen before.
"""
import hashlib
import json
import logging
import re
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from config import DATA_DIR

logger = logging.getLogger(__name__)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _flatten_record(record: Dict) -> Dict:
    """Flatten nested dicts to a single level for CSV export."""
    flat = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}_{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _record_key(record: Dict) -> str:
    """Stable dedup hash for a record.

    Deliberately excludes pulled_at/source_url volatility: the same speech or
    question fetched on two different runs must hash identically. Text is
    truncated so cosmetic trailing changes on huge transcripts don't defeat
    the dedup.
    """
    m = record.get("member") or {}
    raw = "|".join([
        str(record.get("data_type", "")),
        str(m.get("id", "")),
        str(m.get("name", "")),
        str(record.get("date", ""))[:10],
        str(record.get("title", "")),
        str(record.get("text", ""))[:300],
    ])
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _load_seen_keys(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _split_new_records(records: List[Dict], seen: Set[str]) -> Tuple[List[Dict], List[str]]:
    """Return (records not seen before, their keys) — also dedupes within the batch."""
    new_records, new_keys = [], []
    batch_seen = set(seen)
    for r in records:
        key = _record_key(r)
        if key in batch_seen:
            continue
        batch_seen.add(key)
        new_records.append(r)
        new_keys.append(key)
    return new_records, new_keys


def _append_master_csv(master_path: Path, df: pd.DataFrame):
    """Append rows to the cumulative master CSV, aligning to its existing columns."""
    if not master_path.exists():
        df.to_csv(master_path, index=False, encoding="utf-8-sig")
        return
    existing_cols = list(pd.read_csv(master_path, nrows=0, encoding="utf-8-sig").columns)
    extra = [c for c in df.columns if c not in existing_cols]
    if extra:
        logger.info(f"Master CSV {master_path.name}: new columns {extra} not in existing "
                    f"header — present in per-run files but omitted from master")
    aligned = df.reindex(columns=existing_cols, fill_value="")
    aligned.to_csv(master_path, mode="a", header=False, index=False, encoding="utf-8-sig")


def save_results(parliament_name: str, data_type: str, records: List[Dict],
                 run_date: Optional[str] = None) -> Dict[str, Path]:
    """
    Write records to JSON and CSV files, deduplicated against everything
    previously pulled: only records not saved by an earlier run are written.
    Returns a dict with paths to the written files.
    """
    if not records:
        logger.info(f"No records to save for {parliament_name}/{data_type}")
        return {}

    run_date = run_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parliament_slug = _slug(parliament_name)
    data_type_slug = _slug(data_type)

    out_dir = DATA_DIR / parliament_slug / data_type_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    seen_path = out_dir / ".seen_keys"
    seen = _load_seen_keys(seen_path)
    new_records, new_keys = _split_new_records(records, seen)
    skipped = len(records) - len(new_records)

    if not new_records:
        logger.info(f"{parliament_name}/{data_type}: all {len(records)} records "
                    f"already pulled previously — nothing new to save")
        return {}
    if skipped:
        logger.info(f"{parliament_name}/{data_type}: {len(new_records)} new records, "
                    f"{skipped} already pulled (skipped)")

    base_name = f"{run_date}_{data_type_slug}"
    json_path = out_dir / f"{base_name}.json"
    csv_path = out_dir / f"{base_name}.csv"

    # If an earlier run today already wrote this file, merge so it isn't overwritten
    day_records = new_records
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                day_records = json.load(f) + new_records
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not merge existing {json_path}: {e} — overwriting")

    # JSON (all new records saved on this run date)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(day_records, f, ensure_ascii=False, indent=2, default=_json_default)
    logger.info(f"Saved {len(day_records)} records → {json_path}")

    # CSV (flattened)
    df = pd.DataFrame([_flatten_record(r) for r in day_records])
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")  # utf-8-sig for Excel compatibility
    logger.info(f"Saved {len(day_records)} records → {csv_path}")

    # Cumulative master CSV — the growing, deduped dataset across all runs.
    # Only this run's genuinely-new rows are appended (today's earlier rows,
    # merged into the JSON above, are already in the master).
    master_path = out_dir / f"{data_type_slug}_master.csv"
    new_df = pd.DataFrame([_flatten_record(r) for r in new_records])
    if not new_df.empty:
        _append_master_csv(master_path, new_df)
        logger.info(f"Appended {len(new_df)} records → {master_path}")

    # Record the new keys only after the data has been written, so a crash
    # mid-save never marks unwritten records as already pulled.
    with open(seen_path, "a", encoding="utf-8") as f:
        f.write("".join(k + "\n" for k in new_keys))

    return {"json": json_path, "csv": csv_path, "master": master_path}


def load_manifest(parliament_name: str) -> Dict:
    path = DATA_DIR / _slug(parliament_name) / "manifest.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def write_manifest(parliament_name: str, manifest: Dict):
    out_dir = DATA_DIR / _slug(parliament_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=_json_default)
    logger.debug(f"Manifest written → {path}")
