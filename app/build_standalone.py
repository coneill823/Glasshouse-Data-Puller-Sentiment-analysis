#!/usr/bin/env python3
"""
Build a single self-contained HTML file: the app with its data inlined.

`app/index.html` normally fetches `data.json` alongside it, which needs a web
server. This inlines the JSON into the page instead, so the result is one file
that works by double-clicking it, and uploads to any host — including ones that
won't serve a .json file or let you create folders.

Usage:
    python app/build_standalone.py
    python app/build_standalone.py --out ~/Desktop/glasshouse-grades.html
"""
from __future__ import annotations

import argparse
from pathlib import Path

PLACEHOLDER = '<script id="app-data" type="application/json">null</script>'
APP = Path(__file__).resolve().parent


def build(page: Path, data: Path, out: Path) -> Path:
    for p in (page, data):
        if not p.exists():
            raise SystemExit(
                f"Missing {p}"
                + ("\n  Run: python -m analysis.export_app_data" if p == data else "")
            )

    payload = data.read_text(encoding="utf-8")
    # The JSON sits inside a <script> block, so it must not contain anything
    # that could close it early.
    for bad in ("</script", "<!--", "<script"):
        if bad in payload:
            raise SystemExit(f"Refusing to inline: data contains {bad!r}")

    html = page.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise SystemExit(f"Couldn't find the data placeholder in {page}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        html.replace(PLACEHOLDER, PLACEHOLDER.replace("null", payload)),
        encoding="utf-8",
    )
    print(f"Built {out} ({out.stat().st_size / 1024:,.0f} KB) — open it or upload it anywhere.")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--page", default=APP / "index.html", type=Path)
    ap.add_argument("--data", default=APP / "data.json", type=Path)
    ap.add_argument("--out", default=APP.parent / "dist" / "glasshouse-grades.html",
                    type=Path)
    a = ap.parse_args(argv)
    build(a.page, a.data, a.out)


if __name__ == "__main__":
    main()
