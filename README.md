# ppt

Personal Package Tool

`ppt` installs CLI tools from Git repository releases into your home directory on
Linux without root.

It is meant for systems where you want a modern personal toolbox such as `bat`,
`nvim`, `btop`, `rg`, and `fd`, but do not want to depend on the system package
manager.

`ppt` is especially aimed at:
- shared Linux servers
- locked-down enterprise hosts
- ephemeral VMs and containers
- mixed distros such as Ubuntu, Debian, Fedora, and RHEL
- mixed architectures such as `x86_64` and `arm64`

`ppt` is binary-first:
- you give it a full Git repository URL
- it inspects the project's releases
- it selects a Linux asset that matches the current system
- it installs that release into a user-owned prefix
- it exposes the installed commands through a personal `bin` directory

If a project does not publish usable Linux release binaries, it is out of scope
for the first version.

`ppt` is also intended to work well with version-controlled dotfiles. You should
be able to keep `ppt` config in `yadm` or another dotfile manager and share it
across different Linux systems.

## Install

From a local checkout:

```bash
./install.sh
```

Planned hosted bootstrap command:

```bash
curl -fsSL https://gitlab.com/xxx/ppt/install.sh | bash
```

If needed, add `ppt` to your `PATH`:

```bash
export PATH="$HOME/.local/ppt/bin:$PATH"
```

## Usage

```text
# add a package to the managed set and install it
ppt add <repo-url> [--version <version>] [--prefix <prefix>]

# remove a package
ppt remove <repo-url|short-id>

# change the command prefix used for an installed package
ppt prefix <repo-url|short-id> <prefix>

# make this machine match the shared config and lock file
ppt sync

# bump locked versions for unpinned packages and install them locally
ppt upgrade [repo-url|short-id]

# list configured packages and current status
ppt list

# show details for one package
ppt info <repo-url|short-id>
```

## Config Files

`ppt` keeps its shared configuration in `~/.config/ppt/`.

```text
~/.config/ppt/
  packages.toml
  packages.lock.toml
```

- `packages.toml` is the desired package set that you can keep under version control
- `packages.lock.toml` records the resolved versions that unpinned packages should use

This means you can share the same `ppt` config across machines while still
keeping upgrades explicit.

## Supported Package Sources

For the MVP, `ppt` expects full GitHub repository URLs.

Supported examples:

```text
https://github.com/neovim/neovim
https://github.com/sharkdp/bat
```

Not supported yet:
- short aliases such as `github:owner/repo`
- arbitrary download URLs
- GitLab and other Git hosts
- source-only repositories without usable release binaries

## Examples

```bash
# install ~/.local/ppt/bin/nvim
ppt add https://github.com/neovim/neovim

# install ~/.local/ppt/bin/my-nvim
ppt add https://github.com/myself/neovim --prefix my-

# install ~/.local/ppt/bin/nvim-0.12.1
ppt add https://github.com/neovim/neovim --version v0.12.1

# change prefixes so your fork becomes nvim and upstream becomes official-nvim
ppt prefix https://github.com/neovim/neovim official-
ppt prefix https://github.com/myself/neovim ""

# apply the shared config and locked versions on this machine
ppt sync

# explicitly bump unpinned packages to newer releases
ppt upgrade
```

## Command Model

`ppt add` records a package in config and installs it immediately when possible.

`ppt sync` makes the current machine match `packages.toml` and
`packages.lock.toml`. This is the command to run after pulling updated dotfiles
onto another machine.

`ppt upgrade` updates the locked versions for unpinned packages and installs
those new versions on the current machine. This keeps upgrades explicit, which
is useful when tool config or plugins may break across releases.

If a package is configured but has no matching release artifact for the current
platform, `ppt` should warn and continue. `ppt list` should still show that
package as unavailable on this machine.

## Notes

`ppt` is intended to complement, not replace, the system package manager. Use
the system package manager for operating system packages, shared libraries, and
services. Use `ppt` for personal CLI tools installed in your home directory.

Implementation notes and design details live in `docs/design.md`.
