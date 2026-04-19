# ppt Design Notes

This document is for project design and implementation discussion. The
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
- `ppt update` refreshes remote release metadata
- `ppt upgrade` installs newer matching releases for managed packages
- `ppt prefix` changes the exposed command prefix for an installed package

The choice of `add` rather than `install` is deliberate: `ppt` manages a
personal package set, not only one-off installs.

## Shared Config

The managed package set should be easy to keep under version control and share
across machines, for example with `yadm`.

That implies:
- `~/.config/ppt/packages.toml` should be the source of truth for desired packages
- the config may contain packages that are not installable on every machine
- differing CPU architecture or upstream release availability should not make a shared config unusable

This is a core product property, not an edge case.

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
- `ppt add <repo-url>`: add the package to config even if it is unavailable on the current machine, but print a warning
- `ppt sync`: skip unavailable packages with a warning and continue with the rest
- `ppt upgrade`: do not fail the overall command for unavailable packages; warn and continue
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
2. find the latest release, or the requested version
3. detect the current Linux platform details
4. locate a matching release artifact
5. download and unpack into a versioned package directory
6. expose selected binaries in the active `bin` directory

The model should stay transparent and easy to debug.

If the package is valid but no matching artifact exists for the current
platform, `ppt` should still be able to record it in the managed set and report
that it is unavailable on this machine.

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
```

Intended meanings:
- `~/.local/ppt/bin/` contains commands exposed by `ppt`, including `ppt`
- `~/.local/ppt/packages/` contains installed package contents
- `~/.local/ppt/cache/` contains downloaded release artifacts
- `~/.local/ppt/state.json` tracks current local installation state
- `~/.config/ppt/packages.toml` describes the packages that should be managed

Packages should be installed into immutable versioned directories. Upgrades can
install a new version beside the old one, then atomically switch the active
symlink.

## Bootstrap

Planned bootstrap command:

```bash
curl -fsSL https://gitlab.com/xxx/ppt/install.sh | bash
```

Prototype assumption:
- the first implementation may install `ppt` into a virtual environment under
  the `ppt` home directory
- later this can be replaced by a standalone binary bootstrap

## Future Ideas

Potential follow-up features:
- stronger artifact verification such as checksums or signatures
- rollback support for previously installed versions
- declarative sync from a config file
- source-build fallback for projects without release binaries
- system-wide configuration such as `/etc/ppt/packages.toml`
