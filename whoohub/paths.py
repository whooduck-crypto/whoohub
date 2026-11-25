# SPDX-License-Identifier: GPL-3.0-or-later
"""Where whoohub keeps its files (XDG base directories)."""
import os
from pathlib import Path

_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "whoohub"
DATA = _DATA_HOME / "whoohub"

DB = CACHE / "catalog.sqlite"          # merged catalog
FEED = CACHE / "appimage-feed.json"    # AppImageHub catalog
IMG = CACHE / "img"                    # downloaded icons and screenshots
AUR_BUILD = CACHE / "aur"              # AUR sources and builds
APPIMAGES = Path.home() / "Applications"            # the .AppImage files themselves
APPIMAGE_REG = DATA / "appimages.json"              # AppImages installed by whoohub
APPIMAGE_ICONS = DATA / "icons"
DESKTOP_DIR = _DATA_HOME / "applications"

for d in (CACHE, DATA, IMG, AUR_BUILD, APPIMAGE_ICONS):
    d.mkdir(parents=True, exist_ok=True)
