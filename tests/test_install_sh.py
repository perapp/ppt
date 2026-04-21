from __future__ import annotations

import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest


pytestmark = pytest.mark.slow


def _make_hosted_archive(path: Path) -> None:
    # Matches install.sh expectation: a top-level directory containing `src/`.
    top = "ppt-main"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in {
            f"{top}/src/ppt/__init__.py": "__all__ = []\n",
            f"{top}/src/ppt/__main__.py": "def main():\n    return 0\n",
        }.items():
            tmp = path.parent / "_tmp"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(data, encoding="utf-8")
            archive.add(tmp, arcname=name)
            tmp.unlink()


def test_install_script_from_stdin_uses_hosted_path(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    install_sh = (repo_root / "install.sh").read_text(encoding="utf-8")

    tarball = tmp_path / "ppt-main.tar.gz"
    _make_hosted_archive(tarball)

    # Regression guard: when invoked via stdin, the installer must NOT treat the
    # current working directory as a local checkout even if it contains `src/`.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "not_ppt.txt").write_text("nope\n", encoding="utf-8")

    # Stub `curl` so the installer never hits the network.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
cat "$PPT_TEST_TARBALL"
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    ppt_home = tmp_path / "home"
    ppt_config = tmp_path / "config"

    env = os.environ.copy()
    env.update(
        {
            "PPT_HOME": str(ppt_home),
            "PPT_CONFIG_DIR": str(ppt_config),
            "PPT_ARCHIVE_URL": "https://example.invalid/ppt.tar.gz",
            "PPT_TEST_TARBALL": str(tarball),
            "PATH": f"{bin_dir}:{env.get('PATH','')}",
        }
    )

    # Simulate `curl ... | bash` by feeding the script on stdin.
    subprocess.run(
        ["bash", "-s"],
        input=install_sh,
        text=True,
        cwd=tmp_path,
        env=env,
        check=True,
    )

    assert (ppt_home / "app" / "current" / "src" / "ppt" / "__main__.py").exists()
    assert not (ppt_home / "app" / "current" / "src" / "not_ppt.txt").exists()
    launcher = ppt_home / "bin" / "ppt"
    assert launcher.exists()
    assert launcher.stat().st_mode & stat.S_IXUSR


def test_install_script_from_checkout_copies_src(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    ppt_home = tmp_path / "home"
    ppt_config = tmp_path / "config"
    env = os.environ.copy()
    env.update({"PPT_HOME": str(ppt_home), "PPT_CONFIG_DIR": str(ppt_config)})

    subprocess.run(
        ["bash", str(repo_root / "install.sh")],
        cwd=repo_root,
        env=env,
        check=True,
    )

    # Local-checkout install should have copied the real project sources.
    assert (ppt_home / "app" / "current" / "src" / "ppt" / "__main__.py").exists()
    assert (ppt_home / "bin" / "ppt").exists()
