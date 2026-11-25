# SPDX-License-Identifier: GPL-3.0-or-later
import sys


def main():
    from .ui import StoreApp
    return StoreApp().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
