"""Former members: who counts as one, and how they are described."""
import unittest

from analysis import others


class FakePeople:
    """Just enough of the register for three careers."""
    posts = {"p1": {"area": {"name": "Sedgefield"}}, "p2": {"area": {"name": "Bath"}}}
    by_person = {
        1: [{"post_id": "p1", "start_date": "1983-06-09", "end_date": "1997-04-08", "on_behalf_of_id": "labour"},
            {"post_id": "p1", "start_date": "1997-05-01", "end_date": "2007-06-27", "on_behalf_of_id": "labour"}],
        2: [{"post_id": "p2", "start_date": "2015-05-07", "end_date": "9999-12-31", "on_behalf_of_id": "libdem"}],
        3: [],
    }

    def chamber_of(self, m):
        return "commons"

    def party_name(self, slug):
        return {"labour": "Labour", "libdem": "Liberal Democrat"}.get(slug, slug)

    def name(self, pid, on="", as_peer=False):
        return {1: "Tony Example", 2: "Still Sitting", 3: "No Career"}[pid]


def rec(votes, rebellions=0):
    return {"votes_cast": votes, "party_line_divisions": votes, "with_party": votes - rebellions,
            "rebellions": rebellions, "chamber_decided_divisions": votes, "with_chamber": votes // 2,
            "receipts": [["2005-01-01", "T" * 300, "no", "aye", "pw-2005-01-01-1-commons"]] * 9}


class Former(unittest.TestCase):
    def setUp(self):
        records = {1: rec(200, 4), 2: rec(900), 3: rec(10), 4: rec(0)}
        self.out = others.former_members(FakePeople(), "commons", records, sitting={9})

    def test_only_people_who_voted_and_have_left_are_former_members(self):
        self.assertEqual([m["name"] for m in self.out], ["Tony Example"])

    def test_a_former_member_is_described_by_their_last_seat_and_their_years(self):
        m = self.out[0]
        self.assertEqual((m["party"], m["area"], m["parliament"], m["status"], m["since"], m["until"]),
                         ("Labour", "Sedgefield", "UK Parliament", "former", "1983", "2007"))
        self.assertEqual((m["votesCast"], m["rebellions"], m["partyAgreement"]), (200, 4, 98.0))
        self.assertNotIn("turnout", m)          # there is no "this term" for someone who has left

    def test_only_the_latest_breaks_with_party_are_carried_and_titles_are_cut(self):
        m = self.out[0]
        self.assertEqual(len(m["receipts"]), others.MAX_RECEIPTS)
        self.assertEqual(len(m["receipts"][0][1]), others.MAX_TITLE)


if __name__ == "__main__":
    unittest.main()
