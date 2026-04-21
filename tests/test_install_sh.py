from __future__ import annotations

import os
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest


pytestmark = pytest.mark.slow


def _make_ppt_release_asset(repo_root: Path, out_path: Path) -> None:
    """Create a tarball matching the published ppt release asset layout."""

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "bin").mkdir(parents=True)
        (tmp / "src").mkdir(parents=True)

        # Launcher matches what we publish in GitLab release assets.
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

        # Include the real project sources.
        with tarfile.open(out_path, "w:gz") as tf:
            tf.add(tmp / "bin", arcname="bin")
            tf.add(repo_root / "src" / "ppt", arcname="src/ppt")


def test_install_script_bootstraps_self_managed_ppt(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    version = "v9.9.9"
    asset_name = f"ppt-{version}-linux.tar.gz"
    asset_url = f"https://example.invalid/{asset_name}"
    api_url = "https://example.invalid/api/v4"
    project_id = "perapp%2Fppt"
    latest_release_url = f"{api_url}/projects/{project_id}/releases/permalink/latest"

    tarball = tmp_path / asset_name
    _make_ppt_release_asset(repo_root, tarball)

    # Stub `curl` to avoid network access.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

out=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o)
      out="$2"; shift 2 ;;
    http://*|https://*)
      url="$1"; shift ;;
    *)
      shift ;;
  esac
done

if [ "$url" = "$PPT_TEST_RELEASE_URL" ]; then
  cat <<EOF
{"tag_name":"$PPT_TEST_TAG","assets":{"links":[{"name":"$PPT_TEST_ASSET_NAME","url":"$PPT_TEST_ASSET_URL"}]}}
EOF
  exit 0
fi

if [[ "$url" == */releases/permalink/latest ]]; then
  # Be tolerant of API base variations.
  cat <<EOF
{"tag_name":"$PPT_TEST_TAG","assets":{"links":[{"name":"$PPT_TEST_ASSET_NAME","url":"$PPT_TEST_ASSET_URL"}]}}
EOF
  exit 0
fi

if [ "$url" = "$PPT_TEST_ASSET_URL" ]; then
  if [ -n "$out" ]; then
    cp "$PPT_TEST_TARBALL" "$out"
  else
    cat "$PPT_TEST_TARBALL"
  fi
  exit 0
fi

printf 'unexpected curl url: %s\n' "$url" >&2
exit 2
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
            "PPT_REPO_URL": "https://gitlab.com/perapp/ppt",
            "GITLAB_API_V4_URL": api_url,
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "PPT_TEST_RELEASE_URL": latest_release_url,
            "PPT_TEST_TAG": version,
            "PPT_TEST_ASSET_NAME": asset_name,
            "PPT_TEST_ASSET_URL": asset_url,
            "PPT_TEST_TARBALL": str(tarball),
        }
    )

    subprocess.run(["bash", str(repo_root / "install.sh")], cwd=tmp_path, env=env, check=True)

    launcher = ppt_home / "bin" / "ppt"
    assert launcher.exists()
    assert not launcher.is_symlink()
    assert launcher.stat().st_mode & stat.S_IXUSR

    packages_toml = (ppt_config / "packages.toml").read_text(encoding="utf-8")
    assert "https://gitlab.com/perapp/ppt" in packages_toml
    lock_toml = (ppt_config / "packages.lock.toml").read_text(encoding="utf-8")
    assert version in lock_toml

    # The installed ppt should report itself as the single configured package.
    proc = subprocess.run(
        [str(launcher), "list"],
        env={"PPT_HOME": str(ppt_home), "PPT_CONFIG_DIR": str(ppt_config), "PATH": env["PATH"]},
        check=True,
        capture_output=True,
        text=True,
    )
    assert "perapp/ppt" in proc.stdout
