"""The sign-in entry and the translation catalogue."""

import ast
import tempfile
import unittest
from pathlib import Path

from nextvpn.core import autostart, i18n

LINUX = Path(__file__).resolve().parent.parent


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="nextvpn-autostart")
        self.path = Path(self._tmp.name) / "autostart" / "nextvpn.desktop"

    def tearDown(self):
        self._tmp.cleanup()

    def test_enabling_writes_an_entry_that_starts_hidden(self):
        self.assertTrue(autostart.set_enabled(True, self.path, ["nextvpn"]))
        text = self.path.read_text()
        self.assertIn("Exec=nextvpn --minimised\n", text)
        self.assertIn("Type=Application\n", text)
        self.assertTrue(autostart.is_enabled(self.path))

    def test_disabling_removes_the_entry_and_tolerates_its_absence(self):
        autostart.set_enabled(True, self.path, ["nextvpn"])
        self.assertTrue(autostart.set_enabled(False, self.path))
        self.assertFalse(self.path.exists())
        self.assertTrue(autostart.set_enabled(False, self.path))
        self.assertFalse(autostart.is_enabled(self.path))

    def test_an_entry_the_desktop_disabled_reads_as_off(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[Desktop Entry]\nExec=nextvpn\nX-GNOME-Autostart-enabled=false\n")
        self.assertFalse(autostart.is_enabled(self.path))
        self.path.write_text("[Desktop Entry]\nExec=nextvpn\nHidden=true\n")
        self.assertFalse(autostart.is_enabled(self.path))

    def test_paths_with_spaces_are_quoted_for_the_exec_key(self):
        text = autostart.render(["/home/me/My Apps/nextvpn"])
        self.assertIn('Exec="/home/me/My Apps/nextvpn" --minimised\n', text)


def translatable_strings():
    """Every literal passed to _() or N_() anywhere in the application."""
    found = set()
    for path in (LINUX / "nextvpn").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("_", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


class TranslationTests(unittest.TestCase):
    def test_the_po_reader_handles_continuations_escapes_and_fuzzy_entries(self):
        catalogue = i18n.parse_po(
            'msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
            '#: a.py:1\nmsgid "Hello"\nmsgstr "Привет"\n\n'
            'msgid "Two "\n"lines"\nmsgstr "Две "\n"строки \\"тут\\""\n\n'
            '#, fuzzy\nmsgid "Unsure"\nmsgstr "Не уверен"\n')
        self.assertEqual("Привет", catalogue["Hello"])
        self.assertEqual('Две строки "тут"', catalogue["Two lines"])
        self.assertNotIn("Unsure", catalogue)
        self.assertNotIn("", catalogue)

    def test_languages_come_from_the_usual_variables(self):
        self.assertEqual(["ru_RU", "ru"], i18n.wanted_languages({"LANG": "ru_RU.UTF-8"}))
        self.assertEqual(["uk", "ru"], i18n.wanted_languages({"LANGUAGE": "uk:ru", "LANG": "en_US"}))
        self.assertEqual([], i18n.wanted_languages({"LANG": "C.UTF-8"}))

    def test_the_russian_catalogue_covers_every_string_in_the_interface(self):
        catalogue = i18n.parse_po((LINUX / "po" / "ru.po").read_text(encoding="utf-8"))
        missing = sorted(s for s in translatable_strings() if s not in catalogue)
        self.assertEqual([], missing)

    def test_format_placeholders_survive_translation(self):
        import re
        catalogue = i18n.parse_po((LINUX / "po" / "ru.po").read_text(encoding="utf-8"))
        for source, translated in catalogue.items():
            self.assertEqual(sorted(re.findall(r"\{\w+\}", source)),
                             sorted(re.findall(r"\{\w+\}", translated)), source)


if __name__ == "__main__":
    unittest.main()
