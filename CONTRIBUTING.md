# Contributing

## Development Setup

This project uses `uv` for running tests locally.

Run the unit test suite:

```bash
uv run pytest
```

Run integration tests:

```bash
uv run pytest tests/integration
```

Run container integration tests:

```bash
uv run pytest tests/integration -m container
```

## CI Config Validation

We validate YAML syntax for all `*.yml` / `*.yaml` files in the repository and do a lightweight structural check of `.gitlab-ci.yml`.

In addition, there is an optional GitLab CI Lint API test that can catch semantic errors that still produce valid YAML.

### GitLab CI Lint API Test

The test is implemented in `tests/integration/test_gitlab_ci_lint_api.py`.

It is marked `gitlab_api` and runs as part of the integration suite.

Why opt-in:
- Some GitLab instances do not allow CI lint via `CI_JOB_TOKEN`.
- We want local development to work without requiring network access.

To enable the online check locally:

1. Create a **Project access token** for this project.
2. Set role: `Developer`.
3. Set scopes: `api` (recommended) and optionally `read_api`.
4. Export it as `GITLAB_TOKEN` in your shell.

```bash
export GITLAB_TOKEN=***
uv run pytest -q tests/integration -m gitlab_api -rs
```

Alternatively, you can put the token in a local `.env` file in the repo root
(it is gitignored). `uv run pytest` will auto-load it for tests.

To enable the online check in GitLab CI:

1. Add the token as a masked CI/CD variable named `GITLAB_TOKEN`.
2. Keep it protected if you only want it to run on protected branches/tags.

Security notes:
- Treat access tokens as secrets. Do not paste them into chat or commit them to the repo.
- Prefer short expirations and rotate when needed.

# ppt Design Notes

This section is for project design and implementation discussion. The
user-facing overview and usage live in `README.md`.

## Scope

`ppt` is a user-space, binary-first package tool for Linux.

The initial scope is intentionally narrow:
- install CLI tools into a user-owned prefix
- use full GitHub repository URLs as package identifiers for the MVP
- inspect upstream releases and pick a matching Linux artifact
- expose installed commands through a personal `bin` directory
- avoid root, daemons, and system-wide integration by default

Out of scope for the first version:
- source-only repositories without usable release binaries
- general dependency solving
- daemons and system services
- full distro-package replacement
- non-GitHub hosts unless they become necessary for the MVP package set

## Package Model

A package is identified by a GitHub repository URL for the MVP.

Examples:

```text
https://github.com/sharkdp/bat
https://github.com/neovim/neovim
```

Current assumptions:
- `ppt add <repo-url>` adds the package to the managed set and installs it
- `ppt remove <repo-url|short-id>` removes it from the managed set
- `ppt sync` makes the current machine match config and lock state
- `ppt upgrade` bumps resolved versions for unpinned packages and installs them locally
- `ppt prefix` changes the exposed command prefix for an installed package

The choice of `add` rather than `install` is deliberate: `ppt` manages a
personal package set, not only one-off installs.

## Shared Config

The managed package set should be easy to keep under version control and share
across machines, for example with `yadm`.

That implies:
- `~/.config/ppt/packages.toml` should be the source of truth for desired packages
- `~/.config/ppt/packages.lock.toml` should record the resolved versions to use for unpinned packages
- the config may contain packages that are not installable on every machine
- differing CPU architecture or upstream release availability should not make a shared config unusable

This is a core product property, not an edge case.

## Config And Lock Model

Recommended shared files:

```text
~/.config/ppt/
  packages.toml
  packages.lock.toml
```

Recommended meaning:
- `packages.toml`: desired packages, optional explicit version pins, optional prefix overrides
- `packages.lock.toml`: resolved versions for packages that are not explicitly pinned

Example intent:

```toml
[[package]]
repo = "https://github.com/neovim/neovim"

[[package]]
repo = "https://github.com/sharkdp/bat"
version = "v0.25.0"
```

Example lock state:

```toml
[[package]]
repo = "https://github.com/neovim/neovim"
version = "v0.12.1"

[[package]]
repo = "https://github.com/sharkdp/bat"
version = "v0.25.0"
```

This separates:
- desired package set
- chosen tool versions
- local installation state on one machine

That separation is useful when editor plugins or user config may break across
upstream releases. `upgrade` becomes an explicit choice rather than an implicit
side effect of `sync`.

## MVP Package Coverage

The MVP should cover the packages currently installed by `~/.local/bin/home_init`
via release archives, excluding the source build of `tmux`.

Current package set:
- `eza`
- `bat`
- `fzf`
- `ripgrep`
- `bottom`
- `btop`
- `delta`
- `gdu`
- `uv`
- `helix`
- `neovim`

Implications from that set:
- GitHub releases are sufficient for the MVP package source
- source-build fallback is not required for the MVP
- AppImage support is not required for the MVP
- explicit version install is needed because the old script mixes pinned and latest versions
- `latest` release install is needed because several packages are installed from `releases/latest`
- package support is per-package and per-platform: for example, `neovim` should be treated as unsupported on your 32-bit Raspberry Pi systems because upstream does not publish Linux binary releases for that target

## Artifact Handling

The current MVP package set requires support for these archive formats:
- `.tar.gz`
- `.tgz`
- `.tar.xz`
- `.tbz`

Archives may contain either a single top-level directory or files directly at
the archive root. Extraction logic should handle both.

The package set also implies that asset selection cannot rely on one uniform
naming scheme. The MVP needs package-specific or rule-based matching for names
such as:
- `x86_64`, `amd64`
- `aarch64`, `arm64`
- `armv7l`, `armv7`, `arm`
- `gnu`, `musl`, `gnueabihf`, `musleabihf`

When no suitable upstream artifact exists for the current platform, `ppt` should
report that clearly instead of failing late during extraction or activation.

## Unavailable Packages

Packages that are present in shared config but do not have a usable upstream
artifact for the current machine should be treated as unavailable, not broken.

Examples:
- `neovim` on a 32-bit Raspberry Pi where upstream does not publish a Linux binary release
- a package that has `x86_64` binaries but no `arm64` binaries

Recommended command behavior:
- `ppt add <repo-url>`: add the package to config, resolve or record its locked version, and install it if possible; if unavailable on the current machine, keep it in config but print a warning
- `ppt sync`: skip unavailable packages with a warning and continue with the rest
- `ppt upgrade`: update locked versions for unpinned packages; do not fail the overall command for unavailable packages, warn and continue
- `ppt list`: show configured packages even when unavailable locally, with an explicit status
- `ppt info`: explain why the package is unavailable on the current platform

This favors a shared declarative config across heterogeneous systems.

Possible status model for `ppt list`:
- `installed`
- `available`
- `unavailable on this platform`
- `error`

Hard errors should be reserved for cases such as:
- invalid repository URL
- repository cannot be resolved
- requested version does not exist
- package metadata is malformed

Lack of a matching artifact for the current platform should normally be a
warning-level condition.

## Install Flow

When adding a package, the intended flow is:

1. resolve the repository
2. determine the target version:
   - explicit pinned version from `packages.toml`, or
   - existing locked version, or
   - latest release if creating a new lock entry
3. detect the current Linux platform details
4. locate a matching release artifact for that version
5. download and unpack into a versioned package directory
6. expose selected binaries in the active `bin` directory

The model should stay transparent and easy to debug.

If the package is valid but no matching artifact exists for the current
platform, `ppt` should still be able to record it in the managed set and report
that it is unavailable on this machine.

## Command Semantics

Recommended user-facing commands:
- `ppt add`: add a package to `packages.toml`, update lock state, and install locally when possible
- `ppt remove`: remove a package from config and uninstall it locally
- `ppt list`: show config, locked version, installed version, and status
- `ppt info`: explain package details and local status
- `ppt sync`: make the local machine match `packages.toml` plus `packages.lock.toml`
- `ppt sync --check`: perform a fast local drift check without fetching releases or changing state
- `ppt upgrade`: refresh locked versions for unpinned packages, then apply them locally

Recommended behavior split:
- `sync` does not discover newer versions; it applies the current lock file
- `sync --check` does not hit the network; if an unpinned package has no lock entry yet, it reports that sync is needed
- `upgrade` is the explicit command that moves unpinned packages to newer releases

`update` is likely unnecessary for the MVP. Unlike `apt`, `ppt` does not need a
separate user-visible command just to refresh package indexes. `sync` and
`upgrade` can fetch the metadata they need internally.

## Platform Matching

Artifact selection likely needs more than just CPU architecture.

Important dimensions:
- Linux distribution differences
- `x86_64` vs `arm64`
- `glibc` vs `musl`
- minimum supported `glibc` version for some upstream binaries
- `armv7` / hard-float variants where upstream publishes them

A simple first version may rely on release naming conventions and conservative
matching rules, with better libc-aware detection added as needed.

## Prefix Layout

Current working layout:

```text
~/.local/ppt/
  bin/
  packages/
  cache/
  state.json
~/.config/ppt/
  packages.toml
  packages.lock.toml
```

Intended meanings:
- `~/.local/ppt/bin/` contains commands exposed by `ppt`, including `ppt`
- `~/.local/ppt/packages/` contains installed package contents
- `~/.local/ppt/cache/` contains downloaded release artifacts
- `~/.local/ppt/state.json` tracks current local installation state
- `~/.config/ppt/packages.toml` describes the packages that should be managed
- `~/.config/ppt/packages.lock.toml` records the resolved versions used by unpinned packages

Packages should be installed into immutable versioned directories. Upgrades can
install a new version beside the old one, then atomically switch the active
symlink.

## Bootstrap

Planned bootstrap command:

```bash
curl -fsSL https://gitlab.com/xxx/ppt/install.sh | bash
```

The first implementation should be a self-contained Python application installed
without relying on PyPI.

Preferred bootstrap layout:

```text
~/.local/ppt/
  bin/
  app/
  venv/
  cache/
  state.json
~/.config/ppt/
  packages.toml
  packages.lock.toml
```

Bootstrap behavior for the Python version:
- create `~/.local/ppt/venv`
- install the Python application under `~/.local/ppt/app/`
- create a launcher in `~/.local/ppt/bin/ppt`
- avoid any dependency on PyPI packaging or global Python installation state beyond having a usable Python interpreter

`app/` is preferred over `src/` because this is installed application code, not
necessarily a developer checkout.

## Python First, Rust Later

The first version should be implemented in Python for speed of iteration.

However, the long-term expectation is that `ppt` may be replaced by a Rust
implementation while preserving the same overall user model.

That suggests a few design constraints even in the Python version:
- keep config and package state format independent of the implementation language
- keep the on-disk package layout stable across implementations
- keep the launcher and install model simple enough that a future Rust binary can replace the Python entrypoint
- avoid PyPI-specific concepts becoming part of the product identity

Desired migration shape:
- Python version: `install.sh` installs app code plus venv and exposes `ppt`
- Rust version: `install.sh` can later install a standalone binary into the same prefix
- user config and installed packages remain compatible where practical

## Future Ideas

Potential follow-up features:
- stronger artifact verification such as checksums or signatures
- rollback support for previously installed versions
- declarative sync from a config file
- source-build fallback for projects without release binaries
- system-wide configuration such as `/etc/ppt/packages.toml`
