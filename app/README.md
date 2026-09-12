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

## Standalone / hosted copy

`index.html` reads its data from an inline
`<script id="app-data" type="application/json">` block if one is populated, and
otherwise falls back to `fetch("data.json")`. So the same file serves the repo
unchanged, and a self-contained single-file copy is just:

```bash
python - <<'PY'
import pathlib
d = pathlib.Path("app/data.json").read_text(encoding="utf-8")
h = pathlib.Path("app/index.html").read_text(encoding="utf-8")
pathlib.Path("glasshouse-grades.html").write_text(
    h.replace('<script id="app-data" type="application/json">null</script>',
              '<script id="app-data" type="application/json">' + d + '</script>'),
    encoding="utf-8")
PY
```
