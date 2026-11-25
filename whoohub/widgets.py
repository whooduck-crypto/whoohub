# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable widgets: app icons, install buttons, list rows, shelves, the home banner, progress.

The look follows familiar phone stores (App Store, Google Play): big icons, one obvious button per app,
horizontal shelves on the home page, no packaging jargon in lists.
"""
import hashlib
import threading
import urllib.request
import weakref
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from . import backends, catalog, paths  # noqa: E402
from .i18n import _  # noqa: E402

SOURCE_ORDER = ["pacman", "flatpak", "appimage", "aur"]  # default source preference

CSS = """
/* ── typography ── */
.shelf-title { font-size: 15pt; font-weight: 800; }
.page-title  { font-size: 20pt; font-weight: 800; }
.app-title   { font-size: 24pt; font-weight: 800; }
.developer   { color: var(--accent-color); font-weight: 600; }
.caption-dim { font-size: 9pt; opacity: 0.7; }
.row-name    { font-weight: 700; font-size: 11pt; }
.row-sub     { font-size: 9.5pt; opacity: 0.75; }
.shelf-name  { font-weight: 600; font-size: 10pt; min-height: 36px; }  /* always room for 2 lines */

/* ── buttons ── */
.get-button  { border-radius: 99px; padding: 4px 16px; font-weight: 800; min-width: 88px; }
.big-button  { border-radius: 99px; padding: 10px 28px; font-weight: 800; font-size: 12pt; min-width: 200px; }
.see-all     { font-weight: 700; padding: 2px 10px; }
.shelf-arrow { min-width: 36px; min-height: 36px; padding: 0; border-radius: 99px; }

/* ── home banner ── */
.banner      { border-radius: 20px; }
.banner-shade { background-image: linear-gradient(to right, alpha(black, 0.82) 0%, alpha(black, 0.55) 45%,
                alpha(black, 0.0) 80%); }
.banner-name { color: white; font-size: 24pt; font-weight: 800; }
.banner-sum  { color: alpha(white, 0.85); font-size: 11.5pt; }
.banner-tag  { color: alpha(white, 0.75); font-size: 9pt; font-weight: 800; letter-spacing: 1px; }

/* ── cards and lists ── */
.app-row     { padding: 8px; border-radius: 14px; }
.app-row:hover { background: alpha(currentColor, 0.05); }
.shelf-item  { padding: 6px; border-radius: 14px; }
.shelf-item:hover { background: alpha(currentColor, 0.05); }
.shot        { border-radius: 14px; }
.info-card   { padding: 14px 16px; }
.chip        { border-radius: 99px; padding: 4px 14px; font-weight: 700; }
.chip:checked { background: var(--accent-bg-color); color: var(--accent-fg-color); }
.log         { font-family: monospace; font-size: 8.5pt; padding: 8px; }
.community   { font-size: 8pt; font-weight: 800; padding: 1px 7px; border-radius: 6px;
               color: #e66100; background: alpha(#e66100, 0.15); }
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


def app_icon(app, size):
    img = Gtk.Image(pixel_size=size)
    load_image(img, app.get("icon") if app else None)
    return img


def clear(box):
    c = box.get_first_child()
    while c is not None:
        n = c.get_next_sibling()
        box.remove(c)
        c = n


def section_caption(app):
    _sid, title = catalog.primary_section(app)
    return _(title) if title else ""


def default_source(app, state):
    """The source used by one-click install: an installed one, else the first by SOURCE_ORDER."""
    srcs = sorted(app.get("sources") or [], key=lambda s: SOURCE_ORDER.index(s["type"]))
    inst = [s for s in srcs if backends.is_installed(state, s)]
    return (inst or srcs or [None])[0]


# ── install button ─────────────────────────────────────────────────────────────────────────────────────
class InstallButton(Gtk.Button):
    """The one button every app has: Install → (busy) → Open. Several buttons can show the same app
    (banner, shelf, list, app page); the window keeps them in sync through refresh_all()."""

    _all = weakref.WeakSet()

    def __init__(self, win, app, big=False):
        super().__init__(css_classes=["big-button" if big else "get-button"], valign=Gtk.Align.CENTER)
        self.win, self.app = win, app
        self.box = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.spinner = Adw.Spinner(visible=False)
        self.label = Gtk.Label()
        self.box.append(self.spinner)
        self.box.append(self.label)
        self.set_child(self.box)
        self.connect("clicked", self._clicked)
        InstallButton._all.add(self)
        self.refresh()

    def source(self):
        return default_source(self.app, self.win.state)

    def refresh(self):
        key = self.app["key"]
        src = self.source()
        busy = key in self.win.busy
        self.spinner.set_visible(busy)
        for c in ("suggested-action", "opaque"):
            self.remove_css_class(c)
        if busy:
            self.label.set_label(_("Installing…") if self.win.busy[key] == "install" else _("Removing…"))
            self.set_sensitive(False)
            return
        self.set_sensitive(src is not None)
        if src and backends.is_installed(self.win.state, src):
            self.label.set_label(_("Open"))
        elif src and src["type"] == "appimage" and not src["ref"]:
            self.label.set_label(_("Download"))
            self.add_css_class("suggested-action")
        else:
            self.label.set_label(_("Install"))
            self.add_css_class("suggested-action")

    def _clicked(self, *_a):
        src = self.source()
        if src and backends.is_installed(self.win.state, src):
            self.win.launch(self.app, src)
        elif src and src["type"] == "appimage" and not src["ref"]:
            Gtk.UriLauncher(uri=src.get("download", "")).launch(self.win, None, None, None)
        elif src:
            self.win.install(self.app, src)

    @classmethod
    def refresh_all(cls, key=None):
        for b in list(cls._all):
            if key is None or b.app["key"] == key:
                b.refresh()


# ── list row (category pages, search, my apps) ─────────────────────────────────────────────────────────
def app_row(win, app, subtitle=None, button=True):
    """Icon, name, one-line description, category — and the install button on the right."""
    btn = Gtk.Button(css_classes=["flat", "app-row"], hexpand=True)
    box = Gtk.Box(spacing=12)
    box.append(app_icon(app, 56))
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER, hexpand=True)
    v.append(Gtk.Label(label=app["name"], css_classes=["row-name"], xalign=0, ellipsize=Pango.EllipsizeMode.END,
                       max_width_chars=26))
    # single line, no wrapping: every row has the same height, whatever the description looks like
    summary = " ".join((app.get("summary") or "").split())
    v.append(Gtk.Label(label=summary or " ", css_classes=["row-sub"], xalign=0, ellipsize=Pango.EllipsizeMode.END,
                       max_width_chars=26))  # narrow enough for two columns in a normal window
    cap = subtitle if subtitle is not None else section_caption(app)
    if cap:
        v.append(Gtk.Label(label=cap, css_classes=["caption-dim"], xalign=0, ellipsize=Pango.EllipsizeMode.END))
    box.append(v)
    btn.set_child(box)
    btn.connect("clicked", lambda *_a: win.open_app(app["key"]))
    if not button:
        return btn
    row = Gtk.Box(spacing=8)
    row.append(btn)
    row.append(InstallButton(win, app))
    return row


def row_grid():
    """2–3 columns of rows (wide windows), every cell the same height."""
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=3,
                       min_children_per_line=1, row_spacing=4, column_spacing=18, valign=Gtk.Align.START)


# ── shelves (home page) ────────────────────────────────────────────────────────────────────────────────
def shelf_item(win, app):
    btn = Gtk.Button(css_classes=["flat", "shelf-item"], width_request=128)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    v.append(app_icon(app, 96))
    name = Gtk.Label(label=app["name"], css_classes=["shelf-name"], xalign=0, yalign=0, wrap=True, lines=2,
                     ellipsize=Pango.EllipsizeMode.END, max_width_chars=14, width_chars=14,
                     natural_wrap_mode=Gtk.NaturalWrapMode.WORD)
    v.append(name)
    cap = section_caption(app)
    v.append(Gtk.Label(label=cap or " ", css_classes=["caption-dim"], xalign=0, ellipsize=Pango.EllipsizeMode.END,
                       max_width_chars=14))
    btn.set_child(v)
    btn.connect("clicked", lambda *_a: win.open_app(app["key"]))
    return btn


class Shelf(Gtk.Box):
    """A titled horizontal row of apps with ‹ › arrows (mouse users can't swipe) and a "See all" link."""

    def __init__(self, win, title, apps, on_see_all=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label=title, css_classes=["shelf-title"], xalign=0, hexpand=True))
        if on_see_all:
            b = Gtk.Button(label=_("See all"), css_classes=["flat", "see-all"])
            b.connect("clicked", lambda *_a: on_see_all())
            head.append(b)
        self.append(head)
        row = Gtk.Box(spacing=4)
        for a in apps:
            row.append(shelf_item(win, a))
        # propagate_natural_height: otherwise the row gets its minimum height and two-line names lose
        # their caption
        self.scroll = Gtk.ScrolledWindow(child=row, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                         hscrollbar_policy=Gtk.PolicyType.EXTERNAL, propagate_natural_height=True)
        ov = Gtk.Overlay(child=self.scroll)
        self.prev = self._arrow("go-previous-symbolic", Gtk.Align.START, -1)
        self.next = self._arrow("go-next-symbolic", Gtk.Align.END, 1)
        ov.add_overlay(self.prev)
        ov.add_overlay(self.next)
        self.append(ov)
        adj = self.scroll.get_hadjustment()
        for sig in ("value-changed", "changed"):
            adj.connect(sig, lambda *_a: self._arrows())

    def _arrow(self, icon, halign, direction):
        b = Gtk.Button(icon_name=icon, css_classes=["osd", "shelf-arrow"], halign=halign, valign=Gtk.Align.CENTER,
                       margin_start=4, margin_end=4, visible=False)
        b.connect("clicked", lambda *_a: self._page(direction))
        return b

    def _page(self, direction):
        adj = self.scroll.get_hadjustment()
        target = min(max(adj.get_value() + direction * adj.get_page_size() * 0.85, adj.get_lower()),
                     adj.get_upper() - adj.get_page_size())
        start, t0 = adj.get_value(), GLib.get_monotonic_time()

        def step(*_a):  # short ease-out animation
            k = min((GLib.get_monotonic_time() - t0) / 250000, 1.0)
            adj.set_value(start + (target - start) * (1 - (1 - k) ** 3))
            return k < 1.0
        GLib.timeout_add(16, step)

    def _arrows(self):
        adj = self.scroll.get_hadjustment()
        self.prev.set_visible(adj.get_value() > adj.get_lower() + 1)
        self.next.set_visible(adj.get_value() + adj.get_page_size() < adj.get_upper() - 1)


# ── home banner ────────────────────────────────────────────────────────────────────────────────────────
class Banner(Gtk.Box):
    """Big rotating cards: screenshot as background, app name, short description, Install."""

    def __init__(self, win, apps):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.carousel = Adw.Carousel(allow_scroll_wheel=False, spacing=12, reveal_duration=0)
        for a in apps:
            self.carousel.append(self._card(win, a))
        self.append(self.carousel)
        if len(apps) > 1:
            self.append(Adw.CarouselIndicatorDots(carousel=self.carousel))
            self._timer = GLib.timeout_add_seconds(7, self._advance)
            self.connect("destroy", lambda *_a: GLib.source_remove(self._timer))

    def _advance(self):
        if not self.get_mapped():
            return True
        n = self.carousel.get_n_pages()
        i = (round(self.carousel.get_position()) + 1) % n
        self.carousel.scroll_to(self.carousel.get_nth_page(i), True)
        return True

    @staticmethod
    def _card(win, app):
        ov = Gtk.Overlay(css_classes=["banner"], height_request=300, hexpand=True, overflow=Gtk.Overflow.HIDDEN)
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, hexpand=True)
        load_image(pic, app["screenshots"][0])
        ov.set_child(pic)
        shade = Gtk.Box(css_classes=["banner-shade"])
        ov.add_overlay(shade)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.END,
                          halign=Gtk.Align.START, margin_start=32, margin_bottom=32, margin_end=32)
        content.append(Gtk.Label(label=_("APP OF THE DAY").upper(), css_classes=["banner-tag"], xalign=0))
        top = Gtk.Box(spacing=14)
        top.append(app_icon(app, 72))
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        names.append(Gtk.Label(label=app["name"], css_classes=["banner-name"], xalign=0))
        names.append(Gtk.Label(label=app["summary"], css_classes=["banner-sum"], xalign=0, wrap=True,
                               max_width_chars=48, lines=2, ellipsize=Pango.EllipsizeMode.END))
        top.append(names)
        content.append(top)
        btns = Gtk.Box(spacing=10, margin_top=6)
        btns.append(InstallButton(win, app))
        more = Gtk.Button(label=_("More"), css_classes=["get-button", "osd"])
        more.connect("clicked", lambda *_a: win.open_app(app["key"]))
        btns.append(more)
        content.append(btns)
        ov.add_overlay(content)
        return ov


# ── progress of an install on the app page ─────────────────────────────────────────────────────────────
class JobUI(Gtk.Box):
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
        else:
            GLib.timeout_add_seconds(4, lambda: self.set_visible(self.busy) or False)
        if self.on_end:
            self.on_end(ok)
