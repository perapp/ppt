.PHONY: help dist release-assets install uninstall sandbox-image sandbox clean

# We rely on bash features (notably `set -o pipefail`).
SHELL := bash

VERSION ?= $(shell python3 -c 'import re; from pathlib import Path; s=Path("src/ppt/__init__.py").read_text(encoding="utf-8"); m=re.search(r"^__version__\s*=\s*\"([^\"]+)\"", s, re.M); print(m.group(1) if m else "0.0.0")')

# Host platform identifier (Rust-style) as detected by ppt.
HOST_PLATFORM ?= $(shell PYTHONPATH=src python3 -c 'from ppt.__main__ import detect_platform; print(detect_platform().key)')

RUNTIME ?= $(shell if command -v podman >/dev/null 2>&1; then echo podman; elif command -v docker >/dev/null 2>&1; then echo docker; else echo none; fi)
SANDBOX_VOLUME := $(CURDIR):/workspace$(if $(filter podman,$(RUNTIME)),:Z,)

DIST_DIR := dist
DIST_DIR_STAMP := $(DIST_DIR)/.dir.stamp
PYTHON_SOURCES := $(shell find src/ppt -type f -name '*.py' | sort)

# Standard install variables.
DESTDIR ?=
PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib

# Where the bundled runtime (python/ + venv/ + bin/) is installed.
PPT_INSTALL_DIR ?= $(LIBDIR)/ppt

# python-build-standalone pin used for release assets.
PPT_PBS_TAG ?= 20260414
PPT_PBS_CPYTHON ?= 3.12.13
PPT_PBS_FLAVOR ?= install_only_stripped

PPT_DIST_USE_CONTAINER ?= 0

# Default to building only for the current host platform.
# Override with e.g. `make dist PPT_DIST_TARGETS="x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu"`.
PPT_DIST_TARGETS ?= $(HOST_PLATFORM)

DIST_TARBALLS := $(foreach t,$(PPT_DIST_TARGETS),$(DIST_DIR)/ppt-$(VERSION)-$(t).tar.gz)

# System install uses the host-native tarball contents.
INSTALL_TARBALL := $(DIST_DIR)/ppt-$(VERSION)-$(HOST_PLATFORM).tar.gz

# Local dev defaults.
RELEASE_TARBALL := $(DIST_DIR)/ppt-$(VERSION)-x86_64-unknown-linux-gnu.tar.gz
SANDBOX_TARBALL := $(DIST_DIR)/ppt-sandbox-linux.tar.gz
INSTALL_SH := $(DIST_DIR)/install.sh

INSTALL_TEMPLATE := install.sh.template
REPO_URL ?= $(shell \
	if [ -n "$$CI_PROJECT_URL" ]; then \
	  echo "$$CI_PROJECT_URL"; \
	elif [ -n "$$GITHUB_SERVER_URL" ] && [ -n "$$GITHUB_REPOSITORY" ]; then \
	  echo "$$GITHUB_SERVER_URL/$$GITHUB_REPOSITORY"; \
	else \
	  echo "https://gitlab.com/perapp/ppt"; \
	fi)

help:
	@printf '%s\n' \
	  'Targets:' \
	  '  dist            Build dist tarballs + install.sh' \
	  '  release-assets   Build default local Linux tarball + install.sh' \
	  '  install         Install ppt to $(PREFIX) (respects DESTDIR)' \
	  '  uninstall       Remove files installed by `make install`' \
	  '  sandbox          Build assets and start interactive sandbox' \
	  '  clean            Remove dist and sandbox image stamp'

$(DIST_DIR_STAMP):
	@mkdir -p "$(DIST_DIR)"
	@touch "$(DIST_DIR_STAMP)"

$(DIST_DIR)/ppt-$(VERSION)-%.tar.gz: dev/build_dist.py pyproject.toml $(PYTHON_SOURCES) | $(DIST_DIR_STAMP)
	@set -euo pipefail; \
	target="$*"; \
	python3 dev/build_dist.py \
	  --target "$$target" \
	  --version "$(VERSION)" \
	  --pbs-tag "$(PPT_PBS_TAG)" \
	  --cpython "$(PPT_PBS_CPYTHON)" \
	  --flavor "$(PPT_PBS_FLAVOR)" \
	  --out "$@"


$(INSTALL_SH): $(INSTALL_TEMPLATE) dev/render_install_sh.py | $(DIST_DIR_STAMP)
	@python3 dev/render_install_sh.py --template "$(INSTALL_TEMPLATE)" --out "$(INSTALL_SH)" --repo-url "$(REPO_URL)" --version "$(VERSION)"


dist: $(DIST_TARBALLS) $(INSTALL_SH)
	@printf 'Built %s\n' "$(DIST_DIR)"/*.tar.gz
	@printf 'Built %s\n' "$(INSTALL_SH)"

install: $(INSTALL_TARBALL)
	@set -euo pipefail; \
	  dest='$(DESTDIR)$(PPT_INSTALL_DIR)'; \
	  bindir='$(DESTDIR)$(BINDIR)'; \
	  case "$$dest" in ''|'/') printf '%s\n' 'error: refusing to install into empty or / (check PPT_INSTALL_DIR/DESTDIR)' >&2; exit 2;; esac; \
	  tmp=$$(mktemp -d); \
	  trap 'rm -rf "$$tmp"' EXIT; \
	  mkdir -p "$$bindir"; \
	  tar -xzf "$(INSTALL_TARBALL)" -C "$$tmp"; \
	  rm -rf "$$dest"; \
	  mkdir -p "$$dest"; \
	  cp -a "$$tmp/"* "$$dest/"; \
	  link="$$bindir/ppt"; \
	  target='$(PPT_INSTALL_DIR)/bin/ppt'; \
	  rel=$$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], os.path.dirname(sys.argv[2])))' "$$target" '$(BINDIR)/ppt'); \
	  ln -sfn "$$rel" "$$link"; \
	  printf 'Installed %s\n' "$$link"

uninstall:
	@set -euo pipefail; \
	  link='$(DESTDIR)$(BINDIR)/ppt'; \
	  dest='$(DESTDIR)$(PPT_INSTALL_DIR)'; \
	  if [ -L "$$link" ] || [ -f "$$link" ]; then rm -f "$$link"; fi; \
	  case "$$dest" in ''|'/') printf '%s\n' 'error: refusing to uninstall from empty or / (check PPT_INSTALL_DIR/DESTDIR)' >&2; exit 2;; esac; \
	  rm -rf "$$dest"; \
	  printf 'Removed %s and %s\n' "$$link" "$$dest"

release-assets: $(RELEASE_TARBALL) $(INSTALL_SH)
	@cp -f "$(RELEASE_TARBALL)" "$(SANDBOX_TARBALL)"
	@printf 'Built %s\n' "$(RELEASE_TARBALL)"
	@printf 'Updated %s\n' "$(SANDBOX_TARBALL)"
	@printf 'Built %s\n' "$(INSTALL_SH)"

sandbox-image:
	@if [ "$(RUNTIME)" = "none" ]; then \
	  printf '%s\n' 'error: need podman or docker for sandbox' >&2; \
	  exit 2; \
	fi
	@$(RUNTIME) build -f dev/Containerfile.sandbox -t ppt:sandbox .

sandbox: release-assets sandbox-image
	@if [ ! -t 0 ] || [ ! -t 1 ]; then \
	  printf '%s\n' 'error: `make sandbox` is interactive; run it from a real terminal (TTY)' >&2; \
	  exit 2; \
	fi
	@$(RUNTIME) run --rm -it \
	  -v "$(SANDBOX_VOLUME)" \
	  ppt:sandbox

empty-sandbox: release-assets sandbox-image
	@$(RUNTIME) run --rm -it \
	  -v "$(SANDBOX_VOLUME)" \
	  ppt:sandbox bash

clean:
	rm -rf $(DIST_DIR)
