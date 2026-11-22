# Glasshouse

Find the people who represent you in the House of Commons, the Scottish
Parliament, the Senedd and the Northern Ireland Assembly; see what they
actually did; and take a quiz that compares your views with how your MP voted.

Everything is built from recorded acts — votes first, words last. The reasoning
is in [docs/METHODS.md](docs/METHODS.md).

## Quick start

```bash
pip install -r requirements.txt
python -m analysis.build                        # builds the app's data, ~20 seconds
python -m http.server 8000 --directory app      # then open http://localhost:8000
```

That is enough to run the app with today's votes. It also writes
`dist/glasshouse.html`, the whole app as one file you can open or upload.

## How the data flows

```
mySociety open data  ──────────────┐   small, daily: who sits where, every vote,
(analysis/mysociety.py)            │   the vote-to-policy mapping, motions signed
                                   ├──► analysis/build.py ──► app/data.json
Glasshouse scrapers  ──────────────┘                          app/quiz.json
(main.py -> data/)                     large, slow: questions, speeches,
                                       registers of interests, NI Assembly votes
```

The scrapers are only needed for what mySociety does not publish: what members
ask and speak about, and Northern Ireland Assembly divisions. Without them the
build still works and carries the previous speech figures forward, dated.

```bash
python main.py --parliament ni                          # everything for the Assembly
python main.py --parliament uk --skip votes_on_division # skip the slowest scrape:
                                                        # those votes come from mySociety
python main.py --parliament scotland --only questions,plenary_business
```

## What is where

| Path | What it is |
|---|---|
| `app/` | The app: one page, no build step. See [app/README.md](app/README.md) |
| `analysis/` | Turns raw data into what the app shows. See [analysis/README.md](analysis/README.md) |
| `analysis/quiz_editorial.json` | Every editorial decision we make, in one file |
| `scrapers/`, `main.py`, `config.py` | Collecting from the four legislatures' own sites |
| `tests/` | `python -m unittest discover -s tests -t .` |
| `docs/METHODS.md` | Every way to assess a representative, and which we use |

## Tests

```bash
python -m unittest discover -s tests -t .
```

No network, under a second. Each test in `tests/test_behaviour.py` and
`tests/test_record.py` pins a bug that was found on real data.

## Credits

Votes, memberships and policy groupings: [TheyWorkForYou Votes](https://votes.theyworkforyou.com)
and the parlparse register, by [mySociety](https://www.mysociety.org) (CC BY 4.0).
Contains Parliamentary information licensed under the Open Parliament Licence
v3.0, and information published by the Scottish Parliament, Senedd Cymru and
the Northern Ireland Assembly. Postcode lookup by [postcodes.io](https://postcodes.io).
Glasshouse is not affiliated with any of them.
