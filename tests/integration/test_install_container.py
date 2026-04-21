from __future__ import annotations

import os
import shutil
import subprocess
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

    volume = f"{repo_root}:/workspace"
    if runtime == "podman":
        volume = f"{repo_root}:/workspace:Z"

    env_flags = ["-e", f"PPT_REPO_URL={repo_url}"]

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
        "apt-get update -qq && apt-get install -y -qq curl ca-certificates python3 tar >/dev/null && bash ./install.sh && /root/.local/ppt/bin/ppt list",
    ]

    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert expected_repo_name in proc.stdout
