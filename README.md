# ppt

Personal Package Tool

`ppt` installs CLI tools into your home directory on Linux without root.

It is designed for multi-user Linux systems where you want a modern personal
toolbox — `bat`, `nvim`, `btop`, `rg`, `fd`, and similar tools — without
depending on the system package manager.

`ppt` is especially aimed at:
- shared Linux servers
- locked-down enterprise hosts
- ephemeral VMs and containers
- mixed distros such as Ubuntu, Debian and RHEL
- mixed architectures such as x86_64 and arm64
- providing the very latest version of tools from the project repository
- installing recent versions of tools directly from project releases

## Install

```bash
curl -fsSL https://gitlab.com/xxx/ppt/install.sh | bash
```

### Usage

```
# add a new package to be installed on this system
ppt add <repo-url> [--version <version>] [--prefix <prefix>]

# remove a package
ppt remove <repo-url|short-id>

# refresh remote release metadata
ppt update   

# install newer versions for already added packages.
ppt upgrade [repo-url|short-id]  

# list all added packages and their installed versions
ppt list
```

Examples:
```
# install ~/.local/bin/nvim
ppt add https://github.com/neovim/neovim

# install ~/.local/bin/my-nvim
ppt add https://github.com/myself/neovim --prefix my-

# install ~/.local/bin/nvim-0.12.1
ppt add https://github.com/neovim/neovim --version v0.12.1

# Change prefixes such that my fork is nvim and the upstream is official-nvim
ppt prefix https://github.com/neovim/neovim official
ppt prefix https://github.com/myself/neovim ""
```

## Architecture

 - ~/.local/bin/ppt: installed version of ppt executable
 - ~/.conf/ppt/packages.toml: config for what packages should be on this system. What prefixes are used and which versions are added. A good candidate for dot file manager to share between systems.
 - ~/.local/ppt/state.json: current state of packages. MAybe individual files instead to make parallell install easier?
 - ~/.local/ppt/bin/{x,y} symlinks into directories below for executable binaries for x and y 
 - ~/.local/ppt/packages/{X,Y}/ X and Y represent different immutable downloaded packages. If a package X is being upgraded, it is: downloaded and prepared into Z, relinked to Z and then X is "garbage collected" if not used anymore.

Considirations for potential future features:
 - Also support system wide install using /etc/ppt/packages.toml
