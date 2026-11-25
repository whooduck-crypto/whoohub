# SPDX-License-Identifier: GPL-3.0-or-later
"""whoohub user interface (GTK 4 + libadwaita)."""
import hashlib
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_ID, __version__, backends, catalog, paths  # noqa: E402
from .backends import source_info  # noqa: E402
from .i18n import _  # noqa: E402

SOURCE_ORDER = ["pacman", "flatpak", "appimage", "aur"]  # default source preference

CSS = """
.tile { padding: 12px; }
.tile-name { font-weight: 800; font-size: 11.5pt; }
.tile-sum  { font-size: 9.5pt; }
.badge { font-size: 8pt; font-weight: 800; padding: 1px 7px; border-radius: 6px; }
.badge.pacman   { color: #2190a4; background: alpha(#2190a4, 0.15); }
.badge.Flathub  { color: #3584e4; background: alpha(#3584e4, 0.15); }
.badge.AUR      { color: #e66100; background: alpha(#e66100, 0.15); }
.badge.AppImage { color: #26a269; background: alpha(#26a269, 0.15); }
.badge.votes    { color: alpha(currentColor, 0.7); background: alpha(currentColor, 0.08); }
.badge.inst     { color: var(--accent-fg-color); background: var(--accent-bg-color); }
.chip { border-radius: 99px; padding: 4px 14px; font-weight: 700; }
.app-name { font-size: 22pt; font-weight: 800; }
.log { font-family: monospace; font-size: 8.5pt; padding: 8px; }
.shot { border-radius: 12px; }
"""


# ── images ─────────────────────────────────────────────────────────────────────────────────────────────
_img_lock = threading.Lock()
_img_inflight = {}


def _cached_file(url):
    return paths.IMG / (hashlib.sha1(url.encode()).hexdigest() + Path(url.split("?")[0]).suffix[:5])


def _apply_image(widget, path):
    try:
        if isinstance(widget, Gtk.Picture):
            widget.set_filename(path)
        else:
            widget.set_from_file(path)
    except GLib.Error:
        pass
    return False


def load_image(widget, src, fallback="application-x-executable"):
    """Fill a Gtk.Image or Gtk.Picture from a path or URL (URLs download in the background, cached)."""
    if isinstance(widget, Gtk.Image):
        widget.set_from_icon_name(fallback)
    if not src:
        return
    if not src.startswith("http"):
        _apply_image(widget, src)
        return
    f = _cached_file(src)
    if f.exists() and f.stat().st_size:
        _apply_image(widget, str(f))
        return
    with _img_lock:
        waiters = _img_inflight.setdefault(src, [])
        waiters.append(widget)
        if len(waiters) > 1:
            return

    def work():
        ok = False
        try:
            with urllib.request.urlopen(urllib.request.Request(src, headers=backends.UA), timeout=20) as r:
                data = r.read(15 << 20)
            tmp = f.with_suffix(f.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(f)
            ok = True
        except OSError:
            pass
        with _img_lock:
            ws = _img_inflight.pop(src, [])
        if ok:
            for w in ws:
                GLib.idle_add(_apply_image, w, str(f))
    threading.Thread(target=work, daemon=True).start()


def badge(text, kind=None):
    return Gtk.Label(label=text, css_classes=["badge", kind or text], valign=Gtk.Align.CENTER)


def clear(box):
    c = box.get_first_child()
    while c is not None:
        n = c.get_next_sibling()
        box.remove(c)
        c = n


def idle(fn, *a):
    GLib.idle_add(lambda: fn(*a) and False)


def tile_grid():
    # min 2 per line: with 1, a homogeneous FlowBox sizes every tile for the narrowest layout (very tall tiles)
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=4,
                       min_children_per_line=2, row_spacing=12, column_spacing=12, valign=Gtk.Align.START,
                       margin_bottom=18)


def tile(title, summary, icon_src, badges, on_click, icon_name=None):
    btn = Gtk.Button(css_classes=["card", "tile"])
    g = Gtk.Box(spacing=12)
    img = Gtk.Image(pixel_size=56, valign=Gtk.Align.START)
    if icon_name:
        img.set_from_icon_name(icon_name)
    else:
        load_image(img, icon_src)
    g.append(img)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
    v.append(Gtk.Label(label=title, css_classes=["tile-name"], xalign=0, ellipsize=Pango.EllipsizeMode.END))
    v.append(Gtk.Label(label=summary or " ", css_classes=["tile-sum", "dim-label"], xalign=0, wrap=True, lines=2,
                       ellipsize=Pango.EllipsizeMode.END, max_width_chars=30, width_chars=20))
    bb = Gtk.Box(spacing=4, margin_top=3)
    for b in badges:
        bb.append(b)
    v.append(bb)
    g.append(v)
    btn.set_child(g)
    btn.connect("clicked", lambda *_a: on_click())
    return btn


# ── main window ────────────────────────────────────────────────────────────────────────────────────────
class StoreWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="whoohub", default_width=1240, default_height=840)
        self.catalog = None
        self.current_section = "featured"
        self.state = {"pacman": {}, "foreign": set(), "flatpak": {}, "appimage": {}}
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.nav = Adw.NavigationView()
        self._loading_page()
        threading.Thread(target=self._prepare, daemon=True).start()

    # ── loading the catalog ────────────────────────────────────────────────────────────────────────────
    def _loading_page(self):
        self.status = Adw.StatusPage(title=_("Preparing the catalog…"),
                                     description=_("The first start can take up to a minute"),
                                     icon_name="system-software-install-symbolic")
        self.status.set_child(Adw.Spinner(width_request=48, height_request=48, halign=Gtk.Align.CENTER))
        tv = Adw.ToolbarView(content=self.status)
        tv.add_top_bar(Adw.HeaderBar())
        self.toasts.set_child(tv)

    def _prepare(self):
        try:
            idle(self.status.set_description, _("Downloading the AppImage catalog…"))
            catalog.fetch_appimage_feed()
        except (OSError, ValueError) as e:
            print("whoohub: AppImage catalog:", e)
        if catalog.needs_rebuild():
            catalog.build(lambda t: idle(self.status.set_description, t))
        idle(self._ready, backends.installed_state())
        self._refresh_flathub_later()

    def _refresh_flathub_later(self):
        """Once a day fetch a fresh Flathub catalog; if anything changed, quietly rebuild the DB."""
        try:
            age = time.time() - (catalog.FLATHUB_DIRS[0] / "appstream.xml.gz").stat().st_mtime
        except OSError:
            age = 1e9
        remotes = backends._words(["flatpak", "remotes", "--user", "--columns=name"])
        if age > 86400 and "flathub" in remotes:
            try:
                subprocess.run(["flatpak", "update", "--user", "--appstream", "flathub"],
                               capture_output=True, timeout=1800)
            except (OSError, subprocess.SubprocessError):
                return
        if catalog.needs_rebuild():
            catalog.build()
            idle(self._reload_catalog)

    def _reload_catalog(self):
        self.catalog = catalog.Catalog()
        if hasattr(self, "grid"):
            self.show_section(self.current_section)
            self.toast(_("Catalog updated: {count} apps").format(count=self.catalog.count()))

    def _ready(self, state):
        self.state = state
        self.catalog = catalog.Catalog()
        if not self.catalog.count():
            self.status.set_title(_("The catalog is empty"))
            self.status.set_description(
                _("No sources found. Install archlinux-appstream-data for the Arch repositories "
                  "and/or flatpak for Flathub, then start whoohub again."))
            self.status.set_child(None)
            return
        self._build_main()

    # ── main page ──────────────────────────────────────────────────────────────────────────────────────
    def _build_main(self):
        self.views = Adw.ViewStack()
        self.views.add_titled_with_icon(self._browse_page(), "browse", _("Explore"), "view-grid-symbolic")
        self.views.add_titled_with_icon(self._installed_page(), "installed", _("Installed"), "emblem-ok-symbolic")
        self.views.connect("notify::visible-child-name", self._on_view)

        self.outer = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.outer.add_named(self.views, "views")
        self.outer.add_named(self._search_page(), "search")

        header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.search = Gtk.SearchEntry(placeholder_text=_("Search apps…"), width_request=300)
        self.search.connect("search-changed", self._on_search)
        self.search.set_key_capture_widget(self)
        header.pack_start(self.search)
        menu = Gio.Menu()
        menu.append(_("Rebuild catalog"), "app.rebuild")
        menu.append(_("About whoohub"), "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        tv = Adw.ToolbarView(content=self.outer)
        tv.add_top_bar(header)
        self.nav.add(Adw.NavigationPage(child=tv, title="whoohub", tag="main"))
        self.toasts.set_child(self.nav)
        self.show_section("featured")
        # debugging aids: WHOOHUB_OPEN=<app id>, WHOOHUB_SEARCH=<text>, WHOOHUB_VIEW=installed
        if os.environ.get("WHOOHUB_SEARCH"):
            self.search.set_text(os.environ["WHOOHUB_SEARCH"])
        elif os.environ.get("WHOOHUB_OPEN"):
            self.open_app(os.environ["WHOOHUB_OPEN"])
        elif os.environ.get("WHOOHUB_VIEW"):
            self.views.set_visible_child_name(os.environ["WHOOHUB_VIEW"])

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    # ── explore ────────────────────────────────────────────────────────────────────────────────────────
    def _browse_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=14, margin_start=18, margin_end=18)
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12, row_spacing=6,
                            column_spacing=6)
        self.chips, first = {}, None
        for sid, icon, title, _cats in catalog.SECTIONS:
            b = Gtk.ToggleButton(label=f"{icon}  {_(title)}", css_classes=["chip"])
            if first:
                b.set_group(first)
            first = first or b
            b.connect("toggled", lambda b, sid=sid: b.get_active() and self.show_section(sid))
            chips.append(b)
            self.chips[sid] = b
        box.append(chips)
        self.section_title = Gtk.Label(css_classes=["title-2"], xalign=0, margin_top=6)
        box.append(self.section_title)
        self.grid = tile_grid()
        self.browse_scroll = Gtk.ScrolledWindow(child=self.grid, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        box.append(self.browse_scroll)
        return box

    def show_section(self, sid):
        self.current_section = sid
        if not self.chips[sid].get_active():
            self.chips[sid].set_active(True)  # re-enters through "toggled"
            return
        sec = next(s for s in catalog.SECTIONS if s[0] == sid)
        apps = self.catalog.section(sid)
        self.section_title.set_label(f"{sec[1]}  {_(sec[2])}" + (f"  ·  {len(apps)}" if sid != "featured" else ""))
        self._fill(self.grid, apps)
        self.browse_scroll.get_vadjustment().set_value(0)

    def _fill(self, grid, apps):
        clear(grid)
        for a in apps:
            grid.append(self._app_tile(a))

    def _app_tile(self, a):
        badges, seen = [], set()
        for s in a["sources"]:
            if s["type"] not in seen:
                seen.add(s["type"])
                badges.append(badge(source_info(s["type"])[1]))
        if any(backends.is_installed(self.state, s) for s in a["sources"]):
            badges.append(badge("✓ " + _("installed"), "inst"))
        return tile(a["name"], a["summary"], a["icon"], badges, lambda: self.open_app(a["key"]))

    # ── search ─────────────────────────────────────────────────────────────────────────────────────────
    def _search_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_start=18, margin_end=18)
        self.search_title = Gtk.Label(css_classes=["title-2"], xalign=0)
        box.append(self.search_title)
        self.search_grid = tile_grid()
        box.append(self.search_grid)
        self.aur_title = Gtk.Label(label="📦  " + _("More in the AUR"), css_classes=["title-2"], xalign=0,
                                   visible=False)
        box.append(self.aur_title)
        self.aur_note = Gtk.Label(label=_("Community packages: built on your computer from the packager's script."),
                                  css_classes=["dim-label"], xalign=0, visible=False)
        box.append(self.aur_note)
        self.aur_grid = tile_grid()
        box.append(self.aur_grid)
        self.search_scroll = Gtk.ScrolledWindow(child=box, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._search_seq = 0
        self._search_timer = None
        return self.search_scroll

    def _on_search(self, entry):
        text = entry.get_text().strip()
        if self.nav.get_visible_page().get_tag() != "main":
            self.nav.pop_to_tag("main")
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = None
        self._search_seq += 1
        if not text:
            self.outer.set_visible_child_name("views")
            return
        self.outer.set_visible_child_name("search")
        res = self.catalog.search(text)
        self.search_title.set_label(f"🔎  “{text}”  ·  {len(res)}" if res
                                    else "🔎  " + _("Nothing found for “{text}” in the catalog").format(text=text))
        self._fill(self.search_grid, res)
        self.search_scroll.get_vadjustment().set_value(0)
        clear(self.aur_grid)
        self.aur_title.set_visible(False)
        self.aur_note.set_visible(False)
        if len(text) >= 3:
            self._search_timer = GLib.timeout_add(500, self._aur_search, text, self._search_seq)

    def _aur_search(self, text, seq):
        self._search_timer = None

        def work():
            try:
                res = backends.aur_search(text)
            except (OSError, ValueError):
                res = []
            idle(self._aur_results, res, seq)
        threading.Thread(target=work, daemon=True).start()
        return False

    def _aur_results(self, res, seq):
        if seq != self._search_seq or not res:
            return
        self.aur_title.set_visible(True)
        self.aur_note.set_visible(True)
        for p in res:
            badges = [badge("AUR"), badge(f"♥ {p.get('NumVotes', 0)}", "votes")]
            if p["Name"] in self.state["pacman"]:
                badges.append(badge("✓ " + _("installed"), "inst"))
            if p.get("OutOfDate"):
                badges.append(badge(_("out of date"), "AUR"))
            self.aur_grid.append(tile(p["Name"], p.get("Description"), None, badges,
                                      lambda p=p: self.open_aur(p), icon_name="package-x-generic"))

    # ── installed ──────────────────────────────────────────────────────────────────────────────────────
    def _installed_page(self):
        self.inst_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE,
                                     valign=Gtk.Align.START)
        clamp = Adw.Clamp(child=self.inst_list, maximum_size=900, margin_top=18, margin_bottom=18,
                          margin_start=12, margin_end=12)
        return Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER)

    def _on_view(self, *_a):
        if self.views.get_visible_child_name() == "installed":
            self.refresh_installed()

    def refresh_installed(self):
        clear(self.inst_list)
        st = self.state
        rows, seen_pkgs = [], set()
        for stype, refs in (("flatpak", set(st["flatpak"])), ("pacman", set(st["pacman"]))):
            for a in self.catalog.by_refs(stype, refs):
                src = next(s for s in a["sources"] if s["type"] == stype and s["ref"] in refs)
                seen_pkgs.add(src["ref"])
                rows.append((a, src))
        for key, info in st["appimage"].items():
            a = self.catalog.get(key) or {"key": key, "name": info.get("name", key), "summary": "",
                                          "icon": info.get("icon", ""), "sources": []}
            rows.append((a, {"type": "appimage", "ref": info.get("repo", ""), "version": info.get("version", "")}))
        for pkg in sorted(st["foreign"] - seen_pkgs):
            rows.append(({"key": "aur:" + pkg, "name": pkg, "icon": "", "sources": [],
                          "summary": _("Not from the repositories (AUR or built by hand)")},
                         {"type": "aur", "ref": pkg, "version": st["pacman"].get(pkg, "")}))
        rows.sort(key=lambda r: r[0]["name"].lower())
        if not rows:
            self.inst_list.append(Gtk.Label(label=_("Nothing from the catalog is installed yet"),
                                            margin_top=30, margin_bottom=30))
        for a, src in rows:
            row = Adw.ActionRow(title=GLib.markup_escape_text(a["name"]),
                                subtitle=GLib.markup_escape_text(a.get("summary") or ""), subtitle_lines=1)
            img = Gtk.Image(pixel_size=40)
            load_image(img, a.get("icon"))
            row.add_prefix(img)
            ver = src.get("version") or (st["pacman"].get(src["ref"], "") if src["type"] in ("pacman", "aur") else "")
            row.add_suffix(badge(source_info(src["type"])[1]))
            if ver:
                row.add_suffix(Gtk.Label(label=ver, css_classes=["dim-label"]))
            if not a["key"].startswith("aur:"):
                row.set_activatable(True)
                row.connect("activated", lambda *_a, k=a["key"]: self.open_app(k))
                row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            else:
                rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                tooltip_text=_("Remove"))
                rm.connect("clicked", lambda *_a, p=src["ref"]: self.confirm_remove(p, backends.pacman_remove(p), None))
                row.add_suffix(rm)
            self.inst_list.append(row)

    def confirm_remove(self, name, steps, jobui, detail=None):
        d = Adw.AlertDialog(heading=_("Remove {name}?").format(name=name),
                            body=detail or _("The app and the dependencies nothing else needs will be removed."))
        d.add_response("cancel", _("Cancel"))
        d.add_response("rm", _("Remove"))
        d.set_response_appearance("rm", Adw.ResponseAppearance.DESTRUCTIVE)

        def resp(_d, r):
            if r == "rm":
                self.run_job(steps, jobui, done=lambda ok, m: self.views.get_visible_child_name() == "installed"
                             and self.refresh_installed())
        d.connect("response", resp)
        d.present(self)

    # ── running installs/removals ──────────────────────────────────────────────────────────────────────
    def run_job(self, steps, ui, done=None):
        """ui is the JobUI of an app page (progress + log), or None."""
        if ui:
            ui.begin()

        def on_line(line):
            if ui:
                idle(ui.log, line)

        def on_done(ok, msg):
            state = backends.installed_state()

            def fin():
                self.state = state
                if ui:
                    ui.end(ok, msg)
                self.toast(("✅ " if ok else "⚠️ ") + msg)
                if done:
                    done(ok, msg)
            idle(fin)
        job = backends.Job(steps, on_line, on_done)
        if ui:
            ui.job = job
        job.start()

    # ── app pages ──────────────────────────────────────────────────────────────────────────────────────
    def open_app(self, key):
        a = self.catalog.get(key)
        if a:
            self.nav.push(AppPage(self, a))

    def open_aur(self, p):
        self.nav.push(AurPage(self, p))


class JobUI(Gtk.Box):
    """Progress, status and log of an install on an app page."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False)
        top = Gtk.Box(spacing=10)
        self.bar = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
        top.append(self.bar)
        self.cancel = Gtk.Button(label=_("Cancel"), css_classes=["flat"])
        self.cancel.connect("clicked", lambda *_a: self.job and self.job.cancel())
        top.append(self.cancel)
        self.append(top)
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label"], wrap=True)
        self.append(self.status)
        self.buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self.buf, editable=False, monospace=True, css_classes=["log", "card"],
                          wrap_mode=Gtk.WrapMode.CHAR)
        self.tv_scroll = Gtk.ScrolledWindow(child=tv, min_content_height=160, max_content_height=260)
        self.exp = Gtk.Expander(label=_("Details"), child=self.tv_scroll)
        self.append(self.exp)
        self.job, self._pulse, self.on_end = None, None, None

    @property
    def busy(self):
        return self._pulse is not None

    def begin(self):
        self.set_visible(True)
        self.buf.set_text("")
        self.bar.set_fraction(0)
        self.status.set_label(_("Working… (a password prompt, if any, comes from polkit)"))
        self.cancel.set_visible(True)
        self._pulse = GLib.timeout_add(150, lambda: (self.bar.pulse(), True)[1])

    def log(self, line):
        self.buf.insert(self.buf.get_end_iter(), line + "\n")
        if line.strip() and not line.startswith("$"):
            self.status.set_label(line.strip()[:160])
        adj = self.tv_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) and False)

    def end(self, ok, msg):
        if self._pulse:
            GLib.source_remove(self._pulse)
            self._pulse = None
        self.bar.set_fraction(1.0 if ok else 0.0)
        self.cancel.set_visible(False)
        self.status.set_label(("✅ " if ok else "⚠️ ") + msg)
        if not ok:
            self.exp.set_expanded(True)
        if self.on_end:
            self.on_end(ok)


def page_scaffold(page, body):
    clamp = Adw.Clamp(child=body, maximum_size=920, margin_start=18, margin_end=18)
    tv = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER))
    tv.add_top_bar(Adw.HeaderBar())
    page.set_child(tv)


class AppPage(Adw.NavigationPage):
    def __init__(self, win, a):
        super().__init__(title=a["name"], tag="app:" + a["key"])
        self.win, self.a = win, a
        self.sources = sorted(a["sources"], key=lambda s: SOURCE_ORDER.index(s["type"]))
        inst = [i for i, s in enumerate(self.sources) if backends.is_installed(win.state, s)]
        self.sel = inst[0] if inst else 0

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=30)
        head = Gtk.Box(spacing=20)
        img = Gtk.Image(pixel_size=96, valign=Gtk.Align.START)
        load_image(img, a["icon"])
        head.append(img)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
        info.append(Gtk.Label(label=a["name"], css_classes=["app-name"], xalign=0, wrap=True))
        if a["developer"]:
            info.append(Gtk.Label(label=a["developer"], css_classes=["dim-label"], xalign=0))
        if a["summary"]:
            info.append(Gtk.Label(label=a["summary"], xalign=0, wrap=True))
        head.append(info)
        body.append(head)

        # source picker + buttons
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=14,
                        margin_start=16, margin_end=16)
        row = Gtk.Box(spacing=10)
        self.dd = Gtk.DropDown(model=Gtk.StringList.new(self._source_labels()), selected=self.sel,
                               valign=Gtk.Align.CENTER)
        self.dd.connect("notify::selected", self._on_source)
        row.append(Gtk.Label(label=_("Source:"), css_classes=["dim-label"]))
        row.append(self.dd)
        row.append(Gtk.Box(hexpand=True))
        self.btns = Gtk.Box(spacing=8)
        row.append(self.btns)
        inner.append(row)
        self.note = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"])
        inner.append(self.note)
        self.jobui = JobUI()
        self.jobui.on_end = lambda ok: self._refresh_labels()
        inner.append(self.jobui)
        card.append(inner)
        body.append(card)

        if a["screenshots"]:
            car = Adw.Carousel(spacing=12, height_request=380, allow_scroll_wheel=False)
            for url in a["screenshots"]:
                pic = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, css_classes=["shot"], hexpand=True)
                load_image(pic, url)
                car.append(pic)
            body.append(car)
            if len(a["screenshots"]) > 1:
                body.append(Adw.CarouselIndicatorDots(carousel=car))

        if a["description"]:
            body.append(Gtk.Label(label=a["description"], xalign=0, wrap=True, selectable=True))

        facts = Gtk.Box(spacing=18)
        if a["license"]:
            facts.append(Gtk.Label(label=_("License: {license}").format(license=a["license"]),
                                   css_classes=["dim-label"], wrap=True, xalign=0))
        if a["homepage"]:
            facts.append(Gtk.LinkButton(uri=a["homepage"], label=_("Website")))
        body.append(facts)
        page_scaffold(self, body)
        self._update()

    @property
    def src(self):
        return self.sources[self.sel]

    def _source_labels(self):
        labels = []
        for s in self.sources:
            lab = source_info(s["type"])[0]
            if s.get("version"):
                lab += f"  ·  {s['version']}"
            if backends.is_installed(self.win.state, s):
                lab += "  ·  ✓ " + _("installed")
            labels.append(lab)
        return labels

    def _refresh_labels(self):
        sel = self.sel
        self.dd.set_model(Gtk.StringList.new(self._source_labels()))
        self.dd.set_selected(sel)
        self._update()

    def _on_source(self, *_a):
        self.sel = self.dd.get_selected()
        self._update()

    def _update(self):
        clear(self.btns)
        s, busy = self.src, self.jobui.busy
        note = source_info(s["type"])[2]
        if s["type"] == "pacman" and s.get("repo"):
            note += "  " + _("Repository: {repo}, package {pkg}.").format(repo=s["repo"], pkg=s["ref"])
        elif s["type"] == "flatpak":
            note += "  " + _("ID: {id}.").format(id=s["ref"])
        elif s["type"] == "appimage":
            note += "  " + (_("GitHub: {repo}.").format(repo=s["ref"]) if s["ref"] else
                            _("The file is published on the author's website — whoohub opens the download page."))
        self.note.set_label(note)
        if backends.is_installed(self.win.state, s):
            op = Gtk.Button(label=_("Open"), css_classes=["suggested-action", "pill"], sensitive=not busy)
            op.connect("clicked", self._launch)
            rm = Gtk.Button(label=_("Remove"), css_classes=["destructive-action", "pill"], sensitive=not busy)
            rm.connect("clicked", self._remove)
            self.btns.append(op)
            self.btns.append(rm)
        elif s["type"] == "appimage" and not s["ref"]:
            dl = Gtk.Button(label=_("Open download page"), css_classes=["suggested-action", "pill"])
            dl.connect("clicked", lambda *_a: Gtk.UriLauncher(uri=s["download"]).launch(self.win, None, None, None))
            self.btns.append(dl)
        else:
            ins = Gtk.Button(label=_("Install"), css_classes=["suggested-action", "pill"], sensitive=not busy)
            ins.connect("clicked", self._install)
            self.btns.append(ins)
        self.dd.set_sensitive(not busy)

    def _install(self, *_a):
        s, a = self.src, self.a
        if s["type"] == "pacman":
            steps = backends.pacman_install(s["ref"])
        elif s["type"] == "flatpak":
            steps = backends.flatpak_install(s["ref"])
        else:
            steps = backends.appimage_install(a["key"], a["name"], s["ref"],
                                              a["icon"] if a["icon"].startswith("http") else "")
        self.win.run_job(steps, self.jobui)
        self._update()

    def _remove(self, *_a):
        s, a = self.src, self.a
        if s["type"] == "pacman":
            steps = backends.pacman_remove(s["ref"])
        elif s["type"] == "flatpak":
            steps = backends.flatpak_remove(s["ref"], self.win.state["flatpak"].get(s["ref"], "user"))
        else:
            key = next((k for k, v in self.win.state["appimage"].items() if v.get("repo") == s["ref"]), a["key"])
            steps = backends.appimage_remove(key)
        self.win.confirm_remove(a["name"], steps, self.jobui,
                                detail=_("Source: {source}").format(source=source_info(s["type"])[0]))
        GLib.idle_add(lambda: self._update() and False)

    def _launch(self, *_a):
        if not backends.launch(self.a["key"], self.src, self.win.state):
            self.win.toast(_("Could not find how to start it — look for the app in your menu"))


class AurPage(Adw.NavigationPage):
    def __init__(self, win, p):
        super().__init__(title=p["Name"], tag="aur:" + p["Name"])
        self.win, self.p = win, p
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=24, margin_bottom=30)
        head = Gtk.Box(spacing=18)
        head.append(Gtk.Image(icon_name="package-x-generic", pixel_size=80, valign=Gtk.Align.START))
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        info.append(Gtk.Label(label=p["Name"], css_classes=["app-name"], xalign=0, wrap=True))
        info.append(Gtk.Label(label=p.get("Description") or "", xalign=0, wrap=True))
        meta = _("Version {version}  ·  ♥ {votes}  ·  maintainer: {maintainer}").format(
            version=p.get("Version"), votes=p.get("NumVotes", 0), maintainer=p.get("Maintainer") or _("none (orphan)"))
        info.append(Gtk.Label(label=meta, css_classes=["dim-label"], xalign=0, wrap=True))
        head.append(info)
        body.append(head)
        warn = "⚠️ " + _("AUR packages are built from a script (PKGBUILD) written by the packager, "
                         "and it runs on your computer.")
        if p.get("OutOfDate"):
            warn += "  " + _("Flagged out of date.")
        if not p.get("Maintainer"):
            warn += "  " + _("The package has no maintainer.")
        body.append(Gtk.Label(label=warn, css_classes=["warning"], xalign=0, wrap=True))
        self.btns = Gtk.Box(spacing=8)
        body.append(self.btns)
        self.jobui = JobUI()
        self.jobui.on_end = lambda ok: self._update()
        body.append(self.jobui)
        if p.get("URL"):
            body.append(Gtk.LinkButton(uri=p["URL"], label=_("Website"), halign=Gtk.Align.START))
        self.pkgbuild_view = Gtk.TextView(editable=False, monospace=True, css_classes=["log", "card"])
        self.pkgbuild_exp = Gtk.Expander(label="PKGBUILD", child=Gtk.ScrolledWindow(child=self.pkgbuild_view,
                                                                                    min_content_height=360))
        self.pkgbuild_exp.connect("notify::expanded", lambda *_a: self._load_pkgbuild())
        body.append(self.pkgbuild_exp)
        self._pkgbuild_loaded = False
        page_scaffold(self, body)
        self._update()

    def _load_pkgbuild(self):
        if self._pkgbuild_loaded or not self.pkgbuild_exp.get_expanded():
            return
        self._pkgbuild_loaded = True
        self.pkgbuild_view.get_buffer().set_text(_("Loading…"))

        def work():
            try:
                txt = backends.aur_pkgbuild(self.p["PackageBase"])
            except OSError as e:
                txt = _("Could not load it: {error}").format(error=e)
                self._pkgbuild_loaded = False
            idle(self.pkgbuild_view.get_buffer().set_text, txt)
        threading.Thread(target=work, daemon=True).start()

    def _update(self):
        clear(self.btns)
        busy, name = self.jobui.busy, self.p["Name"]
        if name in self.win.state["pacman"]:
            rm = Gtk.Button(label=_("Remove"), css_classes=["destructive-action", "pill"], sensitive=not busy)
            rm.connect("clicked", lambda *_a: self.win.confirm_remove(name, backends.pacman_remove(name), self.jobui))
            self.btns.append(rm)
            self.btns.append(Gtk.Label(label=_("Installed: {version}").format(version=self.win.state["pacman"][name]),
                                       css_classes=["dim-label"]))
        else:
            b = Gtk.Button(label=_("Build and install"), css_classes=["suggested-action", "pill"], sensitive=not busy)
            b.connect("clicked", self._confirm)
            self.btns.append(b)
            v = Gtk.Button(label=_("View PKGBUILD"), css_classes=["pill"])
            v.connect("clicked", lambda *_a: self.pkgbuild_exp.set_expanded(True))
            self.btns.append(v)

    def _confirm(self, *_a):
        d = Adw.AlertDialog(heading=_("Build {name}?").format(name=self.p["Name"]),
                            body=_("The build script (PKGBUILD) was written by the packager, not by Arch Linux, "
                                   "and it will run on your computer. If you have not read it yet, do it first."))
        d.add_response("cancel", _("Cancel"))
        d.add_response("view", _("View PKGBUILD"))
        d.add_response("go", _("Build and install"))
        d.set_response_appearance("go", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            if r == "view":
                self.pkgbuild_exp.set_expanded(True)
            elif r == "go":
                self.win.run_job(backends.aur_install(self.p["PackageBase"], self.p["Name"]), self.jobui)
                self._update()
        d.connect("response", resp)
        d.present(self.win)


class StoreApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win = None
        for name, cb in (("rebuild", self._rebuild), ("about", self._about)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

    def do_startup(self):
        Adw.Application.do_startup(self)
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if not self.win:
            self.win = StoreWindow(self)
        self.win.present()

    def _rebuild(self, *_a):
        paths.DB.unlink(missing_ok=True)
        if self.win:
            self.win.destroy()
        self.win = StoreWindow(self)
        self.win.present()

    def _about(self, *_a):
        Adw.AboutDialog(application_name="whoohub", application_icon=APP_ID, version=__version__,
                        developer_name="whooduck-crypto", license_type=Gtk.License.GPL_3_0,
                        website="https://github.com/whooduck-crypto/whoohub",
                        issue_url="https://github.com/whooduck-crypto/whoohub/issues",
                        comments=_("One app store for Arch-based systems: repositories, Flathub, AUR and AppImage.")
                        ).present(self.win)
