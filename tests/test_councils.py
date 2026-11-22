"""Reading a council's own committee system."""
import unittest

from analysis import councils as cn

WARDS = """<?xml version="1.0"?><councillorsbyward><wards>
<ward><wardtitle>Balmoral</wardtitle><councillors><councillorcount>2</councillorcount>
<councillor><councillorid>597</councillorid><fullusername>Councillor Natasha Brennan</fullusername>
<politicalpartytitle>Sinn Fein</politicalpartytitle></councillor>
<councillor><councillorid>12</councillorid><fullusername>The Deputy Lord Mayor, Councillor Hedley Abernethy</fullusername>
<politicalpartytitle></politicalpartytitle></councillor></councillors></ward>
<ward><wardtitle>Empty</wardtitle><councillors></councillors></ward>
</wards></councillorsbyward>"""

ATTENDANCE = """<html><body><h1>Attendance record</h1><table>
<tr><th>Statistic</th><th>Count</th><th>Percentage</th></tr>
<tr><td>Total expected attendances:</td><td>19</td><td></td></tr>
<tr><td>Present as expected:</td><td>17</td><td>89%</td></tr></table></body></html>"""

AREAS = """<table>
<tr><td>1. Name of district</td><td>2. Name of district electoral area</td><td>3. Constituent wards</td><td>4. Number of councillors</td></tr>
<tr><td>Belfast</td><td>Balmoral</td><td>Belvoir</td><td>5</td></tr>
<tr><td>Finaghy</td></tr>
<tr><td>Botanic</td><td>Blackstaff</td><td>5</td></tr>
<tr><td>Stranmillis</td></tr>
<tr><td>Derry City and Strabane</td><td>Ballyarnett</td><td>Culmore</td><td>6</td></tr>
</table>"""


class Parsing(unittest.TestCase):
    def test_councillors_come_with_their_ward_and_party_and_without_their_titles(self):
        wards = cn.parse_wards(WARDS)
        self.assertEqual([w["name"] for w in wards], ["Balmoral"])        # empty wards dropped
        self.assertEqual([(c["name"], c["party"]) for c in wards[0]["councillors"]],
                         [("Natasha Brennan", "Sinn Fein"), ("Hedley Abernethy", "Independent")])

    def test_a_page_that_is_not_the_data_gives_nothing(self):
        self.assertEqual(cn.parse_wards("<html>Access denied</html>"), [])
        self.assertIsNone(cn.parse_attendance("<html>Access denied</html>"))

    def test_attendance_is_expected_and_present(self):
        self.assertEqual(cn.parse_attendance(ATTENDANCE), (19, 17))

    def test_wards_are_grouped_into_the_areas_councillors_are_elected_for(self):
        areas = cn.parse_ni_areas(AREAS)
        self.assertEqual(areas["Belfast"], {"Balmoral": ["Belvoir", "Finaghy"],
                                            "Botanic": ["Blackstaff", "Stranmillis"]})
        self.assertEqual(areas["Derry City and Strabane"], {"Ballyarnett": ["Culmore"]})


if __name__ == "__main__":
    unittest.main()
