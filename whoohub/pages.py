# SPDX-License-Identifier: GPL-3.0-or-later
"""The pages of the store: Home, Games, Apps, Search, My apps, an app's page and an AUR package's page."""
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import backends, catalog  # noqa: E402
from .backends import source_info  # noqa: E402
from .i18n import _  # noqa: E402
from .widgets import (SOURCE_ORDER, Banner, InstallButton, JobUI, Shelf, app_icon, app_row,  # noqa: E402
                      clear, load_image, row_grid, section_caption)


def scroll_page(child, width=1200):
    clamp = Adw.Clamp(child=child, maximum_size=width, margin_start=20, margin_end=20)
    sw = Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    sw.get_child().set_scroll_to_focus(False)  # pages open at the top, whatever takes the focus
    return sw


def short_text(text, limit=350):
    """The first paragraphs of a description, up to about limit characters, ending with "…" if cut."""
    out = ""
    for para in text.split("\n"):
        if out and len(out) + len(para) > limit:
            return out.rstrip() + " …"
        out += para + "\n"
        if len(out) > limit:
            cut = out[:limit].rsplit(" ", 1)[0]
            return cut.rstrip(" ,.;:") + "…"
    return out.rstrip()


def idle(fn, *a):
    GLib.idle_add(lambda: fn(*a) and False)


# ── Home ───────────────────────────────────────────────────────────────────────────────────────────────
# where "See all" of a shelf leads: (view, section)
SEE_ALL = {"popular": ("apps", "featured"), "games": ("games", None), "create": ("apps", "graphics"),
           "work": ("apps", "office"), "social": ("apps", "network"), "tools": ("apps", "utility")}


def home_page(win):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30, margin_top=20, margin_bottom=30)
    banner = win.catalog.banner()
    if banner:
        box.append(Banner(win, banner))
    for sid, title, _section, _curated in catalog.SHELVES:
        apps = win.catalog.shelf(sid)
        if apps:
            view, section = SEE_ALL[sid]
            box.append(Shelf(win, _(title), apps, on_see_all=lambda v=view, s=section: win.show_view(v, s)))
    return scroll_page(box)


# ── Games / Apps ───────────────────────────────────────────────────────────────────────────────────────
class BrowsePage(Gtk.Box):
    """Games: popular games + all games. Apps: category chips + the apps of the chosen category."""

    def __init__(self, win, kind):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win, self.kind = win, kind
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_top=20, margin_bottom=30)
        self.chips = {}
        if kind == "games":
            games = win.catalog.shelf("games")
            box.append(Shelf(win, _("Popular games"), games))
            box.append(Gtk.Label(label=_("All games"), css_classes=["shelf-title"], xalign=0, margin_top=8))
        else:
            chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12,
                                row_spacing=6, column_spacing=6)
            first = None
            for sid, icon, title, _cats in catalog.SECTIONS:
                if sid == "game":
                    continue
                b = Gtk.ToggleButton(label=f"{icon}  {_(title)}", css_classes=["chip"])
                if first:
                    b.set_group(first)
                first = first or b
                b.connect("toggled", lambda b, sid=sid: b.get_active() and self._fill(sid))
                chips.append(b)
                self.chips[sid] = b
            box.append(chips)
            self.title = Gtk.Label(css_classes=["page-title"], xalign=0, margin_top=4)
            box.append(self.title)
        self.grid = row_grid()
        box.append(self.grid)
        self.scroll = scroll_page(box)
        self.append(self.scroll)
        if kind == "games":
            self._fill("game")
        else:
            self.select("featured")

    def select(self, sid):
        if self.kind == "apps" and sid in self.chips:
            if self.chips[sid].get_active():
                self._fill(sid)
            else:
                self.chips[sid].set_active(True)

    def _fill(self, sid):
        apps = self.win.catalog.section(sid)
        if self.kind == "apps":
            sec = next(s for s in catalog.SECTIONS if s[0] == sid)
            self.title.set_label(_(sec[2]))
        clear(self.grid)
        for a in apps:
            self.grid.append(app_row(self.win, a))
        self.scroll.get_vadjustment().set_value(0)


# ── Search ─────────────────────────────────────────────────────────────────────────────────────────────
class SearchPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=20, margin_bottom=30)
        self.title = Gtk.Label(css_classes=["page-title"], xalign=0)
        box.append(self.title)
        self.grid = row_grid()
        box.append(self.grid)
        self.aur_head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=16, visible=False)
        self.aur_head.append(Gtk.Label(label=_("From the community (AUR)"), css_classes=["shelf-title"], xalign=0))
        self.aur_head.append(Gtk.Label(label=_("Built on your computer from the packager's script."),
                                       css_classes=["caption-dim"], xalign=0))
        box.append(self.aur_head)
        self.aur_grid = row_grid()
        box.append(self.aur_grid)
        self.scroll = scroll_page(box)
        self.append(self.scroll)
        self.seq, self.timer = 0, None

    def run(self, text):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        self.seq += 1
        res = self.win.catalog.search(text)
        self.title.set_label(_("Results for “{text}”").format(text=text) if res
                             else _("Nothing found for “{text}”").format(text=text))
        clear(self.grid)
        for a in res:
            self.grid.append(app_row(self.win, a))
        clear(self.aur_grid)
        self.aur_head.set_visible(False)
        self.scroll.get_vadjustment().set_value(0)
        if len(text) >= 3:
            self.timer = GLib.timeout_add(500, self._aur, text, self.seq)

    def _aur(self, text, seq):
        self.timer = None

        def work():
            try:
                res = backends.aur_search(text)
            except (OSError, ValueError):
                res = []
            idle(self._aur_results, res, seq)
        threading.Thread(target=work, daemon=True).start()
        return False

    def _aur_results(self, res, seq):
        if seq != self.seq or not res:
            return
        self.aur_head.set_visible(True)
        for p in res[:24]:
            fake = {"key": "aur:" + p["Name"], "name": p["Name"], "summary": p.get("Description") or "",
                    "icon": "", "categories": [], "sources": []}
            votes = _("♥ {votes} · community package").format(votes=p.get("NumVotes", 0))
            row = app_row(self.win, fake, subtitle=votes, button=False)
            row.connect("clicked", lambda *_a, p=p: self.win.open_aur(p))
            self.aur_grid.append(row)


# ── My apps ────────────────────────────────────────────────────────────────────────────────────────────
class MyAppsPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=20, margin_bottom=30)
        box.append(Gtk.Label(label=_("My apps"), css_classes=["page-title"], xalign=0))
        self.count = Gtk.Label(css_classes=["caption-dim"], xalign=0)
        box.append(self.count)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.append(self.list)
        self.append(scroll_page(box, width=900))

    def refresh(self):
        clear(self.list)
        st, cat = self.win.state, self.win.catalog
        rows, seen = [], set()
        for stype, refs in (("flatpak", set(st["flatpak"])), ("pacman", set(st["pacman"]))):
            for a in cat.by_refs(stype, refs):
                if a["key"] not in seen:
                    seen.add(a["key"])
                    src = next(s for s in a["sources"] if s["type"] == stype and s["ref"] in refs)
                    rows.append((a, src))
        for key, info in st["appimage"].items():
            if key in seen:
                continue
            a = cat.get(key) or {"key": key, "name": info.get("name", key), "summary": "", "categories": [],
                                 "icon": info.get("icon", ""), "sources": []}
            rows.append((a, {"type": "appimage", "ref": info.get("repo", ""), "version": info.get("version", "")}))
        known_pkgs = {s["ref"] for _a, s in rows if s["type"] == "pacman"}
        for pkg in sorted(st["foreign"] - known_pkgs):
            rows.append(({"key": "aur:" + pkg, "name": pkg, "icon": "", "categories": [], "sources": [],
                          "summary": _("Community package (AUR) or built by hand")},
                         {"type": "aur", "ref": pkg, "version": st["pacman"].get(pkg, "")}))
        rows.sort(key=lambda r: r[0]["name"].lower())
        self.count.set_label(_("{count} installed").format(count=len(rows)) if rows
                             else _("Nothing installed from the store yet"))
        for a, src in rows:
            line = Gtk.Box(spacing=8)
            ver = src.get("version") or st["pacman"].get(src["ref"], "")
            sub = " · ".join(x for x in (source_info(src["type"])[0], ver) if x)
            row = app_row(self.win, a, subtitle=sub, button=False)
            line.append(row)
            if not a["key"].startswith("aur:"):
                op = Gtk.Button(label=_("Open"), css_classes=["get-button"], valign=Gtk.Align.CENTER)
                op.connect("clicked", lambda *_a, a=a, s=src: self.win.launch(a, s))
                line.append(op)
            rm = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "circular"], valign=Gtk.Align.CENTER,
                            tooltip_text=_("Remove"))
            rm.connect("clicked", lambda *_a, a=a, s=src: self.win.remove(a, s))
            line.append(rm)
            self.list.append(line)


# ── an app's page ──────────────────────────────────────────────────────────────────────────────────────
class PageInstallButton(InstallButton):
    """The big button on an app page: installs from the source chosen on that page."""

    def __init__(self, win, app, page):
        self.page = page
        super().__init__(win, app, big=True)

    def source(self):
        return self.page.src


def info_row(title, value_widget):
    row = Gtk.Box(spacing=12)
    row.append(Gtk.Label(label=title, css_classes=["dim-label"], xalign=0, width_chars=14))
    row.append(value_widget)
    return row


class AppPage(Adw.NavigationPage):
    def __init__(self, win, app):
        super().__init__(title=app["name"], tag="app:" + app["key"])
        self.win, self.app = win, app
        self.sources = sorted(app["sources"], key=lambda s: SOURCE_ORDER.index(s["type"]))
        inst = [i for i, s in enumerate(self.sources) if backends.is_installed(win.state, s)]
        self.sel = inst[0] if inst else 0

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=26, margin_top=24, margin_bottom=40)

        # header: icon, name, developer, category; the main button
        head = Gtk.Box(spacing=24)
        head.append(app_icon(app, 128))
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        info.append(Gtk.Label(label=app["name"], css_classes=["app-title"], xalign=0, wrap=True))
        if app["developer"]:
            info.append(Gtk.Label(label=app["developer"], css_classes=["developer"], xalign=0))
        cap = section_caption(app)
        if cap:
            info.append(Gtk.Label(label=cap, css_classes=["caption-dim"], xalign=0))
        self.actions = Gtk.Box(spacing=10, margin_top=12)
        self.main_btn = PageInstallButton(win, app, self)
        self.actions.append(self.main_btn)
        self.remove_btn = Gtk.Button(label=_("Remove"), css_classes=["big-button", "flat"], valign=Gtk.Align.CENTER)
        self.remove_btn.connect("clicked", lambda *_a: win.remove(app, self.src, self.jobui))
        self.actions.append(self.remove_btn)
        info.append(self.actions)
        head.append(info)
        body.append(head)
        self.jobui = JobUI()
        body.append(self.jobui)

        if app["summary"]:
            body.append(Gtk.Label(label=app["summary"], css_classes=["title-4"], xalign=0, wrap=True))

        # screenshots: a horizontal strip, like on a phone store
        if app["screenshots"]:
            strip = Gtk.Box(spacing=12)
            for url in app["screenshots"]:
                frame = Gtk.Box(css_classes=["card", "shot"], overflow=Gtk.Overflow.HIDDEN)
                pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, width_request=480, height_request=290)
                load_image(pic, url)
                frame.append(pic)
                strip.append(frame)
            body.append(Gtk.ScrolledWindow(child=strip, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                           hscrollbar_policy=Gtk.PolicyType.AUTOMATIC))

        # about: a few lines, expandable
        if app["description"]:
            about = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            about.append(Gtk.Label(label=_("About this app"), css_classes=["shelf-title"], xalign=0))
            # collapsed = a short excerpt cut by hand: "lines" can't limit text that has its own paragraphs.
            # Not selectable: a selectable label takes the focus and the page scrolls down to it.
            self.desc_full = app["description"]
            self.desc_short = short_text(self.desc_full)
            self.desc = Gtk.Label(label=self.desc_short, xalign=0, wrap=True)
            about.append(self.desc)
            if self.desc_short != self.desc_full:
                more = Gtk.Button(label=_("Read more"), css_classes=["flat", "see-all"], halign=Gtk.Align.START)
                more.connect("clicked", self._toggle_desc)
                about.append(more)
            body.append(about)

        # where to install from — quiet, at the bottom
        src_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        src_box.append(Gtk.Label(label=_("Install from"), css_classes=["shelf-title"], xalign=0))
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "info-card"])
        self.dd = Gtk.DropDown(model=Gtk.StringList.new(self._source_labels()), selected=self.sel,
                               halign=Gtk.Align.START)
        self.dd.connect("notify::selected", self._on_source)
        card.append(self.dd)
        self.note = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        card.append(self.note)
        src_box.append(card)
        if len(self.sources) == 1:
            self.dd.set_sensitive(False)
        body.append(src_box)

        # facts
        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        facts.append(Gtk.Label(label=_("Information"), css_classes=["shelf-title"], xalign=0))
        fcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["card", "info-card"])
        self.version_label = Gtk.Label(xalign=0, selectable=True)
        fcard.append(info_row(_("Version"), self.version_label))
        if app["developer"]:
            fcard.append(info_row(_("Developer"), Gtk.Label(label=app["developer"], xalign=0, wrap=True)))
        if app["license"]:
            fcard.append(info_row(_("License"), Gtk.Label(label=app["license"], xalign=0, wrap=True)))
        if app["homepage"]:
            fcard.append(info_row(_("Website"), Gtk.LinkButton(uri=app["homepage"], label=app["homepage"],
                                                               halign=Gtk.Align.START)))
        facts.append(fcard)
        body.append(facts)

        tv = Adw.ToolbarView(content=scroll_page(body, width=1000))
        tv.add_top_bar(Adw.HeaderBar())
        self.set_child(tv)
        self.update()

    @property
    def src(self):
        return self.sources[self.sel] if self.sources else None

    def _source_labels(self):
        out = []
        for s in self.sources:
            lab = source_info(s["type"])[0]
            if backends.is_installed(self.win.state, s):
                lab += "  ·  ✓ " + _("installed")
            out.append(lab)
        return out

    def _on_source(self, *_a):
        self.sel = self.dd.get_selected()
        self.update()

    def _toggle_desc(self, btn):
        expanded = self.desc.get_label() == self.desc_full
        self.desc.set_label(self.desc_short if expanded else self.desc_full)
        btn.set_label(_("Read more") if expanded else _("Show less"))

    def update(self):
        """Refresh after a source change or an install/removal."""
        s = self.src
        installed = bool(s) and backends.is_installed(self.win.state, s)
        busy = self.app["key"] in self.win.busy
        self.remove_btn.set_visible(installed)
        self.remove_btn.set_sensitive(not busy)
        self.dd.set_sensitive(len(self.sources) > 1 and not busy)
        self.main_btn.refresh()
        if not s:
            return
        note = source_info(s["type"])[2]
        if s["type"] == "appimage" and not s["ref"]:
            note += "  " + _("The file is published on the author's website — whoohub opens the download page.")
        self.note.set_label(note)
        ver = s.get("version") or (self.win.state["pacman"].get(s["ref"], "") if installed and s["type"] == "pacman"
                                   else "")
        self.version_label.set_label(ver or "—")

    def refresh_sources(self):
        sel = self.sel
        self.dd.set_model(Gtk.StringList.new(self._source_labels()))
        self.dd.set_selected(sel)
        self.update()


# ── an AUR package's page ──────────────────────────────────────────────────────────────────────────────
class AurPage(Adw.NavigationPage):
    def __init__(self, win, p):
        super().__init__(title=p["Name"], tag="aur:" + p["Name"])
        self.win, self.p = win, p
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22, margin_top=24, margin_bottom=40)
        head = Gtk.Box(spacing=24)
        head.append(Gtk.Image(icon_name="package-x-generic", pixel_size=128))
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        info.append(Gtk.Label(label=p["Name"], css_classes=["app-title"], xalign=0, wrap=True))
        info.append(Gtk.Label(label=p.get("Maintainer") or _("no maintainer (orphan)"), css_classes=["developer"],
                              xalign=0))
        info.append(Gtk.Label(label=_("Community package (AUR)"), css_classes=["community"], xalign=0,
                              halign=Gtk.Align.START))
        self.btns = Gtk.Box(spacing=10, margin_top=12)
        info.append(self.btns)
        head.append(info)
        body.append(head)
        self.jobui = JobUI()
        self.jobui.on_end = lambda ok: self._update()
        body.append(self.jobui)
        if p.get("Description"):
            body.append(Gtk.Label(label=p["Description"], css_classes=["title-4"], xalign=0, wrap=True))
        warn = "⚠️ " + _("AUR packages are built from a script (PKGBUILD) written by the packager, "
                         "and it runs on your computer.")
        if p.get("OutOfDate"):
            warn += "  " + _("Flagged out of date.")
        body.append(Gtk.Label(label=warn, css_classes=["warning"], xalign=0, wrap=True))

        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["card", "info-card"])
        facts.append(info_row(_("Version"), Gtk.Label(label=p.get("Version") or "—", xalign=0)))
        facts.append(info_row(_("Votes"), Gtk.Label(label=str(p.get("NumVotes", 0)), xalign=0)))
        if p.get("URL"):
            facts.append(info_row(_("Website"), Gtk.LinkButton(uri=p["URL"], label=p["URL"], halign=Gtk.Align.START)))
        body.append(facts)

        self.pkgbuild_view = Gtk.TextView(editable=False, monospace=True, css_classes=["log", "card"])
        self.pkgbuild_exp = Gtk.Expander(label="PKGBUILD", child=Gtk.ScrolledWindow(child=self.pkgbuild_view,
                                                                                    min_content_height=360))
        self.pkgbuild_exp.connect("notify::expanded", lambda *_a: self._load_pkgbuild())
        body.append(self.pkgbuild_exp)
        self._pkgbuild_loaded = False
        tv = Adw.ToolbarView(content=scroll_page(body, width=1000))
        tv.add_top_bar(Adw.HeaderBar())
        self.set_child(tv)
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
            rm = Gtk.Button(label=_("Remove"), css_classes=["big-button"], sensitive=not busy)
            rm.connect("clicked", lambda *_a: self.win.remove_pkg(name, self.jobui))
            self.btns.append(rm)
        else:
            b = Gtk.Button(label=_("Build and install"), css_classes=["big-button", "suggested-action"],
                           sensitive=not busy)
            b.connect("clicked", self._confirm)
            self.btns.append(b)
            v = Gtk.Button(label=_("View PKGBUILD"), css_classes=["big-button", "flat"])
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
