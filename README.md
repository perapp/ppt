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

## Install

Planned bootstrap command:

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

# refresh remote release metadata
ppt update

# install newer versions for already added packages
ppt upgrade [repo-url|short-id]

# list added packages and installed versions
ppt list
```

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
```

## Notes

`ppt` is intended to complement, not replace, the system package manager. Use
the system package manager for operating system packages, shared libraries, and
services. Use `ppt` for personal CLI tools installed in your home directory.

Implementation notes and design details live in `docs/design.md`.
