"""Reading the member register: who sits where, since when, for whom."""
import json
import tempfile
import unittest
from pathlib import Path

from analysis.mysociety import People

PW = "uk.org.publicwhip"


def person(pid, given, family=None, **name_extra):
    name = {"given_name": given, "note": "Main"}
    if family:
        name["family_name"] = family
    name.update(name_extra)
    return {"id": f"{PW}/person/{pid}", "other_names": [name],
            "identifiers": [{"scheme": "datadotparl_id", "identifier": str(pid + 5000)}]}


def membership(mid, pid, post, party, start, end=None, reason="general_election"):
    m = {"id": f"{PW}/member/{mid}", "person_id": f"{PW}/person/{pid}",
         "post_id": f"{PW}/cons/{post}", "on_behalf_of_id": party,
         "start_date": start, "start_reason": reason}
    if end:
        m["end_date"] = end
    return m


def register():
    persons = [person(1, "Ann", "Able"), person(3, "Cy", "Cole"), person(4, "Dee", "Dunn"),
               person(2, "Katy", lordname="Clark", lordofname="Kilwinning",
                      honorific_prefix="Baroness")]
    posts = [
        {"id": f"{PW}/cons/1", "organization_id": "house-of-commons",
         "area": {"name": "Alpha"}, "identifiers": [{"scheme": "gss", "identifier": "E14000001"}]},
        {"id": f"{PW}/cons/2", "organization_id": "scottish-parliament",
         "area": {"name": "West Scotland"}},
    ]
    memberships = [
        # Ann: re-elected. Parliament was dissolved in between, but she never left.
        membership(1, 1, 1, "labour", "2019-12-13", "2024-05-30"),
        membership(2, 1, 1, "labour", "2024-07-05"),
        # Cy: lost in 2019, came back in 2024 for another party.
        membership(3, 3, 1, "conservative", "2010-05-06", "2019-11-06"),
        membership(4, 3, 1, "reform", "2024-07-05"),
        # Dee: elected 2024, lost the whip, got it back. Three records, one spell.
        membership(5, 4, 1, "labour", "2024-07-05", "2025-07-16"),
        membership(6, 4, 1, "independent", "2025-07-17", "2026-07-31", reason="whip_removed"),
        membership(7, 4, 1, "labour", "2026-08-01", reason="whip_restored"),
        # a peer who also sits at Holyrood
        membership(8, 2, 2, "labour", "2026-05-08", reason="regional_election"),
        {"id": f"{PW}/member/99", "redirect": f"{PW}/member/1"},
    ]
    # a general election seats a whole cohort on one day
    for i in range(100, 125):
        persons.append(person(i, "Filler", f"Member{i}"))
        memberships.append(membership(i, i, 1, "labour", "2024-07-05"))
    return {"persons": persons, "posts": posts, "memberships": memberships,
            "organizations": [{"id": "labour", "name": "Labour"},
                              {"id": "reform", "name": "Reform UK"},
                              {"id": "independent", "name": "Independent"}]}


class Register(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        Path(cls.tmp.name, "people.json").write_text(json.dumps(register()), encoding="utf-8")
        cls.people = People(Path(cls.tmp.name))
        cls.now = "2026-11-22"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def current(self, chamber="commons"):
        return {m["name"]: m for m in self.people.current_members(chamber, self.now)}

    def test_sitting_members_carry_party_area_and_ids(self):
        ann = self.current()["Ann Able"]
        self.assertEqual((ann["party"], ann["area"], ann["gss"]), ("Labour", "Alpha", "E14000001"))
        self.assertEqual(ann["ids"]["mnis"], "5001")

    def test_party_is_the_current_one(self):
        cur = self.current()
        self.assertEqual(cur["Cy Cole"]["party"], "Reform UK")
        self.assertEqual(cur["Dee Dunn"]["party"], "Labour")      # whip restored

    def test_party_at_the_time_of_a_vote(self):
        """A vote cast under membership 6 was cast as an independent."""
        self.assertEqual(self.people.party_of_membership(5), "labour")
        self.assertEqual(self.people.party_of_membership(6), "independent")
        self.assertEqual(self.people.party_of_membership(3), "conservative")

    def test_term_start_is_the_last_general_election(self):
        self.assertEqual(self.people.term_start("commons", self.now), "2024-07-05")
        self.assertEqual(self.people.term_start("commons", "2023-01-01"), "")

    def test_re_election_does_not_restart_the_clock(self):
        self.assertEqual(self.people.first_elected(1, "commons"), "2019-12-13")

    def test_a_returner_is_counted_from_their_return(self):
        self.assertEqual(self.people.first_elected(3, "commons"), "2024-07-05")

    def test_losing_and_regaining_the_whip_is_one_spell(self):
        self.assertEqual(self.people.first_elected(4, "commons"), "2024-07-05")

    def test_a_peer_in_an_elected_chamber_is_named_as_a_person(self):
        self.assertIn("Katy Clark", self.current("scotland"))
        self.assertEqual(self.people.name(2, self.now, as_peer=True),
                         "Baroness Clark of Kilwinning")

    def test_redirect_records_are_ignored(self):
        self.assertNotIn(99, self.people.memberships)


if __name__ == "__main__":
    unittest.main()
