# SPDX-License-Identifier: GPL-3.0-or-later
"""Checking GitHub Releases for a newer whoohub and updating the installed package.

At most one request per day (and none if the user turned the check off). Only whoohub's own release
metadata is fetched from the GitHub API; nothing about the user is sent.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from . import __version__, paths
from .backends import UA, JobError
from .i18n import _

REPO = "whooduck-crypto/whoohub"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 86400
DEFAULTS = {"auto_check": True, "last_check": 0, "skipped": ""}


# ── settings ───────────────────────────────────────────────────────────────────────────────────────────
def load_settings():
    try:
        return {**DEFAULTS, **json.loads(paths.SETTINGS.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(s):
    tmp = paths.SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(paths.SETTINGS)


def set_setting(key, value):
    s = load_settings()
    s[key] = value
    save_settings(s)


# ── versions ───────────────────────────────────────────────────────────────────────────────────────────
def current_version():
    return os.environ.get("WHOOHUB_FAKE_VERSION") or __version__  # the env var is for testing the dialog


def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def is_newer(remote, local):
    return _vtuple(remote) > _vtuple(local)


def install_kind():
    """'pacman' if whoohub was installed as a package (it can update itself), otherwise 'source'."""
    try:
        r = subprocess.run(["pacman", "-Qqo", str(Path(__file__).resolve())], capture_output=True, text=True)
        return "pacman" if r.returncode == 0 and r.stdout.strip() == "whoohub" else "source"
    except OSError:
        return "source"


# ── checking ───────────────────────────────────────────────────────────────────────────────────────────
def check(force=False):
    """Info about a newer release, or None. Without force: respects the daily limit, the on/off setting
    and a skipped version. Raises OSError/ValueError on network problems only when forced."""
    s = load_settings()
    if not force and (not s["auto_check"] or time.time() - s["last_check"] < CHECK_EVERY):
        return None
    try:
        req = urllib.request.Request(API, headers={**UA, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rel = json.load(r)
    except (OSError, ValueError):
        if force:
            raise
        return None
    finally:
        set_setting("last_check", int(time.time()))
    version = (rel.get("tag_name") or "").lstrip("v")
    if not version or not is_newer(version, current_version()):
        return None
    if not force and s["skipped"] == version:
        return None
    asset = next((a for a in rel.get("assets") or []
                  if re.fullmatch(r"whoohub-.+-any\.pkg\.tar\.zst", a.get("name", ""))), None)
    digest = (asset or {}).get("digest") or ""
    return {
        "version": version,
        "notes": (rel.get("body") or "").strip(),
        "page": rel.get("html_url") or f"https://github.com/{REPO}/releases",
        "asset_url": asset["browser_download_url"] if asset else "",
        "asset_name": asset["name"] if asset else "",
        "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
    }


# ── updating ───────────────────────────────────────────────────────────────────────────────────────────
def update_steps(info):
    def steps(job):
        if not info["asset_url"]:
            raise JobError(_("This release has no package to install — open the release page instead"))
        dest = paths.CACHE / info["asset_name"]
        job.on_line(_("Downloading {file}…").format(file=info["asset_name"]))
        h = hashlib.sha256()
        with urllib.request.urlopen(urllib.request.Request(info["asset_url"], headers=UA), timeout=60) as r, \
                open(dest, "wb") as f:
            while chunk := r.read(1 << 20):
                if job.cancelled:
                    raise JobError(_("Cancelled"))
                f.write(chunk)
                h.update(chunk)
        if info["sha256"]:
            if h.hexdigest() != info["sha256"]:
                dest.unlink(missing_ok=True)
                raise JobError(_("The downloaded file is damaged (checksum mismatch) — nothing was installed"))
            job.on_line(_("Checksum OK"))
        job.run(["pkexec", "pacman", "-U", "--noconfirm", str(dest)], what=_("pacman could not install the update"))
        dest.unlink(missing_ok=True)
        return _("whoohub {version} installed").format(version=info["version"])
    return steps
