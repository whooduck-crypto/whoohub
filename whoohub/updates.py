# SPDX-License-Identifier: GPL-3.0-or-later
"""Checking GitHub Releases for a newer whoohub and updating the installed package.

At most one request per day (and none if the user turned the check off). Only whoohub's own release
metadata is fetched from the GitHub API; nothing about the user is sent.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
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
    """How this copy of whoohub was installed — that decides how it can update itself:
      ("pacman", None)    a package: download the release package, pacman -U through polkit
      ("prefix", prefix)  `make install PREFIX=…`: download the release sources, make install into the same prefix
      ("checkout", root)  running from a source tree: update with git pull, not from the app
    """
    here = Path(__file__).resolve()
    try:
        r = subprocess.run(["pacman", "-Qqo", str(here)], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip() == "whoohub":
            return "pacman", None
    except OSError:
        pass
    # installed layout: <prefix>/share/whoohub/whoohub/updates.py
    if here.parent.name == "whoohub" and here.parents[1].name == "whoohub" and here.parents[2].name == "share":
        return "prefix", here.parents[3]
    return "checkout", here.parents[1]


def _asset(rel, pattern):
    a = next((a for a in rel.get("assets") or [] if re.fullmatch(pattern, a.get("name", ""))), None)
    if not a:
        return {"url": "", "name": "", "sha256": ""}
    digest = a.get("digest") or ""
    return {"url": a["browser_download_url"], "name": a["name"],
            "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else ""}


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
    return {
        "version": version,
        "notes": (rel.get("body") or "").strip(),
        "page": rel.get("html_url") or f"https://github.com/{REPO}/releases",
        "package": _asset(rel, r"whoohub-.+-any\.pkg\.tar\.zst"),   # for package installs
        "source": _asset(rel, r"whoohub-[\d.]+\.tar\.gz"),           # for make-install installs
    }


def can_update_in_app(info):
    """(True, "") or (False, reason shown in the update dialog)."""
    kind, _where = install_kind()
    if kind == "pacman":
        return (True, "") if info["package"]["url"] else \
            (False, _("This release has no package attached — the release page has the new version."))
    if kind == "prefix":
        if not info["source"]["url"]:
            return False, _("This release has no source archive attached — the release page has the new version.")
        missing = [t for t in ("make", "msgfmt") if not shutil.which(t)]
        if missing:
            return False, _("Updating needs {tools} (sudo pacman -S make gettext).").format(tools=", ".join(missing))
        return True, ""
    return False, _("whoohub runs from a source folder — update it with git pull.")


# ── updating ───────────────────────────────────────────────────────────────────────────────────────────
def _download(job, asset):
    """Download a release asset into the cache, verifying the sha256 GitHub publishes for it."""
    if not asset["sha256"]:
        raise JobError(_("GitHub did not publish a checksum for {file} — not installing it").format(file=asset["name"]))
    dest = paths.CACHE / asset["name"]
    job.on_line(_("Downloading {file}…").format(file=asset["name"]))
    h = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(asset["url"], headers=UA), timeout=60) as r, \
            open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            if job.cancelled:
                raise JobError(_("Cancelled"))
            f.write(chunk)
            h.update(chunk)
    if h.hexdigest() != asset["sha256"]:
        dest.unlink(missing_ok=True)
        raise JobError(_("The downloaded file is damaged (checksum mismatch) — nothing was installed"))
    job.on_line(_("Checksum OK"))
    return dest


def _writable(prefix):
    """Can this user install into prefix without root? (~/.local: yes, /usr/local: no)"""
    p = Path(prefix) / "share" / "whoohub"
    while not p.exists():
        p = p.parent
    return os.access(p, os.W_OK)


def update_steps(info):
    kind, where = install_kind()

    def from_package(job):
        dest = _download(job, info["package"])
        job.run(["pkexec", "pacman", "-U", "--noconfirm", str(dest)], what=_("pacman could not install the update"))
        dest.unlink(missing_ok=True)

    def from_source(job):
        archive = _download(job, info["source"])
        work = paths.CACHE / "update-src"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(work, filter="data")  # "data" refuses absolute paths, .. and device files
        tops = [d for d in work.iterdir() if d.is_dir()]
        if len(tops) != 1 or not (tops[0] / "Makefile").exists():
            raise JobError(_("The source archive has an unexpected layout — nothing was installed"))
        job.run(["make", "-C", str(tops[0])], what=_("Building the translations failed — see the log"))
        # translations are built as the user above; only the copying may need root
        argv = ["make", "-C", str(tops[0]), "install", f"PREFIX={where}"]
        if not _writable(where):
            argv = ["pkexec", "env", f"PATH={os.environ.get('PATH', '/usr/bin')}"] + argv
        job.run(argv, what=_("make install failed — see the log"))
        shutil.rmtree(work, ignore_errors=True)
        archive.unlink(missing_ok=True)

    def steps(job):
        if kind == "pacman":
            from_package(job)
        elif kind == "prefix":
            from_source(job)
        else:
            raise JobError(_("whoohub runs from a source folder — update it with git pull."))
        return _("whoohub {version} installed").format(version=info["version"])
    return steps
