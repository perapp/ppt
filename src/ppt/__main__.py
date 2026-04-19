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
    "x86_64": ["x86_64", "amd64"],
    "arm64": ["aarch64", "arm64"],
    "armv7": ["armv7l", "armv7", "arm"],
}

PACKAGE_BINS = {
    "eza-community/eza": {"eza": ["eza"]},
    "sharkdp/bat": {"bat": ["bat"]},
    "junegunn/fzf": {"fzf": ["fzf"]},
    "BurntSushi/ripgrep": {"rg": ["rg"]},
    "ClementTsang/bottom": {"btm": ["btm"]},
    "aristocratos/btop": {"btop": ["btop"]},
    "dandavison/delta": {"delta": ["delta"]},
    "dundee/gdu": {"gdu": ["gdu", "gdu_linux_"]},
    "astral-sh/uv": {"uv": ["uv"]},
    "helix-editor/helix": {"hx": ["hx"]},
    "neovim/neovim": {"nvim": ["nvim"]},
}

SUPPORTED_ARCHIVES = (".tar.gz", ".tgz", ".tar.xz", ".tbz", ".tar.bz2")


class PptError(Exception):
    pass


@dataclass
class PackageConfig:
    repo: str
    version: str | None = None
    prefix: str | None = None


@dataclass
class PlatformInfo:
    os_name: str
    arch: str
    libc: str

    @property
    def key(self) -> str:
        return f"{self.os_name}-{self.arch}-{self.libc}"


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

    add_parser = subparsers.add_parser("add", help="Add a package and install it")
    add_parser.add_argument("repo")
    add_parser.add_argument("--version", dest="version")
    add_parser.add_argument("--prefix", dest="prefix")
    add_parser.set_defaults(handler=cmd_add)

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

    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade unpinned packages")
    upgrade_parser.add_argument("packages", nargs="*")
    upgrade_parser.set_defaults(handler=cmd_upgrade)

    list_parser = subparsers.add_parser("list", help="List configured packages")
    list_parser.set_defaults(handler=cmd_list)

    info_parser = subparsers.add_parser("info", help="Show package details")
    info_parser.add_argument("package")
    info_parser.set_defaults(handler=cmd_info)

    return parser


def cmd_add(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    platform_info = detect_platform()
    config = read_package_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)

    repo = normalize_repo_url(args.repo)
    config_entry = PackageConfig(repo=repo, version=args.version, prefix=args.prefix)
    config = upsert_config(config, config_entry)
    write_package_file(paths.config_file, config)

    target_version = args.version or lock.get(repo)
    if target_version is None:
        release = fetch_release(repo, None)
        target_version = release["tag_name"]
    lock[repo] = target_version
    write_lock_file(paths.lock_file, lock)

    result = install_package(paths, platform_info, config_entry, target_version, state)
    write_state(paths.state_file, state)
    print(result)
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_package_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)
    repo = resolve_package_ref(args.package, config)

    config = [entry for entry in config if entry.repo != repo]
    lock.pop(repo, None)
    uninstall_package(paths, repo, state)
    write_package_file(paths.config_file, config)
    write_lock_file(paths.lock_file, lock)
    write_state(paths.state_file, state)
    print(f"removed {repo}")
    return 0


def cmd_prefix(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_package_file(paths.config_file)
    state = read_state(paths.state_file)
    repo = resolve_package_ref(args.package, config)
    entry = get_config_entry(config, repo)
    entry.prefix = args.prefix
    write_package_file(paths.config_file, config)

    repo_state = state.get(repo)
    if repo_state and repo_state.get("installed_version"):
        relink_installed_package(paths, repo, entry, repo_state)
        write_state(paths.state_file, state)
    print(f"set prefix for {repo} to {args.prefix!r}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_package_file(paths.config_file)
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
        target_version = entry.version or lock.get(entry.repo)
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
        target_version = entry.version or lock.get(entry.repo)
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
                    f"{entry.repo} installed {installed_version or '-'} but wants {target_version}"
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
    config = read_package_file(paths.config_file)
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
        if entry.version:
            messages.append(f"skipped pinned package {entry.repo} ({entry.version})")
            continue
        release = fetch_release(entry.repo, None)
        target_version = release["tag_name"]
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
    config = read_package_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)
    if not config:
        print("no packages configured")
        return 0

    print("PACKAGE\tWANTED\tLOCKED\tINSTALLED\tSTATUS\tPREFIX")
    for entry in sorted(config, key=lambda item: display_name(item.repo)):
        repo_state = state.get(entry.repo, {})
        wanted = entry.version or "latest"
        locked = lock.get(entry.repo, "-")
        installed = repo_state.get("installed_version", "-")
        status = repo_state.get("status", "configured")
        prefix = entry.prefix if entry.prefix is not None else ""
        print(
            f"{display_name(entry.repo)}\t{wanted}\t{locked}\t{installed}\t{status}\t{prefix}"
        )
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    paths = ensure_layout()
    config = read_package_file(paths.config_file)
    lock = read_lock_file(paths.lock_file)
    state = read_state(paths.state_file)
    repo = resolve_package_ref(args.package, config)
    entry = get_config_entry(config, repo)
    repo_state = state.get(repo, {})

    print(f"repo: {repo}")
    print(f"package: {display_name(repo)}")
    print(f"wanted: {entry.version or 'latest'}")
    print(f"locked: {lock.get(repo, '-')}")
    print(f"installed: {repo_state.get('installed_version', '-')}")
    print(f"status: {repo_state.get('status', 'configured')}")
    print(f"prefix: {entry.prefix if entry.prefix is not None else ''}")
    if repo_state.get("message"):
        print(f"message: {repo_state['message']}")
    if repo_state.get("bin_links"):
        print("bin links:")
        for item in repo_state["bin_links"]:
            print(f"  {item}")
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
        write_package_file(config_file, [])
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
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("armv7l", "armv7", "arm"):
        arch = "armv7"
    else:
        raise PptError(f"unsupported architecture: {machine}")

    libc = detect_libc()
    return PlatformInfo(os_name="linux", arch=arch, libc=libc)


def detect_libc() -> str:
    libc_name, _ = platform.libc_ver()
    if libc_name and libc_name.lower().startswith("glibc"):
        return "glibc"
    if libc_name and libc_name.lower().startswith("musl"):
        return "musl"

    try:
        proc = subprocess.run(
            ["ldd", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "glibc"

    text = f"{proc.stdout}\n{proc.stderr}".lower()
    if "musl" in text:
        return "musl"
    return "glibc"


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

    archive_path = download_asset(paths.cache_dir, asset)
    extract_archive(archive_path, package_dir)
    bin_links = activate_binaries(paths, entry, version, package_dir, state)
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
    expected_links = {
        str(paths.bin_dir / f"{entry.prefix or ''}{exposed_name}")
        for exposed_name in expected_binaries(entry.repo)
    }
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

    expected_bins = expected_binaries(repo)
    links: list[str] = []
    for exposed_name, candidates in expected_bins.items():
        source = find_binary(package_dir, candidates)
        link_name = f"{entry.prefix or ''}{exposed_name}"
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

    request = urllib.request.Request(
        asset["browser_download_url"],
        headers={"User-Agent": f"ppt/{__version__}"},
    )
    try:
        with urllib.request.urlopen(request) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise PptError(f"failed to download {asset['name']}: {exc.reason}") from exc
    return target


def extract_archive(archive_path: Path, destination: Path) -> None:
    if not archive_path.name.endswith(SUPPORTED_ARCHIVES):
        raise PptError(f"unsupported archive format: {archive_path.name}")
    with tempfile.TemporaryDirectory(prefix="ppt-extract-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        with tarfile.open(archive_path, mode="r:*") as archive:
            extract_kwargs = {}
            if "filter" in inspect.signature(archive.extractall).parameters:
                extract_kwargs["filter"] = "data"
            archive.extractall(temp_dir, **extract_kwargs)
        for child in temp_dir.iterdir():
            shutil.move(str(child), destination / child.name)


def expected_binaries(repo: str) -> dict[str, list[str]]:
    owner_repo = owner_repo_name(repo)
    binaries = PACKAGE_BINS.get(owner_repo)
    if binaries is None:
        raise PptError(f"unsupported MVP package: {owner_repo}")
    return binaries


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
    matches = re.findall(r"([A-Za-z0-9._+-]+(?:\.tar\.gz|\.tgz|\.tar\.xz|\.tbz|\.tar\.bz2))", html_text)
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
    if "linux" not in lowered:
        return None

    aliases = SUPPORTED_ARCHES[platform_info.arch]
    if not any(alias in lowered for alias in aliases):
        return None

    for arch, arch_aliases in SUPPORTED_ARCHES.items():
        if arch == platform_info.arch:
            continue
        if any(alias in lowered for alias in arch_aliases):
            return None

    score = 100
    score += 10 if "linux" in lowered else 0
    score += 20 if lowered.endswith(".tar.gz") else 0
    score += 18 if lowered.endswith(".tgz") else 0
    score += 16 if lowered.endswith(".tar.xz") else 0
    score += 14 if lowered.endswith(".tbz") or lowered.endswith(".tar.bz2") else 0

    contains_musl = "musl" in lowered
    contains_glibc = "glibc" in lowered or "gnu" in lowered
    if platform_info.libc == "musl":
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


def normalize_repo_url(raw: str) -> str:
    text = raw.strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise PptError("MVP only supports full https://github.com/... repository URLs")
    if parsed.netloc != "github.com":
        raise PptError("MVP only supports github.com repositories")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise PptError(f"invalid GitHub repository URL: {raw}")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    normalized = f"https://github.com/{owner}/{repo}"
    return normalized


def owner_repo_name(repo: str) -> str:
    parsed = urllib.parse.urlparse(repo)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise PptError(f"invalid repository URL: {repo}")
    return f"{parts[0]}/{parts[1]}"


def package_slug(repo: str) -> str:
    return owner_repo_name(repo).replace("/", "--")


def display_name(repo: str) -> str:
    return owner_repo_name(repo).split("/", 1)[1]


def resolve_package_ref(raw: str, config: list[PackageConfig]) -> str:
    if raw.startswith("http://") or raw.startswith("https://"):
        repo = normalize_repo_url(raw)
        if any(entry.repo == repo for entry in config):
            return repo
        raise PptError(f"package not configured: {repo}")

    matches = []
    for entry in config:
        owner_repo = owner_repo_name(entry.repo)
        short_name = owner_repo.split("/", 1)[1]
        if raw in (short_name, owner_repo):
            matches.append(entry.repo)
    if not matches:
        raise PptError(f"package not configured: {raw}")
    if len(matches) > 1:
        raise PptError(f"package reference is ambiguous: {raw}")
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
            version = candidate.version if candidate.version is not None else entry.version
            result.append(PackageConfig(repo=entry.repo, version=version, prefix=prefix))
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


def read_package_file(path: Path) -> list[PackageConfig]:
    packages = []
    if not path.exists():
        return packages
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text == "[[package]]":
            if current is not None:
                packages.append(package_from_mapping(current, path))
            current = {}
            continue
        if current is None:
            raise PptError(f"unsupported TOML structure in {path}")
        key, value = parse_key_value(text, path)
        current[key] = value
    if current is not None:
        packages.append(package_from_mapping(current, path))
    return packages


def read_lock_file(path: Path) -> dict[str, str]:
    lock: dict[str, str] = {}
    for package in read_package_file(path):
        if not package.version:
            raise PptError(f"lock entry missing version in {path}")
        lock[package.repo] = package.version
    return lock


def write_package_file(path: Path, packages: list[PackageConfig]) -> None:
    lines = ["# Managed by ppt", ""]
    for package in sorted(packages, key=lambda item: item.repo):
        lines.append("[[package]]")
        lines.append(f'repo = {toml_string(package.repo)}')
        if package.version is not None:
            lines.append(f'version = {toml_string(package.version)}')
        if package.prefix is not None:
            lines.append(f'prefix = {toml_string(package.prefix)}')
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_lock_file(path: Path, lock: dict[str, str]) -> None:
    packages = [PackageConfig(repo=repo, version=version) for repo, version in sorted(lock.items())]
    write_package_file(path, packages)


def package_from_mapping(mapping: dict[str, str], path: Path) -> PackageConfig:
    repo = mapping.get("repo")
    if not repo:
        raise PptError(f"package entry missing repo in {path}")
    return PackageConfig(repo=normalize_repo_url(repo), version=mapping.get("version"), prefix=mapping.get("prefix"))


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
