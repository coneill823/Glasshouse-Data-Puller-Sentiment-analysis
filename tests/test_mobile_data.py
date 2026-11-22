"""The phone app must ship the same data as the website."""
import tempfile
import unittest
from pathlib import Path

from analysis.build import ROOT, sync_mobile

FILES = ("data.json", "quiz.json")


class MobileData(unittest.TestCase):
    def test_the_phone_app_ships_what_the_website_serves(self):
        mobile = ROOT / "mobile" / "assets" / "data"
        if not mobile.is_dir():
            self.skipTest("no mobile app in this checkout")
        for name in FILES:
            self.assertEqual(
                (ROOT / "app" / name).read_bytes(), (mobile / name).read_bytes(),
                f"mobile/assets/data/{name} is out of date: run python -m analysis.build")

    def test_sync_copies_what_changed_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, mobile = Path(tmp, "app"), Path(tmp, "mobile")
            app.mkdir()
            mobile.mkdir()
            (app / "data.json").write_text('{"v": 2}')
            (app / "quiz.json").write_text('{"q": 1}')
            (mobile / "data.json").write_text('{"v": 1}')
            (mobile / "quiz.json").write_text('{"q": 1}')

            self.assertEqual(sync_mobile(app, mobile), ["data.json"])
            self.assertEqual((mobile / "data.json").read_text(), '{"v": 2}')
            self.assertEqual(sync_mobile(app, mobile), [])        # already the same

    def test_sync_does_nothing_without_a_mobile_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp, "app")
            app.mkdir()
            (app / "data.json").write_text("{}")
            self.assertEqual(sync_mobile(app, Path(tmp, "no-such-folder")), [])
            self.assertFalse(Path(tmp, "no-such-folder").exists())


if __name__ == "__main__":
    unittest.main()
