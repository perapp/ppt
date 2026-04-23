.PHONY: help dist dist-image release-assets sandbox-image sandbox clean

# We rely on bash features (notably `set -o pipefail`).
SHELL := bash

VERSION ?= $(shell python3 -c 'import re; from pathlib import Path; s=Path("src/ppt/__init__.py").read_text(encoding="utf-8"); m=re.search(r"^__version__\s*=\s*\"([^\"]+)\"", s, re.M); print(m.group(1) if m else "0.0.0")')

# Host platform identifier (Rust-style) as detected by ppt.
HOST_PLATFORM ?= $(shell PYTHONPATH=src python3 -c 'from ppt.__main__ import detect_platform; print(detect_platform().key)')

RUNTIME ?= $(shell if command -v podman >/dev/null 2>&1; then echo podman; elif command -v docker >/dev/null 2>&1; then echo docker; else echo none; fi)
SANDBOX_VOLUME := $(CURDIR):/workspace$(if $(filter podman,$(RUNTIME)),:Z,)

DIST_DIR := dist
DIST_DIR_STAMP := $(DIST_DIR)/.dir.stamp
PYOXIDIZER ?= pyoxidizer

# Use a containerized build for Linux targets by default. This avoids producing
# binaries that depend on a newer glibc than the sandbox/release environments.
PPT_DIST_USE_CONTAINER ?= $(if $(filter none,$(RUNTIME)),0,1)
PPT_DIST_CONTAINER_IMAGE ?= ppt:dist

# Cache volume for containerized dist builds.
PPT_DIST_CACHE_VOLUME ?= ppt-dist-cache

# Default to building only for the current host platform.
# Override with e.g. `make dist PPT_DIST_TARGETS="x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu"`.
PPT_DIST_TARGETS ?= $(HOST_PLATFORM)

DIST_TARBALLS := $(foreach t,$(PPT_DIST_TARGETS),$(DIST_DIR)/ppt-$(VERSION)-$(t).tar.gz)

# Local dev defaults.
RELEASE_TARBALL := $(DIST_DIR)/ppt-$(VERSION)-x86_64-unknown-linux-gnu.tar.gz
SANDBOX_TARBALL := $(DIST_DIR)/ppt-sandbox-linux.tar.gz
INSTALL_SH := $(DIST_DIR)/install.sh

INSTALL_TEMPLATE := install.sh.template
REPO_URL ?= $(shell if [ -n "$$CI_PROJECT_URL" ]; then echo "$$CI_PROJECT_URL"; else echo "https://gitlab.com/perapp/ppt"; fi)

help:
	@printf '%s\n' \
	  'Targets:' \
	  '  dist            Build dist tarballs + install.sh' \
	  '  dist-image      Build local container image used for dist (optional)' \
	  '  release-assets   Build default local Linux tarball + install.sh' \
	  '  sandbox          Build assets and start interactive sandbox' \
	  '  clean            Remove dist and sandbox image stamp'

dist-image:
	@if [ "$(RUNTIME)" = "none" ]; then \
	  printf '%s\n' 'error: need podman or docker for dist-image' >&2; \
	  exit 2; \
	fi
	@$(RUNTIME) build -f dev/Containerfile.dist -t $(PPT_DIST_CONTAINER_IMAGE) .

$(DIST_DIR_STAMP):
	@mkdir -p "$(DIST_DIR)"
	@touch "$(DIST_DIR_STAMP)"

$(DIST_DIR)/ppt-$(VERSION)-%.tar.gz: | $(DIST_DIR_STAMP)
	@set -euo pipefail; \
	target="$*"; \
	use_container="$(PPT_DIST_USE_CONTAINER)"; \
	case "$$target" in \
	  *-unknown-linux-*) ;; \
	  *) use_container=0 ;; \
	esac; \
	if [ "$$use_container" = "1" ]; then \
	  if [ "$(RUNTIME)" = "none" ]; then \
	    printf '%s\n' 'error: container runtime not available (need podman or docker)' >&2; \
	    exit 2; \
	  fi; \
	  $(MAKE) --no-print-directory dist-image; \
	  $(RUNTIME) volume create "$(PPT_DIST_CACHE_VOLUME)" >/dev/null 2>&1 || true; \
	  $(RUNTIME) run --rm \
	    -v "$(PPT_DIST_CACHE_VOLUME):/cache" \
	    -v "$(CURDIR):/workspace$(if $(filter podman,$(RUNTIME)),:Z,)" \
	    -w /workspace \
	    -e "HOME=/cache/home" \
	    -e "CARGO_HOME=/cache/cargo" \
	    -e "RUSTUP_HOME=/cache/rustup" \
	    "$(PPT_DIST_CONTAINER_IMAGE)" \
	    bash -c "set -euo pipefail; make --no-print-directory PPT_DIST_USE_CONTAINER=0 VERSION='$(VERSION)' PYOXIDIZER=/usr/local/cargo/bin/pyoxidizer '$@'"; \
	  exit 0; \
	fi; \
	$(PYOXIDIZER) build --release --target-triple "$$target"; \
	install_dir="build/$$target/release/install"; \
	if [ ! -x "$$install_dir/bin/ppt" ]; then \
	  printf '%s\n' "error: expected $$install_dir/bin/ppt from pyoxidizer" >&2; \
	  exit 2; \
	fi; \
	tar -C "$$install_dir" -czf "$@" bin


$(INSTALL_SH): $(INSTALL_TEMPLATE) dev/render_install_sh.py | $(DIST_DIR_STAMP)
	@python3 dev/render_install_sh.py --template "$(INSTALL_TEMPLATE)" --out "$(INSTALL_SH)" --repo-url "$(REPO_URL)" --version "$(VERSION)"


dist: $(DIST_TARBALLS) $(INSTALL_SH)
	@printf 'Built %s\n' "$(DIST_DIR)"/*.tar.gz
	@printf 'Built %s\n' "$(INSTALL_SH)"

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
