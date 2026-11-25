# SPDX-License-Identifier: GPL-3.0-or-later
"""whoohub main window and application (GTK 4 + libadwaita)."""
import os
import re
import subprocess
import sys
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, __version__, backends, catalog, paths, updates  # noqa: E402
from .i18n import _  # noqa: E402
from .pages import AppPage, AurPage, BrowsePage, MyAppsPage, SearchPage, home_page  # noqa: E402
from .widgets import CSS, InstallButton, JobUI  # noqa: E402


def idle(fn, *a):
    GLib.idle_add(lambda: fn(*a) and False)


def release_notes_text(md):
    """GitHub release notes are Markdown; show them as plain text (bullets kept, markup dropped)."""
    out = []
    for line in md.splitlines():
        line = line.rstrip()
        line = re.sub(r"^\s*[-*+]\s+", "• ", line)          # list items
        line = re.sub(r"^#+\s*", "", line)                   # headings
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)  # [text](url) -> text
        out.append(line.replace("`", ""))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def restart_app():
    """Replace this process with a fresh whoohub (after an update)."""
    if sys.argv[0].endswith("__main__.py"):          # started as `python3 -m whoohub`
        argv = [sys.executable, "-m", "whoohub"]
    else:                                            # the installed launcher script
        argv = [sys.executable, sys.argv[0]]
    os.execv(sys.executable, argv)


class StoreWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="whoohub", default_width=1280, default_height=860)
        self.catalog = None
        self.state = {"pacman": {}, "foreign": set(), "flatpak": {}, "appimage": {}}
        self.busy = {}  # app key -> "install" | "remove" while a job runs
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
            idle(self.toast, _("The catalog was updated — restart whoohub to see the new apps"))

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

    # ── main layout: tabs on top, search always visible ────────────────────────────────────────────────
    def _build_main(self):
        self.views = Adw.ViewStack()
        self.views.add_titled_with_icon(home_page(self), "home", _("Home"), "go-home-symbolic")
        self.games = BrowsePage(self, "games")
        self.views.add_titled_with_icon(self.games, "games", _("Games"), "applications-games-symbolic")
        self.apps = BrowsePage(self, "apps")
        self.views.add_titled_with_icon(self.apps, "apps", _("Apps"), "view-app-grid-symbolic")
        self.mine = MyAppsPage(self)
        # TRANSLATORS: tab with the apps the user has installed (like "Library" in Google Play / Steam); keep it short
        self.views.add_titled_with_icon(self.mine, "mine", _("Library"), "folder-download-symbolic")
        self.views.connect("notify::visible-child-name", self._on_view)

        self.outer = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.outer.add_named(self.views, "views")
        self.search_page = SearchPage(self)
        self.outer.add_named(self.search_page, "search")

        header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.search = Gtk.SearchEntry(placeholder_text=_("Search apps and games"), width_request=260)
        self.search.connect("search-changed", self._on_search)
        self.search.set_key_capture_widget(self)
        header.pack_start(self.search)
        menu = Gio.Menu()
        upd = Gio.Menu()
        upd.append(_("Check for updates"), "app.check-updates")
        upd.append(_("Check for updates automatically"), "app.auto-update")
        menu.append_section(None, upd)
        other = Gio.Menu()
        other.append(_("Rebuild catalog"), "app.rebuild")
        other.append(_("About whoohub"), "app.about")
        menu.append_section(None, other)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        tv = Adw.ToolbarView(content=self.outer)
        tv.add_top_bar(header)
        self.nav.add(Adw.NavigationPage(child=tv, title="whoohub", tag="main"))
        self.toasts.set_child(self.nav)
        # debugging aids: WHOOHUB_OPEN=<app id>, WHOOHUB_SEARCH=<text>, WHOOHUB_VIEW=games|apps|mine
        # (also WHOOHUB_DEV=1 for a separate instance, WHOOHUB_FAKE_VERSION=0.0.1 to test the update dialog)
        if os.environ.get("WHOOHUB_SEARCH"):
            self.search.set_text(os.environ["WHOOHUB_SEARCH"])
        elif os.environ.get("WHOOHUB_OPEN"):
            self.open_app(os.environ["WHOOHUB_OPEN"])
        elif os.environ.get("WHOOHUB_VIEW"):
            self.views.set_visible_child_name(os.environ["WHOOHUB_VIEW"])
        self.check_updates(manual=False)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def show_view(self, view, section=None):
        """Used by the "See all" links of the home shelves."""
        self.search.set_text("")
        self.views.set_visible_child_name(view)
        if view == "apps" and section:
            self.apps.select(section)

    def _on_view(self, *_a):
        if self.views.get_visible_child_name() == "mine":
            self.mine.refresh()

    def _on_search(self, entry):
        text = entry.get_text().strip()
        if self.nav.get_visible_page().get_tag() != "main":
            self.nav.pop_to_tag("main")
        if not text:
            self.outer.set_visible_child_name("views")
            return
        self.outer.set_visible_child_name("search")
        self.search_page.run(text)

    # ── pages ──────────────────────────────────────────────────────────────────────────────────────────
    def open_app(self, key):
        a = self.catalog.get(key)
        if a:
            self.nav.push(AppPage(self, a))

    def open_aur(self, p):
        self.nav.push(AurPage(self, p))

    def _app_pages(self, key):
        page = self.nav.get_visible_page()
        return [page] if isinstance(page, AppPage) and page.app["key"] == key else []

    # ── install / remove / open ────────────────────────────────────────────────────────────────────────
    def install(self, app, src, jobui=None):
        if src["type"] == "pacman":
            steps = backends.pacman_install(src["ref"])
        elif src["type"] == "flatpak":
            steps = backends.flatpak_install(src["ref"])
        elif src["type"] == "appimage":
            steps = backends.appimage_install(app["key"], app["name"], src["ref"],
                                              app["icon"] if app["icon"].startswith("http") else "")
        else:
            return
        pages = self._app_pages(app["key"])
        jobui = jobui or (pages[0].jobui if pages else None)
        if not jobui:
            self.toast(_("Installing {name}…").format(name=app["name"]))
        self._start(app["key"], "install", steps, jobui)

    def remove(self, app, src, jobui=None):
        if src["type"] in ("pacman", "aur"):
            steps = backends.pacman_remove(src["ref"])
        elif src["type"] == "flatpak":
            steps = backends.flatpak_remove(src["ref"], self.state["flatpak"].get(src["ref"], "user"))
        else:
            key = next((k for k, v in self.state["appimage"].items() if v.get("repo") == src["ref"]), app["key"])
            steps = backends.appimage_remove(key)
        d = Adw.AlertDialog(heading=_("Remove {name}?").format(name=app["name"]),
                            body=_("The app and the dependencies nothing else needs will be removed."))
        d.add_response("cancel", _("Cancel"))
        d.add_response("rm", _("Remove"))
        d.set_response_appearance("rm", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "rm" and self._start(app["key"], "remove", steps, jobui))
        d.present(self)

    def remove_pkg(self, pkg, jobui):
        self.remove({"key": "aur:" + pkg, "name": pkg}, {"type": "aur", "ref": pkg}, jobui)

    def launch(self, app, src):
        if not backends.launch(app["key"], src, self.state):
            self.toast(_("Could not find how to start it — look for the app in your menu"))

    def _start(self, key, what, steps, jobui):
        self.busy[key] = what
        InstallButton.refresh_all(key)
        for p in self._app_pages(key):
            p.update()

        def done(ok, msg):
            self.busy.pop(key, None)
            InstallButton.refresh_all(key)
            for p in self._app_pages(key):
                p.refresh_sources()
            if self.views.get_visible_child_name() == "mine":
                self.mine.refresh()
        self.run_job(steps, jobui, done)

    def run_job(self, steps, ui, done=None):
        """ui is a JobUI (progress + log) or None; done(ok, message) runs in the main loop afterwards."""
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

    # ── self-update ────────────────────────────────────────────────────────────────────────────────────
    def check_updates(self, manual):
        def work():
            try:
                info = updates.check(force=manual)
            except (OSError, ValueError):
                if manual:
                    idle(self.toast, _("Could not check for updates — no connection to GitHub?"))
                return
            if info:
                idle(self.offer_update, info)
            elif manual:
                idle(self.toast, _("You have the latest version ({version})").format(version=updates.current_version()))
        threading.Thread(target=work, daemon=True).start()

    def offer_update(self, info):
        can_install, why_not = updates.can_update_in_app(info)
        body = _("You have {current}.").format(current=updates.current_version())
        if why_not:
            body += " " + why_not
        d = Adw.AlertDialog(heading=_("whoohub {version} is available").format(version=info["version"]), body=body)
        notes = release_notes_text(info["notes"])
        if notes:  # left-aligned and scrollable: release notes can be long
            # not selectable: a focused selectable label gets all its text selected
            lab = Gtk.Label(label=notes, xalign=0, wrap=True, css_classes=["body"])
            d.set_extra_child(Gtk.ScrolledWindow(child=lab, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                 propagate_natural_height=True, max_content_height=220))
        d.add_response("later", _("Later"))
        d.add_response("skip", _("Skip this version"))
        if can_install:
            d.add_response("update", _("Update"))
            d.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)
            d.set_default_response("update")
        else:
            d.add_response("open", _("Open release page"))
            d.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)
        d.set_close_response("later")

        def resp(_d, r):
            if r == "skip":
                updates.set_setting("skipped", info["version"])
            elif r == "open":
                Gtk.UriLauncher(uri=info["page"]).launch(self, None, None, None)
            elif r == "update":
                self.run_update(info)
        d.connect("response", resp)
        d.present(self)

    def run_update(self, info):
        dlg = Adw.Dialog(title=_("Updating whoohub"), content_width=520)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                      margin_start=18, margin_end=18)
        jobui = JobUI()
        box.append(jobui)
        restart = Gtk.Button(label=_("Restart whoohub"), css_classes=["suggested-action", "pill"],
                             halign=Gtk.Align.CENTER, visible=False)
        restart.connect("clicked", lambda *_a: restart_app())
        box.append(restart)
        tv = Adw.ToolbarView(content=box)
        tv.add_top_bar(Adw.HeaderBar())
        dlg.set_child(tv)
        jobui.on_end = lambda ok: restart.set_visible(ok)
        dlg.present(self)
        self.run_job(updates.update_steps(info), jobui)


class StoreApp(Adw.Application):
    def __init__(self):
        # WHOOHUB_DEV=1: a separate instance, so a test run does not just raise an already open window
        flags = Gio.ApplicationFlags.NON_UNIQUE if os.environ.get("WHOOHUB_DEV") else Gio.ApplicationFlags.DEFAULT_FLAGS
        super().__init__(application_id=APP_ID, flags=flags)
        self.win = None
        for name, cb in (("rebuild", self._rebuild), ("about", self._about),
                         ("check-updates", lambda *_a: self.win and self.win.check_updates(manual=True))):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
        auto = Gio.SimpleAction.new_stateful("auto-update", None,
                                             GLib.Variant.new_boolean(updates.load_settings()["auto_check"]))
        auto.connect("change-state", self._toggle_auto_update)
        self.add_action(auto)

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

    @staticmethod
    def _toggle_auto_update(action, value):
        action.set_state(value)
        updates.set_setting("auto_check", value.get_boolean())

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
