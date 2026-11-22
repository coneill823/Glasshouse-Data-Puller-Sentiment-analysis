# analysis/

Turns raw data into what the app shows. One command runs all of it:

```bash
python -m analysis.build
```

| Step | Module | Output |
|---|---|---|
| 1 | `mysociety.py` — download / refresh mySociety's open data | `data/_mysociety/` (cache) |
| 2 | `positions.py` — Commons statements and every MP's position; `devolved.py` — one question per vote for each devolved legislature | `app/quiz.json` |
| 3 | `behaviour.py` — what members work on; NI votes (needs the scraped corpus) | `analysis/output/*.csv` |
| 4 | `export_app_data.py` — one record per sitting representative; `others.py` — former members and peers; `candidates.py` — upcoming elections; `councils.py` — the two trial councils | `app/data.json` |
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
scoring vote; a position is `(for − against) / (for + against + abstained)`
over scoring votes only. Policies voted on in the current parliament are the
core list (`statements`); the rest are `moreStatements`, asked as a second
part. Former MPs with a position on anything go in `former`. The core list
was checked against mySociety's own published counts when first built: all
23,217 identical.

**`devolved.py`** — questions for the Scottish Parliament, the Senedd and the
Northern Ireland Assembly. Each is one division; which divisions are asked is
decided by `qualifies` (no amendments or procedure, a real minority, one per
title, most recent first). Wording is the legislature's own title and motion
text. `python -m analysis.devolved` prints what would be asked.

**`quizmath.py`** — the arithmetic of a match, a compass position and the
asking order, in plain Python. It is the reference the website and the phone
app are held to: `python -m analysis.quizmath` writes a frozen slice of real
data with the results it should give, and the phone app's tests reproduce
them. Change a rule here first.

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

**`others.py`** — everyone with a voting record who holds no seat now: former
MPs, MSPs and MSs, and the House of Lords. Same record, marked `former` or
`peer`.

**`candidates.py`** — elections that have not happened yet and who is standing,
from Democracy Club. Keeps a candidate's name, party and ballot, and nothing
else the register holds. `python -m analysis.candidates` prints what is coming.

**`councils.py`** — a trial: councillors and their attendance for the councils
listed in `COUNCILS`, from each council's own committee system. Its docstring
records what the trial found, including that named votes are not there to
collect. `python -m analysis.councils` prints it.

**`topics.py`** — keyword lists that sort a question or speech into subjects.
Only the `keywords` are used now.

**`grade.py`** — the original lexicon stance scorer. **Superseded and no longer
part of the build**: it inferred positions from word lists and could not tell
a member attacking a policy from one supporting it. Kept as a record of what
was tried; see docs/METHODS.md §18.

## Outputs the app reads

Both files carry `"schema": 2`. Everything a version-1 reader used is still
there under the same key; what is new is in new keys. The phone app refuses a
pair it does not understand and keeps the copy it shipped with.

`app/quiz.json`

```jsonc
{
  "schema": 2,
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
    "votes": ["fff", "", "afa", …],                  // one character per division:
                                                     // f for · a against · b abstained
                                                     // x absent · . not a member then
                                                     // "" if not a member for any of it
    "morePos": […], "moreVotes": […]                 // the same for moreStatements;
  }],                                                // left out if they have none
  "moreStatements": [ … ],     // policies last voted on in earlier parliaments
  "former": [ … ],             // former MPs, as members, plus "from" and "to"
  "chambers": {                // one quiz per devolved legislature
    "NI Assembly": {
      "termStart": "2022-05-05", "votesAsOf": "…", "source": "…",
      "statements": [{         // as above, with one division each, and:
        "result": [49, 24],    //   ayes, noes
        "detail": "That this Assembly …",            // the motion as it was put
        "divisions": [{"date": "…", "title": "…", "alignment": "agree", "url": "…"}]
      }],
      "members": [{"id": 25451, "name": "…", "pos": [1, -1, null, …], "votes": ["f", "a", "x", …]}]
    }
  }
}
```

`app/data.json` — `chambers` (medians and term dates per legislature) and
`members` (identity, voting record, break-with-party receipts, subjects,
motions). `sources` carries the date of the vote data and of the speech data
separately, because they refresh on different schedules. Also:

- `others` — former members and peers, shaped like `members`, with `status`
  (`former` or `peer`) and, for a former member, `until`;
- `elections` — `asOf`, and `ballots`, each with its date, area, the area's
  official `gss` code, and `candidates` (`name`, `party`, and `record`: their
  id here if they have ever held a seat);
- `councils` — `period`, and `bodies`, each with `wards` (`name`, the wards it
  `covers`) and their `councillors` (`name`, `party`, `url`, and `expected` and
  `present` meetings where the council publishes attendance).

## Tests

```bash
python -m unittest discover -s tests -t .
```
