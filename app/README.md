# Glasshouse Grades — app layer

A single-page, no-build front end: **search your area → see its sitting
representatives, graded**.

## Files

- `index.html` — the whole app (no framework, no build step).
- `data.json` — generated payload: every sitting representative with a
  constituency/region, their activity counts, tone, and per-topic stance.

## Regenerate the data

```bash
python -m analysis.grade                 # produces analysis/output/*.csv
python -m analysis.export_app_data       # CSVs -> app/data.json
```

`export_app_data` keeps only members with `status=current` **and** a
constituency — the app answers "who represents my area", so historical members
and unmatched speakers aren't useful in it. Pass `--all` to include them anyway.

## Run it

```bash
python -m http.server 8000 --directory app
# then open http://localhost:8000
```

A `file://` open works too, except `fetch("data.json")` is blocked by the
browser — use the server, or inline the JSON (see below).

## Payload shape

```jsonc
{
  "generated": "2026-09-12",
  "topics": ["Business & industry", "Crime & justice", ...],   // 20, "Pro-" stripped
  "members": [
    {
      "name": "Stephen Kinnock", "party": "Labour",
      "area": "Aberafan Maesteg", "parliament": "UK Parliament",
      "activity": 4384, "questions": 804, "speeches": 1795, "votes": 1785,
      "tone": 0.386, "topPro": "Energy", "topCon": "Health & social care",
      "topics": { "Energy": [0.94, 312], ... }   // topic -> [stance, evidence hits]
    }
  ]
}
```

Stance runs **−1 (against) … +1 (pro)** and is always read as *pro that topic* —
the grading CSVs name categories `Pro-<topic>`; the exporter strips the prefix
because the app states the convention once, in its method note.

## Standalone single-file build

`index.html` reads its data from an inline
`<script id="app-data" type="application/json">` block if one is populated, and
otherwise falls back to `fetch("data.json")`. So the same page serves the repo
unchanged, and a self-contained copy — one file, no server needed, opens by
double-clicking — is:

```bash
python app/build_standalone.py          # -> dist/glasshouse-grades.html
python app/build_standalone.py --out ~/Desktop/grades.html
```

Use this for hosts that won't serve a `.json` file or let you create folders,
and for emailing someone a working copy.

## Putting it on a website

Nothing server-side is involved — it's static files — so any host works:

- **A folder on your host** (FTP/cPanel, Netlify, Cloudflare Pages): upload
  `index.html` and `data.json` together into e.g. `/grades/`.
- **GitHub Pages**: Settings → Pages → deploy from branch, folder `/app`.
- **One file**: upload `dist/glasshouse-grades.html` anywhere.
- **Inside an existing page** (WordPress/Squarespace/Wix, where you can't upload
  loose HTML): host it by one of the above, then embed it:
  ```html
  <iframe src="https://yoursite.com/grades/" title="Glasshouse Grades"
          style="width:100%;height:min(1100px,85vh);border:0"
          loading="lazy"></iframe>
  ```

Re-run `analysis.export_app_data` (and `build_standalone.py` if you use it)
after each data pull to refresh what's published.
