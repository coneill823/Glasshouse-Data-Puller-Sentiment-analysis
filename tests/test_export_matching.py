"""Joining the member register to speech-derived data by area and name.

Each case here is a real mismatch between the two sources found in the data.
"""
import unittest

from analysis.export_app_data import LegacyIndex, same_person


def legacy(parliament, area, name, **extra):
    return dict(parliament=parliament, area=area, name=name, **extra)


class Names(unittest.TestCase):
    def test_titles_are_ignored(self):
        self.assertTrue(same_person("Sir Christopher Chope", "Christopher Chope"))
        self.assertTrue(same_person("Mr Bayo Alaba", "Bayo Alaba"))
        self.assertTrue(same_person("Rt Hon Dame Diana Johnson", "Diana Johnson"))

    def test_the_assembly_writes_surname_first(self):
        self.assertTrue(same_person("Brogan, Nicola", "Nicola Brogan"))
        self.assertTrue(same_person("O'Toole, Matthew", "Matthew O'Toole"))

    def test_accents_and_short_forms(self):
        self.assertTrue(same_person("Sinéad McLaughlin", "Sinead McLaughlin"))
        self.assertTrue(same_person("John Martin McDonnell", "John McDonnell"))

    def test_same_surname_is_not_enough(self):
        self.assertFalse(same_person("Kate Forbes", "Fergus Ewing"))
        self.assertFalse(same_person("Angela Eagle", "Maria Eagle"))
        self.assertFalse(same_person("", "Maria Eagle"))


class Areas(unittest.TestCase):
    def test_exact_area_and_name(self):
        idx = LegacyIndex([legacy("UK Parliament", "Ynys Môn", "Llinos Medi", questions=7)])
        self.assertEqual(idx.find("UK Parliament", "Ynys Môn", "Llinos Medi")["questions"], 7)

    def test_word_order(self):
        """The Assembly publishes 'East Belfast'; the register has 'Belfast East'."""
        idx = LegacyIndex([legacy("NI Assembly", "East Belfast", "Long, Naomi")])
        self.assertIsNotNone(idx.find("NI Assembly", "Belfast East", "Naomi Long"))

    def test_truncated_area(self):
        idx = LegacyIndex([legacy("Scottish Parliament", "Central Scot and Lothians West",
                                  "Gillian Mackay")])
        self.assertIsNotNone(idx.find("Scottish Parliament",
                                      "Central Scotland and Lothians West", "Gillian Mackay"))

    def test_a_new_member_in_the_seat_does_not_inherit_the_old_ones_record(self):
        idx = LegacyIndex([legacy("UK Parliament", "Makerfield", "Josh Simons", questions=40)])
        self.assertIsNone(idx.find("UK Parliament", "Makerfield", "Andy Burnham"))

    def test_similar_areas_are_not_confused(self):
        idx = LegacyIndex([legacy("Scottish Parliament", "Glasgow Southside", "A Person"),
                           legacy("UK Parliament", "Glasgow South", "A Person")])
        self.assertIsNone(idx.find("Scottish Parliament", "Glasgow South", "A Person"))
        self.assertIsNone(idx.find("UK Parliament", "Glasgow Southside", "A Person"))

    def test_region_with_several_members(self):
        idx = LegacyIndex([legacy("Scottish Parliament", "Glasgow", "Patrick Harvie", speeches=1),
                           legacy("Scottish Parliament", "Glasgow", "Thomas Kerr", speeches=2)])
        self.assertEqual(idx.find("Scottish Parliament", "Glasgow", "Thomas Kerr")["speeches"], 2)


if __name__ == "__main__":
    unittest.main()
