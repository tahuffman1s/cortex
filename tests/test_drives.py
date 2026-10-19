import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cortex import drives


class Drives(unittest.TestCase):
    def test_upsert(self):
        ds, d = drives.upsert([], "  Team   Docs ", "//files/docs", login=True)
        self.assertEqual(d, {"name": "Team Docs", "path": r"\\files\docs", "login": True, "sidebar": True})
        ds, _ = drives.upsert(ds, "Apps", r"\\files\apps")
        self.assertEqual([x["name"] for x in ds], ["Apps", "Team Docs"])
        with self.assertRaisesRegex(ValueError, "already a drive"):
            drives.upsert(ds, "apps", r"\\files\other")
        with self.assertRaisesRegex(ValueError, "already added, as Apps"):
            drives.upsert(ds, "Other", "smb://FILES/Apps")
        with self.assertRaises(ValueError):
            drives.upsert(ds, "", r"\\files\x")
        with self.assertRaises(ValueError):
            drives.upsert(ds, "x", "files")

    def test_replace(self):
        ds, _ = drives.upsert([], "Apps", r"\\files\apps")
        ds, d = drives.upsert(ds, "Applications", r"\\files\apps", sidebar=False, replacing="apps")
        self.assertEqual(ds, [d])

    def test_suggest_name(self):
        ds, _ = drives.upsert([], "Projects", r"\\a\Projects")
        self.assertEqual(drives.suggest_name(r"\\b\Projects", ds), "Projects 2")
        self.assertEqual(drives.suggest_name(r"\\b\setups$", ds), "setups")

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            ds, _ = drives.upsert([], "Apps", "//files/apps")
            drives.save(ds)
            self.assertEqual(drives.load(), ds)
            (Path(tmp) / "cortex" / "drives.json").write_text('[{"name": "x", "path": "nonsense"}, 5]')
            self.assertEqual(drives.load(), [])


class Bookmarks(unittest.TestCase):
    def test_sync_keeps_other_bookmarks(self):
        from cortex import desktop
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bookmarks"
            path.write_text("file:///home/me/Code\nsmb://files/apps/ Old name\n")
            with mock.patch.object(desktop, "BOOKMARKS", path):
                desktop.sync_bookmarks({"smb://files/apps/": "Apps", "smb://files/docs/": "Docs"},
                                       {"smb://files/apps/", "smb://files/docs/"})
                self.assertEqual(path.read_text(), "file:///home/me/Code\nsmb://files/apps/ Apps\n"
                                                   "smb://files/docs/ Docs\n")
                desktop.sync_bookmarks({}, {"smb://files/apps/", "smb://files/docs/"})
                self.assertEqual(path.read_text(), "file:///home/me/Code\n")


if __name__ == "__main__":
    unittest.main()
