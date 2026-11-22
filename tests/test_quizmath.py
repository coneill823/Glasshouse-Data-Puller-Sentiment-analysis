"""The reference arithmetic the website and the phone app are held to."""
import json
import unittest

from analysis import quizmath as qm


class Match(unittest.TestCase):
    def test_same_view_scores_one_and_opposite_zero(self):
        r = qm.match([1, -1, None, 1 / 3], ["f", "a", "", "ffa"],
                     {0: (1, False), 1: (0.5, False), 2: (1, False), 3: (0, False)})
        self.assertEqual(r["overlap"], 3)
        self.assertAlmostEqual(r["pct"], 100 * (1 + 0.25 + (1 - 1 / 6)) / 3)

    def test_what_matters_a_lot_counts_twice(self):
        r = qm.match([1, -1], ["f", "a"], {0: (1, False), 1: (0.5, True)})
        self.assertAlmostEqual(r["pct"], 100 * (1 + 2 * 0.25) / 3)

    def test_unanswered_statements_are_not_evidence(self):
        r = qm.match([1, -1], ["f", "a"], {0: (1, False), 1: (None, False)})
        self.assertEqual((r["pct"], r["overlap"], r["eligible"]), (100.0, 1, 1))

    def test_a_vote_before_their_time_does_not_count_against_them(self):
        # Ten answers. The member sat for five of the votes and voted in all five.
        positions = [1] * 5 + [None] * 5
        votes = ["f"] * 5 + ["", "..", ".", "", "..."]
        r = qm.match(positions, votes, {i: (1, False) for i in range(10)})
        self.assertEqual((r["overlap"], r["eligible"]), (5, 5))
        self.assertTrue(qm.enough(r, answered=10))

    def test_being_there_and_not_voting_does_count(self):
        # Same answers, but they were a member throughout and missed most.
        positions = [1] * 3 + [None] * 7
        votes = ["f"] * 3 + ["x"] * 7
        r = qm.match(positions, votes, {i: (1, False) for i in range(10)})
        self.assertEqual((r["overlap"], r["eligible"]), (3, 10))
        self.assertFalse(qm.enough(r, answered=10))

    def test_a_partial_record_is_shown_but_not_ranked(self):
        # A member for all twelve who voted in five. Their constituents see
        # the figure; it does not sit in a ranking above members with a full
        # record.
        positions = [1] * 5 + [None] * 7
        votes = ["f"] * 5 + ["x"] * 7
        r = qm.match(positions, votes, {i: (1, False) for i in range(12)})
        self.assertEqual((r["pct"], r["overlap"], r["eligible"]), (100.0, 5, 12))
        self.assertTrue(qm.shown(r, answered=12))
        self.assertFalse(qm.enough(r, answered=12))
        # Exactly half is enough to be ranked.
        r = qm.match([1] * 6 + [None] * 6, ["f"] * 6 + ["x"] * 6, {i: (1, False) for i in range(12)})
        self.assertTrue(qm.enough(r, answered=12))

    def test_a_match_needs_five_statements_in_common(self):
        r = qm.match([1] * 4, ["f"] * 4, {i: (1, False) for i in range(4)})
        self.assertTrue(qm.shown(r, answered=4))         # everything answered so far
        self.assertTrue(qm.enough(r, answered=4))
        r = qm.match([1] * 4 + [None] * 4, ["f"] * 4 + [""] * 4, {i: (1, False) for i in range(8)})
        self.assertFalse(qm.shown(r, answered=8))        # four is not five
        self.assertFalse(qm.enough(r, answered=8))

    def test_someone_who_never_votes_has_no_match(self):
        r = qm.match([None] * 6, ["x"] * 6, {i: (1, False) for i in range(6)})
        self.assertIsNone(r["pct"])
        self.assertFalse(qm.shown(r, answered=6))
        self.assertFalse(qm.enough(r, answered=6))

    def test_nothing_is_ranked_that_is_not_shown(self):
        for overlap in range(0, 13):
            for there in range(overlap, 13):
                positions = [1] * overlap + [None] * (12 - overlap)
                votes = ["f"] * overlap + ["x"] * (there - overlap) + [""] * (12 - there)
                r = qm.match(positions, votes, {i: (1, False) for i in range(12)})
                if qm.enough(r, answered=12):
                    self.assertTrue(qm.shown(r, answered=12), (overlap, there))


class Compass(unittest.TestCase):
    STATEMENTS = [{"econ": -1, "social": 0}, {"econ": 1, "social": 0},
                  {"econ": 0, "social": 1}, {"econ": 0, "social": 0}]

    def test_supporting_a_left_statement_moves_you_left(self):
        c = qm.place(self.STATEMENTS, lambda i: [1, None, None, 1][i])
        self.assertEqual((c["econ"], c["social"], c["econWeight"], c["socialWeight"]),
                         (-1.0, None, 1.0, 0.0))

    def test_opposing_views_on_one_axis_cancel(self):
        c = qm.place(self.STATEMENTS, lambda i: [1, 1, -0.5, None][i])
        self.assertEqual((c["econ"], c["social"]), (0.0, -0.5))


class Order(unittest.TestCase):
    def test_three_lanes_are_taken_in_turn(self):
        s = [{"econ": 0, "social": 0, "group": "g"}, {"econ": 1, "social": 0, "group": "g"},
             {"econ": 0, "social": 1, "group": "g"}, {"econ": 0, "social": 0, "group": "g"},
             {"econ": -1, "social": 0, "group": "g"}]
        self.assertEqual(qm.asking_order(s), [2, 1, 0, 4, 3])

    def test_this_parliament_comes_before_earlier_ones(self):
        core = [{"econ": 0, "social": 0, "group": "a"}, {"econ": 0, "social": 1, "group": "a"}]
        more = [{"econ": 1, "social": 0, "group": "a"}, {"econ": 0, "social": 1, "group": "a"}]
        self.assertEqual(qm.full_order(core, more), [1, 0, 3, 2])


class Fixture(unittest.TestCase):
    def test_the_frozen_slice_is_what_this_code_produces(self):
        if not qm.FIXTURE.exists():
            self.skipTest("no phone app in this checkout")
        f = json.loads(qm.FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(qm.expected(f["quiz"], f["answers"]), f["expected"],
                         "the arithmetic changed: run python -m analysis.quizmath, "
                         "then make the apps agree with it")

    def test_the_slice_exercises_the_cases_that_matter(self):
        if not qm.FIXTURE.exists():
            self.skipTest("no phone app in this checkout")
        f = json.loads(qm.FIXTURE.read_text(encoding="utf-8"))
        people = f["expected"]["members"].values()
        self.assertTrue(any(m["enough"] for m in people))
        self.assertTrue(any(not m["shown"] for m in people))
        self.assertTrue(any(m["shown"] and not m["enough"] for m in people),
                        "nobody in the slice has a match that is shown but not ranked")
        self.assertTrue(any(m["eligible"] < f["expected"]["answered"] for m in people),
                        "nobody in the slice was elected after a statement was voted on")
        self.assertTrue(f["quiz"]["former"] and f["quiz"]["moreStatements"])


if __name__ == "__main__":
    unittest.main()
