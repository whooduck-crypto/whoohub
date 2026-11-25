# whoohub — build translations, run from the source tree, install.
#   make            compile translations into build/locale
#   make run        run from the source tree
#   make pot        refresh po/whoohub.pot after changing strings (then: msgmerge -U po/<lang>.po po/whoohub.pot)
#   make install    install (PREFIX=/usr/local by default; packagers: DESTDIR=… PREFIX=/usr)
PREFIX  ?= /usr/local
DESTDIR ?=
APP_ID  := io.github.whooduck_crypto.Whoohub
DATADIR := $(PREFIX)/share
PKGDIR  := $(DATADIR)/whoohub
LINGUAS := $(shell cat po/LINGUAS)
MOFILES := $(foreach l,$(LINGUAS),build/locale/$(l)/LC_MESSAGES/whoohub.mo)
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' whoohub/__init__.py)

.PHONY: all run pot install uninstall clean

all: $(MOFILES)

build/locale/%/LC_MESSAGES/whoohub.mo: po/%.po
	@mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

run: all
	python3 -m whoohub

pot:
	xgettext --language=Python --keyword=_ --keyword=N_ --from-code=UTF-8 --add-comments=TRANSLATORS \
		--package-name=whoohub --package-version=$(VERSION) \
		--msgid-bugs-address=https://github.com/whooduck-crypto/whoohub/issues \
		-f po/POTFILES -o po/whoohub.pot

install: all
	install -Dm644 -t $(DESTDIR)$(PKGDIR)/whoohub whoohub/*.py
	python3 -m compileall -q -d $(PKGDIR)/whoohub $(DESTDIR)$(PKGDIR)/whoohub
	install -d $(DESTDIR)$(PREFIX)/bin
	sed 's|@PKGDIR@|$(PKGDIR)|' bin/whoohub.in > $(DESTDIR)$(PREFIX)/bin/whoohub
	chmod 755 $(DESTDIR)$(PREFIX)/bin/whoohub
	install -Dm644 data/$(APP_ID).desktop $(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop
	install -Dm644 data/$(APP_ID).metainfo.xml $(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml
	install -Dm644 data/icons/$(APP_ID).svg $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg
	for l in $(LINGUAS); do \
		install -Dm644 build/locale/$$l/LC_MESSAGES/whoohub.mo $(DESTDIR)$(DATADIR)/locale/$$l/LC_MESSAGES/whoohub.mo; \
	done

uninstall:
	rm -rf $(DESTDIR)$(PKGDIR)
	rm -f $(DESTDIR)$(PREFIX)/bin/whoohub \
		$(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop \
		$(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml \
		$(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg
	for l in $(LINGUAS); do rm -f $(DESTDIR)$(DATADIR)/locale/$$l/LC_MESSAGES/whoohub.mo; done

clean:
	rm -rf build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
