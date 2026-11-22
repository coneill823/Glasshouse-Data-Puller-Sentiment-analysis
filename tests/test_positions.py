"""Quiz positions: how a vote becomes a stance on a statement."""
import unittest

from analysis import positions as P


def link(date, number, alignment="agree", strength="strong"):
    return {"alignment": alignment, "strength": strength,
            "decision": {"key": f"pw-{date}-{number}-commons", "date": date,
                         "division_number": number, "division_name": f"Division {number}"}}


def policy(pid, links, **extra):
    base = {"id": pid, "name": f"Policy {pid}", "chamber_slug": "commons",
            "status": "active", "context_description": "<b>doing a thing</b>.",
            "policy_description": "About it - [learn more](https://bills.parliament.uk/bills/1)",
            "groups": [{"slug": "misc", "description": "Miscellaneous"}],
            "division_links": links, "free_vote_parties": []}
    base.update(extra)
    return base


class VoteCodes(unittest.TestCase):
    def test_alignment_decides_what_an_aye_means(self):
        self.assertEqual(P.vote_code("aye", "agree"), P.FOR)
        self.assertEqual(P.vote_code("no", "agree"), P.AGAINST)
        # the division was a motion AGAINST the policy: voting it down supports it
        self.assertEqual(P.vote_code("aye", "against"), P.AGAINST)
        self.assertEqual(P.vote_code("no", "against"), P.FOR)

    def test_non_votes(self):
        self.assertEqual(P.vote_code("abstain", "agree"), P.ABSTAIN)
        self.assertEqual(P.vote_code("absent", "agree"), P.ABSENT)
        self.assertEqual(P.vote_code("Aye", "agree"), P.FOR)       # case-insensitive


class Position(unittest.TestCase):
    def test_ratio_of_votes_cast(self):
        self.assertEqual(P.position("fff"), (1.0, 3))
        self.assertEqual(P.position("aa"), (-1.0, 2))
        self.assertEqual(P.position("ffa"), (0.333, 3))

    def test_absence_and_non_membership_are_not_evidence(self):
        """Present for one vote in ten is one vote of evidence, not ten."""
        self.assertEqual(P.position("fxxxxxxxxx"), (1.0, 1))
        self.assertEqual(P.position("f....."), (1.0, 1))
        self.assertEqual(P.position("xx.."), (None, 0))
        self.assertEqual(P.position(""), (None, 0))

    def test_abstention_is_a_vote_for_neither_side(self):
        self.assertEqual(P.position("fb"), (0.5, 2))
        self.assertEqual(P.position("bb"), (0.0, 2))


class Selection(unittest.TestCase):
    TERM = "2024-07-05"

    def select(self, policies, editorial=None):
        return P.select_statements(policies, self.TERM, editorial or {})

    def test_needs_a_scoring_vote_this_parliament(self):
        old = policy(1, [link("2019-01-01", 1), link("2022-01-01", 2)])
        current = policy(2, [link("2019-01-01", 1), link("2025-01-01", 3)])
        self.assertEqual([s["id"] for s in self.select([old, current])], [2])

    def test_informative_votes_never_count(self):
        """A motion that only expresses a view is not a direct action."""
        only_weak = policy(3, [link("2025-01-01", 1, strength="weak")])
        mixed = policy(4, [link("2025-01-01", 1), link("2025-02-01", 2, strength="weak")])
        out = self.select([only_weak, mixed])
        self.assertEqual([s["id"] for s in out], [4])
        self.assertEqual([d["number"] for d in out[0]["divisions"]], [1])

    def test_divisions_are_in_date_order_and_all_time(self):
        p = policy(5, [link("2025-03-01", 9), link("2016-05-01", 2), link("2025-03-01", 4)])
        got = [(d["date"], d["number"]) for d in self.select([p])[0]["divisions"]]
        self.assertEqual(got, [("2016-05-01", 2), ("2025-03-01", 4), ("2025-03-01", 9)])
        self.assertEqual(self.select([p])[0]["termVotes"], 2)

    def test_text_is_cleaned_but_the_source_is_kept(self):
        s = self.select([policy(6, [link("2025-01-01", 1)])])[0]
        self.assertEqual(s["text"], "doing a thing")
        self.assertEqual(s["detail"], "About it - learn more")
        self.assertEqual(s["link"], "https://bills.parliament.uk/bills/1")

    def test_editorial_file_is_the_only_way_wording_or_axes_change(self):
        editorial = {"wording": {"7": {"text": "doing the thing"}},
                     "compass": {"7": {"econ": -1}}}
        s = self.select([policy(7, [link("2025-01-01", 1)])], editorial)[0]
        self.assertEqual((s["text"], s["sourceText"]), ("doing the thing", "doing a thing"))
        self.assertEqual((s["econ"], s["social"]), (-1, 0))
        untouched = self.select([policy(8, [link("2025-01-01", 1)])], editorial)[0]
        self.assertEqual((untouched["econ"], untouched["social"]), (0, 0))

    def test_other_chambers_and_excluded_policies_are_skipped(self):
        lords = policy(9, [link("2025-01-01", 1)], chamber_slug="lords")
        dropped = policy(10, [link("2025-01-01", 1)])
        self.assertEqual(self.select([lords, dropped], {"exclude": {"10": "why"}}), [])


class CoreAndMore(unittest.TestCase):
    """Statements voted on this parliament are asked first; the rest follow."""

    @staticmethod
    def policy(pid, dates, name="P"):
        return {"id": pid, "chamber_slug": "commons", "status": "active", "name": name,
                "context_description": f"statement {pid}.", "policy_description": "",
                "groups": [{"description": "G"}], "free_vote_parties": [],
                "division_links": [{"strength": "strong", "alignment": "agree",
                                    "decision": {"key": f"k{pid}-{i}", "date": d,
                                                 "division_number": i, "division_name": "D"}}
                                   for i, d in enumerate(dates)]}

    def setUp(self):
        self.policies = [self.policy(1, ["2019-01-01", "2025-03-01"]),      # still live
                         self.policy(2, ["2004-01-01", "2010-01-01"]),      # long settled
                         self.policy(3, ["2021-06-01"]),
                         self.policy(4, ["2012-01-01"])]

    def test_a_statement_voted_on_this_parliament_is_core(self):
        core, more = P._split(self.policies, "2024-07-05", {})
        self.assertEqual([s["id"] for s in core], [1])
        self.assertEqual(core[0]["termVotes"], 1)

    def test_the_rest_follow_most_recently_voted_on_first(self):
        more = P.select_more(self.policies, "2024-07-05", {})
        self.assertEqual([s["id"] for s in more], [3, 4, 2])
        self.assertTrue(all(s["termVotes"] == 0 for s in more))

    def test_an_excluded_statement_is_in_neither_list(self):
        editorial = {"exclude": {"3": "a bundle of unrelated measures"}}
        core, more = P._split(self.policies, "2024-07-05", editorial)
        self.assertNotIn(3, [s["id"] for s in core + more])

    def test_compass_tags_apply_to_both_lists(self):
        editorial = {"compass": {"2": {"econ": 1}, "1": {"social": -1}}}
        core, more = P._split(self.policies, "2024-07-05", editorial)
        self.assertEqual((core[0]["social"], more[-1]["econ"]), (-1, 1))


if __name__ == "__main__":
    unittest.main()
