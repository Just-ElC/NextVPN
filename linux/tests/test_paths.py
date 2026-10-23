"""Where the app looks for things other programs must find too."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nextvpn.core import paths


class SharedIconTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def env(self, *dirs):
        return mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "home"),
                                            "XDG_DATA_DIRS": ":".join(str(d) for d in dirs)})

    def install(self, share: Path, rel: str) -> None:
        f = share / "icons" / "hicolor" / rel
        f.parent.mkdir(parents=True)
        f.write_text("x")

    def test_an_icon_in_a_system_data_directory_is_shared(self):
        self.install(self.root / "usr", "scalable/status/nextvpn-tray-disconnected.svg")
        with self.env(self.root / "usr"):
            self.assertTrue(paths.shared_icon_exists("nextvpn-tray-disconnected"))

    def test_a_png_at_any_size_counts(self):
        self.install(self.root / "usr", "22x22/status/nextvpn-tray-disconnected.png")
        with self.env(self.root / "usr"):
            self.assertTrue(paths.shared_icon_exists("nextvpn-tray-disconnected"))

    def test_the_user_data_directory_counts(self):
        self.install(self.root / "home", "scalable/status/nextvpn-tray-disconnected.svg")
        with self.env(self.root / "usr"):
            self.assertTrue(paths.shared_icon_exists("nextvpn-tray-disconnected"))

    def test_nothing_installed_means_not_shared(self):
        with self.env(self.root / "usr"):
            self.assertFalse(paths.shared_icon_exists("nextvpn-tray-disconnected"))

    def test_a_nix_store_path_only_this_process_was_given_does_not_count(self):
        real_is_file = Path.is_file

        def is_file(path):
            return str(path).startswith("/nix/store/") or real_is_file(path)

        with self.env("/nix/store/0000-nextvpn/share"), mock.patch.object(Path, "is_file", is_file):
            self.assertFalse(paths.shared_icon_exists("nextvpn-tray-disconnected"))


if __name__ == "__main__":
    unittest.main()
