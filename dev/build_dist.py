#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(argv, cwd=str(cwd) if cwd else None, env=env, check=True)


def read_runtime_dependencies(pyproject_toml: Path) -> list[str]:
    import tomllib

    data = tomllib.loads(pyproject_toml.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if not isinstance(deps, list):
        raise SystemExit(f"error: expected [project].dependencies to be a list in {pyproject_toml}")
    return [str(d).strip() for d in deps if str(d).strip()]


def pbs_asset_name(*, cpython: str, tag: str, target: str, flavor: str) -> str:
    if flavor not in {"install_only", "install_only_stripped"}:
        raise SystemExit(f"error: unsupported python-build-standalone flavor: {flavor}")
    suffix = "install_only.tar.gz" if flavor == "install_only" else "install_only_stripped.tar.gz"
    return f"cpython-{cpython}+{tag}-{target}-{suffix}"


def pbs_download_url(*, tag: str, asset_name: str) -> str:
    return f"https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/{asset_name}"


def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def write_ppt_launcher(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

# Resolve symlinks (the stable launcher installed by `ppt install` is a symlink).
SCRIPT_PATH="$0"
if command -v readlink >/dev/null 2>&1; then
  while [ -L "$SCRIPT_PATH" ]; do
    base_dir=$(CDPATH= cd -- "$(dirname "$SCRIPT_PATH")" && pwd)
    link=$(readlink "$SCRIPT_PATH" || true)
    if [ -z "$link" ]; then
      break
    fi
    case "$link" in
      /*) SCRIPT_PATH="$link" ;;
      *) SCRIPT_PATH="$base_dir/$link" ;;
    esac
  done
fi

APP_DIR=$(CDPATH= cd -- "$(dirname "$SCRIPT_PATH")/.." && pwd)

PY="$APP_DIR/python/bin/python3"
if [ ! -x "$PY" ]; then
  printf '%s\n' "error: missing bundled python: $PY" >&2
  exit 2
fi

export PYTHONPATH="$APP_DIR/venv/site-packages${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m ppt "$@"
""",
        encoding="utf-8",
    )
    ensure_executable(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ppt release asset tarball using python-build-standalone")
    parser.add_argument("--target", required=True, help="Rust-style target triple (e.g. x86_64-unknown-linux-gnu)")
    parser.add_argument("--version", required=True, help="ppt version string (used for logging only)")
    parser.add_argument("--pbs-tag", required=True, help="python-build-standalone release tag (e.g. 20260414)")
    parser.add_argument("--cpython", required=True, help="CPython version (e.g. 3.12.13)")
    parser.add_argument(
        "--flavor",
        default="install_only_stripped",
        choices=("install_only", "install_only_stripped"),
        help="python-build-standalone artifact flavor",
    )
    parser.add_argument("--out", required=True, help="Output tar.gz path")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    pyproject = repo_root / "pyproject.toml"
    src_dir = repo_root / "src" / "ppt"
    if not pyproject.exists() or not src_dir.exists():
        raise SystemExit(f"error: expected repo layout at {repo_root}")

    target = args.target
    # Known unsupported target in our release matrix: python-build-standalone does not publish armv7 musl.
    if target == "armv7-unknown-linux-musleabihf":
        raise SystemExit(
            "error: python-build-standalone does not publish CPython install_only tarballs for "
            "armv7-unknown-linux-musleabihf"
        )

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    asset = pbs_asset_name(cpython=args.cpython, tag=args.pbs_tag, target=target, flavor=args.flavor)
    url = pbs_download_url(tag=args.pbs_tag, asset_name=asset)

    cache_dir = repo_root / "dist" / ".cache" / "python-build-standalone" / args.pbs_tag
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / asset
    if not archive_path.exists():
        run(["curl", "-fsSL", url, "-o", str(archive_path)])

    with tempfile.TemporaryDirectory(prefix="ppt-dist-") as td:
        stage = Path(td) / "root"
        stage.mkdir(parents=True)

        # Extract python-build-standalone archive.
        run(["tar", "-xzf", str(archive_path), "-C", str(stage)])

        python_dir = stage / "python"
        python_exe = python_dir / "bin" / "python3"
        if not python_exe.exists():
            raise SystemExit(f"error: expected python/bin/python3 in python-build-standalone archive: {archive_path}")

        site_dir = stage / "venv" / "site-packages"
        site_dir.mkdir(parents=True, exist_ok=True)

        # Install runtime dependencies using the build host Python.
        # We intentionally do not execute the bundled Python here so that we can
        # build tarballs for non-native targets on a single runner.
        deps = read_runtime_dependencies(pyproject)
        if deps:
            env = os.environ.copy()
            env.update(
                {
                    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                    "PIP_NO_CACHE_DIR": "1",
                    "PYTHONNOUSERSITE": "1",
                }
            )
            run([sys.executable, "-m", "pip", "install", "--target", str(site_dir), *deps], env=env)

        # Bundle ppt sources directly (the project is not currently wheel-installable).
        shutil.copytree(src_dir, site_dir / "ppt", dirs_exist_ok=True)

        bin_dir = stage / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        write_ppt_launcher(bin_dir / "ppt")

        # Create the release asset.
        tmp_out = out_path.with_suffix(out_path.suffix + ".tmp")
        if tmp_out.exists():
            tmp_out.unlink()
        run(["tar", "-C", str(stage), "-czf", str(tmp_out), "bin", "python", "venv"])
        tmp_out.replace(out_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
