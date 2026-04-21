#!/usr/bin/env bash

set -euo pipefail

PPT_HOME=${PPT_HOME:-$HOME/.local/ppt}
PPT_CONFIG_DIR=${PPT_CONFIG_DIR:-$HOME/.config/ppt}
PPT_REPO_URL=${PPT_REPO_URL:-https://gitlab.com/perapp/ppt}
GITLAB_API_V4_URL=${GITLAB_API_V4_URL:-https://gitlab.com/api/v4}

SHELL_CONFIG=${PPT_INSTALL_SHELL_CONFIG:-}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --shell-config)
      SHELL_CONFIG="${2:-}"; shift 2 ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 2 ;;
  esac
done

if [ -z "$SHELL_CONFIG" ]; then
  if [ -t 0 ]; then
    SHELL_CONFIG=ask
  else
    SHELL_CONFIG=no
  fi
fi

case "$SHELL_CONFIG" in
  ask|yes|no) ;;
  *)
    printf 'invalid --shell-config value: %s (expected ask|yes|no)\n' "$SHELL_CONFIG" >&2
    exit 2
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  printf 'python3 is required to install ppt\n' >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  printf 'curl is required to install ppt\n' >&2
  exit 1
fi



ASSET_URL=${PPT_INSTALL_ASSET_URL:-}
ASSET_NAME=${PPT_INSTALL_ASSET_NAME:-}
VERSION=${PPT_INSTALL_VERSION:-}

if [ -n "$ASSET_URL" ]; then
  if [ -z "$ASSET_NAME" ]; then
    ASSET_NAME=$(python3 - <<'PY'
import os
import urllib.parse

url = os.environ.get("PPT_INSTALL_ASSET_URL", "")
parsed = urllib.parse.urlparse(url)
name = parsed.path.split("/")[-1]
print(name)
PY
    )
  fi

  if [ -z "$VERSION" ]; then
    VERSION=$(python3 - <<'PY'
import os
import re
import urllib.parse

url = os.environ.get("PPT_INSTALL_ASSET_URL", "")
name = urllib.parse.urlparse(url).path.split("/")[-1]
m = re.match(r"^ppt-(.+)-linux\.tar\.gz$", name)
if m:
    print(m.group(1))
else:
    print("local")
PY
    )
  fi
else
  # Resolve the latest release tarball from GitLab.
  readarray -t project_info < <(
    PPT_REPO_URL="$PPT_REPO_URL" python3 - <<'PY'
import os
import urllib.parse

repo = os.environ["PPT_REPO_URL"].strip()
parsed = urllib.parse.urlparse(repo)
parts = [p for p in parsed.path.split("/") if p]
if "-" in parts:
    parts = parts[: parts.index("-")]
if parts and parts[-1].endswith(".git"):
    parts[-1] = parts[-1][:-4]
if len(parts) < 2:
    raise SystemExit(1)
project_path = "/".join(parts)
project_id = urllib.parse.quote(project_path, safe="")
print(project_path)
print(project_id)
PY
  )

  PROJECT_ID=${project_info[1]}
  release_url="$GITLAB_API_V4_URL/projects/$PROJECT_ID/releases/permalink/latest"

  rel_info_raw=$(curl -fsSL "$release_url" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
tag = payload.get("tag_name") or ""
if not tag:
    raise SystemExit(1)

asset_name = f"ppt-{tag}-linux.tar.gz"
asset_url = None
for link in (payload.get("assets") or {}).get("links") or []:
    if link.get("name") == asset_name:
        asset_url = link.get("direct_asset_url") or link.get("url")
        break
if not asset_url:
    raise SystemExit(2)

print(tag)
print(asset_name)
print(asset_url)
') || {
    printf 'failed to resolve latest release asset from %s\n' "$release_url" >&2
    exit 1
  }

  readarray -t rel_info <<<"$rel_info_raw"
  VERSION=${rel_info[0]}
  ASSET_NAME=${rel_info[1]}
  ASSET_URL=${rel_info[2]}

  # GitLab package registry asset links may require authentication even for public
  # projects. Prefer the job artifact URL pattern when we detect a packages link.
  if [[ "$ASSET_URL" == *"/-/packages/generic/"* ]]; then
    ASSET_URL="$PPT_REPO_URL/-/jobs/artifacts/$VERSION/raw/dist/$ASSET_NAME?job=build_release_assets"
  fi
fi

tmp_dir=$(mktemp -d)
cleanup() { rm -rf "$tmp_dir"; }
trap cleanup EXIT

archive_path="$tmp_dir/$ASSET_NAME"
curl -fsSL "$ASSET_URL" -o "$archive_path"

extract_dir="$tmp_dir/extract"
mkdir -p "$extract_dir"
ARCHIVE_PATH="$archive_path" EXTRACT_DIR="$extract_dir" python3 - <<'PY'
import os
import tarfile
from pathlib import Path

archive_path = Path(os.environ["ARCHIVE_PATH"])
extract_dir = Path(os.environ["EXTRACT_DIR"])
with tarfile.open(archive_path, mode="r:*") as tf:
    tf.extractall(extract_dir)
PY

if [ ! -f "$extract_dir/src/ppt/__main__.py" ]; then
  printf 'downloaded release asset did not contain src/ppt\n' >&2
  exit 1
fi

shell_config_flag=("--shell-config" "$SHELL_CONFIG")

PPT_HOME="$PPT_HOME" \
PPT_CONFIG_DIR="$PPT_CONFIG_DIR" \
PPT_REPO_URL="$PPT_REPO_URL" \
PPT_INSTALL_VERSION="$VERSION" \
PPT_INSTALL_ASSET_NAME="$ASSET_NAME" \
PPT_INSTALL_ASSET_URL="$ASSET_URL" \
PYTHONPATH="$extract_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
python3 -m ppt install \
  --repo "$PPT_REPO_URL" \
  --version "$VERSION" \
  --asset-name "$ASSET_NAME" \
  --asset-url "$ASSET_URL" \
  --from-dir "$extract_dir" \
  "${shell_config_flag[@]}"
