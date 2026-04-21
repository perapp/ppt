from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest


pytestmark = pytest.mark.container


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("failed to locate repo root")


def _container_runtime() -> str:
    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    pytest.skip("no container runtime found (need podman or docker)")
    raise AssertionError("unreachable")


def _repo_path_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if "-" in parts:
        parts = parts[: parts.index("-")]
    if parts and parts[-1].endswith(".git"):
        parts[-1] = parts[-1][:-4]
    return "/".join(parts)


def test_install_script_works_in_minimal_ubuntu_container() -> None:
    runtime = _container_runtime()
    repo_root = _repo_root()

    repo_url = os.environ.get("CI_PROJECT_URL") or "https://gitlab.com/perapp/ppt"
    expected_repo_name = _repo_path_from_url(repo_url)

    # Create a minimal workspace that mimics release assets.
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        (workspace / "dist").mkdir(parents=True)
        installer = workspace / "dist" / "install.sh"
        tarball = workspace / "dist" / "ppt-sandbox-linux.tar.gz"

        subprocess.run(
            [
                "python3",
                str(repo_root / "dev" / "render_install_sh.py"),
                "--template",
                str(repo_root / "install.sh.template"),
                "--out",
                str(installer),
                "--repo-url",
                repo_url,
                "--version",
                "sandbox",
            ],
            check=True,
            cwd=repo_root,
        )

        # Build a tarball matching release layout.
        with tempfile.TemporaryDirectory() as asset_td:
            tmp = Path(asset_td)
            (tmp / "bin").mkdir(parents=True)
            (tmp / "src").mkdir(parents=True)
            launcher = tmp / "bin" / "ppt"
            launcher.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_PATH="$0"
if command -v readlink >/dev/null 2>&1; then
  SCRIPT_PATH=$(readlink -f -- "$0" 2>/dev/null || printf '%s' "$0")
fi
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")/.." && pwd)
export PYTHONPATH="$APP_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m ppt "$@"
""",
                encoding="utf-8",
            )
            launcher.chmod(0o755)

            with tarfile.open(tarball, "w:gz") as tf:
                tf.add(tmp / "bin", arcname="bin")
                tf.add(repo_root / "src" / "ppt", arcname="src/ppt")

        volume = f"{workspace}:/workspace"
        if runtime == "podman":
            volume = f"{workspace}:/workspace:Z"

        env_flags = [
            "-e",
            f"PPT_REPO_URL={repo_url}",
            "-e",
            "PPT_INSTALL_ASSET_URL=file:///workspace/dist/ppt-sandbox-linux.tar.gz",
        ]

        cmd = [
            runtime,
            "run",
            "--rm",
            "-v",
            volume,
            "-w",
            "/workspace",
            *env_flags,
            "ubuntu:24.04",
            "bash",
            "-lc",
            "apt-get update -qq && apt-get install -y -qq curl ca-certificates python3 tar >/dev/null && bash ./dist/install.sh --shell-config no && /root/.local/ppt/bin/ppt list",
        ]

        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        assert expected_repo_name in proc.stdout
