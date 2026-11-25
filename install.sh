#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Install (or update to) the latest whoohub release:
#   curl -fsSL https://raw.githubusercontent.com/whooduck-crypto/whoohub/main/install.sh | sh
#
# Why not `pacman -U <url>`: pacman requires a signature for packages installed straight from a URL
# (RemoteFileSigLevel defaults to SigLevel = Required), and whoohub's packages are not signed. This script
# downloads the package, checks it against the sha256 GitHub publishes for the release asset, and installs
# the local file (LocalFileSigLevel = Optional) — pacman pulls the dependencies from the repositories.
set -eu

REPO="whooduck-crypto/whoohub"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

command -v pacman >/dev/null 2>&1 || die "whoohub is for Arch-based systems (pacman not found)."
command -v curl >/dev/null 2>&1 || die "curl is needed."
command -v python3 >/dev/null 2>&1 || die "python3 is needed (sudo pacman -S python)."
command -v sudo >/dev/null 2>&1 || die "sudo is needed."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

say "Looking for the latest whoohub release"
curl -fsSL -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$REPO/releases/latest" \
    -o "$tmp/release.json" || die "could not reach GitHub."

# tag, file name, download URL and sha256 of the package asset
info=$(python3 - "$tmp/release.json" <<'EOF'
import json, re, sys
rel = json.load(open(sys.argv[1]))
a = next((a for a in rel.get("assets", []) if re.fullmatch(r"whoohub-.+-any\.pkg\.tar\.zst", a["name"])), None)
if not a or not (a.get("digest") or "").startswith("sha256:"):
    sys.exit(1)
print(rel["tag_name"], a["name"], a["browser_download_url"], a["digest"].split(":", 1)[1])
EOF
) || die "the latest release has no package with a published checksum."
set -- $info
tag=$1 name=$2 url=$3 sha=$4
case "$name" in whoohub-*-any.pkg.tar.zst) ;; *) die "unexpected file name: $name" ;; esac

say "Downloading whoohub $tag"
curl -fL --progress-bar -o "$tmp/$name" "$url" || die "download failed."
echo "$sha  $tmp/$name" | sha256sum -c --quiet - || die "checksum mismatch — the download is damaged, nothing was installed."
say "Checksum OK"

say "Installing (sudo will ask for your password)"
if [ -t 0 ]; then
    sudo pacman -U --needed "$tmp/$name"
elif (: </dev/tty) 2>/dev/null; then  # subshell: a failed redirection on ":" would end the whole script
    # piped into sh: pacman's questions must still reach the keyboard
    sudo pacman -U --needed "$tmp/$name" </dev/tty
else
    # no terminal at all (e.g. run from another program): don't wait for answers nobody can give
    sudo pacman -U --needed --noconfirm "$tmp/$name"
fi

say "Done. Start whoohub from your app menu or run: whoohub"
