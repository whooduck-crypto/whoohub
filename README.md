<p align="center">
  <img src="data/icons/io.github.whooduck_crypto.Whoohub.svg" width="128" alt="whoohub icon">
</p>

<h1 align="center">whoohub</h1>

<p align="center">
  <b>One app store for Arch Linux: the official repositories, Flathub, the AUR and AppImage — in one place.</b>
  <br>
  Looks and feels like the store on your phone. Install anything with one button.
</p>

<p align="center">
  <a href="https://github.com/whooduck-crypto/whoohub/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/whooduck-crypto/whoohub?label=release"></a>
  <a href="LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
  <img alt="For Arch-based systems" src="https://img.shields.io/badge/for-Arch%20Linux-1793d1">
  <img alt="GTK 4 + libadwaita" src="https://img.shields.io/badge/GTK%204-libadwaita-4a86cf">
  <br>
  <a href="README.ru.md">Читать по-русски</a>
</p>

<p align="center">
  <img src="docs/screenshots/home.png" width="820" alt="whoohub: the Home page with the app-of-the-day banner and shelves">
</p>

## Why

On Arch, software lives in four places, and each has its own tool: `pacman` for the repositories,
`flatpak` for Flathub, an AUR helper for the AUR, and AppImages you download by hand. If you don't
already know which one has the app you want, finding it is a chore.

whoohub searches all four at once and shows **each app once** — with a big **Install** button that just
works, the way a phone store does. Which source to use is chosen for you (and can be changed on the
app's page, with a plain explanation of the difference).

## Screenshots

| Games | App page | Search (with AUR results) |
|---|---|---|
| <img src="docs/screenshots/games.png" alt="Games tab"> | <img src="docs/screenshots/app.png" alt="App page"> | <img src="docs/screenshots/search.png" alt="Search"> |

## Features

- **Feels like a phone store.** Home with an app-of-the-day banner and shelves (Popular, Games, Create,
  Work, Internet & chat, Handy tools), Games and Apps tabs, a Library of your apps, search at the top.
- **One button per app.** Install / Open right from any list — no need to open the app's page.
- **One page per app.** Firefox from the repositories and from Flathub is one app; *Install from* at the
  bottom of its page lets you pick the source, explained in plain words.
- **Repositories (pacman)** — installed through the graphical polkit password prompt, no terminal needed.
- **Flathub** — installed for your user, no password.
- **AUR** — searched online; whoohub shows the PKGBUILD and warns before building, installs missing
  dependencies from the repositories, then builds with `makepkg`.
- **AppImage** — the AppImageHub catalog; whoohub downloads the latest stable release from the author's
  GitHub into `~/Applications` and adds a menu entry.
- **Updates itself.** Once a day whoohub checks for a new version and offers to update right from the app,
  after verifying the checksum GitHub publishes. You can turn the check off in the menu.
- Follows the system light/dark style. English and Russian — more languages welcome.

## Install

### Quick install (recommended)

```sh
curl -fsSL https://raw.githubusercontent.com/whooduck-crypto/whoohub/main/install.sh | sh
```

The [script](install.sh) downloads the latest release package, checks it against the checksum GitHub
publishes and installs it with pacman (sudo asks for your password; pacman pulls in the dependencies).
Feel free to read it first. Later updates come from inside whoohub.

### Manually

Download `whoohub-…-any.pkg.tar.zst` from [Releases](https://github.com/whooduck-crypto/whoohub/releases), then:

```sh
sudo pacman -U ~/Downloads/whoohub-*-any.pkg.tar.zst
```

(`pacman -U <URL>` straight from the web does not work: pacman requires a signature for packages
installed from a URL, and whoohub's packages are not signed.)

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

## How it compares

| | Repositories | Flathub | AUR | AppImage | One page per app |
|---|:-:|:-:|:-:|:-:|:-:|
| **whoohub** | ✓ | ✓ | ✓ | ✓ | ✓ |
| GNOME Software | ✓ | ✓ | — | — | ✓ |
| KDE Discover | ✓ | ✓ | — | — | — |
| pamac (Manjaro) | ✓ | ✓ | ✓ | — | — |

pamac is the closest relative and far more mature — if you are happy with it, keep it. whoohub's angle
is a simpler, phone-store-like interface, AppImages, and showing every app once no matter where it comes
from.

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

## FAQ

**Is it safe?**
Repository packages and Flatpaks come from Arch and Flathub, exactly as with `pacman` and `flatpak`.
AUR packages and AppImages are made by their packagers and authors, not by Arch or Flathub — whoohub
says so on every such page and shows the AUR build script before building. Root access only goes through
the polkit password prompt. Network: besides the catalogs and the files you install, whoohub makes one
request a day to the GitHub API for its own latest release (nothing about you is sent; you can turn it
off in the menu).

**Does it work on EndeavourOS, CachyOS, Garuda, Manjaro…?**
It is made for Arch and Arch-based systems. Manjaro has its own repositories, which lag behind Arch, and
the Manjaro team does not recommend the AUR — whoohub should still start there, but that is untested.

**Ubuntu, Fedora, openSUSE?**
Not yet. The Flathub and AppImage parts would work anywhere; distribution packages would need a
PackageKit backend. Contributions welcome.

**Why no ratings and download counts?**
None of the sources publishes them in a usable form (yet).

**Who made it?**
whoohub is a hobby project by [whooduck-crypto](https://github.com/whooduck-crypto). Most of the code
was written together with Claude, an AI assistant by Anthropic — commits say so with a `Co-Authored-By`
line. Bug reports are very welcome.

## Roadmap

- Updates for installed apps, not just for whoohub itself
- AUR packages that depend on other AUR packages
- An AUR package of whoohub (as soon as AUR registration reopens)
- Flathub + AppImage on non-Arch distributions
- More languages

## Contributing

Bug reports and ideas: [Issues](https://github.com/whooduck-crypto/whoohub/issues). Code, translations and
packaging: see [CONTRIBUTING.md](CONTRIBUTING.md).

## Development

```sh
make run                                   # run from the source tree
WHOOHUB_OPEN=org.mozilla.firefox make run  # open an app page directly
WHOOHUB_SEARCH=obs make run                # start with a search
WHOOHUB_VIEW=games make run                # start on a tab: games, apps, mine
WHOOHUB_DEV=1 make run                     # a separate instance next to an open whoohub
```

The code is plain Python + PyGObject, no build system beyond `make`:

- `whoohub/catalog.py` — reading AppStream / AppImageHub, building and querying the catalog
- `whoohub/backends.py` — install, remove and launch for every source
- `whoohub/ui.py` — the main window: tabs, search, install/remove, self-update
- `whoohub/pages.py`, `whoohub/widgets.py` — the pages and the widgets they are built from
- `whoohub/updates.py` — checking for and installing new whoohub releases
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
