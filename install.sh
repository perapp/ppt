#!/usr/bin/env bash

set -euo pipefail

PPT_HOME=${PPT_HOME:-$HOME/.local/ppt}
PPT_CONFIG_DIR=${PPT_CONFIG_DIR:-$HOME/.config/ppt}
BIN_DIR="$PPT_HOME/bin"
PPT_REPO_URL=${PPT_REPO_URL:-https://gitlab.com/perapp/ppt}
GITLAB_API_V4_URL=${GITLAB_API_V4_URL:-https://gitlab.com/api/v4}

if ! command -v python3 >/dev/null 2>&1; then
  printf 'python3 is required to install ppt\n' >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  printf 'curl is required to install ppt\n' >&2
  exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
  printf 'tar is required to install ppt\n' >&2
  exit 1
fi

mkdir -p "$PPT_HOME" "$PPT_CONFIG_DIR" "$BIN_DIR" "$PPT_HOME/cache/downloads" "$PPT_HOME/packages"

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

PROJECT_PATH=${project_info[0]}
PROJECT_ID=${project_info[1]}
SLUG=${PROJECT_PATH//\//--}

release_url="$GITLAB_API_V4_URL/projects/$PROJECT_ID/releases/permalink/latest"

rel_info_raw=$(
  curl -fsSL "$release_url" | python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except json.JSONDecodeError:
    raise SystemExit(3)

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
'
) || {
  rc=$?
  if [ "$rc" -eq 3 ]; then
    printf 'failed to parse release metadata from %s\n' "$release_url" >&2
  else
    printf 'failed to resolve latest release asset from %s\n' "$release_url" >&2
  fi
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

ASSET_PATH="$PPT_HOME/cache/downloads/$ASSET_NAME"
if [ ! -f "$ASSET_PATH" ] || [ ! -s "$ASSET_PATH" ]; then
  tmp_asset="$ASSET_PATH.tmp"
  rm -f "$tmp_asset"
  curl -fsSL "$ASSET_URL" -o "$tmp_asset"
  mv -f "$tmp_asset" "$ASSET_PATH"
fi

PACKAGE_DIR="$PPT_HOME/packages/$SLUG/$VERSION"
rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"
tar -xzf "$ASSET_PATH" -C "$PACKAGE_DIR"

if [ ! -f "$PACKAGE_DIR/src/ppt/__main__.py" ]; then
  printf 'downloaded release asset did not contain src/ppt\n' >&2
  exit 1
fi

# Install a stable launcher that points at the installed sources.
tmp_launcher="$BIN_DIR/.ppt.tmp.$$"
rm -f "$tmp_launcher"
cat >"$tmp_launcher" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PPT_HOME="${PPT_HOME}"
export PPT_CONFIG_DIR="${PPT_CONFIG_DIR}"
export PYTHONPATH="${PACKAGE_DIR}/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m ppt "\$@"
EOF
chmod 755 "$tmp_launcher"
mv -f "$tmp_launcher" "$BIN_DIR/ppt"

# Seed config + lock + state so ppt can manage itself.
cat >"$PPT_CONFIG_DIR/packages.toml" <<EOF
# Managed by ppt

[[package]]
repo = "${PPT_REPO_URL}"
EOF

cat >"$PPT_CONFIG_DIR/packages.lock.toml" <<EOF
# Managed by ppt

[[package]]
repo = "${PPT_REPO_URL}"
version = "${VERSION}"
EOF

PPT_HOME="$PPT_HOME" \
PPT_CONFIG_DIR="$PPT_CONFIG_DIR" \
PPT_REPO_URL="$PPT_REPO_URL" \
VERSION="$VERSION" \
ASSET_NAME="$ASSET_NAME" \
ASSET_URL="$ASSET_URL" \
PACKAGE_DIR="$PACKAGE_DIR" \
python3 - <<'PY'
import json
import os
import time
from pathlib import Path

home = Path(os.environ["PPT_HOME"]).expanduser()
config_dir = Path(os.environ["PPT_CONFIG_DIR"]).expanduser()
repo = os.environ["PPT_REPO_URL"]
version = os.environ["VERSION"]
asset_name = os.environ["ASSET_NAME"]
package_dir = Path(os.environ["PACKAGE_DIR"]).expanduser()
bin_dir = home / "bin"
link = str(bin_dir / "ppt")

state_path = home / "state.json"
state = {
    repo: {
        "status": "installed",
        "resolved_version": version,
        "installed_version": version,
        "prefix": "",
        "bin_links": [link],
        "package_dir": str(package_dir),
        "asset_name": asset_name,
        "message": "",
        "updated_at": int(time.time()),
    }
}
state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

receipt = {
    "repo": repo,
    "version": version,
    "asset_name": asset_name,
    "asset_url": os.environ.get("ASSET_URL", ""),
    "bin_links": [link],
    "installed_at": int(time.time()),
}
(package_dir / ".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
PY

printf 'Installed ppt to %s\n' "$BIN_DIR/ppt"
printf 'Add %s to PATH if needed:\n' "$BIN_DIR"
printf '  export PATH="%s:\$PATH"\n' "$BIN_DIR"
