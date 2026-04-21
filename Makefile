.PHONY: help release-assets sandbox-image sandbox clean

VERSION ?= $(shell python3 -c 'import re; from pathlib import Path; s=Path("src/ppt/__init__.py").read_text(encoding="utf-8"); m=re.search(r"^__version__\s*=\s*\"([^\"]+)\"", s, re.M); print(m.group(1) if m else "0.0.0")')

RUNTIME ?= $(shell if command -v podman >/dev/null 2>&1; then echo podman; elif command -v docker >/dev/null 2>&1; then echo docker; else echo none; fi)
SANDBOX_VOLUME := $(CURDIR):/workspace$(if $(filter podman,$(RUNTIME)),:Z,)

DIST_DIR := dist
RELEASE_TARBALL := $(DIST_DIR)/ppt-$(VERSION)-linux.tar.gz
SANDBOX_TARBALL := $(DIST_DIR)/ppt-sandbox-linux.tar.gz
INSTALL_SH := $(DIST_DIR)/install.sh

INSTALL_TEMPLATE := install.sh.template
REPO_URL ?= $(shell if [ -n "$$CI_PROJECT_URL" ]; then echo "$$CI_PROJECT_URL"; else echo "https://gitlab.com/perapp/ppt"; fi)

help:
	@printf '%s\n' \
	  'Targets:' \
	  '  release-assets   Build dist/ppt-<version>-linux.tar.gz' \
	  '  sandbox          Build assets and start interactive sandbox' \
	  '  clean            Remove dist and sandbox image stamp'

$(DIST_DIR):
	mkdir -p $(DIST_DIR)

$(RELEASE_TARBALL): | $(DIST_DIR)
	@set -euo pipefail; \
	tmp=$$(mktemp -d); \
	trap 'rm -rf "$$tmp"' EXIT; \
	mkdir -p "$$tmp/bin" "$$tmp/src"; \
	cp -R src/ppt "$$tmp/src/ppt"; \
	{ \
	  printf '%s\n' \
	    '#!/usr/bin/env bash' \
	    'set -euo pipefail' \
	    'SCRIPT_PATH="$0"' \
	    'if command -v readlink >/dev/null 2>&1; then' \
	    '  SCRIPT_PATH=$(readlink -f -- "$0" 2>/dev/null || printf "%s" "$0")' \
	    'fi' \
	    'APP_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")/.." && pwd)' \
	    'export PYTHONPATH="$APP_DIR/src${PYTHONPATH:+:$PYTHONPATH}"' \
	    'exec python3 -m ppt "$@"'; \
	} >"$$tmp/bin/ppt"; \
	chmod 0755 "$$tmp/bin/ppt"; \
	tar -C "$$tmp" -czf "$(RELEASE_TARBALL)" bin src

$(INSTALL_SH): $(INSTALL_TEMPLATE) dev/render_install_sh.py | $(DIST_DIR)
	@python3 dev/render_install_sh.py --template "$(INSTALL_TEMPLATE)" --out "$(INSTALL_SH)" --repo-url "$(REPO_URL)" --version "$(VERSION)"

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
