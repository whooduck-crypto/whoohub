# SPDX-License-Identifier: GPL-3.0-or-later
"""Translations (gettext). Source strings are English; translations live in po/<lang>.po."""
import gettext
import os
from pathlib import Path

DOMAIN = "whoohub"


def _localedir():
    env = os.environ.get("WHOOHUB_LOCALEDIR")
    if env:
        return env
    here = Path(__file__).resolve()
    for cand in (here.parents[1] / "build" / "locale",   # running from a source checkout (make run)
                 here.parents[2] / "locale"):             # installed: <prefix>/share/whoohub/whoohub -> <prefix>/share/locale
        if cand.is_dir():
            return str(cand)
    return None


_t = gettext.translation(DOMAIN, _localedir(), fallback=True)
_ = _t.gettext
ngettext = _t.ngettext


def ui_language():
    """Two-letter language of the interface, used to pick AppStream translations ("ru", "de", "en"…)."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val and val not in ("C", "POSIX") and not val.startswith("C."):
            return val.split(":")[0].split("_")[0].split(".")[0].lower() or "en"
    return "en"
