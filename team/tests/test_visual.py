"""visual.py: where the team's pictures go, and what happens when there's no browser to take screenshots with.

    python3 -m unittest discover team/tests      (from the Hive folder; works on temporary copies)
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]   # the Hive folder


class VisualTest(unittest.TestCase):

    def test_dir_makes_the_topics_folder_under_data_visuals(self):
        kit = self._a_kit()

        done = self._visual(kit, "dir", "orders-csv-export")

        self.assertEqual(done.returncode, 0)
        self.assertEqual(Path(done.stdout.strip()), kit / "data" / "visuals" / "orders-csv-export")
        self.assertTrue((kit / "data" / "visuals" / "orders-csv-export").is_dir())

    def test_a_topic_is_a_plain_name_never_a_path(self):
        kit = self._a_kit()

        for topic in ("../outside", "Orders CSV", "a/b"):
            done = self._visual(kit, "dir", topic)
            self.assertNotEqual(done.returncode, 0, topic)
        self.assertFalse((kit / "outside").exists())

    def test_without_a_browser_it_says_to_rebuild_the_screen_as_a_mockup(self):
        kit = self._a_kit()
        mockup = kit / "data" / "visuals" / "t" / "proposed.html"
        mockup.parent.mkdir(parents=True)
        mockup.write_text("<p>Orders</p>")

        # no Playwright for Python (-S: no site packages) and no node on the PATH
        done = subprocess.run([sys.executable, "-S", str(kit / "team" / "tools" / "visual.py"), "preview", str(mockup)],
                              capture_output=True, text=True, env={"PATH": "/nonexistent"})

        self.assertEqual(done.returncode, 3)
        self.assertIn("Rebuild the screen as it is today as a mockup", done.stderr)
        self.assertFalse(mockup.with_suffix(".png").exists())

    def _visual(self, kit: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(kit / "team" / "tools" / "visual.py"), *args], capture_output=True, text=True)

    def _a_kit(self) -> Path:
        kit = Path(tempfile.mkdtemp()) / "kit"
        shutil.copytree(KIT / "team", kit / "team", ignore=shutil.ignore_patterns("__pycache__"))
        self.addCleanup(shutil.rmtree, kit.parent)
        return kit


if __name__ == "__main__":
    unittest.main()
