"""
Handles persisting scraped records as JSON and CSV files.

Directory layout:
  data/{parliament_slug}/{data_type}/YYYY-MM-DD_{data_type}.json
  data/{parliament_slug}/{data_type}/YYYY-MM-DD_{data_type}.csv
  data/{parliament_slug}/manifest.json  ← tracks last-pulled timestamps
"""
import json
import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

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


def save_results(parliament_name: str, data_type: str, records: List[Dict],
                 run_date: Optional[str] = None) -> Dict[str, Path]:
    """
    Write records to JSON and CSV files.
    Returns a dict with paths to the written files.
    """
    if not records:
        logger.info(f"No records to save for {parliament_name}/{data_type}")
        return {}

    run_date = run_date or datetime.utcnow().strftime("%Y-%m-%d")
    parliament_slug = _slug(parliament_name)
    data_type_slug = _slug(data_type)

    out_dir = DATA_DIR / parliament_slug / data_type_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{run_date}_{data_type_slug}"
    json_path = out_dir / f"{base_name}.json"
    csv_path = out_dir / f"{base_name}.csv"

    # JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=_json_default)
    logger.info(f"Saved {len(records)} records → {json_path}")

    # CSV (flattened)
    flat_records = [_flatten_record(r) for r in records]
    df = pd.DataFrame(flat_records)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")  # utf-8-sig for Excel compatibility
    logger.info(f"Saved {len(records)} records → {csv_path}")

    return {"json": json_path, "csv": csv_path}


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
