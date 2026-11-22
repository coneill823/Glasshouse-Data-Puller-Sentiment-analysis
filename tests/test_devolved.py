"""Questions for the devolved legislatures: what is asked, and how it is worded."""
import unittest

from analysis import devolved as dv


class Selection(unittest.TestCase):
    def test_a_whole_motion_the_house_divided_on_is_asked(self):
        self.assertTrue(dv.qualifies("UK-EU Customs Union", "Motion Private Members' Motion", 44, 23))
        self.assertTrue(dv.qualifies("Second Stage: Hunting with Dogs Bill (NIA Bill 3/22-27)",
                                     "Motion Legislation", 60, 15))

    def test_amendments_and_parts_of_bills_are_not(self):
        for title in ("Amendment 29 - Consideration Stage: Justice Bill",
                      "-#1 Agreement on a Budget - Amendment 1: Motion Amendment 1",
                      "Clause 1 - Consideration Stage: Irish-medium Education Bill",
                      "Long Title - Consideration Stage: Irish-medium Education Bill",
                      "Item 6. Reform UK Debate - phones. Amendment 1, tabled in the name of A"):
            self.assertFalse(dv.qualifies(title, "Motion", 40, 30), title)
        self.assertFalse(dv.qualifies("Decision Time: Affordable Bus Fares", "amendment", 60, 50))

    def test_the_senedds_motion_without_amendment_is_the_motion_itself(self):
        self.assertTrue(dv.qualifies(
            "Item 6. Reform UK Debate - Use of mobile phones in classrooms. Motion without amendment.",
            "", 40, 45))

    def test_procedure_is_not_a_view_on_anything(self):
        for title in ("Business Motion", "Closure of Debate - Second Stage: Flags Bill",
                      "Extension of Committee Stage: Flags Bill", "New Standing Order 28A",
                      "Non-Domestic Rates Bill: Financial Resolution"):
            self.assertFalse(dv.qualifies(title, "Motion", 40, 30), title)

    def test_a_vote_nearly_everyone_agreed_on_tells_you_nothing(self):
        self.assertFalse(dv.qualifies("A Motion", "Motion", 70, 5))
        self.assertTrue(dv.qualifies("A Motion", "Motion", 67, 9))
        self.assertFalse(dv.qualifies("A Motion", "Motion", 0, 0))


class Wording(unittest.TestCase):
    def test_titles_are_the_legislatures_own_minus_filing_details(self):
        self.assertEqual(
            dv._ni_title("Second Stage: Display of Flags and Emblems Bill (NIA Bill 44/22-27) [Ms Paula Bradshaw]"),
            "Second Stage: Display of Flags and Emblems Bill")
        self.assertEqual(
            dv._senedd_title("Item 6. Reform UK Debate - Use of mobile phones in classrooms. Motion without amendment. "),
            "Reform UK Debate - Use of mobile phones in classrooms")

    def test_the_motion_is_cut_out_of_the_announcement_of_its_result(self):
        text = ("The result of the division on motion S7M-1, in the name of A, on buses, is: "
                "For 93, Against 26. Motion agreed to, That the Parliament believes fares are too high.")
        self.assertEqual(dv._motion_wording(text), "That the Parliament believes fares are too high.")
        self.assertEqual(dv._motion_wording("Decision Time"), "")

    def test_what_follows_i_would_have_voted_for(self):
        q = {"title": "Final Stage: Hospital Parking Charges Bill"}
        self.assertEqual(dv.statement_text(q), "the Hospital Parking Charges Bill at its Final Stage")
        self.assertEqual(dv.statement_text({"title": "UK-EU Customs Union"}),
                         "the motion “UK-EU Customs Union”")
        self.assertEqual(dv.statement_text({"title": "Affordable Bus Fares", "asAmended": True}),
                         "the motion “Affordable Bus Fares” as amended")

    def test_votes_translate_literally(self):
        self.assertEqual([dv.vote_code(v) for v in ("aye", "No", "abstained", "Abstain", "absent", "")],
                         ["f", "a", "b", "b", "x", "x"])


class Build(unittest.TestCase):
    QUESTIONS = [
        {"key": "k1", "date": "2026-06-01", "number": 7, "title": "Final Stage: A Bill",
         "detail": "", "asAmended": False, "ayes": 50, "noes": 30, "link": "u1"},
        {"key": "k2", "date": "2025-01-10", "number": 3, "title": "A Motion",
         "detail": "That this Assembly…", "asAmended": False, "ayes": 30, "noes": 40, "link": "u2"},
    ]
    MEMBERS = [{"person_id": 1, "name": "A", "party": "P", "area": "X"},
               {"person_id": 2, "name": "B", "party": "Q", "area": "Y"}]

    def build(self):
        cast = {"k1": {1: "f", 2: "a"}, "k2": {1: "b"}}
        # member 2 was elected between the two votes
        return dv.build_set("ni", self.QUESTIONS, self.MEMBERS, lambda q: cast[q["key"]],
                            lambda pid, day: pid == 1 or day >= "2026-01-01")

    def test_aye_is_for_no_is_against_and_abstaining_is_the_middle(self):
        quiz = self.build()
        self.assertEqual(quiz["members"][0]["pos"], [1, 0])
        self.assertEqual(quiz["members"][0]["votes"], ["f", "b"])

    def test_not_yet_a_member_is_told_apart_from_absent(self):
        self.assertEqual(self.build()["members"][1]["votes"], ["a", "."])
        self.assertEqual(self.build()["members"][1]["pos"], [-1, None])

    def test_each_question_is_one_division_and_reads_like_a_statement(self):
        s = self.build()["statements"][0]
        self.assertEqual((s["text"], s["group"], len(s["divisions"]), s["divisions"][0]["alignment"]),
                         ("the A Bill at its Final Stage", "Bill", 1, "agree"))
        self.assertEqual((s["econ"], s["social"]), (0, 0))   # no compass tags: none are ours to give

    def test_ids_cannot_collide_between_legislatures_or_with_the_commons(self):
        q = self.QUESTIONS[0]
        ids = {dv.statement_id(c, q) for c in ("scotland", "senedd", "ni")}
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(i > 10 ** 9 for i in ids))        # Commons policy ids are five digits


if __name__ == "__main__":
    unittest.main()
