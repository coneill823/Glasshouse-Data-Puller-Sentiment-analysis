# analysis/

Turns raw data into what the app shows. One command runs all of it:

```bash
python -m analysis.build
```

| Step | Module | Output |
|---|---|---|
| 1 | `mysociety.py` — download / refresh mySociety's open data | `data/_mysociety/` (cache) |
| 2 | `positions.py` — quiz statements and every MP's position | `app/quiz.json` |
| 3 | `behaviour.py` — what members work on; NI votes (needs the scraped corpus) | `analysis/output/*.csv` |
| 4 | `export_app_data.py` — one record per sitting representative | `app/data.json` |
| 5 | `app/build_standalone.py` — the app as a single file | `dist/glasshouse.html` |
| | `build.sync_mobile` — the same two data files, for the phone app to ship with | `mobile/assets/data/` |

Each step also runs on its own (`python -m analysis.positions`, …). Useful
flags on `build`: `--no-fetch` (use the cache as it is), `--skip-speech`
(don't re-read the scraped corpus).

## The modules

**`mysociety.py`** — the source for who sits where, every vote, the
vote-to-policy mapping and motions signed. `People` reads the member register:
sitting members, party *at the time of a vote*, and the date of the last
general election, which is read off the register rather than hardcoded.

**`positions.py`** — a statement is a mySociety policy with at least one
scoring vote this parliament; a position is
`(for − against) / (for + against + abstained)` over scoring votes only.
Checked against mySociety's own published counts: all 23,217 identical.

**`quiz_editorial.json`** — everything *we* decide: wording fixes, and which
compass axis each statement belongs to, each with a reason. If you disagree
with the quiz, this is the only file you need to read.

**`record.py`** — turnout, voting with the party, breaking with it, being on
the winning side, from mySociety's tables (Commons, Scottish Parliament,
Senedd). Eligibility is known and party is the party at the time.

**`behaviour.py`** — the same record computed from scraped CSVs, where
eligibility has to be reconstructed. Still the source for the NI Assembly,
which mySociety does not cover, and for what members ask and speak about.

**`export_app_data.py`** — the member list always comes from the register, so
the app is current to the day. Speech figures are joined by legislature +
area + name; where the scraped corpus is absent they are carried forward from
the previous export and dated.

**`topics.py`** — keyword lists that sort a question or speech into subjects.
Only the `keywords` are used now.

**`grade.py`** — the original lexicon stance scorer. **Superseded and no longer
part of the build**: it inferred positions from word lists and could not tell
a member attacking a policy from one supporting it. Kept as a record of what
was tried; see docs/METHODS.md §18.

## Outputs the app reads

`app/quiz.json`

```jsonc
{
  "termStart": "2024-07-05", "votesAsOf": "2026-11-22",
  "statements": [{
    "id": 20011, "name": "Private School VAT",
    "text": "charging VAT on private school fees",   // "I support …"
    "group": "Taxation", "freeVote": false,
    "econ": -1, "social": 0,                         // from quiz_editorial.json
    "divisions": [{"date": "2024-11-27", "number": 51, "title": "…", "alignment": "agree"}]
  }],
  "members": [{
    "id": 10001, "name": "Diane Abbott", "party": "Labour", "area": "…",
    "pos":   [1.0, null, -0.33, …],                  // one per statement
    "votes": ["fff", "..", "afa", …]                 // one character per division:
  }]                                                 // f for · a against · b abstained
}                                                    // x absent · . not an MP then
```

`app/data.json` — `chambers` (medians and term dates per legislature) and
`members` (identity, voting record, break-with-party receipts, subjects,
motions). `sources` carries the date of the vote data and of the speech data
separately, because they refresh on different schedules.

## Tests

```bash
python -m unittest discover -s tests -t .
```
