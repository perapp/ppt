from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import uuid
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
            (tmp / "python" / "bin").mkdir(parents=True)
            (tmp / "venv" / "site-packages").mkdir(parents=True)

            # Stub "bundled" python.
            py = tmp / "python" / "bin" / "python3"
            py.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
exec python3 "$@"
""",
                encoding="utf-8",
            )
            py.chmod(0o755)

            # Bundle ppt sources into venv/site-packages.
            shutil.copytree(repo_root / "src" / "ppt", tmp / "venv" / "site-packages" / "ppt")

            # Stub rich so imports work in a minimal container.
            rich_dir = tmp / "venv" / "site-packages" / "rich"
            rich_dir.mkdir(parents=True, exist_ok=True)
            (rich_dir / "__init__.py").write_text("from . import box\n", encoding="utf-8")
            (rich_dir / "box.py").write_text("ASCII = object()\n", encoding="utf-8")
            (rich_dir / "console.py").write_text(
                """class Console:
    def __init__(self, *args, **kwargs):
        pass

    def print(self, *args, **kwargs):
        if args:
            import builtins

            builtins.print(*args)
""",
                encoding="utf-8",
            )
            (rich_dir / "progress.py").write_text(
                """class SpinnerColumn: ...
class TextColumn:
    def __init__(self, *args, **kwargs):
        pass

class BarColumn:
    def __init__(self, *args, **kwargs):
        pass

class TaskProgressColumn: ...
class TimeElapsedColumn: ...

class Progress:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add_task(self, *args, **kwargs):
        return 1

    def update(self, *args, **kwargs):
        pass

    def advance(self, *args, **kwargs):
        pass
""",
                encoding="utf-8",
            )
            (rich_dir / "table.py").write_text(
                """class Table:
    def __init__(self, *args, **kwargs):
        self.rows = []

    def add_column(self, *args, **kwargs):
        pass

    def add_row(self, *args, **kwargs):
        self.rows.append(args)
""",
                encoding="utf-8",
            )

            # Launcher matches what we publish in GitLab release assets.
            launcher = tmp / "bin" / "ppt"
            launcher.write_text(
                """#!/usr/bin/env bash
set -euo pipefail

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
export PYTHONPATH="$APP_DIR/venv/site-packages${PYTHONPATH:+:$PYTHONPATH}"
exec "$APP_DIR/python/bin/python3" -m ppt "$@"
""",
                encoding="utf-8",
            )
            launcher.chmod(0o755)

            with tarfile.open(tarball, "w:gz") as tf:
                tf.add(tmp / "bin", arcname="bin")
                tf.add(tmp / "python", arcname="python")
                tf.add(tmp / "venv", arcname="venv")

        env_flags = [
            "-e",
            f"PPT_REPO_URL={repo_url}",
            "-e",
            "PPT_INSTALL_ASSET_URL=file:///workspace/dist/ppt-sandbox-linux.tar.gz",
        ]

        # In GitLab CI we use docker:dind (remote daemon). Bind mounts from the
        # job container filesystem won't exist inside the dind daemon, so the
        # container won't see the workspace. Detect that case and fall back to a
        # tiny image build that copies the workspace into the image.
        remote_docker = runtime == "docker" and (os.environ.get("DOCKER_HOST") or "").startswith("tcp://")
        if remote_docker:
            dockerfile = workspace / "Dockerfile"
            dockerfile.write_text(
                """FROM ubuntu:24.04
WORKDIR /workspace
COPY dist/ /workspace/dist/
""",
                encoding="utf-8",
            )
            image = f"ppt-test-install:{uuid.uuid4().hex}"
            subprocess.run([runtime, "build", "-t", image, str(workspace)], check=True, capture_output=True)
            try:
                cmd = [
                    runtime,
                    "run",
                    "--rm",
                    *env_flags,
                    image,
                    "bash",
                    "-lc",
                    "apt-get update -qq && apt-get install -y -qq curl ca-certificates python3 tar >/dev/null && bash ./dist/install.sh --shell-config no && /root/.local/ppt/bin/ppt list",
                ]
                proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
                assert expected_repo_name in proc.stdout
            finally:
                subprocess.run([runtime, "rmi", "-f", image], check=False, capture_output=True)
            return

        volume = f"{workspace}:/workspace"
        if runtime == "podman":
            volume = f"{workspace}:/workspace:Z"

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
