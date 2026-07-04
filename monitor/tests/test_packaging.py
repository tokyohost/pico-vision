"""Ensure runtime modules are included in every Linux package path."""

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class LinuxPackagingTest(unittest.TestCase):
    def test_history_module_is_packaged(self):
        deb_install = (ROOT / "monitor" / "debian" / "install").read_text(encoding="utf-8")
        generic_installer = (ROOT / "monitor" / "install-linux.sh").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "build-linux-deb.yml").read_text(encoding="utf-8")

        self.assertIn("history.py usr/lib/pico-monitor", deb_install)
        self.assertIn('"$script_directory/history.py"', generic_installer)
        self.assertIn("qbittorrent_monitor.py history.py requirements.txt", workflow)


if __name__ == "__main__":
    unittest.main()
