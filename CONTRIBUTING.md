# Contributing to whoohub

Thanks for helping! Bug reports, ideas, translations and code are all welcome.
Русскоязычные сообщения тоже приветствуются — пиши как удобно.

## Reporting a bug

Open an [issue](https://github.com/whooduck-crypto/whoohub/issues/new/choose) and include:

- your distribution (Arch, EndeavourOS, CachyOS, …) and desktop or window manager;
- the whoohub version (menu → About whoohub);
- what you did, what you expected and what happened;
- for a failed install: the text under **Details** on the app page;
- if whoohub crashed: run `whoohub` from a terminal and copy what it printed.

## Translating

whoohub uses gettext; the English strings are the source.

```sh
make pot                                       # refresh po/whoohub.pot
msginit -i po/whoohub.pot -o po/de.po -l de    # start a new language (de = German, …)
echo de >> po/LINGUAS
# translate po/de.po in any PO editor (Poedit, Lokalize, a text editor)
make && LANG=de_DE.UTF-8 make run              # check it
```

Keep tab labels short (they share the header with the search field) and keep `{placeholders}` as they are.

## Code

- Plain Python 3 + PyGObject (GTK 4, libadwaita); no build system beyond `make`.
- `make run` runs from the source tree; `WHOOHUB_DEV=1` starts a separate instance next to an open
  whoohub; `WHOOHUB_OPEN`, `WHOOHUB_SEARCH`, `WHOOHUB_VIEW` jump straight to a page (see README).
- Every user-visible string goes through `_()`; run `make pot` after changing strings.
- whoohub never uses `sudo`: anything that needs root goes through `pkexec` (the polkit prompt).
- Downloads that get installed must be verified (see `updates.py`, `install.sh`).
- Keep pull requests focused on one change and describe how you tested it.

## Releases (maintainer notes)

1. Bump `__version__` in `whoohub/__init__.py`, add a `<release>` to the metainfo file, set `pkgver` in
   `packaging/aur/PKGBUILD`.
2. Commit, tag `vX.Y.Z`, push, create the GitHub release.
3. Build the package from the tag's tarball (`makepkg` in `packaging/aur` after `updpkgsums`), create the
   source archive with `git archive --prefix=whoohub-X.Y.Z/ vX.Y.Z | gzip`, attach **both** to the release
   (installed copies update themselves from them), commit the new checksum and `.SRCINFO`.

## License

By contributing you agree that your work is released under [GPL-3.0-or-later](LICENSE).
