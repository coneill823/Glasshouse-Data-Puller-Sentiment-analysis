"""Upcoming elections and who is standing, from canned copies of the registers."""
import json
import tempfile
import unittest
from pathlib import Path

from analysis import candidates as cd

ELECTIONS = {"next": None, "results": [
    {"election_id": "local.2026-12-10", "group_type": "election", "poll_open_date": "2026-12-10"},
    {"election_id": "local.leeds.cross-gates.by.2026-12-10", "group_type": None,
     "poll_open_date": "2026-12-10", "election_title": "Leeds local election Cross Gates by-election",
     "organisation": {"common_name": "Leeds", "official_identifier": "gss:E08000035"},
     "division": {"name": "Cross Gates & Whinmoor", "official_identifier": "gss:E05011391"},
     "seats_contested": 1, "cancelled": False},
    {"election_id": "mayor.somewhere.2026-12-10", "group_type": None, "poll_open_date": "2026-12-10",
     "election_title": "Somewhere mayoral election", "division": None,
     "organisation": {"common_name": "Somewhere", "official_identifier": "gss:E06000099"},
     "seats_contested": 1, "cancelled": True},
    {"election_id": "local.old.ward.2026-01-01", "group_type": None, "poll_open_date": "2026-01-01",
     "organisation": {}, "division": {}},
]}
CSV = ("person_id,person_name,election_id,ballot_paper_id,election_date,party_name,email,twfy_id\n"
       "1,Zoe Adams,local.leeds,local.leeds.cross-gates.by.2026-12-10,2026-12-10,Green Party,z@example.org,\n"
       "2,Sam Young,local.leeds,local.leeds.cross-gates.by.2026-12-10,2026-12-10,,s@example.org,10999\n"
       "3,Pat Other,local.x,local.x.y.2026-12-10,2026-12-10,Labour Party,,25000\n")


class Candidates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        (self.cache / "elections_0.json").write_text(json.dumps(ELECTIONS))
        (self.cache / "candidates_2026-12-10.csv").write_text(CSV)
        self.out = cd.build(self.cache, today="2026-11-22", fetch=False, known_ids={10999})

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_ballot_papers_from_today_on_are_listed(self):
        self.assertEqual([b["id"] for b in self.out["ballots"]],
                         ["local.leeds.cross-gates.by.2026-12-10", "mayor.somewhere.2026-12-10"])

    def test_a_ballot_is_keyed_by_its_areas_official_code(self):
        ward, mayor = self.out["ballots"]
        self.assertEqual((ward["gss"], ward["area"], ward["body"], ward["kind"], ward["byElection"]),
                         ("E05011391", "Cross Gates & Whinmoor", "Leeds", "Council", True))
        self.assertEqual((mayor["gss"], mayor["kind"], mayor["cancelled"]),
                         ("E06000099", "Mayor", True))       # no division: the council's own code

    def test_candidates_are_listed_by_surname_with_their_party(self):
        people = self.out["ballots"][0]["candidates"]
        self.assertEqual([(c["name"], c["party"]) for c in people],
                         [("Zoe Adams", "Green Party"), ("Sam Young", "Independent")])

    def test_a_candidate_links_to_a_record_only_if_we_hold_one(self):
        people = {c["name"]: c["record"] for c in self.out["ballots"][0]["candidates"]}
        self.assertEqual(people, {"Zoe Adams": None, "Sam Young": 10999})
        self.assertEqual(self.out["ballots"][1]["candidates"], [])

    def test_nothing_personal_is_carried_over(self):
        self.assertNotIn("example.org", json.dumps(self.out))
        self.assertEqual(set(self.out["ballots"][0]["candidates"][0]), {"name", "party", "record"})


if __name__ == "__main__":
    unittest.main()
