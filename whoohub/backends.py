# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing, removing and launching apps from each source.

Long operations are "steps" functions: a Job runs them in a worker thread and streams output lines to
the UI. Root access goes through pkexec (the graphical polkit password prompt), never sudo.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, paths
from .i18n import _

UA = {"User-Agent": f"whoohub/{__version__} (+https://github.com/whooduck-crypto/whoohub)"}


def source_info(stype):
    """(label, badge, explanation) of a source type, translated."""
    return {
        "pacman": (_("Arch repositories (pacman)"), "pacman",
                   _("A distribution package: updated together with the system (pacman -Syu). Needs your password.")),
        "flatpak": (_("Flathub"), "Flathub",
                    _("A sandboxed Flatpak, installed for your user without a password. Usually the newest version.")),
        "aur": (_("AUR"), "AUR",
                _("Built from a community script (PKGBUILD) — worth reading before installing.")),
        "appimage": (_("AppImage"), "AppImage",
                     _("A single file from the author's GitHub, nothing installed system-wide. Does not update itself.")),
    }[stype]


class JobError(Exception):
    pass


# ── what is installed ──────────────────────────────────────────────────────────────────────────────────
def _words(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []


def installed_state():
    """{'pacman': {pkg: ver}, 'foreign': set, 'flatpak': {appid: 'user'|'system'}, 'appimage': {key: info}}"""
    pac = {}
    out = subprocess.run(["pacman", "-Q"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        name, _sep, ver = line.partition(" ")
        pac[name] = ver
    fp = {}
    try:
        out = subprocess.run(["flatpak", "list", "--app", "--columns=application,installation"],
                             capture_output=True, text=True, timeout=20).stdout
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                fp[parts[0]] = parts[1]
    except (OSError, subprocess.SubprocessError):
        pass  # Flatpak not installed
    return {"pacman": pac, "foreign": set(_words(["pacman", "-Qqm"])), "flatpak": fp,
            "appimage": load_appimage_reg()}


def is_installed(state, src):
    t, ref = src["type"], src["ref"]
    if t in ("pacman", "aur"):
        return ref in state["pacman"]
    if t == "flatpak":
        return ref in state["flatpak"]
    if t == "appimage":
        return any(v.get("repo") == ref for v in state["appimage"].values())
    return False


# ── launching ──────────────────────────────────────────────────────────────────────────────────────────
def launch(app_key, src, state):
    t, ref = src["type"], src["ref"]
    if t == "flatpak":
        argv = ["flatpak", "run", ref]
    elif t == "appimage":
        info = next((v for v in state["appimage"].values() if v.get("repo") == ref), None)
        if not info:
            return False
        argv = [info["path"]]
    else:
        desktop = _desktop_for(app_key, ref)
        if not desktop:
            return False
        argv = ["gtk-launch", desktop]
    subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _desktop_for(app_key, pkg):
    """Name of the app's .desktop file (for gtk-launch)."""
    for d in (Path("/usr/share/applications"), paths.DESKTOP_DIR):
        for cand in (app_key + ".desktop", app_key.split(".")[-1] + ".desktop", pkg + ".desktop"):
            if (d / cand).exists():
                return cand
    try:  # look through the package's files
        out = subprocess.run(["pacman", "-Qlq", pkg], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith("/usr/share/applications/") and line.endswith(".desktop"):
                return os.path.basename(line)
    except OSError:
        pass
    return None


# ── running commands ───────────────────────────────────────────────────────────────────────────────────
class Job:
    """Runs steps in a thread. on_line(str) and on_done(ok, message) are called from that thread —
    the UI moves them to the main loop itself (GLib.idle_add)."""

    def __init__(self, steps, on_line, on_done):
        self.steps, self.on_line, self.on_done = steps, on_line, on_done
        self.proc = None
        self.cancelled = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def run(self, argv, cwd=None, what=None):
        if self.cancelled:
            raise JobError(_("Cancelled"))
        self.on_line("$ " + " ".join(argv))
        self.proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
        for line in self.proc.stdout:
            self.on_line(line.rstrip("\n"))
        code = self.proc.wait()
        if self.cancelled:
            raise JobError(_("Cancelled"))
        if code in (126, 127) and argv[0] == "pkexec":
            raise JobError(_("No password entered — nothing was changed"))
        if code != 0:
            raise JobError(what or _("The command failed (exit code {code})").format(code=code))

    def _run(self):
        try:
            msg = self.steps(self)
            self.on_done(True, msg or _("Done"))
        except JobError as e:
            self.on_done(False, str(e))
        except Exception as e:  # noqa: BLE001 — report in the UI instead of killing the thread
            self.on_done(False, _("Error: {error}").format(error=e))


# ── pacman ─────────────────────────────────────────────────────────────────────────────────────────────
def pacman_install(pkg):
    def steps(job):
        job.run(["pkexec", "pacman", "-S", "--noconfirm", "--needed", pkg],
                what=_("pacman could not install the package. If the log says “404” or “not found”, "
                       "update the system first (sudo pacman -Syu)"))
        return _("{name} installed").format(name=pkg)
    return steps


def pacman_remove(pkg):
    def steps(job):
        job.run(["pkexec", "pacman", "-Rns", "--noconfirm", pkg],
                what=_("pacman could not remove the package (other packages may need it — see the log)"))
        return _("{name} removed").format(name=pkg)
    return steps


# ── Flatpak ────────────────────────────────────────────────────────────────────────────────────────────
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"


def ensure_user_flathub(job):
    """Per-user Flathub remote: lets whoohub install Flatpaks without a password."""
    remotes = _words(["flatpak", "remotes", "--user", "--columns=name"])
    if "flathub" not in remotes:
        job.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_REPO],
                what=_("Could not add Flathub for your user"))


def flatpak_install(appid):
    def steps(job):
        ensure_user_flathub(job)
        job.run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", appid],
                what=_("Flatpak could not install the app"))
        return _("Installed from Flathub")
    return steps


def flatpak_remove(appid, installation):
    def steps(job):
        where = "--system" if installation == "system" else "--user"
        job.run(["flatpak", "uninstall", where, "-y", "--noninteractive", appid],
                what=_("Flatpak could not remove the app"))
        return _("Removed")
    return steps


# ── AUR ────────────────────────────────────────────────────────────────────────────────────────────────
AUR_RPC = "https://aur.archlinux.org/rpc/v5"


def aur_search(text):
    q = urllib.parse.quote(text)
    with urllib.request.urlopen(urllib.request.Request(f"{AUR_RPC}/search/{q}?by=name-desc", headers=UA),
                                timeout=15) as r:
        res = json.load(r).get("results", [])
    res.sort(key=lambda p: (-(p.get("Popularity") or 0), p["Name"]))
    return res[:40]


def aur_pkgbuild(pkgbase):
    url = f"https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h={urllib.parse.quote(pkgbase)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def _srcinfo_deps(path):
    deps = []
    for line in Path(path).read_text().splitlines():
        key, _sep, val = line.strip().partition(" = ")
        if key in ("depends", "makedepends", "depends_x86_64", "makedepends_x86_64"):
            deps.append(re.split(r"[<>=]", val, maxsplit=1)[0])
    return deps


def aur_install(pkgbase, pkgname):
    if not re.fullmatch(r"[a-z0-9@._+-]+", pkgbase):
        raise ValueError(f"bad AUR package name: {pkgbase!r}")

    def steps(job):
        d = paths.AUR_BUILD / pkgbase
        if (d / ".git").exists():
            job.run(["git", "-C", str(d), "pull", "--ff-only"], what=_("Could not update the AUR sources"))
        else:
            shutil.rmtree(d, ignore_errors=True)
            job.run(["git", "clone", "--depth=1", f"https://aur.archlinux.org/{pkgbase}.git", str(d)],
                    what=_("Could not download the package from the AUR"))
        deps = _srcinfo_deps(d / ".SRCINFO")
        missing = subprocess.run(["pacman", "-T", *deps], capture_output=True, text=True).stdout.split() if deps else []
        if missing:
            if subprocess.run(["pacman", "-Sp", "--print-format", "%n", *missing], capture_output=True).returncode:
                not_found = [m for m in missing
                             if subprocess.run(["pacman", "-Si", m], capture_output=True).returncode != 0]
                raise JobError(_("It needs packages that are not in the repositories (they are in the AUR too): "
                                 "{names}. Install them first.").format(names=", ".join(not_found)))
            job.on_line(_("Installing dependencies from the repositories: {names}").format(names=" ".join(missing)))
            job.run(["pkexec", "pacman", "-S", "--noconfirm", "--needed", "--asdeps", *missing],
                    what=_("Could not install the dependencies"))
        job.run(["makepkg", "-f", "--noconfirm", "--needed"], cwd=str(d), what=_("The build failed"))
        built = subprocess.run(["makepkg", "--packagelist"], cwd=str(d), capture_output=True, text=True).stdout.split()
        built = [p for p in built if os.path.exists(p) and f"/{pkgname}-" in p] or \
                [p for p in built if os.path.exists(p) and "-debug-" not in p]
        if not built:
            raise JobError(_("makepkg did not produce a package"))
        job.run(["pkexec", "pacman", "-U", "--noconfirm", "--needed", *built],
                what=_("Could not install the built package"))
        return _("{name} built and installed").format(name=pkgname)
    return steps


# ── AppImage ───────────────────────────────────────────────────────────────────────────────────────────
def load_appimage_reg():
    try:
        return json.loads(paths.APPIMAGE_REG.read_text())
    except (OSError, ValueError):
        return {}


def _save_appimage_reg(reg):
    paths.APPIMAGE_REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1))


def _pick_asset(assets):
    good = [a for a in assets if a["name"].lower().endswith(".appimage")]
    bad = ("aarch64", "arm64", "armhf", "armv7", "i386", "i686")
    good = [a for a in good if not any(b in a["name"].lower() for b in bad)]
    good.sort(key=lambda a: (not ("x86_64" in a["name"] or "amd64" in a["name"]), -a.get("size", 0)))
    return good[0] if good else None


def _desktop_value(text):
    """Make text safe for a .desktop value: no control characters (a newline would inject keys)."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()


def appimage_install(app_key, name, repo, icon_url):
    def steps(job):
        if not repo:
            raise JobError(_("This app has no GitHub link — download it from the author's page"))
        job.on_line(_("Looking for the latest release on GitHub: {repo}").format(repo=repo))
        api = f"https://api.github.com/repos/{repo}/releases"
        req = urllib.request.Request(api, headers={**UA, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            releases = json.load(r)
        asset, tag = None, ""
        # stable releases first; pre-releases (nightly, beta) only if there is no stable one
        for rel in sorted((r for r in releases if not r.get("draft")), key=lambda r: bool(r.get("prerelease"))):
            asset = _pick_asset(rel.get("assets") or [])
            if asset:
                tag = rel.get("tag_name", "") + (" " + _("(pre-release)") if rel.get("prerelease") else "")
                break
        if not asset:
            raise JobError(_("The GitHub releases have no .AppImage file for x86_64"))
        paths.APPIMAGES.mkdir(exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "app"
        dest = paths.APPIMAGES / f"{slug}.AppImage"
        job.on_line(_("Downloading {file} ({size} MB)…").format(file=asset["name"],
                                                                size=asset.get("size", 0) // (1024 * 1024)))
        tmp = dest.with_suffix(".part")
        req = urllib.request.Request(asset["browser_download_url"], headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total, done, last = asset.get("size") or 0, 0, -1
            while chunk := r.read(1 << 20):
                if job.cancelled:
                    tmp.unlink(missing_ok=True)
                    raise JobError(_("Cancelled"))
                f.write(chunk)
                done += len(chunk)
                if total and (pct := done * 100 // total) // 10 != last:
                    last = pct // 10
                    job.on_line(f"  {pct}%")
        tmp.chmod(0o755)
        tmp.replace(dest)
        icon = "application-x-executable"
        if icon_url:
            try:
                ip = paths.APPIMAGE_ICONS / f"{slug}{Path(icon_url).suffix or '.png'}"
                with urllib.request.urlopen(urllib.request.Request(icon_url, headers=UA), timeout=20) as r:
                    ip.write_bytes(r.read())
                icon = str(ip)
            except OSError:
                pass  # keep the generic icon
        desktop = paths.DESKTOP_DIR / f"whoohub-{slug}.desktop"
        desktop.write_text(f"[Desktop Entry]\nType=Application\nName={_desktop_value(name)}\n"
                           f"Exec=\"{dest}\" %U\nIcon={icon}\nTerminal=false\nCategories=Utility;\n"
                           f"X-Whoohub-Key={_desktop_value(app_key)}\n")
        reg = load_appimage_reg()
        reg[app_key] = {"path": str(dest), "desktop": str(desktop), "icon": icon if icon.startswith("/") else "",
                        "repo": repo, "version": tag, "name": name}
        _save_appimage_reg(reg)
        return _("Saved to ~/Applications/{file}, a menu entry was added").format(file=dest.name)
    return steps


def appimage_remove(app_key):
    def steps(job):
        reg = load_appimage_reg()
        info = reg.pop(app_key, None)
        if not info:
            raise JobError(_("This app was not installed by whoohub"))
        for p in (info.get("path"), info.get("desktop"), info.get("icon")):
            if p and os.path.exists(p):
                os.remove(p)
                job.on_line(_("Removed {path}").format(path=p))
        _save_appimage_reg(reg)
        return _("Removed")
    return steps
