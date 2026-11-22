# Glasshouse

Find the people who represent you in the House of Commons, the Scottish
Parliament, the Senedd and the Northern Ireland Assembly; see what they
actually did; and take a quiz that compares your views with how each of them
voted, in each parliament you are represented in.

Everything is built from recorded acts — votes first, words last. The reasoning
is in [docs/METHODS.md](docs/METHODS.md).

Also here, each by what the public record can support and no further:

- **former MPs, MSPs and MSs, and the House of Lords**, found by name, with
  the same voting record;
- **who you can vote for**: elections coming up for a postcode and the
  candidates standing, from Democracy Club. Nobody is scored for standing;
- **councillors**, as a trial with two councils. Councils do not record who
  voted which way, so this is names, parties and, where published, attendance.

## Quick start

```bash
pip install -r requirements.txt
python -m analysis.build                        # builds the app's data, ~20 seconds
python -m http.server 8000 --directory app      # then open http://localhost:8000
```

That is enough to run the app with today's votes. It also writes
`dist/glasshouse.html`, the whole app as one file you can open or upload.

There are two apps over the same data: the website in `app/`, and the Android
and iPhone app in `mobile/`, written in Flutter. [mobile/README.md](mobile/README.md)
covers running it, installing a test build on your phone, and releasing it on
Google Play and the App Store.

## How the data flows

```
mySociety open data  ──────────────┐   small, daily: who sits where, every vote,
(analysis/mysociety.py)            │   the vote-to-policy mapping, motions signed
                                   │
Democracy Club  ───────────────────┤   small, daily: elections coming up and
(analysis/candidates.py)           │   who is standing
                                   ├──► analysis/build.py ──► app/data.json
Two councils' own records  ────────┤                          app/quiz.json
(analysis/councils.py)             │   a trial: councillors and attendance
                                   │
Glasshouse scrapers  ──────────────┘   large, slow: questions, speeches,
(main.py -> data/)                     registers of interests, NI Assembly votes
```

The scrapers are only needed for what mySociety does not publish: what members
ask and speak about, and Northern Ireland Assembly divisions. Without them the
build still works and carries the previous speech figures forward, dated.
Everything fetched is cached under `data/`; `python -m analysis.build
--no-fetch` rebuilds from the cache alone.

```bash
python main.py --parliament ni                          # everything for the Assembly
python main.py --parliament uk --skip votes_on_division # skip the slowest scrape:
                                                        # those votes come from mySociety
python main.py --parliament scotland --only questions,plenary_business
```

## What is where

| Path | What it is |
|---|---|
| `app/` | The website: one page, no build step. See [app/README.md](app/README.md) |
| `mobile/` | The Android and iPhone app. See [mobile/README.md](mobile/README.md) |
| `analysis/` | Turns raw data into what the app shows. See [analysis/README.md](analysis/README.md) |
| `analysis/quiz_editorial.json` | Every editorial decision we make, in one file |
| `scrapers/`, `main.py`, `config.py` | Collecting from the four legislatures' own sites |
| `tests/` | `python -m unittest discover -s tests -t .` |
| `docs/METHODS.md` | Every way to assess a representative, and which we use |
| `docs/PRIVACY.md` | A draft privacy policy for the website and the apps |

## Tests

```bash
python -m unittest discover -s tests -t .
```

No network, a couple of seconds. Each test in `tests/test_behaviour.py` and
`tests/test_record.py` pins a bug that was found on real data;
`tests/test_published_data.py` checks the two files the apps read, including
that nothing is kept about a candidate beyond name, party and where they are
standing. The phone app has its own suite: `cd mobile && flutter test`.

The quiz arithmetic is written once, in `analysis/quizmath.py`. It writes a
small frozen slice of real data with the answers it should give, which the
phone app's tests must reproduce.

## Credits

Votes, memberships and policy groupings: [TheyWorkForYou Votes](https://votes.theyworkforyou.com)
and the parlparse register, by [mySociety](https://www.mysociety.org) (CC BY 4.0).
Elections and candidates: [Democracy Club](https://democracyclub.org.uk) (CC BY 4.0).
Contains Parliamentary information licensed under the Open Parliament Licence
v3.0, public sector information licensed under the Open Government Licence
v3.0, and information published by the Scottish Parliament, Senedd Cymru, the
Northern Ireland Assembly, Belfast City Council and Cardiff Council. Postcode
lookup by [postcodes.io](https://postcodes.io). Glasshouse is not affiliated
with any of them.
