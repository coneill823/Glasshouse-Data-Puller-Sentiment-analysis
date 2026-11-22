"""behaviour.py over scraped CSVs — the path the NI Assembly still depends on.

Every expectation here was first worked out by hand when the corresponding
bug was found on real data; the docstrings say which bug.
"""
import csv
import datetime as dt
import random
import tempfile
import unittest
from pathlib import Path

from analysis import behaviour

VOTE_COLS = ["parliament", "data_type", "member_id", "member_name", "member_party",
             "member_constituency", "date", "title", "text",
             "metadata_division_id", "metadata_vote_direction"]
MEMBER_COLS = ["id", "name", "party", "constituency", "status", "role"]


def write(path: Path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def vote(parl, mid, name, party, date, div, direction):
    return {"parliament": parl, "data_type": "vote", "member_id": mid, "member_name": name,
            "member_party": party, "member_constituency": "", "date": date,
            "title": f"Motion {div}", "text": f"Voted {direction} on: Motion {div}",
            "metadata_division_id": div, "metadata_vote_direction": direction}


def run(data_dir: Path):
    out = data_dir.parent / "out"
    behaviour.analyse(data_dir, out)
    with open(out / "member_record.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(out / "member_rebellions.csv", encoding="utf-8") as f:
        rebellions = list(csv.DictReader(f)) if (out / "member_rebellions.csv").stat().st_size else []
    return rows, rebellions


class SmallChamber(unittest.TestCase):
    """Red = A B C D (+X, who voted as Red but sits as an Independent now);
    Blue = E F G; H is an Independent with no party recorded on any vote."""

    VOTES = {
        "d1": dict(A="aye", B="aye", C="aye", D="aye", E="no", F="no", G="no", H="no", X="aye"),
        "d2": dict(A="aye", B="aye", C="aye", D="no", E="no", F="no", G="no", H="aye", X="aye"),
        "d3": dict(A="aye", B="aye", C="aye", D="aye", E="aye", F="aye", G="aye", H="aye", X="aye"),
        "d4": dict(A="aye", B="aye", C="no", D="no", E="no", F="no", G="no", H="no", X="aye"),
        "d5": dict(A="no", B="no", C="no", D="no", E="aye", F="aye", G="aye", H="aye", X="no"),
    }

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        parl = Path(cls.tmp.name) / "data" / "test_parliament"
        roster_party = dict(A="Red", B="Red", C="Red", D="Red", E="Blue", F="Blue", G="Blue",
                            H="Independent", X="Independent")
        write(parl / "members" / "members_master.csv",
              [{"id": n, "name": f"Member {n}", "party": p, "constituency": f"Area {n}",
                "status": "current", "role": "MP"} for n, p in roster_party.items()],
              MEMBER_COLS)
        rows = []
        for i, (div, cast) in enumerate(sorted(cls.VOTES.items()), start=1):
            for n, direction in cast.items():
                # the vote record carries the party at the time only for X
                rows.append(vote("Test Parliament", n, f"Member {n}", "Red" if n == "X" else "",
                                 f"2025-01-0{i}", div, direction))
        write(parl / "votes_on_division" / "votes_on_division_master.csv", rows, VOTE_COLS)
        write(parl / "questions" / "questions_master.csv",
              [{"parliament": "Test Parliament", "data_type": "question", "member_id": "A",
                "member_name": "Member A", "member_party": "", "member_constituency": "",
                "date": "2025-01-01", "title": "", "text": t} for t in (
                  "What is being done about social housing waiting lists?",
                  "Will the minister fund more affordable housing?",
                  "How many hospital beds are available in the NHS?")],
              ["parliament", "data_type", "member_id", "member_name", "member_party",
               "member_constituency", "date", "title", "text"])
        records, cls.rebellions = run(Path(cls.tmp.name) / "data")
        cls.rows = {r["member"]: r for r in records}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def summary(self, name):
        r = self.rows[f"Member {name}"]
        return (r["party_agreement_pct"], r["party_line_divisions"], r["rebellions"],
                r["chamber_agreement_pct"])

    def test_loyal_member(self):
        self.assertEqual(self.summary("A"), ("100.0", "5", "0", "80.0"))

    def test_rebel(self):
        self.assertEqual(self.summary("D"), ("60.0", "5", "2", "80.0"))
        mine = [(r["division"], r["their_vote"], r["party_voted"])
                for r in self.rebellions if r["member"] == "Member D"]
        self.assertEqual(sorted(mine), [("Motion d2", "no", "aye"), ("Motion d4", "no", "aye")])

    def test_opposition_member(self):
        self.assertEqual(self.summary("E"), ("100.0", "5", "0", "40.0"))

    def test_independents_are_not_a_party(self):
        """47% of all 'rebellions' in the first real run were independents
        disagreeing with other independents."""
        self.assertEqual(self.summary("H"), ("", "0", "0", "60.0"))

    def test_party_at_the_time_of_the_vote_wins_over_the_roster(self):
        """Rosie Duffield's Labour-era votes were being judged as an Independent's."""
        self.assertEqual(self.summary("X"), ("100.0", "5", "0", "80.0"))

    def test_legislature_keeps_its_display_name(self):
        """Seeding members from the roster once left every member labelled with
        the directory slug ('test_parliament'), which broke the app's lookups."""
        self.assertEqual({r["parliament"] for r in self.rows.values()}, {"Test Parliament"})

    def test_salience_counts_statements_per_topic(self):
        a = self.rows["Member A"]
        self.assertEqual((a["n_questions"], a["top_topic_1"], a["top_topic_1_share_pct"]),
                         ("3", "Housing & planning", "66.7"))


def calendar(start, end, step=3):
    days, d = [], start
    while d < end:
        if d.month != 8:                 # summer recess: no divisions
            days.append(d.isoformat())
        d += dt.timedelta(days=step)
    return days


class ServiceSpells(unittest.TestCase):
    """Turnout must not charge a member for divisions held while they were out
    of the chamber — the bug that put a Cabinet minister on 28% turnout."""

    DIVS = calendar(dt.date(2010, 1, 10), dt.date(2025, 7, 1))

    def between(self, a, b, every=1):
        return [x for i, x in enumerate(self.DIVS) if a <= x <= b and i % every == 0]

    def spells(self, dates):
        return behaviour._service_spells(sorted(set(dates)), self.DIVS)

    def test_continuous_service_is_one_spell(self):
        self.assertEqual(len(self.spells(self.between("2024-07-20", "2025-06-30"))), 1)

    def test_losing_a_seat_and_returning_is_two(self):
        got = self.spells(self.between("2010-06-01", "2018-03-01")
                          + self.between("2024-07-20", "2025-06-30"))
        self.assertEqual(len(got), 2)
        self.assertEqual(got[-1][0][:7], "2024-07")

    def test_a_quiet_backbencher_over_a_long_recess_stays_whole(self):
        self.assertEqual(len(self.spells(self.between("2015-01-10", "2016-09-05", every=9))), 1)

    def test_eight_months_of_illness_is_absence_not_departure(self):
        got = self.spells(self.between("2020-01-10", "2020-03-01")
                          + self.between("2020-11-01", "2021-06-01"))
        self.assertEqual(len(got), 1)

    def test_three_separate_spells(self):
        got = self.spells(self.between("2010-01-10", "2012-06-01")
                          + self.between("2015-06-01", "2017-04-01")
                          + self.between("2024-07-20", "2025-06-30"))
        self.assertEqual(len(got), 3)


class TermWindow(unittest.TestCase):
    """Everyone is measured over the current term, found from the data: an
    election seats a cohort on one day."""

    @classmethod
    def setUpClass(cls):
        random.seed(3)
        cls.tmp = tempfile.TemporaryDirectory()
        parl = Path(cls.tmp.name) / "data" / "sim"
        divs = calendar(dt.date(2016, 3, 1), dt.date(2025, 7, 1), step=4)
        cls.term_divisions = len([d for d in divs if d >= "2024-07-20"])
        members, votes = [], []

        def add(mid, name, party, start, rate):
            members.append({"id": mid, "name": name, "party": party,
                            "constituency": f"Seat {mid}", "status": "current", "role": "MP"})
            for d in divs:
                if d >= start and random.random() < rate:
                    votes.append(vote("Sim", mid, name, party, d, d,
                                      "aye" if random.random() < 0.5 else "no"))

        for k in range(10):
            add(f"vet{k}", f"Veteran {k}", "Red", "2016-03-01", 0.75)
        for k in range(20):
            add(f"new{k}", f"Newcomer {k}", "Blue", "2024-07-20", 0.75)
        add("by1", "Byelection Arrival", "Red", "2025-02-01", 0.75)
        add("abs1", "Abstainer", "Green", "2099-01-01", 0.0)        # never votes
        write(parl / "members" / "members_master.csv", members, MEMBER_COLS)
        write(parl / "votes_on_division" / "votes_on_division_master.csv", votes, VOTE_COLS)
        records, _ = run(Path(cls.tmp.name) / "data")
        cls.rows = {r["member"]: r for r in records}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def eligible(self, prefix):
        return {r["divisions_eligible"] for n, r in self.rows.items() if n.startswith(prefix)}

    def test_veterans_and_the_new_intake_share_one_denominator(self):
        """A veteran was being judged over 2,367 divisions and a newcomer over
        582, both against the same median."""
        self.assertEqual(self.eligible("Veteran"), {str(self.term_divisions)})
        self.assertEqual(self.eligible("Newcomer"), {str(self.term_divisions)})

    def test_a_byelection_arrival_starts_later(self):
        got = int(self.rows["Byelection Arrival"]["divisions_eligible"])
        self.assertLess(got, self.term_divisions)
        self.assertEqual(self.rows["Byelection Arrival"]["current_spell_from"][:7], "2025-02")

    def test_a_member_who_never_votes_still_appears_at_zero(self):
        """Seven sitting Sinn Féin MPs would otherwise vanish from a product
        whose job is to show who represents you."""
        r = self.rows["Abstainer"]
        self.assertEqual((r["turnout_pct"], r["divisions_eligible"]),
                         ("0.0", str(self.term_divisions)))


if __name__ == "__main__":
    unittest.main()
