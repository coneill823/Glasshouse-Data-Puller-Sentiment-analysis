"""The two files the website and the phone app read, as they are committed.

Everything else in this suite tests the code that makes them. This tests the
files themselves, because they are what people actually see: that they hold
what the apps expect, and that they hold nothing they said they would not.
"""
import json
import re
import unittest

from analysis.build import ROOT

DEVOLVED = ("Scottish Parliament", "Welsh Parliament (Senedd)", "NI Assembly")
MARKUP = re.compile(r"<[^>]*>|&(?:[a-z]+|#\d+);")


def _load(name):
    path = ROOT / "app" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class Published(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.quiz = _load("data.json"), _load("quiz.json")

    def setUp(self):
        if not self.data or not self.quiz:
            self.skipTest("the data has not been built in this checkout")

    def test_both_files_say_which_shape_they_are(self):
        # The phone app refuses a pair it does not understand and keeps the
        # copy it shipped with.
        self.assertEqual((self.data["schema"], self.quiz["schema"]), (2, 2))

    def test_every_question_anywhere_has_its_own_id(self):
        # Answers are kept by statement id, across every parliament at once.
        ids = [s["id"] for s in self.quiz["statements"] + self.quiz["moreStatements"]]
        for c in self.quiz["chambers"].values():
            ids += [s["id"] for s in c["statements"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_each_devolved_legislature_has_a_quiz_that_lines_up(self):
        sitting = {(m["id"], m["parliament"]) for m in self.data["members"]}
        for parliament in DEVOLVED:
            c = self.quiz["chambers"][parliament]
            n = len(c["statements"])
            self.assertGreaterEqual(n, 5, parliament)
            self.assertLessEqual(n, 30, parliament)
            for s in c["statements"]:
                self.assertEqual(len(s["divisions"]), 1, s["name"])
                self.assertTrue(s["divisions"][0]["url"].startswith("https://"), s["name"])
                ayes, noes = s["result"]
                self.assertGreaterEqual(min(ayes, noes) * 10, ayes + noes, s["name"])
                self.assertEqual((s["econ"], s["social"]), (0, 0), s["name"])
            for m in c["members"]:
                self.assertIn((m["id"], parliament), sitting, m["name"])
                self.assertEqual((len(m["pos"]), len(m["votes"])), (n, n), m["name"])
                for p, v in zip(m["pos"], m["votes"]):
                    self.assertEqual(p is None, not re.search("[fab]", v), m["name"])

    def test_the_commons_quiz_lines_up_for_sitting_and_former_mps(self):
        core, more = len(self.quiz["statements"]), len(self.quiz["moreStatements"])
        self.assertTrue(all(s["termVotes"] > 0 for s in self.quiz["statements"]))
        self.assertTrue(all(s["termVotes"] == 0 for s in self.quiz["moreStatements"]))
        for m in self.quiz["members"] + self.quiz["former"]:
            self.assertEqual((len(m["pos"]), len(m["votes"])), (core, core), m["name"])
            if "morePos" in m:
                self.assertEqual((len(m["morePos"]), len(m["moreVotes"])), (more, more), m["name"])
        self.assertEqual(len(self.quiz["members"]), 650)
        self.assertFalse({m["id"] for m in self.quiz["members"]} & {m["id"] for m in self.quiz["former"]})

    def test_no_title_or_name_carries_markup(self):
        everyone = self.data["members"] + self.data["others"]
        for m in everyone:
            self.assertFalse(MARKUP.search(m["name"]), m["name"])
            self.assertEqual(m["name"], m["name"].strip())
            for r in m.get("receipts", []):
                self.assertFalse(MARKUP.search(r[1] or ""), f"{m['name']}: {r[1]}")
        statements = self.quiz["statements"] + self.quiz["moreStatements"]
        for c in self.quiz["chambers"].values():
            statements = statements + c["statements"]
        for s in statements:
            for text in (s["text"], s.get("detail") or "", *(d["title"] for d in s["divisions"])):
                self.assertFalse(MARKUP.search(text), f"{s['name']}: {text[:80]}")

    def test_people_who_hold_no_seat_are_marked_as_what_they_are(self):
        sitting = {(m["id"], m["parliament"]) for m in self.data["members"]}
        for m in self.data["others"]:
            self.assertIn(m["status"], ("former", "peer"), m["name"])
            self.assertNotIn((m["id"], m["parliament"]), sitting, m["name"])
            if m["status"] == "peer":
                # known by a title, never by a first name alone
                self.assertGreater(len(m["name"].split()), 1, f'{m["id"]} "{m["name"]}"')
            else:
                self.assertTrue(m["until"], m["name"])

    def test_only_what_is_on_the_ballot_paper_is_kept_about_a_candidate(self):
        # Democracy Club's register also holds email addresses, dates of birth
        # and social-media accounts. None of it belongs here.
        known = {m["id"] for m in self.data["members"] + self.data["others"]}
        for b in self.data["elections"]["ballots"]:
            self.assertEqual(set(b), {"id", "date", "kind", "title", "body", "area", "gss", "seats",
                                      "byElection", "cancelled", "candidates", "url"}, b["id"])
            for c in b["candidates"]:
                self.assertEqual(set(c), {"name", "party", "record"}, b["id"])
                if c["record"] is not None:
                    self.assertIn(c["record"], known, c["name"])   # a link only where it leads somewhere

    def test_only_what_a_council_publishes_about_a_councillor_is_kept(self):
        for body in self.data["councils"]["bodies"]:
            for ward in body["wards"]:
                self.assertTrue(ward["covers"], f'{body["name"]}: {ward["name"]}')
                for c in ward["councillors"]:
                    self.assertLessEqual(set(c), {"name", "party", "url", "expected", "present"}, c["name"])
                    if "expected" in c:
                        self.assertTrue(body["attendance"])
                        self.assertLessEqual(c["present"], c["expected"], c["name"])


if __name__ == "__main__":
    unittest.main()
