# SPDX-License-Identifier: GPL-3.0-or-later
"""App catalog: merges AppStream (Arch repositories, Flathub) and AppImageHub into one searchable SQLite DB.

One app = one row (apps.key). Sources of the same app are merged:
  * Arch and Flathub — by AppStream component id (org.mozilla.firefox, …);
  * AppImage — by name, when exactly one app in the catalog has that name.
The AUR is not stored: it is searched online (backends.aur_search).
"""
import gzip
import html
import json
import os
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import paths
from .i18n import _, ui_language


def N_(text):  # mark for translation, translate later
    return text

LANG = ui_language()
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SCHEMA_VERSION = 6

ARCH_XML_DIR = Path("/usr/share/swcatalog/xml")
ARCH_ICON_DIR = Path("/usr/share/swcatalog/icons")
FLATHUB_DIRS = [  # per-user and system-wide Flathub catalogs
    Path.home() / ".local/share/flatpak/appstream/flathub/x86_64/active",
    Path("/var/lib/flatpak/appstream/flathub/x86_64/active"),
]
APPIMAGE_FEED_URL = "https://appimage.github.io/feed.json"
APPIMAGE_DB_URL = "https://appimage.github.io/database/"
APP_TYPES = {"desktop-application", "desktop", "console-application"}

# Store sections -> AppStream categories. Titles are translated in the UI (N_ marks them for xgettext).
SECTIONS = [
    ("featured", "⭐", N_("Featured"), None),
    ("game", "🎮", N_("Games"), {"Game"}),
    ("network", "🌐", N_("Internet"), {"Network", "WebBrowser", "Chat", "InstantMessaging", "Email"}),
    ("media", "🎬", N_("Audio & Video"), {"AudioVideo", "Audio", "Video", "Music", "Player"}),
    ("graphics", "🎨", N_("Graphics"), {"Graphics", "2DGraphics", "3DGraphics", "Photography", "RasterGraphics"}),
    ("dev", "💻", N_("Development"), {"Development", "IDE", "TextEditor"}),
    ("office", "📝", N_("Office"), {"Office", "WordProcessor", "Spreadsheet", "Presentation"}),
    ("edu", "🔬", N_("Science & Education"), {"Education", "Science", "Math"}),
    ("system", "⚙️", N_("System"), {"System", "Settings", "Monitor", "PackageManager", "Security"}),
    ("utility", "🧰", N_("Utilities"), {"Utility", "FileTools", "Archiving", "Accessories"}),
]

# Featured: what people usually install first
FEATURED = [
    "org.mozilla.firefox", "com.discordapp.discord", "org.telegram.desktop", "com.valvesoftware.steam",
    "com.obsproject.studio", "org.videolan.vlc", "com.spotify.client", "org.gimp.gimp", "org.kde.krita",
    "org.blender.blender", "org.libreoffice.libreoffice", "com.visualstudio.code", "com.heroicgameslauncher.hgl",
    "net.lutris.lutris", "com.usebottles.bottles", "net.davidotek.pupgui2", "org.qbittorrent.qbittorrent",
    "md.obsidian.obsidian", "org.kde.kdenlive", "io.mpv.mpv", "org.prismlauncher.prismlauncher",
    "com.github.tchx84.flatseal", "org.chromium.chromium", "com.brave.browser", "org.keepassxc.keepassxc",
    "org.audacityteam.audacity", "org.inkscape.inkscape", "io.github.peazip.peazip", "org.kde.okular",
    "com.github.wwmm.easyeffects", "org.signal.signal", "com.vscodium.codium", "org.godotengine.godot",
]


def norm_id(i):
    i = i.strip().lower()
    return i[:-8] if i.endswith(".desktop") else i


def norm_name(n):
    return re.sub(r"[\W_]+", "", n.lower())  # letters and digits of any script


# ── AppStream ──────────────────────────────────────────────────────────────────────────────────────────
def _pick(el, tag):
    """Tag text in the UI language, falling back to untranslated, then English."""
    best = {}
    for c in el.findall(tag):
        best.setdefault(c.get(XML_LANG) or "", (c.text or "").strip())
    return best.get(LANG) or best.get("") or best.get("en") or best.get("C") or ""


def _description(el):
    d = el.find("description")
    if d is None:
        return ""
    # catalogs interleave translated paragraphs: <p>…</p><p xml:lang="ru">…</p>
    have_ru = any(c.get(XML_LANG) == LANG for c in d.iter())
    want = LANG if have_ru else None
    out = []
    for c in d:
        if (c.get(XML_LANG) or None) != want and c.tag == "p":
            continue
        if c.tag == "p":
            out.append(" ".join("".join(c.itertext()).split()))
        elif c.tag in ("ul", "ol"):
            items = [li for li in c if li.tag == "li" and (li.get(XML_LANG) or None) == want]
            if not items and want:
                items = [li for li in c if li.tag == "li" and not li.get(XML_LANG)]
            out += ["• " + " ".join("".join(li.itertext()).split()) for li in items]
    return "\n\n".join(x for x in out if x).replace("\n\n• ", "\n• ")


def _icon(el, icon_root, origin):
    """Path of the best cached icon, or the URL of a remote one."""
    cached, remote = [], None
    for ic in el.findall("icon"):
        t, txt = ic.get("type"), (ic.text or "").strip()
        if t == "cached" and txt:
            w = int(ic.get("width") or 64)
            scale = int(ic.get("scale") or 1)
            sub = f"{w}x{w}" + (f"@{scale}" if scale > 1 else "")
            cached.append((w * scale, sub, txt))
        elif t == "remote" and txt:
            remote = txt
    for size, sub, name in sorted(cached, reverse=True):
        for base in ([icon_root / origin / sub] if origin else []) + [icon_root / sub]:
            p = base / name
            if p.exists():
                return str(p)
    return remote or ""


def _screens(el):
    out = []
    for s in el.findall("screenshots/screenshot"):
        imgs = s.findall("image")
        src = [i for i in imgs if i.get("type") == "source"] or imgs
        # a medium-size thumbnail loads much faster than the original
        thumbs = sorted((i for i in imgs if i.get("type") == "thumbnail" and i.get("width")),
                        key=lambda i: int(i.get("width")))
        mid = [i for i in thumbs if int(i.get("width")) >= 600]
        pick = (mid or src or thumbs)
        if pick and pick[0].text:
            url = pick[0].text.strip()
            if url.startswith("http"):
                out.append(url)
        if len(out) >= 6:
            break
    return out


def parse_appstream(path, source, icon_root):
    """App components from an AppStream catalog file (.xml.gz)."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as f:
        origin = None
        for ev, el in ET.iterparse(f, events=("start", "end")):
            if ev == "start":
                if el.tag == "components":
                    origin = el.get("origin")
                continue
            if el.tag != "component":
                continue
            ctype = el.get("type") or "desktop-application"
            cid = (el.findtext("id") or "").strip()
            if ctype not in APP_TYPES or not cid:
                el.clear()
                continue
            name = _pick(el, "name")
            if not name:
                el.clear()
                continue
            ref = (el.findtext("pkgname") or "").strip() if source == "pacman" else cid
            if source == "flatpak":
                b = el.findtext("bundle") or ""
                ref = b.split("/")[1] if b.count("/") >= 2 else cid
            if not ref:
                el.clear()
                continue
            rel = el.find("releases/release")
            dev = el.find("developer")
            yield {
                "key": norm_id(cid),
                "name": name,
                "summary": _pick(el, "summary"),
                "description": _description(el),
                "icon": _icon(el, icon_root, origin),
                "categories": sorted({c.text.strip() for c in el.findall("categories/category") if c.text}),
                "keywords": " ".join(k.text.strip() for k in el.findall("keywords/keyword") if k.text),
                "developer": (_pick(dev, "name") if dev is not None else "") or _pick(el, "developer_name"),
                "homepage": next((u.text.strip() for u in el.findall("url") if u.get("type") == "homepage" and u.text), ""),
                "license": (el.findtext("project_license") or "").strip(),
                "screenshots": _screens(el),
                "console": ctype == "console-application",
                "source": {"type": source, "ref": ref, "version": rel.get("version") if rel is not None else "",
                           "repo": (origin or "").replace("archlinux-arch-", "")},
            }
            el.clear()


def _html_to_text(text):
    """AppImageHub descriptions are often HTML (<p>, <li>, entities): turn them into plain paragraphs."""
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n• ", text)
    text = re.sub(r"(?i)<\s*(br|/p|/li|/ul|/ol|/h\d)\s*/?>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    paras = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(p for p in paras if p)


def _first_sentence(text, limit=140):
    """A one-line summary: the first sentence of the first paragraph, cut at a word boundary."""
    line = text.split("\n", 1)[0].lstrip("• ")
    m = re.match(r"(.+?[.!?])(\s|$)", line)
    line = m.group(1) if m and len(m.group(1)) >= 20 else line
    if len(line) > limit:
        line = line[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-") + "…"
    return line


def _strs(v):
    """List of strings from a feed field — the feed mixes nulls, numbers and dicts."""
    return [str(x) for x in v if isinstance(x, (str, int, float))] if isinstance(v, list) else []


def parse_appimages(feed_path):
    with open(feed_path) as f:
        items = json.load(f).get("items", [])
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("name"), str):
            continue
        name = it["name"].replace("_", " ").strip()
        if not name:
            continue
        links = [l for l in it.get("links") or [] if isinstance(l, dict) and isinstance(l.get("url"), str)]
        gh = next((l["url"] for l in links if l.get("type") == "GitHub"), "")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", gh):  # must be "owner/repo"
            gh = ""
        icons, shots = _strs(it.get("icons")), _strs(it.get("screenshots"))
        desc = _html_to_text(it["description"]) if isinstance(it.get("description"), str) else ""
        authors = [str(a.get("name")) for a in it.get("authors") or [] if isinstance(a, dict) and a.get("name")]
        yield {
            "key": "appimage:" + it["name"].lower(),
            "name": name,
            "summary": _first_sentence(desc),
            "description": desc.replace("\n", "\n\n").replace("\n\n• ", "\n• "),
            "icon": APPIMAGE_DB_URL + icons[0] if icons else "",
            "categories": _strs(it.get("categories")),
            "keywords": "",
            "developer": ", ".join(authors),
            "homepage": f"https://github.com/{gh}" if gh else "",
            "license": it.get("license") if isinstance(it.get("license"), str) else "",
            "screenshots": [APPIMAGE_DB_URL + s for s in shots][:3],
            "console": False,
            "source": {"type": "appimage", "ref": gh, "version": "",
                       "download": next((l["url"] for l in links if l.get("type") == "Download"), "")},
        }


# ── building the DB ────────────────────────────────────────────────────────────────────────────────────────
def source_files():
    """Catalog files the DB is built from (their mtimes decide when to rebuild)."""
    files = []
    if ARCH_XML_DIR.is_dir():
        files += [("pacman", p, ARCH_ICON_DIR) for p in sorted(ARCH_XML_DIR.glob("*.xml*"))]
    for d in FLATHUB_DIRS:
        for name in ("appstream.xml.gz", "appstream.xml"):
            if (d / name).exists():
                files.append(("flatpak", d / name, d / "icons"))
                break
        else:
            continue
        break
    if paths.FEED.exists():
        files.append(("appimage", paths.FEED, None))
    return files


def fetch_appimage_feed(max_age=86400):
    """AppImageHub catalog (~3 MB), refreshed daily."""
    if paths.FEED.exists() and time.time() - paths.FEED.stat().st_mtime < max_age:
        return
    req = urllib.request.Request(APPIMAGE_FEED_URL, headers={"User-Agent": "whoohub (+https://github.com/whooduck-crypto/whoohub)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    json.loads(data)  # never save a broken file
    tmp = paths.FEED.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(paths.FEED)


def needs_rebuild():
    if not paths.DB.exists():
        return True
    try:
        con = sqlite3.connect(paths.DB)
        ver = con.execute("select value from meta where key='schema'").fetchone()
        stamp = con.execute("select value from meta where key='sources'").fetchone()
        con.close()
    except sqlite3.Error:
        return True
    if not ver or int(ver[0]) != SCHEMA_VERSION:
        return True
    return not stamp or stamp[0] != _sources_stamp()


def _sources_stamp():
    return json.dumps([LANG] + [[t, str(p), int(p.stat().st_mtime)] for t, p, _icons in source_files()])


def build(progress=None):
    """Rebuild the DB. progress(text) reports steps for the loading screen."""
    apps = {}          # key -> record
    by_name = {}       # normalized name -> [key] (to merge AppImages)

    def add(rec):
        src = rec.pop("source")
        cur = apps.get(rec["key"])
        if cur is None:
            rec["sources"] = [src]
            apps[rec["key"]] = rec
            by_name.setdefault(norm_name(rec["name"]), []).append(rec["key"])
            return
        cur["sources"].append(src)
        # fill in missing fields; a cached (local) icon beats a remote one
        for k in ("summary", "description", "developer", "homepage", "license", "keywords"):
            if not cur.get(k) and rec.get(k):
                cur[k] = rec[k]
        if rec["icon"] and (not cur["icon"] or cur["icon"].startswith("http")) and not rec["icon"].startswith("http"):
            cur["icon"] = rec["icon"]
        if len(rec["screenshots"]) > len(cur["screenshots"]):
            cur["screenshots"] = rec["screenshots"]
        cur["categories"] = sorted(set(cur["categories"]) | set(rec["categories"]))

    for stype, path, icon_root in source_files():
        if progress:
            progress({"pacman": _("Reading the Arch repositories catalog…"),
                      "flatpak": _("Reading the Flathub catalog…"),
                      "appimage": _("Reading the AppImage catalog…")}[stype])
        if stype == "appimage":
            for rec in parse_appimages(path):
                if not rec["source"]["ref"] and not rec["source"]["download"]:
                    continue  # neither GitHub nor a download page: nowhere to get it from
                keys = by_name.get(norm_name(rec["name"]), [])
                if len(keys) == 1:  # the app is already known: add AppImage as another source
                    apps[keys[0]]["sources"].append(rec["source"])
                    if not apps[keys[0]]["icon"]:
                        apps[keys[0]]["icon"] = rec["icon"]
                else:
                    add(rec)
        else:
            for rec in parse_appstream(path, stype, icon_root):
                add(rec)

    if progress:
        progress(_("Building the search index…"))
    tmp = paths.DB.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
        create table meta(key text primary key, value text);
        create table apps(key text primary key, name text, summary text, description text, icon text,
                          categories text, developer text, homepage text, license text, screenshots text,
                          sources text, console int, rank int);
        create virtual table apps_fts using fts5(key unindexed, name, summary, keywords, refs,
                                                 tokenize='unicode61 remove_diacritics 2', prefix='2 3');
    """)
    feat = {k: i for i, k in enumerate(FEATURED)}
    rows, fts = [], []
    for a in apps.values():
        # lower rank = shown first: featured apps, then apps with richer metadata
        rank = feat.get(a["key"], 1000) * 10 - len(a["sources"]) * 3 - bool(a["icon"]) * 4 \
            - bool(a["screenshots"]) * 2 - bool(a["description"]) + (5 if a["console"] else 0)
        rows.append((a["key"], a["name"], a["summary"], a["description"], a["icon"], ";".join(a["categories"]),
                     a["developer"], a["homepage"], a["license"], json.dumps(a["screenshots"]),
                     json.dumps(a["sources"], ensure_ascii=False), int(a["console"]), rank))
        fts.append((a["key"], a["name"], a["summary"], a["keywords"] + " " + " ".join(a["categories"]),
                    " ".join(s["ref"] for s in a["sources"])))
    con.executemany("insert into apps values (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("insert into apps_fts values (?,?,?,?,?)", fts)
    con.executemany("insert into meta values (?,?)", [("schema", str(SCHEMA_VERSION)), ("sources", _sources_stamp()),
                                                      ("built", str(int(time.time())))])
    con.commit()
    con.close()
    tmp.replace(paths.DB)
    return len(apps)


# ── reading ─────────────────────────────────────────────────────────────────────────────────────────────
class Catalog:
    COLS = "key, name, summary, description, icon, categories, developer, homepage, license, screenshots, sources"

    def __init__(self):
        self.con = sqlite3.connect(paths.DB, check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    @staticmethod
    def _app(row):
        a = dict(row)
        a["categories"] = [c for c in (a["categories"] or "").split(";") if c]
        a["screenshots"] = json.loads(a["screenshots"] or "[]")
        a["sources"] = json.loads(a["sources"] or "[]")
        return a

    def count(self):
        return self.con.execute("select count(*) from apps").fetchone()[0]

    def get(self, key):
        r = self.con.execute(f"select {self.COLS} from apps where key=?", (key,)).fetchone()
        return self._app(r) if r else None

    def section(self, sid, limit=240):
        if sid == "featured":
            keys = [k for k in FEATURED]
            q = f"select {self.COLS} from apps where key in ({','.join('?' * len(keys))}) order by rank"
            return [self._app(r) for r in self.con.execute(q, keys)]
        cats = next(s[3] for s in SECTIONS if s[0] == sid)
        cond = " or ".join("(';'||categories||';') like ?" for _cat in cats)
        q = f"select {self.COLS} from apps where console=0 and ({cond}) order by rank, name limit ?"
        return [self._app(r) for r in self.con.execute(q, [f"%;{c};%" for c in cats] + [limit])]

    def search(self, text, limit=120):
        words = re.findall(r"\w+", text.lower())
        if not words:
            return []
        match = " ".join(f'"{w}"*' for w in words)
        q = f"""select {', '.join('a.' + c.strip() for c in self.COLS.split(','))}
                from apps_fts f join apps a on a.key=f.key
                where apps_fts match ? order by bm25(apps_fts, 0, 10, 3, 2, 4) + a.rank * 0.01 limit ?"""
        try:
            return [self._app(r) for r in self.con.execute(q, (match, limit))]
        except sqlite3.OperationalError:
            return []

    def by_refs(self, stype, refs):
        """Catalog apps having a source of type stype whose ref is in refs (for the Installed view)."""
        out = []
        for r in self.con.execute(f"select {self.COLS} from apps order by name"):
            a = self._app(r)
            if any(s["type"] == stype and s["ref"] in refs for s in a["sources"]):
                out.append(a)
        return out
