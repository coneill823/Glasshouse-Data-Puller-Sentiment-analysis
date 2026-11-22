#!/usr/bin/env python3
"""
Build a single self-contained HTML file: the app with its data inlined.

`app/index.html` normally fetches `data.json` and `quiz.json` alongside it,
which needs a web server. This inlines both into the page instead, so the
result is one file that works by double-clicking it, and uploads to any host —
including ones that won't serve a .json file or let you create folders.

Usage:
    python app/build_standalone.py
    python app/build_standalone.py --out ~/Desktop/glasshouse.html
"""
from __future__ import annotations

import argparse
from pathlib import Path

APP = Path(__file__).resolve().parent
# script id in index.html -> the file whose contents replace its `null`
SLOTS = {"app-data": "data.json", "quiz-data": "quiz.json"}


def _placeholder(slot: str) -> str:
    return f'<script id="{slot}" type="application/json">null</script>'


def build(page: Path, data_dir: Path, out: Path) -> Path:
    if not page.exists():
        raise SystemExit(f"Missing {page}")
    html = page.read_text(encoding="utf-8")
    for slot, filename in SLOTS.items():
        source = data_dir / filename
        if not source.exists():
            if slot == "app-data":
                raise SystemExit(f"Missing {source}\n  Run: python -m analysis.build")
            continue                      # the quiz is optional; the page copes
        payload = source.read_text(encoding="utf-8")
        # The JSON sits inside a <script> block, so it must not contain
        # anything that could close it early.
        for bad in ("</script", "<!--", "<script"):
            if bad in payload:
                raise SystemExit(f"Refusing to inline {filename}: it contains {bad!r}")
        placeholder = _placeholder(slot)
        if placeholder not in html:
            raise SystemExit(f"Couldn't find the {slot} placeholder in {page}")
        html = html.replace(placeholder, placeholder.replace("null", payload))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Built {out} ({out.stat().st_size / 1024:,.0f} KB) — open it or upload it anywhere.")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inline the app's data into one HTML file.")
    ap.add_argument("--page", default=APP / "index.html", type=Path)
    ap.add_argument("--data-dir", default=APP, type=Path)
    ap.add_argument("--out", default=APP.parent / "dist" / "glasshouse.html", type=Path)
    a = ap.parse_args(argv)
    build(a.page, a.data_dir, a.out)


if __name__ == "__main__":
    main()
