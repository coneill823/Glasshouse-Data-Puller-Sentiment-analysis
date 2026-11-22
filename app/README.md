# app/

The Glasshouse app: one page, no framework, no build step.

| File | |
|---|---|
| `index.html` | The whole app |
| `data.json` | Every sitting representative: record, subjects, receipts |
| `quiz.json` | The quiz statements and every MP's position on each |
| `build_standalone.py` | Inlines both data files into one self-contained page |

Rebuild the data with `python -m analysis.build` from the repository root.

## Run it

```bash
python -m http.server 8000 --directory app      # http://localhost:8000
```

Opening `index.html` straight from disk won't load the data (browsers block
`fetch` on `file://`). Use the server, or the single-file build:

```bash
python app/build_standalone.py                  # -> dist/glasshouse.html
```

That file works by double-clicking it.

## What it does

- **Your representatives** — find them by postcode, constituency or name. Each
  card shows turnout, breaks with their party (every one listed, linked to the
  division), what they work on, and for MPs how they voted on each quiz issue.
- **Quiz** — 36 statements MPs have voted on this parliament, answered from
  strongly agree to strongly disagree. Statements can be skipped or marked as
  mattering more.
- **Your match** — agreement with your MP, statement by statement, with every
  vote behind each one; a compass; the MPs and parties closest to you.
- **How it works** — what is counted, whose judgement is involved, and what
  the numbers cannot tell you.

Answers are kept in the visitor's own browser (`localStorage`) and are never
sent anywhere. They are political opinions; the app has no business storing
them.

## Putting it on a website

Nothing runs on a server, so any static host works:

- **A folder on your host**: upload `index.html`, `data.json` and `quiz.json`
  together.
- **GitHub Pages**: Settings → Pages → deploy from a branch, folder `/app`.
- **One file**: upload `dist/glasshouse.html` anywhere.
- **Inside an existing page** (WordPress, Squarespace, Wix): host it one of
  the ways above, then embed it:
  ```html
  <iframe src="https://yoursite.example/glasshouse/" title="Glasshouse"
          style="width:100%;height:min(1200px,90vh);border:0" loading="lazy"></iframe>
  ```

**Postcode lookup** calls the open [postcodes.io](https://postcodes.io) service
from the visitor's browser, so it works on any real website and not inside a
sandboxed preview, where the app falls back to searching by name. It resolves
MPs everywhere and MSPs in Scotland. Senedd constituencies cannot yet be
resolved from a postcode, and NI Assembly seats still use pre-2024 boundaries,
so near an edge the lookup can return the neighbouring seat; the app says so.

## Design notes

- One hue for every mark and a neutral tick for the chamber median. No colour
  means good or bad: being above the median is not a judgement the data makes.
- Your answer and a member's votes are drawn on the same against–for scale;
  where they coincide the dot sits inside the diamond.
- Light and dark themes follow the visitor's system, or a `data-theme`
  attribute on the root element.
- The page declares its own character encoding, because neither a local file
  nor `python -m http.server` sends one and accented names would otherwise
  break.
