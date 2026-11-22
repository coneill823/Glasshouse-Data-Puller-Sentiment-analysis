#!/usr/bin/env python3
"""
Build everything the app needs, in one command.

    python -m analysis.build

    1. refresh mySociety's open data (a few MB; skipped if under a day old)
    2. quiz statements and every MP's position      -> app/quiz.json
    3. speech figures from the scraped corpus, if it is on this machine
                                                    -> analysis/output/*.csv
    4. merge into one file per representative       -> app/data.json
    5. the app as a single self-contained page      -> dist/glasshouse.html
       and the copy the phone app ships with        -> mobile/assets/data/

Step 3 is the only slow one and the only one that needs the scrapers to have
run (`python main.py`). Without the corpus the build still succeeds: the
figures for what members work on are carried forward from the previous build
and dated accordingly.
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import time
from pathlib import Path

from analysis import behaviour, export_app_data, mysociety, positions

ROOT = Path(__file__).resolve().parent.parent
# Legislature folders whose VOTES come from mySociety, so behaviour.py need not
# read them. Their questions and speeches are still read.
VOTES_FROM_MYSOCIETY = ("uk_parliament", "scottish_parliament", "welsh_parliament_senedd")


def sync_mobile(app_dir: Path = ROOT / "app",
                mobile_dir: Path = ROOT / "mobile" / "assets" / "data") -> list:
    """Give the phone app the same two files the website uses.

    The app ships with a copy so that it works from the first launch, with or
    without a connection. Returns the names of the files that changed.
    """
    if not mobile_dir.is_dir():
        return []
    changed = []
    for name in ("data.json", "quiz.json"):
        source, target = app_dir / name, mobile_dir / name
        if source.exists() and (not target.exists()
                                or source.read_bytes() != target.read_bytes()):
            shutil.copyfile(source, target)
            changed.append(name)
    return changed


def _scraped_legislatures(data_dir: Path) -> list:
    if not data_dir.exists():
        return []
    return sorted(p.name for p in data_dir.iterdir()
                  if p.is_dir() and not p.name.startswith(("_", "."))
                  and any(p.glob("*/*_master.csv")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build app/data.json, app/quiz.json and dist/.")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--no-fetch", action="store_true",
                    help="use the mySociety cache as it is")
    ap.add_argument("--skip-speech", action="store_true",
                    help="don't re-read the scraped corpus (carry speech figures forward)")
    a = ap.parse_args(argv)

    data_dir = Path(a.data_dir)
    cache = data_dir / "_mysociety"
    out_dir = Path("analysis/output")
    t0 = time.time()

    print("[1/5] mySociety open data")
    if a.no_fetch:
        print("  using the cache as it is")
    else:
        mysociety.fetch(cache)

    print("[2/5] quiz statements and MP positions")
    positions.build(cache, Path("app/quiz.json"), fetch=not a.no_fetch)

    print("[3/5] speech figures from the scraped corpus")
    scraped = _scraped_legislatures(data_dir)
    if a.skip_speech or not scraped:
        print("  " + ("skipped" if a.skip_speech else
                      f"no scraped data under {data_dir}/ — carrying the previous figures forward"))
    else:
        print(f"  reading {', '.join(scraped)}")
        behaviour.analyse(data_dir, out_dir, skip_votes=VOTES_FROM_MYSOCIETY)

    print("[4/5] one record per representative")
    export_app_data.build(cache, out_dir, Path("app/data.json"), fetch=False)

    print("[5/5] single-file app, and the phone app's copy of the data")
    spec = importlib.util.spec_from_file_location("build_standalone",
                                                  ROOT / "app" / "build_standalone.py")
    standalone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(standalone)
    standalone.build(ROOT / "app" / "index.html", ROOT / "app",
                     ROOT / "dist" / "glasshouse.html")
    changed = sync_mobile()
    if changed:
        print(f"Updated mobile/assets/data/ ({', '.join(changed)}).")
    print(f"Done in {time.time() - t0:.0f}s. Serve it with: "
          f"python -m http.server 8000 --directory app")


if __name__ == "__main__":
    main()
