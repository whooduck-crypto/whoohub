<p align="center">
  <img src="data/icons/io.github.whooduck_crypto.Whoohub.svg" width="128" alt="whoohub icon">
</p>

<h1 align="center">whoohub</h1>

<p align="center">
  One app store for Arch-based systems: the official repositories, Flathub, the AUR and AppImage — in one place.
  <br>
  <a href="README.ru.md">Читать по-русски</a>
</p>

<p align="center">
  <img src="docs/screenshot.png" width="800" alt="whoohub: the Explore page">
</p>

## Why

On Arch, software lives in four places, each with its own tool: `pacman`, `flatpak`, an AUR helper and
AppImages downloaded by hand. whoohub searches all of them at once and shows **each app once**, with a
choice of where to install it from — and a plain explanation of how the sources differ.

## Features

- **One card per app.** Firefox from the repositories and from Flathub is a single card with a source
  picker, not two search results.
- **Explore and search** across every source, by category or by name.
- **Repositories (pacman)** — installed through the graphical polkit password prompt, no terminal needed.
- **Flathub** — installed for your user, no password.
- **AUR** — searched online; whoohub shows the PKGBUILD and warns before building, installs missing
  dependencies from the repositories, then builds with `makepkg`.
- **AppImage** — the AppImageHub catalog; whoohub downloads the latest stable release from the author's
  GitHub into `~/Applications` and adds a menu entry.
- **Installed** view with Open and Remove buttons.
- **Update check** — once a day whoohub asks GitHub for its latest release and offers to update; a package install updates itself (download, checksum check, polkit prompt). Turn it off in the menu.
- Follows the system light/dark style (libadwaita). English and Russian; more languages welcome.

## Install

### Ready-made package (recommended)

```sh
sudo pacman -U https://github.com/whooduck-crypto/whoohub/releases/download/v0.1.1/whoohub-0.1.1-1-any.pkg.tar.zst
```

pacman pulls in the dependencies itself. Newer versions are on the
[Releases](https://github.com/whooduck-crypto/whoohub/releases) page.

### Build the package yourself

```sh
git clone https://github.com/whooduck-crypto/whoohub.git
cd whoohub/packaging/aur
makepkg -si
```

An AUR package is planned — AUR registration is closed for now.

### From source

```sh
sudo pacman -S --needed python python-gobject gtk4 libadwaita polkit archlinux-appstream-data gettext
# optional: flatpak (Flathub), git + base-devel (AUR)
git clone https://github.com/whooduck-crypto/whoohub.git
cd whoohub
make run                       # try it from the source tree
sudo make install              # installs into /usr/local
```

You also need a running **polkit agent** (every desktop environment has one; on a bare window manager
start e.g. `polkit-gnome`) — it shows the password prompt for repository installs.

## How it works

| Source | Catalog | Install | Root |
|---|---|---|---|
| Repositories | AppStream data from `archlinux-appstream-data` | `pkexec pacman -S` | polkit prompt |
| Flathub | Flathub AppStream data (per-user remote) | `flatpak install --user` | no |
| AUR | live search through the AUR RPC | `git clone` → `makepkg` → `pkexec pacman -U` | polkit prompt |
| AppImage | [AppImageHub feed](https://appimage.github.io/) | GitHub releases → `~/Applications` | no |

Repository and Flathub apps are merged by their AppStream ID; AppImages by name when the match is unique.
The merged catalog is cached in `~/.cache/whoohub/catalog.sqlite` (SQLite + FTS5) and rebuilt
automatically when a source catalog changes. whoohub never uses `sudo`.

Network: besides the catalogs and the app files you install, whoohub makes one request a day to the GitHub API for its own latest release (no data about you; off via “Check for updates automatically”).

A word on trust: AUR packages and AppImages come from their packagers and authors, not from Arch Linux
or Flathub. whoohub says so on every such page and shows the AUR build script before building.

## Development

```sh
make run                                   # run from the source tree
WHOOHUB_OPEN=org.mozilla.firefox make run  # open an app page directly
WHOOHUB_SEARCH=obs make run                # start with a search
WHOOHUB_VIEW=installed make run            # start on the Installed view
```

The code is plain Python + PyGObject, no build system beyond `make`:

- `whoohub/catalog.py` — reading AppStream / AppImageHub, building and querying the catalog
- `whoohub/backends.py` — install, remove and launch for every source
- `whoohub/ui.py` — the GTK 4 / libadwaita interface
- `po/` — translations (gettext)

### Translating

```sh
make pot                                   # refresh the template after changing strings
msginit -i po/whoohub.pot -o po/de.po -l de   # start a new language
echo de >> po/LINGUAS
msgmerge -U po/ru.po po/whoohub.pot        # update an existing one
```

## License

[GPL-3.0-or-later](LICENSE).
