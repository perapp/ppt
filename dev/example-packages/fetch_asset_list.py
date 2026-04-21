#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
import zipfile
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_ARCHIVES = (
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".tar.bz2",
    ".tbz",
    ".tbz2",
    ".zip",
)


SLEEP_SECONDS_WITH_TOKEN = 0.2
SLEEP_SECONDS_NO_TOKEN = 2.0


class NoRelease(Exception):
    pass


class RepoNotFound(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, message: str, *, reset_epoch: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.reset_epoch = reset_epoch
        self.retry_after = retry_after


def main() -> int:
    load_dotenv_from_repo_root()

    has_token = bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    sleep_seconds = SLEEP_SECONDS_WITH_TOKEN if has_token else SLEEP_SECONDS_NO_TOKEN
    if not has_token:
        print("WARN: no GH_TOKEN/GITHUB_TOKEN found; GitHub API is limited and may rate limit quickly")

    ap = argparse.ArgumentParser(
        description=(
            "Fetch latest release assets for a project URL and write an asset list JSON, "
            "including archive contents for zip/tarball assets."
        )
    )
    ap.add_argument(
        "project_urls",
        nargs="*",
        help=(
            "Project URL(s), e.g. https://github.com/neovim/neovim. "
            "If omitted, packages are read from packages.txt in --base-dir."
        ),
    )
    ap.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Base directory for output (default: directory containing this script)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing JSON outputs (default: skip if output exists)",
    )
    ap.add_argument(
        "--max-asset-bytes",
        type=int,
        default=500 * 1024 * 1024,
        help="Skip downloading assets larger than this (default: 500MB)",
    )
    args = ap.parse_args()

    urls = list(args.project_urls)
    if not urls:
        urls = read_packages_txt(args.base_dir / "packages.txt")

    total = len(urls)
    try:
        for idx, url in enumerate(urls, start=1):
            pct = (idx / total * 100.0) if total else 100.0
            print(f"{idx}/{total} {pct:.2f}% {url}")
            attempted = False
            try:
                out_path, attempted = process_one(
                    url,
                    base_dir=args.base_dir,
                    max_asset_bytes=args.max_asset_bytes,
                    force=args.force,
                )
                _ = out_path
            except RateLimited as exc:
                msg = "GitHub API rate limit exceeded"
                when = None
                if exc.retry_after is not None:
                    when = time.time() + exc.retry_after
                elif exc.reset_epoch is not None:
                    when = float(exc.reset_epoch)
                if when is not None:
                    msg += f" (resets at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(when))})"
                msg += ". Ensure GH_TOKEN/GITHUB_TOKEN is available (repo-root .env is supported) and rerun."
                print(f"RATE LIMITED: {msg}")
                return 2
            except Exception as exc:
                print(f"ERROR: {url}: {exc}")
            finally:
                # Be polite to the GitHub API and reduce the chance of secondary rate limiting.
                if attempted and sleep_seconds > 0:
                    time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        # Writes are atomic; safe to restart.
        return 130
    return 0


def read_packages_txt(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"No project URLs provided and {path} does not exist")
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        out.append(s)
    return out


def load_dotenv_from_repo_root() -> None:
    """Load optional repo-root .env (same approach as tests/conftest.py).

    This allows local tokens (GH_TOKEN/GITLAB_TOKEN) without exporting them globally.
    """

    repo_root = _repo_root()
    env_path = repo_root / ".env"
    if not env_path.exists():
        return

    # If a token var is present but empty, allow `.env` to populate it.
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GL_TOKEN", "GITLAB_TOKEN"):
        if key in os.environ and not os.environ[key]:
            del os.environ[key]

    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path, override=False)
    except Exception:
        # Keep this script runnable with system python.
        _load_dotenv_fallback(env_path)


def _load_dotenv_fallback(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines).

    Only sets variables that are missing or empty.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        # Strip surrounding quotes.
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]

        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = value


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[1]


def process_one(project_url: str, *, base_dir: Path, max_asset_bytes: int, force: bool) -> tuple[Path | None, bool]:
    repo = parse_github_repo(project_url)
    out_path = asset_list_path(base_dir, repo)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not force:
        return None, False

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        rel = fetch_latest_release_github(repo)
    except NoRelease:
        write_json_atomic(
            out_path,
            {"__meta__": {"repo": project_url, "status": "no_release", "fetched_at": fetched_at}},
        )
        return out_path, True
    except RepoNotFound:
        write_json_atomic(
            out_path,
            {"__meta__": {"repo": project_url, "status": "not_found", "fetched_at": fetched_at}},
        )
        return out_path, True

    out: dict[str, dict] = {
        "__meta__": {
            "repo": project_url,
            "status": "ok",
            "fetched_at": fetched_at,
            "release_tag": rel.tag,
            "release_url": rel.html_url,
            "published_at": rel.published_at,
        }
    }
    for a in rel.assets:
        info: dict[str, object] = {
            "name": a.name,
            "url": a.url,
            "content_type": a.content_type,
            "size": a.size,
            "release_tag": rel.tag,
            "release_url": rel.html_url,
            "published_at": rel.published_at,
        }

        if is_supported_archive(a.name):
            if a.size is not None and a.size > max_asset_bytes:
                info["archive"] = {"skipped": True, "reason": "too_large"}
            else:
                info["archive"] = inspect_archive(a)

        out[a.name] = info

    write_json_atomic(out_path, out)
    return out_path, True


def write_json_atomic(path: Path, obj: object) -> None:
    # Atomic write so kill/restart never leaves a partial JSON output.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp = Path(f.name)
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def asset_list_path(base_dir: Path, repo: "GitHubRepo") -> Path:
    # Required shape: ./asset-lists/github.com/<owner>/<repo>.json
    return base_dir / "asset-lists" / repo.host / repo.owner / f"{repo.name}.json"


def is_supported_archive(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(ext) for ext in SUPPORTED_ARCHIVES)


@dataclass(frozen=True)
class GitHubRepo:
    host: str
    owner: str
    name: str


def parse_github_repo(url: str) -> GitHubRepo:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    if host != "github.com":
        raise SystemExit(f"Only github.com is supported right now (got: {host!r})")
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        raise SystemExit(f"Invalid GitHub repo URL: {url!r}")
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    return GitHubRepo(host=host, owner=owner, name=name)


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    content_type: str | None
    size: int | None


@dataclass(frozen=True)
class Release:
    tag: str
    html_url: str
    published_at: str | None
    assets: list[ReleaseAsset]


def fetch_latest_release_github(repo: GitHubRepo) -> Release:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    url = f"https://api.github.com/repos/{repo.owner}/{repo.name}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ppt-example-packages",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            if github_repo_exists(repo, headers=headers):
                raise NoRelease()
            raise RepoNotFound()
        if exc.code in (403, 429):
            body = b""
            try:
                body = exc.read(4096) or b""
            except Exception:
                pass
            text = body.decode("utf-8", errors="ignore").lower()
            remaining = (exc.headers.get("X-RateLimit-Remaining") or "").strip()
            reset = (exc.headers.get("X-RateLimit-Reset") or "").strip()
            retry_after = (exc.headers.get("Retry-After") or "").strip()
            if remaining == "0" or "rate limit" in text:
                reset_epoch = int(reset) if reset.isdigit() else None
                retry = int(retry_after) if retry_after.isdigit() else None
                raise RateLimited("rate limit exceeded", reset_epoch=reset_epoch, retry_after=retry)
        raise

    tag = payload.get("tag_name") or ""
    html_url = payload.get("html_url") or f"https://github.com/{repo.owner}/{repo.name}/releases/latest"
    published_at = payload.get("published_at")

    assets: list[ReleaseAsset] = []
    for a in payload.get("assets") or []:
        name = a.get("name")
        dl = a.get("browser_download_url")
        if not name or not dl:
            continue
        assets.append(
            ReleaseAsset(
                name=name,
                url=dl,
                content_type=a.get("content_type"),
                size=a.get("size"),
            )
        )

    return Release(tag=tag, html_url=html_url, published_at=published_at, assets=assets)


def github_repo_exists(repo: GitHubRepo, *, headers: dict[str, str]) -> bool:
    url = f"https://api.github.com/repos/{repo.owner}/{repo.name}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return 200 <= int(resp.status) < 300
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        # For other failures (403, transient), conservatively assume it exists.
        return True


def inspect_archive(asset: ReleaseAsset) -> dict:
    # Keep it simple for now: download to a temp file and inspect locally.
    headers = {"User-Agent": "ppt-example-packages"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(asset.url, headers=headers)

    suffix = Path(asset.name).suffix
    # Preserve multi-suffix for .tar.gz, etc.
    lower = asset.name.lower()
    if lower.endswith(".tar.gz"):
        suffix = ".tar.gz"
    elif lower.endswith(".tar.bz2"):
        suffix = ".tar.bz2"
    elif lower.endswith(".tar.xz"):
        suffix = ".tar.xz"

    with tempfile.NamedTemporaryFile(prefix="asset-", suffix=suffix, delete=True) as tf:
        with urllib.request.urlopen(req) as resp:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                tf.write(chunk)
        tf.flush()

        if asset.name.lower().endswith(".zip"):
            return inspect_zip(Path(tf.name))
        return inspect_tar(Path(tf.name))


def _clean_member_name(name: str) -> str:
    return (name or "").lstrip("./")


def inspect_tar(path: Path) -> dict:
    members: list[dict] = []
    total_member_bytes = 0
    with tarfile.open(path, mode="r:*") as tf:
        for m in tf.getmembers():
            n = _clean_member_name(m.name)
            if not n:
                continue
            size = int(m.size or 0)
            total_member_bytes += size
            is_file = m.isfile()
            mode = int(m.mode or 0)
            is_exec = bool(is_file and (mode & 0o111))
            kind = "other"
            if m.isdir():
                kind = "dir"
            elif m.isfile():
                kind = "file"
            elif m.issym():
                kind = "symlink"
            elif m.islnk():
                kind = "hardlink"
            members.append(
                {
                    "path": n,
                    "type": kind,
                    "size": size,
                    "mode": mode,
                    "is_exec": is_exec,
                    "linkname": m.linkname or "",
                    "uid": int(m.uid or 0),
                    "gid": int(m.gid or 0),
                    "uname": m.uname or "",
                    "gname": m.gname or "",
                    "mtime": int(m.mtime or 0),
                }
            )
    return {
        "type": "tar",
        "member_count": len(members),
        "total_member_bytes": total_member_bytes,
        "members": members,
    }


def inspect_zip(path: Path) -> dict:
    members: list[dict] = []
    total_member_bytes = 0
    with zipfile.ZipFile(path) as zf:
        for zi in zf.infolist():
            n = _clean_member_name(zi.filename)
            if not n:
                continue
            is_dir = n.endswith("/") or zi.is_dir()
            n = n[:-1] if is_dir and n.endswith("/") else n
            size = int(zi.file_size or 0)
            total_member_bytes += size
            # Unix mode, if present.
            mode = int((zi.external_attr >> 16) & 0o777)
            is_exec = bool((not is_dir) and (mode & 0o111))
            members.append(
                {
                    "path": n,
                    "type": "dir" if is_dir else "file",
                    "size": size,
                    "compressed_size": int(zi.compress_size or 0),
                    "mode": mode,
                    "is_exec": is_exec,
                    "crc": int(zi.CRC or 0),
                }
            )
    return {
        "type": "zip",
        "member_count": len(members),
        "total_member_bytes": total_member_bytes,
        "members": members,
    }


if __name__ == "__main__":
    raise SystemExit(main())
