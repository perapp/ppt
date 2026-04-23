from __future__ import annotations

import argparse
import html
import inspect
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__


SUPPORTED_ARCHES = {
    # Canonical arch names match Rust target arch naming.
    "x86_64": ["x86_64", "amd64", "x64", "linux64"],
    "aarch64": ["aarch64", "arm64"],
    # armv7/hard-float is commonly tagged as armhf / eabihf.
    "armv7": ["armv7l", "armv7", "armhf", "eabihf", "gnueabihf"],
}

SUPPORTED_ARCHIVES = (".tar.gz", ".tgz", ".tar.xz", ".tbz", ".tar.bz2", ".zip")


# Arch tokens seen in upstream release assets that we do not support.
#
# Without this, an asset like "tool-linux-s390x.tar.gz" would look "arch-agnostic"
# to our limited alias list and could incorrectly be selected as a fallback.
UNSUPPORTED_ARCH_TOKENS = (
    "s390x",
    "ppc64le",
    "ppc64",
    "riscv64",
    "loongarch64",
    "mips64",
    "mips",
    "sparc64",
    "sparc",
    "i686",
    "i386",
)


class PptError(Exception):
    pass


@dataclass
class PackageConfig:
    repo: str
    # Constraint is currently an exact release tag (e.g. "v0.12.1").
    # Future: allow ranges (e.g. "^2" / "~2.3").
    constraint: str | None = None
    prefix: str | None = None


@dataclass
class PackageLockEntry:
    repo: str
    locked: str


@dataclass
class PlatformInfo:
    os_name: str
    vendor: str
    arch: str
    env: str | None

    @property
    def key(self) -> str:
        # Rust-style target identifier.
        # - Linux uses a quadruple: <arch>-<vendor>-<os>-<env>
        # - macOS uses a triple: <arch>-<vendor>-<os>
        if self.env:
            return f"{self.arch}-{self.vendor}-{self.os_name}-{self.env}"
        return f"{self.arch}-{self.vendor}-{self.os_name}"


@dataclass
class AppPaths:
    home: Path
    config_dir: Path
    cache_dir: Path
    packages_dir: Path
    bin_dir: Path
    state_file: Path
    config_file: Path
    lock_file: Path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "handler"):
        parser.print_help()
        return 1

    try:
        return args.handler(args)
    except PptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ppt", description="Personal Package Tool")
    parser.add_argument("--version", action="version", version=f"ppt {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    shell_env_parser = subparsers.add_parser(
        "shell-env",
        help="Print shell init code (PATH + completion)",
    )
    shell_env_parser.add_argument(
        "--shell",
        choices=("bash", "zsh", "fish"),
        default=None,
        help="Target shell (defaults to detection from $SHELL)",
    )
    shell_env_parser.set_defaults(handler=cmd_shell_env)

    # Internal helper for shell completion.
    complete_parser = subparsers.add_parser("_complete", help=argparse.SUPPRESS)
    complete_sub = complete_parser.add_subparsers(dest="complete_command")
    complete_packages = complete_sub.add_parser("packages", help=argparse.SUPPRESS)
    complete_packages.add_argument("--query", default="")
    complete_packages.set_defaults(handler=cmd_complete_packages)

    update_shell_parser = subparsers.add_parser(
        "update-shell-config",
        help="Add ppt shell init to your shell config",
    )
    update_shell_parser.add_argument(
        "--shell",
        choices=("bash", "zsh", "fish"),
        default=None,
        help="Target shell (defaults to detection from $SHELL)",
    )
    update_shell_parser.add_argument(
        "--rc-file",
        default=None,
        help="Shell init file to update (defaults based on --shell)",
    )
    update_shell_parser.add_argument(
        "--yes",
        action="store_true",
        help="Do not prompt; apply changes",
    )
    update_shell_parser.set_defaults(handler=cmd_update_shell_config)

    add_parser = subparsers.add_parser("add", help="Add a package and install it")
    add_parser.add_argument("repo")
    add_parser.add_argument(
        "--constraint",
        dest="constraint",
        help="Exact version constraint (release tag).",
    )
    add_parser.add_argument("--prefix", dest="prefix")
    add_parser.set_defaults(handler=cmd_add)

    install_parser = subparsers.add_parser("install", help="Install ppt into your home directory")
    install_parser.add_argument("--repo", dest="repo", default=None, help="Repo URL to record in config")
    install_parser.add_argument("--version", dest="version", default=None, help="Version to record in lock")
    install_parser.add_argument("--asset-name", dest="asset_name", default=None)
    install_parser.add_argument("--asset-url", dest="asset_url", default=None)
    install_parser.add_argument(
        "--from-dir",
        dest="from_dir",
        default=".",
        help="Directory containing extracted release contents (bin/, src/)",
    )
    install_parser.add_argument(
        "--shell-config",
        choices=("ask", "yes", "no"),
        default="ask",
        help="Whether to update shell init (ask|yes|no)",
    )
    install_parser.set_defaults(handler=cmd_install)

    remove_parser = subparsers.add_parser("remove", help="Remove a package")
    remove_parser.add_argument("package")
    remove_parser.set_defaults(handler=cmd_remove)

    prefix_parser = subparsers.add_parser("prefix", help="Set a package prefix")
    prefix_parser.add_argument("package")
    prefix_parser.add_argument("prefix")
    prefix_parser.set_defaults(handler=cmd_prefix)

    sync_parser = subparsers.add_parser("sync", help="Apply config and lock state")
    sync_parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether local state differs from config/lock state without changing anything",
    )
    sync_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress normal output for --check",
    )
    sync_parser.set_defaults(handler=cmd_sync)

    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Upgrade packages without an explicit constraint",
    )
    upgrade_parser.add_argument("packages", nargs="*")
    upgrade_parser.set_defaults(handler=cmd_upgrade)

    update_parser = subparsers.add_parser(
        "update",
        help="Fetch latest/available versions for configured packages",
    )
    update_parser.add_argument("packages", nargs="*")
    update_parser.set_defaults(handler=cmd_update)

    list_parser = subparsers.add_parser("list", help="List packages")
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="Show all configured packages (default: only installed)",
    )
    list_parser.add_argument(
        "--upgradable",
        action="store_true",
        help="Show packages that would be upgraded by `ppt upgrade`",
    )
    list_parser.set_defaults(handler=cmd_list)

    info_parser = subparsers.add_parser("info", help="Show package details")
    info_parser.add_argument("package")
    info_parser.set_defaults(handler=cmd_info)

    platform_parser = subparsers.add_parser("platform", help="Print current platform identifier")
    platform_parser.set_defaults(handler=cmd_platform)

    return parser


def cmd_shell_env(args: argparse.Namespace) -> int:
    shell = args.shell or detect_shell_name()
    if shell == "bash":
        sys.stdout.write(render_shell_env_bash())
        return 0
    if shell == "zsh":
        sys.stdout.write(render_shell_env_zsh())
        return 0
    if shell == "fish":
        sys.stdout.write(render_shell_env_fish())
        return 0
    raise PptError(f"unsupported shell: {shell}")


def cmd_update_shell_config(args: argparse.Namespace) -> int:
    shell = args.shell or detect_shell_name()
    rc_file = Path(args.rc_file).expanduser() if args.rc_file else default_rc_file(shell)
    rc_file = rc_file.expanduser()

    rc_file.parent.mkdir(parents=True, exist_ok=True)
    if not rc_file.exists():
        rc_file.write_text("", encoding="utf-8")

    existing = rc_file.read_text(encoding="utf-8", errors="replace")

    eval_line = shell_env_eval_line(shell)
    if shell_env_config_present(shell, existing):
        print(f"ppt shell init already present in {rc_file}")
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            raise PptError(
                f"refusing to prompt on non-interactive stdin; rerun with --yes to update {rc_file}"
            )
        reply = input(f"Enable ppt shell init (PATH + completion) in {rc_file}? [y/N] ").strip()
        if reply.lower() not in {"y", "yes"}:
            print("skipped shell config update")
            return 0

    with rc_file.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(eval_line)
        handle.write("\n")
    print(f"added ppt shell init to {rc_file}")
    return 0


def cmd_complete_packages(args: argparse.Namespace) -> int:
    query = (args.query or "").strip()

    config_dir = Path(os.environ.get("PPT_CONFIG_DIR", Path.home() / ".config" / "ppt")).expanduser()
    config_file = config_dir / "packages.toml"
    config = read_config_file(config_file)
    if not config:
        return 0

    owner_repos = [owner_repo_name(entry.repo) for entry in config]
    short_names: list[str] = [item.split("/")[-1] for item in owner_repos]
    short_counts: dict[str, int] = {}
    for item in short_names:
        short_counts[item] = short_counts.get(item, 0) + 1

    candidates: set[str] = set()
    for owner_repo in owner_repos:
        candidates.add(owner_repo)
        short = owner_repo.split("/")[-1]
        if short_counts.get(short, 0) == 1:
            candidates.add(short)

    for value in sorted(candidates):
        if query and not value.startswith(query):
            continue
        sys.stdout.write(value + "\n")
    return 0


def shell_env_eval_line(shell: str) -> str:
    # Use an absolute path so this works before PATH is set.
    if shell == "fish":
        return 'eval ("$HOME/.local/ppt/bin/ppt" shell-env --shell fish)'
    return f'eval "$("${{PPT_HOME:-$HOME/.local/ppt}}/bin/ppt" shell-env --shell {shell})"'


def shell_env_config_present(shell: str, text: str) -> bool:
    # Be tolerant of different quoting/styles; avoid duplicate inserts.
    # We only consider it present if it looks like it wires `ppt shell-env`.
    # (No markers are required.)
    if shell == "fish":
        return "shell-env --shell fish" in text and "ppt" in text
    return f"shell-env --shell {shell}" in text and "ppt" in text


def detect_shell_name() -> str:
    raw = (os.environ.get("SHELL") or "").strip()
    name = Path(raw).name
    if name in {"bash", "zsh", "fish"}:
        return name
    return "bash"


def default_rc_file(shell: str) -> Path:
    home = Path.home()
    if shell == "bash":
        return home / ".bashrc"
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
    return home / ".bashrc"


def render_shell_env_bash() -> str:
    # Keep this fast and side-effect free: just print init code.
    return """# ppt shell-env (bash)
_ppt_bin=\"${PPT_HOME:-$HOME/.local/ppt}/bin\"
case ":$PATH:" in
  *\":${_ppt_bin}:\"*) ;;
  *) PATH=\"${_ppt_bin}:$PATH\"; export PATH ;;
esac
unset _ppt_bin

_ppt() {
  local cur cmd
  cur=\"${COMP_WORDS[COMP_CWORD]}\"
  cmd=\"${COMP_WORDS[1]}\"
  if [ \"$COMP_CWORD\" -eq 1 ]; then
    COMPREPLY=( $(compgen -W 'add remove prefix sync upgrade update list info platform' -- \"$cur\") )
    return 0
  fi
  case \"$cmd\" in
    remove|info)
      if [ \"$COMP_CWORD\" -eq 2 ] && [[ \"$cur\" != -* ]]; then
        COMPREPLY=( $(ppt _complete packages --query \"$cur\") )
        return 0
      fi
      COMPREPLY=()
      ;;
    prefix)
      if [ \"$COMP_CWORD\" -eq 2 ] && [[ \"$cur\" != -* ]]; then
        COMPREPLY=( $(ppt _complete packages --query \"$cur\") )
        return 0
      fi
      COMPREPLY=()
      ;;
    upgrade)
      if [ \"$COMP_CWORD\" -ge 2 ] && [[ \"$cur\" != -* ]]; then
        COMPREPLY=( $(ppt _complete packages --query \"$cur\") )
        return 0
      fi
      COMPREPLY=()
      ;;
    update)
      if [ \"$COMP_CWORD\" -ge 2 ] && [[ \"$cur\" != -* ]]; then
        COMPREPLY=( $(ppt _complete packages --query \"$cur\") )
        return 0
      fi
      COMPREPLY=()
      ;;
    add)
      COMPREPLY=( $(compgen -W '--constraint --prefix' -- \"$cur\") )
      ;;
    sync)
      COMPREPLY=( $(compgen -W '--check --quiet' -- \"$cur\") )
      ;;
    list)
      COMPREPLY=()
      ;;
    platform)
      COMPREPLY=()
      ;;
    *)
      COMPREPLY=( $(compgen -W 'add remove prefix sync upgrade update list info platform' -- \"$cur\") )
      ;;
  esac
}
complete -F _ppt ppt
"""


def render_shell_env_zsh() -> str:
    return """# ppt shell-env (zsh)
_ppt_bin=\"${PPT_HOME:-$HOME/.local/ppt}/bin\"
case ":$PATH:" in
  *\":${_ppt_bin}:\"*) ;;
  *) PATH=\"${_ppt_bin}:$PATH\"; export PATH ;;
esac
unset _ppt_bin

_ppt() {
  local -a commands
  commands=(
    'add:Add a package and install it'
    'remove:Remove a package'
    'prefix:Set a package prefix'
    'sync:Apply config and lock state'
    'upgrade:Upgrade unconstrained packages'
    'update:Fetch available versions'
    'list:List packages'
    'info:Show package details'
    'platform:Print current platform identifier'
  )

  _arguments -C \
    '1:command:->cmds' \
    '*::args:->args'

  case $state in
    cmds)
      _describe 'command' commands
      return
      ;;
    args)
      case $words[2] in
        add)
          _arguments '--constraint=[Exact version constraint]' '--prefix=[Command prefix]'
          ;;
        sync)
          _arguments '--check[Check only]' '--quiet[Suppress normal output for --check]'
          ;;
        remove|info)
          if [[ $CURRENT -eq 3 && $PREFIX != -* ]]; then
            compadd -- ${(f)$(ppt _complete packages --query "$PREFIX")}
          fi
          ;;
        prefix)
          if [[ $CURRENT -eq 3 && $PREFIX != -* ]]; then
            compadd -- ${(f)$(ppt _complete packages --query "$PREFIX")}
          fi
          ;;
        upgrade)
          if [[ $CURRENT -ge 3 && $PREFIX != -* ]]; then
            compadd -- ${(f)$(ppt _complete packages --query "$PREFIX")}
          fi
          ;;
        update)
          if [[ $CURRENT -ge 3 && $PREFIX != -* ]]; then
            compadd -- ${(f)$(ppt _complete packages --query "$PREFIX")}
          fi
          ;;
      esac
      ;;
  esac
}

if command -v compdef >/dev/null 2>&1; then
  compdef _ppt ppt
fi
"""


def render_shell_env_fish() -> str:
    return """# ppt shell-env (fish)
set -l ppt_home "$HOME/.local/ppt"
if set -q PPT_HOME
  set ppt_home "$PPT_HOME"
end
set -l ppt_bin "$ppt_home/bin"
if not contains -- "$ppt_bin" $PATH
  set -gx PATH "$ppt_bin" $PATH
end

complete -c ppt -f
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a add -d "Add a package and install it"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a remove -d "Remove a package"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a prefix -d "Set a package prefix"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a sync -d "Apply config and lock state"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a upgrade -d "Upgrade unconstrained packages"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a update -d "Fetch available versions"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a list -d "List packages"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a info -d "Show package details"
complete -c ppt -n "not __fish_seen_subcommand_from add remove prefix sync upgrade update list info platform" -a platform -d "Print current platform identifier"

complete -c ppt -n "__fish_seen_subcommand_from add" -l constraint -r -d "Exact version constraint"
complete -c ppt -n "__fish_seen_subcommand_from add" -l prefix -r -d "Command prefix"
complete -c ppt -n "__fish_seen_subcommand_from sync" -l check -d "Check only"
complete -c ppt -n "__fish_seen_subcommand_from sync" -l quiet -d "Suppress normal output for --check"

complete -c ppt -n "__fish_seen_subcommand_from remove" -a "(ppt _complete packages --query (commandline -ct))" -d "Configured package"
complete -c ppt -n "__fish_seen_subcommand_from info" -a "(ppt _complete packages --query (commandline -ct))" -d "Configured package"
complete -c ppt -n "__fish_seen_subcommand_from prefix" -a "(ppt _complete packages --query (commandline -ct))" -d "Configured package"
complete -c ppt -n "__fish_seen_subcommand_from upgrade" -a "(ppt _complete packages --query (commandline -ct))" -d "Configured package"
complete -c ppt -n "__fish_seen_subcommand_from update" -a "(ppt _complete packages --query (commandline -ct))" -d "Configured package"
"""


def cmd_add(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    platform_info = detect_platform()
    config = read_config_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)

    repo = normalize_repo_url(args.repo)
    config_entry = PackageConfig(repo=repo, constraint=args.constraint, prefix=args.prefix)
    config = upsert_config(config, config_entry)
    write_config_file(paths.config_file, config)

    target_version = args.constraint or lock.get(repo)
    if target_version is None:
        release = fetch_release(repo, None)
        target_version = release["tag_name"]
    lock[repo] = target_version
    write_lock_file(paths.lock_file, lock)

    result = install_package(paths, platform_info, config_entry, target_version, state)
    write_state(paths.state_file, state)
    print(result)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    from_dir = Path(args.from_dir).expanduser().resolve()

    has_src = (from_dir / "src" / "ppt" / "__main__.py").exists()
    has_bin = (from_dir / "bin" / "ppt").exists()
    if not has_src and not has_bin:
        raise PptError(f"invalid --from-dir (missing bin/ppt or src/ppt): {from_dir}")

    # Install into standard layout.
    paths = ensure_layout()
    repo = args.repo or os.environ.get("PPT_REPO_URL") or "https://gitlab.com/perapp/ppt"
    version = args.version or os.environ.get("PPT_INSTALL_VERSION") or __version__
    asset_name = args.asset_name or os.environ.get("PPT_INSTALL_ASSET_NAME") or ""
    asset_url = args.asset_url or os.environ.get("PPT_INSTALL_ASSET_URL") or ""

    slug = package_slug(repo)
    package_dir = paths.packages_dir / slug / version
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    # Copy extracted release contents into package_dir.
    for child in sorted(from_dir.iterdir()):
        if child.name in {"src", "bin"}:
            dest = package_dir / child.name
            shutil.copytree(child, dest, dirs_exist_ok=True)

    if has_src:
        if not (package_dir / "src" / "ppt" / "__main__.py").exists():
            raise PptError(f"installed package did not contain src/ppt: {package_dir}")

        # Stable launcher that points at installed sources.
        paths.bin_dir.mkdir(parents=True, exist_ok=True)
        launcher = paths.bin_dir / "ppt"
        launcher.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
export PPT_HOME=\"{ppt_home}\"
export PPT_CONFIG_DIR=\"{ppt_config}\"
export PYTHONPATH=\"{pkg_dir}/src${{PYTHONPATH:+:$PYTHONPATH}}\"
exec python3 -m ppt \"$@\"
""".format(
                ppt_home=str(paths.home),
                ppt_config=str(paths.config_dir),
                pkg_dir=str(package_dir),
            ),
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    else:
        # Binary-only distribution: create a stable symlink launcher.
        source = package_dir / "bin" / "ppt"
        if not source.exists():
            raise PptError(f"installed package did not contain bin/ppt: {package_dir}")
        paths.bin_dir.mkdir(parents=True, exist_ok=True)
        launcher = paths.bin_dir / "ppt"
        replace_symlink(source, launcher)

    # Seed config + lock so ppt can manage itself.
    config = [PackageConfig(repo=repo)]
    write_config_file(paths.config_file, config)
    write_lock_file(paths.lock_file, {repo: version})

    state = {
        repo: {
            "status": "installed",
            "resolved_version": version,
            "installed_version": version,
            "prefix": "",
            "bin_links": [str(launcher)],
            "package_dir": str(package_dir),
            "asset_name": asset_name,
            "message": "",
            "updated_at": int(time.time()),
        }
    }
    write_state(paths.state_file, state)
    platform_info = detect_platform()
    write_receipt(
        package_dir,
        repo,
        version,
        {"name": asset_name, "browser_download_url": asset_url},
        platform_info,
        [str(launcher)],
    )

    print(f"Installed ppt to {launcher}")

    shell_config = args.shell_config
    if shell_config == "yes":
        try:
            cmd_update_shell_config(argparse.Namespace(shell=None, rc_file=None, yes=True))
        except PptError as exc:
            print(f"warning: {exc}")
        return 0

    if shell_config == "ask" and sys.stdin.isatty():
        try:
            cmd_update_shell_config(argparse.Namespace(shell=None, rc_file=None, yes=False))
        except PptError as exc:
            # Shell init update is optional.
            print(f"warning: {exc}")
        return 0

    # shell_config == "no" or non-interactive ask.
    print(f"If needed, add {paths.bin_dir} to PATH:")
    print(f"  export PATH=\"{paths.bin_dir}:$PATH\"")
    print("To enable completion and PATH updates on shell startup:")
    print(f"  {launcher} update-shell-config")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_config_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)
    repo = resolve_package_ref(args.package, config)

    config = [entry for entry in config if entry.repo != repo]
    lock.pop(repo, None)
    uninstall_package(paths, repo, state)
    write_config_file(paths.config_file, config)
    write_lock_file(paths.lock_file, lock)
    write_state(paths.state_file, state)
    print(f"removed {repo}")
    return 0


def cmd_prefix(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_config_file(paths.config_file)
    state = read_state(paths.state_file)
    repo = resolve_package_ref(args.package, config)
    entry = get_config_entry(config, repo)
    entry.prefix = args.prefix
    write_config_file(paths.config_file, config)

    repo_state = state.get(repo)
    if repo_state and repo_state.get("installed_version"):
        relink_installed_package(paths, repo, entry, repo_state)
        write_state(paths.state_file, state)
    print(f"set prefix for {repo} to {args.prefix!r}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_config_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)

    if args.check:
        platform_info = detect_platform()
        reasons = sync_needed_reasons(paths, config, lock, state, platform_info)
        if reasons:
            if not args.quiet:
                count = len(reasons)
                noun = "package" if count == 1 else "packages"
                print(f"{count} {noun} out of sync; run `ppt sync`")
            return 10
        return 0

    platform_info = detect_platform()

    configured_repos = {entry.repo for entry in config}
    for repo in list(state):
        if repo not in configured_repos:
            uninstall_package(paths, repo, state)

    messages: list[str] = []
    changed_lock = False
    for entry in config:
        target_version = entry.constraint or lock.get(entry.repo)
        if target_version is None:
            release = fetch_release(entry.repo, None)
            target_version = release["tag_name"]
        if lock.get(entry.repo) != target_version:
            lock[entry.repo] = target_version
            changed_lock = True
        message = install_package(paths, platform_info, entry, target_version, state)
        if message:
            messages.append(message)

    if changed_lock:
        write_lock_file(paths.lock_file, lock)
    write_state(paths.state_file, state)
    for message in messages:
        print(message)
    return 0


def sync_needed_reasons(
    paths: AppPaths,
    config: list[PackageConfig],
    lock: dict[str, str],
    state: dict,
    platform_info: PlatformInfo,
) -> list[str]:
    reasons: list[str] = []
    configured_repos = {entry.repo for entry in config}

    for repo in sorted(state):
        if repo not in configured_repos:
            reasons.append(f"remove unmanaged package {repo}")

    for entry in config:
        target_version = entry.constraint or lock.get(entry.repo)
        if target_version is None:
            reasons.append(f"missing lock entry for {entry.repo}")
            continue

        repo_state = state.get(entry.repo, {})
        if is_current_install(paths, entry, target_version, repo_state):
            continue
        if is_current_unavailable(platform_info, target_version, repo_state):
            continue

        if repo_state.get("status") == "installed":
            installed_version = repo_state.get("installed_version")
            if installed_version != target_version:
                reasons.append(
                    f"{entry.repo} installed {installed_version or '-'} but locked is {target_version}"
                )
            elif (repo_state.get("prefix") or "") != (entry.prefix or ""):
                reasons.append(f"{entry.repo} prefix differs from config")
            else:
                reasons.append(f"{entry.repo} local links or files are missing")
            continue

        if repo_state.get("status") == "unavailable":
            resolved_version = repo_state.get("resolved_version")
            message = repo_state.get("message", "")
            if resolved_version != target_version:
                reasons.append(
                    f"{entry.repo} unavailable state is for {resolved_version or '-'} not {target_version}"
                )
            elif message != f"no release asset for {platform_info.key}":
                reasons.append(f"{entry.repo} availability state is stale for this platform")
            else:
                reasons.append(f"{entry.repo} needs reinstall")
            continue

        reasons.append(f"{entry.repo} is not installed")

    return reasons


def cmd_upgrade(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    platform_info = detect_platform()
    config = read_config_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)
    selected = set()
    if args.packages:
        for raw in args.packages:
            selected.add(resolve_package_ref(raw, config))

    messages: list[str] = []
    changed_lock = False
    for entry in config:
        if selected and entry.repo not in selected:
            continue
        if entry.constraint:
            messages.append(f"skipped constrained package {entry.repo} ({entry.constraint})")
            continue
        repo_state = state.get(entry.repo, {})
        target_version = (repo_state.get("available_version") or "").strip() or None
        if target_version is None:
            release = fetch_release(entry.repo, None)
            target_version = release["tag_name"]
            repo_state = state.setdefault(entry.repo, {})
            repo_state["latest_version"] = target_version
            repo_state["available_version"] = target_version
            repo_state["available_updated_at"] = int(time.time())
        previous = lock.get(entry.repo)
        if previous != target_version:
            changed_lock = True
            lock[entry.repo] = target_version
        message = install_package(paths, platform_info, entry, target_version, state)
        if message:
            messages.append(message)

    if changed_lock:
        write_lock_file(paths.lock_file, lock)
    write_state(paths.state_file, state)
    for message in messages:
        print(message)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_config_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)
    if not config:
        print("no packages configured")
        return 0

    if args.upgradable:
        headers = ["PACKAGE", "INSTALLED", "AVAILABLE", "LOCKED", "CONSTRAINT", "PREFIX"]
        rows: list[list[str]] = []
        missing_availability = False
        for entry in sorted(config, key=lambda item: owner_repo_name(item.repo)):
            if entry.constraint:
                continue
            repo_state = state.get(entry.repo, {})
            installed = repo_state.get("installed_version")
            if not installed:
                continue
            available = (repo_state.get("available_version") or "").strip()
            if not available:
                missing_availability = True
                continue
            if installed == available:
                continue
            rows.append(
                [
                    owner_repo_name(entry.repo),
                    installed,
                    available,
                    lock.get(entry.repo, "-"),
                    entry.constraint or "-",
                    entry.prefix if entry.prefix is not None else "",
                ]
            )

        if not rows:
            if missing_availability:
                print("no upgradable packages (availability unknown; run `ppt update`)")
            else:
                print("no upgradable packages")
            return 0

        _print_table(headers, rows)
        if missing_availability:
            print("\n(note) some packages are missing availability data; run `ppt update`")
        return 0

    # Default: only installed packages, unless --all.
    entries: list[PackageConfig]
    if args.all:
        entries = config
    else:
        entries = []
        for entry in config:
            repo_state = state.get(entry.repo, {})
            if repo_state.get("status") == "installed" and repo_state.get("installed_version"):
                entries.append(entry)

    if not entries:
        print("no installed packages" if not args.all else "no packages configured")
        return 0

    headers = ["PACKAGE", "INSTALLED", "AVAILABLE", "LOCKED", "CONSTRAINT", "STATUS", "PREFIX"]
    rows: list[list[str]] = []
    for entry in sorted(entries, key=lambda item: owner_repo_name(item.repo)):
        repo_state = state.get(entry.repo, {})
        rows.append(
            [
                owner_repo_name(entry.repo),
                repo_state.get("installed_version", "-"),
                (repo_state.get("available_version") or "-").strip() or "-",
                lock.get(entry.repo, "-"),
                entry.constraint or "-",
                repo_state.get("status", "configured"),
                entry.prefix if entry.prefix is not None else "",
            ]
        )

    _print_table(headers, rows)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_config_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)
    repo = resolve_package_ref(args.package, config)
    entry = get_config_entry(config, repo)
    repo_state = state.get(repo, {})

    print(f"repo: {repo}")
    print(f"package: {display_name(repo)}")
    print(f"constraint: {entry.constraint or '-'}")
    print(f"locked: {lock.get(repo, '-')}")
    available = (repo_state.get("available_version") or "-").strip() or "-"
    latest = (repo_state.get("latest_version") or "-").strip() or "-"
    print(f"available: {available}")
    print(f"latest: {latest}")
    print(f"installed: {repo_state.get('installed_version', '-')}")
    asset_name = (repo_state.get("asset_name") or "").strip()
    if asset_name:
        print(f"asset: {asset_name}")
    print(f"status: {repo_state.get('status', 'configured')}")
    print(f"prefix: {entry.prefix if entry.prefix is not None else ''}")
    if repo_state.get("message"):
        print(f"message: {repo_state['message']}")
    if repo_state.get("bin_links"):
        print("bin links:")
        for item in repo_state["bin_links"]:
            print(f"  {item}")
    return 0


def cmd_platform(_args: argparse.Namespace) -> int:
    platform_info = detect_platform()
    print(platform_info.key)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_config_file(paths.config_file)
    state = read_state(paths.state_file)

    selected: set[str] = set()
    if args.packages:
        for raw in args.packages:
            selected.add(resolve_package_ref(raw, config))

    messages: list[str] = []
    for entry in config:
        if selected and entry.repo not in selected:
            continue

        repo_state = state.setdefault(entry.repo, {})
        try:
            latest_release = fetch_release(entry.repo, None)
            latest = (latest_release.get("tag_name") or "").strip()
            if not latest:
                raise PptError(f"failed to resolve latest release for {entry.repo}")
            repo_state["latest_version"] = latest

            if entry.constraint:
                constrained_release = fetch_release(entry.repo, entry.constraint)
                available = (constrained_release.get("tag_name") or entry.constraint).strip()
            else:
                available = latest

            repo_state["available_version"] = available
            repo_state["available_updated_at"] = int(time.time())
            repo_state.pop("available_error", None)
            messages.append(
                f"updated {owner_repo_name(entry.repo)}: available {available} (latest {latest})"
            )
        except Exception as exc:
            # Keep going; a single package failing shouldn't block others.
            repo_state["available_error"] = str(exc)
            repo_state["available_updated_at"] = int(time.time())
            messages.append(f"warning: failed to update {owner_repo_name(entry.repo)}: {exc}")

    write_state(paths.state_file, state)
    for msg in messages:
        print(msg)
    return 0


def ensure_layout() -> AppPaths:
    home = Path(os.environ.get("PPT_HOME", Path.home() / ".local" / "ppt"))
    config_dir = Path(os.environ.get("PPT_CONFIG_DIR", Path.home() / ".config" / "ppt"))
    cache_dir = home / "cache"
    packages_dir = home / "packages"
    bin_dir = home / "bin"
    state_file = home / "state.json"
    config_file = config_dir / "packages.toml"
    lock_file = config_dir / "packages.lock.toml"
    for directory in (home, config_dir, cache_dir, packages_dir, bin_dir):
        directory.mkdir(parents=True, exist_ok=True)
    if not state_file.exists():
        state_file.write_text("{}\n", encoding="utf-8")
    if not config_file.exists():
        write_config_file(config_file, [])
    if not lock_file.exists():
        write_lock_file(lock_file, {})
    return AppPaths(
        home=home,
        config_dir=config_dir,
        cache_dir=cache_dir,
        packages_dir=packages_dir,
        bin_dir=bin_dir,
        state_file=state_file,
        config_file=config_file,
        lock_file=lock_file,
    )


def detect_platform() -> PlatformInfo:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "aarch64"
    elif machine in ("armv7l", "armv7", "arm"):
        arch = "armv7"
    else:
        raise PptError(f"unsupported architecture: {machine}")

    if system == "linux":
        env = detect_env(arch)
        return PlatformInfo(os_name="linux", vendor="unknown", arch=arch, env=env)

    if system == "darwin":
        # Rust uses vendor=apple and os=darwin.
        return PlatformInfo(os_name="darwin", vendor="apple", arch=arch, env=None)

    raise PptError(f"unsupported OS: {system}")


def detect_env(arch: str) -> str:
    """Detect the Rust-style target environment for the current Linux system.

    We intentionally keep this coarse:
    - "gnu" for glibc-based systems
    - "musl" for musl-based systems

    For armv7, Rust targets usually encode hard-float as "*eabihf"; we assume
    that for modern Linux distros.
    """

    libc_name, _ = platform.libc_ver()
    if libc_name and libc_name.lower().startswith("glibc"):
        return "gnueabihf" if arch == "armv7" else "gnu"
    if libc_name and libc_name.lower().startswith("musl"):
        return "musleabihf" if arch == "armv7" else "musl"

    try:
        proc = subprocess.run(
            ["ldd", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "gnueabihf" if arch == "armv7" else "gnu"

    text = f"{proc.stdout}\n{proc.stderr}".lower()
    if "musl" in text:
        return "musleabihf" if arch == "armv7" else "musl"
    return "gnueabihf" if arch == "armv7" else "gnu"


def install_package(
    paths: AppPaths,
    platform_info: PlatformInfo,
    entry: PackageConfig,
    version: str,
    state: dict,
) -> str | None:
    repo_state = state.get(entry.repo, {})
    if is_current_install(paths, entry, version, repo_state):
        return None
    if can_relink_current_install(paths, entry, version, repo_state):
        relink_installed_package(paths, entry.repo, entry, repo_state)
        return f"relinked {display_name(entry.repo)} {version}"
    if is_current_unavailable(platform_info, version, repo_state):
        return None

    release = fetch_release(entry.repo, version)
    asset = select_asset(entry.repo, release, platform_info)
    if asset is None:
        repo_state = state.setdefault(entry.repo, {})
        repo_state.update(
            {
                "status": "unavailable",
                "resolved_version": version,
                "message": f"no release asset for {platform_info.key}",
                "updated_at": int(time.time()),
            }
        )
        return f"warning: {display_name(entry.repo)} {version} unavailable on {platform_info.key}"

    package_dir = paths.packages_dir / package_slug(entry.repo) / version
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    try:
        archive_path = download_asset(paths.cache_dir, asset)
        extract_archive(archive_path, package_dir)
        bin_links = activate_binaries(paths, entry, version, package_dir, state)
    except Exception:
        if package_dir.exists():
            shutil.rmtree(package_dir)
        raise
    state[entry.repo] = {
        "status": "installed",
        "resolved_version": version,
        "installed_version": version,
        "prefix": entry.prefix or "",
        "bin_links": bin_links,
        "package_dir": str(package_dir),
        "asset_name": asset["name"],
        "message": "",
        "updated_at": int(time.time()),
    }
    write_receipt(package_dir, entry.repo, version, asset, platform_info, bin_links)
    return f"installed {display_name(entry.repo)} {version}"


def is_current_install(paths: AppPaths, entry: PackageConfig, version: str, repo_state: dict) -> bool:
    if repo_state.get("status") != "installed":
        return False
    if repo_state.get("installed_version") != version:
        return False
    if (repo_state.get("prefix") or "") != (entry.prefix or ""):
        return False

    package_dir = package_dir_for_state(repo_state)
    if package_dir is None or not package_dir.exists():
        return False
    return bin_links_match(paths, entry, package_dir, repo_state)


def can_relink_current_install(paths: AppPaths, entry: PackageConfig, version: str, repo_state: dict) -> bool:
    if repo_state.get("status") != "installed":
        return False
    if repo_state.get("installed_version") != version:
        return False
    package_dir = package_dir_for_state(repo_state)
    if package_dir is None or not package_dir.exists():
        return False
    return True


def is_current_unavailable(platform_info: PlatformInfo, version: str, repo_state: dict) -> bool:
    if repo_state.get("status") != "unavailable":
        return False
    if repo_state.get("resolved_version") != version:
        return False
    return repo_state.get("message") == f"no release asset for {platform_info.key}"


def package_dir_for_state(repo_state: dict) -> Path | None:
    package_dir_raw = repo_state.get("package_dir")
    if not package_dir_raw:
        return None
    return Path(package_dir_raw)


def bin_links_match(paths: AppPaths, entry: PackageConfig, package_dir: Path, repo_state: dict) -> bool:
    expected_bins = discover_binaries_to_link(package_dir)
    expected_links = {str(paths.bin_dir / f"{entry.prefix or ''}{name}") for name in expected_bins}
    current_links = set(repo_state.get("bin_links", []))
    if current_links != expected_links:
        return False

    for raw_link in expected_links:
        link_path = Path(raw_link)
        if not link_path.is_symlink():
            return False
        try:
            target = link_path.resolve(strict=True)
        except FileNotFoundError:
            return False
        if not str(target).startswith(f"{package_dir}{os.sep}"):
            return False
    return True


def activate_binaries(
    paths: AppPaths,
    entry: PackageConfig,
    version: str,
    package_dir: Path,
    state: dict,
) -> list[str]:
    repo = entry.repo
    previous = state.get(repo, {})
    remove_bin_links(paths, previous.get("bin_links", []))

    expected_bins = discover_binaries_to_link(package_dir)
    links: list[str] = []
    for name in expected_bins:
        source = find_binary(package_dir, [name])
        link_name = f"{entry.prefix or ''}{name}"
        link_path = paths.bin_dir / link_name
        replace_symlink(source, link_path)
        links.append(str(link_path))
    return links


def relink_installed_package(paths: AppPaths, repo: str, entry: PackageConfig, repo_state: dict) -> None:
    package_dir_raw = repo_state.get("package_dir")
    installed_version = repo_state.get("installed_version")
    if not package_dir_raw or not installed_version:
        return
    package_dir = Path(package_dir_raw)
    if not package_dir.exists():
        return
    bin_links = activate_binaries(paths, entry, installed_version, package_dir, {repo: repo_state})
    repo_state["bin_links"] = bin_links
    repo_state["prefix"] = entry.prefix or ""
    repo_state["updated_at"] = int(time.time())


def uninstall_package(paths: AppPaths, repo: str, state: dict) -> None:
    repo_state = state.pop(repo, None)
    if not repo_state:
        package_root = paths.packages_dir / package_slug(repo)
        if package_root.exists():
            shutil.rmtree(package_root)
        return
    remove_bin_links(paths, repo_state.get("bin_links", []))
    package_root = paths.packages_dir / package_slug(repo)
    if package_root.exists():
        shutil.rmtree(package_root)


def remove_bin_links(paths: AppPaths, bin_links: list[str]) -> None:
    for link in bin_links:
        path = Path(link)
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
        except FileNotFoundError:
            continue


def write_receipt(
    package_dir: Path,
    repo: str,
    version: str,
    asset: dict,
    platform_info: PlatformInfo,
    bin_links: list[str],
) -> None:
    receipt = {
        "repo": repo,
        "version": version,
        "asset_name": asset["name"],
        "asset_url": asset["browser_download_url"],
        "platform": platform_info.key,
        "bin_links": bin_links,
        "installed_at": int(time.time()),
    }
    (package_dir / ".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def download_asset(cache_dir: Path, asset: dict) -> Path:
    downloads_dir = cache_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    target = downloads_dir / asset["name"]
    if target.exists() and target.stat().st_size > 0:
        return target

    url = asset["browser_download_url"]
    headers = {"User-Agent": f"ppt/{__version__}"}
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc != "github.com" and gitlab_token():
        headers.update(gitlab_headers())
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise PptError(f"failed to download {asset['name']}: {exc.reason}") from exc
    return target


def extract_archive(archive_path: Path, destination: Path) -> None:
    if not archive_path.name.endswith(SUPPORTED_ARCHIVES):
        raise PptError(f"unsupported archive format: {archive_path.name}")

    if archive_path.name.endswith(".zip"):
        extract_zip(archive_path, destination)
        return
    with tempfile.TemporaryDirectory(prefix="ppt-extract-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        with tarfile.open(archive_path, mode="r:*") as archive:
            extract_kwargs = {}
            if "filter" in inspect.signature(archive.extractall).parameters:
                extract_kwargs["filter"] = "data"
            archive.extractall(temp_dir, **extract_kwargs)
        for child in temp_dir.iterdir():
            shutil.move(str(child), destination / child.name)


def extract_zip(archive_path: Path, destination: Path) -> None:
    # Zip archives are common for Go projects. Use a temp dir and enforce that
    # extracted paths stay within it.
    with tempfile.TemporaryDirectory(prefix="ppt-extract-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        import zipfile

        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.infolist():
                name = member.filename
                if not name or name.endswith("/"):
                    continue
                out_path = (temp_dir / name).resolve()
                if not str(out_path).startswith(str(temp_dir.resolve()) + os.sep):
                    raise PptError(f"refusing to extract zip path outside destination: {name}")
            zf.extractall(temp_dir)

        for child in temp_dir.iterdir():
            shutil.move(str(child), destination / child.name)


def discover_binaries_to_link(package_dir: Path) -> list[str]:
    """Discover executable files to expose from an extracted release archive.

    `ppt` intentionally does not carry per-package knowledge. We instead apply a
    small set of generic heuristics:
    - Prefer executables in a `bin/` directory (common release layout)
    - Otherwise prefer executables at the archive root
    - Otherwise fall back to any executable file in the tree

    The returned list contains binary names (filenames) to link.
    """

    preferred: set[str] = set()
    fallback: set[str] = set()

    for path in package_dir.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if not os.access(path, os.X_OK):
            continue

        name = path.name
        lowered = name.lower()
        if lowered.endswith((".so", ".a", ".o")):
            continue
        if lowered.endswith((".txt", ".md", ".rst", ".json", ".toml", ".yaml", ".yml")):
            continue

        posix = path.as_posix()
        if "/bin/" in posix or path.parent == package_dir:
            preferred.add(name)
        fallback.add(name)

    result = sorted(preferred or fallback)
    if not result:
        raise PptError(
            f"no executable files found in {package_dir}; this release may not contain Linux binaries"
        )
    return result


def find_binary(package_dir: Path, candidates: list[str]) -> Path:
    matches: list[tuple[int, Path]] = []
    for path in package_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        matched_candidate = None
        for candidate in candidates:
            if name == candidate or name.startswith(candidate):
                matched_candidate = candidate
                break
        if matched_candidate is None:
            continue
        score = 0
        if "/bin/" in path.as_posix():
            score += 50
        if os.access(path, os.X_OK):
            score += 20
        if name == matched_candidate:
            score += 30
        score -= len(path.as_posix())
        matches.append((score, path))
    if not matches:
        raise PptError(f"failed to locate binary {candidates[0]} in {package_dir}")
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def replace_symlink(target: Path, link_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    temp_link = link_path.with_name(f".{link_path.name}.tmp")
    if temp_link.exists() or temp_link.is_symlink():
        temp_link.unlink()
    temp_link.symlink_to(target)
    os.replace(temp_link, link_path)


def fetch_release(repo: str, version: str | None) -> dict:
    host = urllib.parse.urlparse(repo).netloc
    if host == "github.com":
        return fetch_release_github(repo, version)
    # Default to GitLab semantics for non-GitHub hosts (supports gitlab.com and
    # self-hosted GitLab instances).
    return fetch_release_gitlab(repo, version)


def fetch_release_github(repo: str, version: str | None) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return fetch_release_from_html(repo, version)

    owner_repo = owner_repo_name(repo)
    if version:
        url = f"https://api.github.com/repos/{owner_repo}/releases/tags/{urllib.parse.quote(version, safe='')}"
    else:
        url = f"https://api.github.com/repos/{owner_repo}/releases/latest"

    request = urllib.request.Request(url, headers=github_headers())
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            return fetch_release_from_html(repo, version)
        if version is None and exc.code == 404:
            raise PptError(f"no release found for {repo}") from exc
        if version is not None and exc.code == 404:
            raise PptError(f"release tag {version} not found for {repo}") from exc
        raise PptError(f"failed to query releases for {repo}: {exc.reason}") from exc


def fetch_release_gitlab(repo: str, version: str | None) -> dict:
    parsed = urllib.parse.urlparse(repo)
    project_path = owner_repo_name(repo)
    project_id = urllib.parse.quote(project_path, safe="")
    api_base = f"{parsed.scheme}://{parsed.netloc}/api/v4"

    if version:
        url = f"{api_base}/projects/{project_id}/releases/{urllib.parse.quote(version, safe='')}"
    else:
        url = f"{api_base}/projects/{project_id}/releases/permalink/latest"

    request = urllib.request.Request(url, headers=gitlab_headers())
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and version is None:
            raise PptError(f"no release found for {repo}") from exc
        if exc.code == 404 and version is not None:
            raise PptError(f"release tag {version} not found for {repo}") from exc
        raise PptError(f"failed to query releases for {repo}: {exc.reason}") from exc

    assets: list[dict] = []
    for link in (payload.get("assets") or {}).get("links") or []:
        name = link.get("name")
        url = link.get("direct_asset_url") or link.get("url")
        if not name or not url:
            continue
        assets.append({"name": name, "browser_download_url": url})
    tag_name = payload.get("tag_name") or payload.get("tag") or version
    return {"tag_name": tag_name, "assets": assets}


def fetch_release_from_html(repo: str, version: str | None) -> dict:
    owner_repo = owner_repo_name(repo)
    tag = version or resolve_latest_tag(owner_repo)
    html_text = fetch_text(
        f"https://github.com/{owner_repo}/releases/expanded_assets/{urllib.parse.quote(tag, safe='')}"
    )
    assets = []
    seen = set()
    for name in parse_asset_names(html_text):
        if name in seen:
            continue
        seen.add(name)
        assets.append(
            {
                "name": name,
                "browser_download_url": github_download_url(owner_repo, tag, name),
            }
        )
    if version is not None and not assets:
        tag_page = fetch_text(
            f"https://github.com/{owner_repo}/releases/tag/{urllib.parse.quote(tag, safe='')}"
        )
        assets = [
            {
                "name": name,
                "browser_download_url": github_download_url(owner_repo, tag, name),
            }
            for name in parse_asset_names(tag_page)
        ]
    if version is not None and not assets:
        raise PptError(f"release tag {version} not found for {repo}")
    if not assets and version is None:
        raise PptError(f"no release found for {repo}")
    return {"tag_name": tag, "assets": assets}


def resolve_latest_tag(owner_repo: str) -> str:
    url = f"https://github.com/{owner_repo}/releases/latest"
    request = urllib.request.Request(url, headers=github_web_headers())
    try:
        with urllib.request.urlopen(request) as response:
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise PptError(f"no release found for https://github.com/{owner_repo}") from exc
        raise PptError(f"failed to query releases for https://github.com/{owner_repo}: {exc.reason}") from exc

    match = re.search(r"/releases/tag/([^/?#]+)", final_url)
    if not match:
        raise PptError(f"failed to resolve latest release for https://github.com/{owner_repo}")
    return urllib.parse.unquote(match.group(1))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers=github_web_headers())
    try:
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return ""
        raise PptError(f"failed to fetch {url}: {exc.reason}") from exc


def parse_asset_names(html_text: str) -> list[str]:
    matches = re.findall(
        r"([A-Za-z0-9._+-]+(?:\.tar\.gz|\.tgz|\.tar\.xz|\.tbz|\.tar\.bz2|\.zip))",
        html_text,
    )
    return [html.unescape(match) for match in matches]


def github_download_url(owner_repo: str, tag: str, name: str) -> str:
    quoted_tag = urllib.parse.quote(tag, safe="")
    quoted_name = urllib.parse.quote(name, safe="")
    return f"https://github.com/{owner_repo}/releases/download/{quoted_tag}/{quoted_name}"


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ppt/{__version__}",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_web_headers() -> dict[str, str]:
    return {"User-Agent": f"ppt/{__version__}"}


def gitlab_token() -> str | None:
    return os.environ.get("GITLAB_TOKEN") or os.environ.get("GL_TOKEN")


def gitlab_headers() -> dict[str, str]:
    headers = {"User-Agent": f"ppt/{__version__}"}
    token = gitlab_token()
    if token:
        # GitLab accepts this for both API calls and authenticated downloads.
        headers["PRIVATE-TOKEN"] = token
    return headers


def select_asset(repo: str, release: dict, platform_info: PlatformInfo) -> dict | None:
    assets = release.get("assets") or []
    scored: list[tuple[int, dict]] = []
    for asset in assets:
        score = score_asset(asset["name"], platform_info)
        if score is None:
            continue
        scored.append((score, asset))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def score_asset(name: str, platform_info: PlatformInfo) -> int | None:
    lowered = name.lower()
    if not lowered.endswith(SUPPORTED_ARCHIVES):
        return None

    if platform_info.os_name == "linux":
        if "linux" not in lowered:
            return None
    elif platform_info.os_name == "darwin":
        # Common naming across projects.
        if not any(token in lowered for token in ("darwin", "macos", "osx")):
            return None
    else:
        return None

    # Prefer arch-specific assets when present, but allow arch-agnostic assets
    # (no arch tokens) as a fallback.
    target_aliases = SUPPORTED_ARCHES[platform_info.arch]
    contains_target_arch = any(alias in lowered for alias in target_aliases)
    contains_other_arch = False
    contains_any_arch = False
    for arch, arch_aliases in SUPPORTED_ARCHES.items():
        if any(alias in lowered for alias in arch_aliases):
            contains_any_arch = True
            if arch != platform_info.arch:
                contains_other_arch = True

    # Reject other-arch assets that use an arch token we don't support.
    if not contains_target_arch and any(_contains_arch_token(lowered, tok) for tok in UNSUPPORTED_ARCH_TOKENS):
        contains_any_arch = True
        contains_other_arch = True
    if contains_other_arch and not contains_target_arch:
        return None

    score = 100
    score += 10 if platform_info.os_name in lowered else 0
    score += 20 if lowered.endswith(".tar.gz") else 0
    score += 18 if lowered.endswith(".tgz") else 0
    score += 16 if lowered.endswith(".tar.xz") else 0
    score += 14 if lowered.endswith(".tbz") or lowered.endswith(".tar.bz2") else 0
    score += 12 if lowered.endswith(".zip") else 0

    if contains_target_arch:
        score += 25
    elif not contains_any_arch:
        # Arch-agnostic: still acceptable, but worse than a correct arch match.
        score -= 40

    if platform_info.os_name == "linux":
        contains_musl = "musl" in lowered
        contains_glibc = "glibc" in lowered or "gnu" in lowered

        env = platform_info.env or ""
        is_musl_platform = env.startswith("musl")
        if is_musl_platform:
            if contains_glibc and not contains_musl:
                return None
            if contains_musl:
                score += 20
        else:
            if contains_glibc:
                score += 18
            if contains_musl:
                score += 16
            if not contains_glibc and not contains_musl:
                score += 8

    if platform_info.arch == "armv7":
        if "eabihf" in lowered:
            score += 10
        elif "armv6" in lowered:
            return None

    if "sha256" in lowered or "checksums" in lowered or "sum" in lowered:
        return None
    return score


def _contains_arch_token(lowered: str, token: str) -> bool:
    # Most upstream assets delimit arch tokens with '-' or '_' characters.
    # Prefer a loose boundary check to avoid false positives in project names.
    return re.search(rf"(?:^|[^a-z0-9_]){re.escape(token)}(?:$|[^a-z0-9_])", lowered) is not None


def normalize_repo_url(raw: str) -> str:
    text = raw.strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise PptError("only full https://... repository URLs are supported")
    if not parsed.netloc:
        raise PptError(f"invalid repository URL: {raw}")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise PptError(f"invalid repository URL: {raw}")

    # Drop UI/action suffixes if the user pasted a non-repo page URL.
    if "-" in parts:
        dash = parts.index("-")
        parts = parts[:dash]
    if len(parts) < 2:
        raise PptError(f"invalid repository URL: {raw}")

    if parts[-1].endswith(".git"):
        parts[-1] = parts[-1][:-4]
    return f"https://{parsed.netloc}/" + "/".join(parts)


def owner_repo_name(repo: str) -> str:
    parsed = urllib.parse.urlparse(repo)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise PptError(f"invalid repository URL: {repo}")
    # GitLab can have nested groups, so keep full path.
    return "/".join(parts)


def package_slug(repo: str) -> str:
    return owner_repo_name(repo).replace("/", "--")


def display_name(repo: str) -> str:
    return owner_repo_name(repo).split("/")[-1]


def resolve_package_ref(raw: str, config: list[PackageConfig]) -> str:
    if raw.startswith("http://") or raw.startswith("https://"):
        repo = normalize_repo_url(raw)
        if any(entry.repo == repo for entry in config):
            return repo
        raise PptError(f"package not configured: {repo}")

    matches = []
    for entry in config:
        owner_repo = owner_repo_name(entry.repo)
        short_name = owner_repo.split("/")[-1]
        if raw in (short_name, owner_repo):
            matches.append(entry.repo)
    if not matches:
        raise PptError(f"package not configured: {raw}")
    if len(matches) > 1:
        options = ", ".join(owner_repo_name(repo) for repo in matches)
        raise PptError(
            f"package reference is ambiguous: {raw} (matches: {options}). "
            f"Use full repo URL or owner/repo (e.g. `ppt remove {owner_repo_name(matches[0])}`)."
        )
    return matches[0]


def get_config_entry(config: list[PackageConfig], repo: str) -> PackageConfig:
    for entry in config:
        if entry.repo == repo:
            return entry
    raise PptError(f"package not configured: {repo}")


def upsert_config(config: list[PackageConfig], candidate: PackageConfig) -> list[PackageConfig]:
    updated = False
    result: list[PackageConfig] = []
    for entry in config:
        if entry.repo == candidate.repo:
            prefix = candidate.prefix if candidate.prefix is not None else entry.prefix
            constraint = candidate.constraint if candidate.constraint is not None else entry.constraint
            result.append(PackageConfig(repo=entry.repo, constraint=constraint, prefix=prefix))
            updated = True
        else:
            result.append(entry)
    if not updated:
        result.append(candidate)
    return result


def read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PptError(f"invalid state file: {path}") from exc


def write_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_lock_file(path: Path) -> dict[str, str]:
    lock: dict[str, str] = {}
    for mapping in read_toml_package_mappings(path):
        repo_raw = mapping.get("repo")
        if not repo_raw:
            raise PptError(f"package entry missing repo in {path}")
        repo = normalize_repo_url(repo_raw)
        locked = mapping.get("locked")
        if not locked:
            raise PptError(f"lock entry missing locked version in {path}")
        lock[repo] = locked
    return lock


def read_config_file(path: Path) -> list[PackageConfig]:
    config: list[PackageConfig] = []
    for mapping in read_toml_package_mappings(path):
        repo_raw = mapping.get("repo")
        if not repo_raw:
            raise PptError(f"package entry missing repo in {path}")
        repo = normalize_repo_url(repo_raw)

        constraint = mapping.get("constraint")
        prefix = mapping.get("prefix")
        config.append(PackageConfig(repo=repo, constraint=constraint, prefix=prefix))
    return config


def write_config_file(path: Path, packages: list[PackageConfig]) -> None:
    lines = ["# Managed by ppt", ""]
    for package in sorted(packages, key=lambda item: item.repo):
        lines.append("[[package]]")
        lines.append(f'repo = {toml_string(package.repo)}')
        if package.constraint is not None:
            lines.append(f'constraint = {toml_string(package.constraint)}')
        if package.prefix is not None:
            lines.append(f'prefix = {toml_string(package.prefix)}')
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_lock_file(path: Path, lock: dict[str, str]) -> None:
    lines = ["# Managed by ppt", ""]
    for repo, locked in sorted(lock.items()):
        lines.append("[[package]]")
        lines.append(f'repo = {toml_string(repo)}')
        lines.append(f'locked = {toml_string(locked)}')
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def read_toml_package_mappings(path: Path) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    if not path.exists():
        return mappings
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text == "[[package]]":
            if current is not None:
                mappings.append(current)
            current = {}
            continue
        if current is None:
            raise PptError(f"unsupported TOML structure in {path}")
        key, value = parse_key_value(text, path)
        current[key] = value
    if current is not None:
        mappings.append(current)
    return mappings


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def format_row(values: list[str]) -> str:
        # Use spaces rather than tabs so this renders consistently.
        parts = []
        for idx, value in enumerate(values):
            if idx == len(values) - 1:
                parts.append(value)
            else:
                parts.append(value.ljust(widths[idx]))
        return "  ".join(parts)

    print(format_row(headers))
    for row in rows:
        print(format_row(row))


def parse_key_value(text: str, path: Path) -> tuple[str, str]:
    if "=" not in text:
        raise PptError(f"invalid line in {path}: {text}")
    key, raw_value = text.split("=", 1)
    key = key.strip()
    value = parse_toml_string(raw_value.strip(), path)
    return key, value


def parse_toml_string(raw: str, path: Path) -> str:
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        raise PptError(f"only quoted TOML strings are supported in {path}: {raw}")
    return bytes(raw[1:-1], "utf-8").decode("unicode_escape")


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


if __name__ == "__main__":
    raise SystemExit(main())
