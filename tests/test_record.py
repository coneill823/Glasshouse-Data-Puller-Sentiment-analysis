"""The voting-record arithmetic, against cases worked out by hand.

A nine-member chamber. Red is A B C D and X; Blue is E F G; H sits as an
independent. X has since left Red — but the votes were cast under a Red
membership, which is what must count.

            A    B    C    D    X  |  E    F    G  |  H     Red line   result
    d1     aye  aye  aye  aye  aye |  no   no   no |  no      aye       aye 5-4
    d2     aye  aye  aye  NO   aye |  no   no   no |  aye     aye       aye 5-4
    d3     aye  aye  aye  aye  aye | aye  aye  aye |  aye     aye       aye 9-0
    d4     aye  aye  no   no   aye |  no   no   no |  no      aye 3-2   no  3-6
    d5     no   no   no   no   no  | aye  aye  aye |  aye     no        no  5-4
"""
import unittest

import pandas as pd

from analysis import record

RED, BLUE = ["A", "B", "C", "D", "X"], ["E", "F", "G"]
VOTES = {
    "d1": dict(A="aye", B="aye", C="aye", D="aye", X="aye", E="no", F="no", G="no", H="no"),
    "d2": dict(A="aye", B="aye", C="aye", D="no", X="aye", E="no", F="no", G="no", H="aye"),
    "d3": dict(A="aye", B="aye", C="aye", D="aye", X="aye", E="aye", F="aye", G="aye", H="aye"),
    "d4": dict(A="aye", B="aye", C="no", D="no", X="aye", E="no", F="no", G="no", H="no"),
    "d5": dict(A="no", B="no", C="no", D="no", X="no", E="aye", F="aye", G="aye", H="aye"),
}
PERSON = {n: i for i, n in enumerate("ABCDEFGHX", start=1)}
# membership id -> party AT THE TIME. X's is red even though X is independent now.
MEMBERSHIP_PARTY = {PERSON[n]: "red" for n in RED}
MEMBERSHIP_PARTY.update({PERSON[n]: "blue" for n in BLUE})
MEMBERSHIP_PARTY[PERSON["H"]] = "independent"


def frames(votes=VOTES, dates=None):
    dates = dates or {d: f"2025-01-0{i}" for i, d in enumerate(sorted(votes), start=1)}
    rows = [{"division_key": d, "person_id": PERSON[n], "membership_id": PERSON[n],
             "effective_vote": v} for d, cast in votes.items() for n, v in cast.items()]
    divisions = pd.DataFrame([{"key": d, "date": dates[d], "division_name": f"Motion {d}"}
                              for d in votes])
    return pd.DataFrame(rows), divisions


def compute(votes=VOTES, term_start="2025-01-01", dates=None, parties=MEMBERSHIP_PARTY):
    v, d = frames(votes, dates)
    out = record.compute(v, d, lambda m: parties.get(int(m), ""), term_start)
    return {n: out.get(pid) for n, pid in PERSON.items()}


class PartyAndChamber(unittest.TestCase):
    def setUp(self):
        self.r = compute()

    def test_loyal_member(self):
        a = self.r["A"]
        self.assertEqual((a["with_party"], a["party_line_divisions"], a["rebellions"]), (5, 5, 0))
        # on the winning side in d1 d2 d3 d5; d4 went 3-6 against
        self.assertEqual((a["with_chamber"], a["chamber_decided_divisions"]), (4, 5))

    def test_rebel_is_counted_once_per_division(self):
        d = self.r["D"]
        # broke with Red on d2 (alone) and d4 (the 3-2 split)
        self.assertEqual((d["with_party"], d["party_line_divisions"], d["rebellions"]), (3, 5, 2))
        self.assertEqual([x[4] for x in d["receipts"]], ["d4", "d2"])   # newest first
        self.assertEqual(d["receipts"][0][2:4], ["no", "aye"])          # their vote, party's

    def test_other_party_has_its_own_line(self):
        e = self.r["E"]
        self.assertEqual((e["with_party"], e["party_line_divisions"], e["rebellions"]), (5, 5, 0))
        self.assertEqual(e["with_chamber"], 2)   # d3 and d4 only

    def test_independent_has_no_line_to_break(self):
        """The bug that made independents the biggest 'rebels' in the House."""
        h = self.r["H"]
        self.assertEqual((h["party_line_divisions"], h["rebellions"]), (0, 0))
        self.assertEqual((h["with_chamber"], h["chamber_decided_divisions"]), (3, 5))

    def test_defector_is_judged_by_party_at_the_time(self):
        """X is independent today but voted as Red: zero breaks, not five."""
        x = self.r["X"]
        self.assertEqual((x["with_party"], x["party_line_divisions"], x["rebellions"]), (5, 5, 0))


class PartyLineRules(unittest.TestCase):
    def test_tied_party_has_no_line(self):
        votes = {"t": dict(A="aye", B="aye", C="no", D="no", E="no", F="no", G="no")}
        r = compute(votes)
        self.assertEqual(r["A"]["party_line_divisions"], 0)
        self.assertEqual(r["C"]["rebellions"], 0)
        self.assertEqual(r["E"]["party_line_divisions"], 1)

    def test_too_few_voters_is_not_a_line(self):
        votes = {"t": dict(A="aye", B="no", E="no", F="no", G="no")}
        r = compute(votes)
        self.assertEqual(r["A"]["party_line_divisions"], 0)   # only two Reds took part

    def test_a_party_can_whip_to_abstain(self):
        """Holyrood and the Senedd record abstentions; staying out can BE the line."""
        votes = {"t": dict(A="abstain", B="abstain", C="abstain", D="aye",
                           E="no", F="no", G="no")}
        r = compute(votes)
        self.assertEqual(r["A"]["with_party"], 1)
        self.assertEqual(r["D"]["rebellions"], 1)
        self.assertEqual(r["D"]["receipts"][0][2:4], ["aye", "abstain"])
        # abstainers took no side, so are not scored against the result
        self.assertEqual(r["A"]["chamber_decided_divisions"], 0)

    def test_co_op_members_take_the_labour_whip(self):
        parties = {1: "labour", 2: "labour", 3: "labourco-operative", 4: "labourco-operative"}
        votes = {"t": dict(A="aye", B="aye", C="aye", D="no")}
        r = compute(votes, parties=parties)
        # one Labour line, 3-1: D broke it. Counted separately the Co-op pair
        # would be 1-1 and D's rebellion would vanish.
        self.assertEqual(r["D"]["rebellions"], 1)
        self.assertEqual(r["C"]["with_party"], 1)

    def test_whip_groups(self):
        for unwhipped in ("", "independent", "Independent", "speaker", "crossbench",
                          "independent-unionist", None):
            self.assertEqual(record.whip_group(unwhipped), "", unwhipped)
        self.assertEqual(record.whip_group("labourco-operative"), "labour")
        self.assertEqual(record.whip_group("conservative"), "conservative")


class Turnout(unittest.TestCase):
    def test_absence_counts_against_turnout_but_nothing_else(self):
        votes = {d: dict(cast) for d, cast in VOTES.items()}
        votes["d5"]["A"] = "absent"
        a = compute(votes)["A"]
        self.assertEqual((a["term_votes"], a["divisions_eligible"]), (4, 5))
        self.assertEqual(a["votes_cast"], 4)
        self.assertEqual((a["party_line_divisions"], a["rebellions"]), (4, 0))

    def test_only_divisions_in_the_term_are_eligible(self):
        dates = {"d1": "2019-03-01", "d2": "2019-03-02", "d3": "2025-01-03",
                 "d4": "2025-01-04", "d5": "2025-01-05"}
        a = compute(term_start="2024-07-05", dates=dates)["A"]
        self.assertEqual((a["term_votes"], a["divisions_eligible"]), (3, 3))
        self.assertEqual(a["votes_cast"], 5)                 # the record is all-time

    def test_member_who_never_votes_still_has_a_denominator(self):
        """Abstentionist MPs: eligible for every division, voted in none."""
        votes = {d: dict(cast, A="absent") for d, cast in VOTES.items()}
        a = compute(votes)["A"]
        self.assertEqual((a["term_votes"], a["divisions_eligible"], a["votes_cast"]), (0, 5, 0))


if __name__ == "__main__":
    unittest.main()
