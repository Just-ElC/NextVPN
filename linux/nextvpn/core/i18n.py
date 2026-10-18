"""
Translations.

Installed builds use the compiled catalogue meson puts in the locale directory.
A source checkout has no compiled catalogue, so the .po files next to the
sources are read directly instead: running from git shows the same language as
an installed copy, with no build step.
"""

from __future__ import annotations

import gettext
import locale
import os
from pathlib import Path

DOMAIN = "nextvpn"

_translation: gettext.NullTranslations = gettext.NullTranslations()


def _(message: str) -> str:
    return _translation.gettext(message)


def N_(message: str) -> str:
    """Marks a string for extraction without translating it yet."""
    return message


def setup(localedir: str | None = None, po_dir: str | os.PathLike | None = None) -> None:
    global _translation

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        # An unsupported locale in the environment must not stop the app.
        pass

    translation: gettext.NullTranslations | None = None
    if localedir and os.path.isdir(localedir):
        try:
            translation = gettext.translation(DOMAIN, localedir)
        except OSError:
            translation = None

    if translation is None and po_dir is not None:
        translation = _from_po_dir(Path(po_dir))

    _translation = translation or gettext.NullTranslations()


def use(translation: gettext.NullTranslations | None) -> None:
    """Replaces the active catalogue. Used by tests."""
    global _translation
    _translation = translation or gettext.NullTranslations()


def wanted_languages(environ=os.environ) -> list[str]:
    """The languages gettext would try, in order, from the usual variables."""
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = environ.get(variable)
        if value:
            break
    else:
        return []

    result: list[str] = []
    for item in value.split(":"):
        item = item.split(".")[0].split("@")[0]
        if not item or item in ("C", "POSIX"):
            continue
        for candidate in (item, item.split("_")[0]):
            if candidate not in result:
                result.append(candidate)
    return result


def _from_po_dir(po_dir: Path) -> gettext.NullTranslations | None:
    for language in wanted_languages():
        path = po_dir / f"{language}.po"
        if path.is_file():
            try:
                return PoTranslations(parse_po(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return None
    return None


class PoTranslations(gettext.NullTranslations):
    def __init__(self, catalogue: dict[str, str]):
        super().__init__()
        self._catalogue = catalogue

    def gettext(self, message):
        return self._catalogue.get(message) or message


def parse_po(text: str) -> dict[str, str]:
    """
    Reads the subset of the PO format this project writes: msgid/msgstr pairs,
    continuation lines and comments. Fuzzy entries are skipped, the way msgfmt
    skips them, so an unreviewed translation never reaches the screen.
    """
    catalogue: dict[str, str] = {}
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    current: list[str] | None = None
    fuzzy = False

    def flush():
        nonlocal msgid, msgstr, fuzzy
        if msgid is not None and msgstr is not None and not fuzzy:
            key, value = "".join(msgid), "".join(msgstr)
            if key and value:
                catalogue[key] = value
        msgid = msgstr = None
        fuzzy = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            current = None
            continue
        if line.startswith("#"):
            if msgstr is not None:
                flush()
                current = None
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            continue
        if line.startswith("msgid "):
            if msgstr is not None:
                flush()
            msgid = [_unquote(line[6:])]
            current = msgid
        elif line.startswith("msgstr "):
            msgstr = [_unquote(line[7:])]
            current = msgstr
        elif line.startswith('"') and current is not None:
            current.append(_unquote(line))
        else:
            raise ValueError(f"unsupported PO line: {raw!r}")

    flush()
    return catalogue


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unquote(token: str) -> str:
    token = token.strip()
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise ValueError(f"not a quoted PO string: {token!r}")

    out: list[str] = []
    body = token[1:-1]
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)
