#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH=${BASH_SOURCE[0]:-$0}
# When invoked via `curl ... | bash`, the script does not exist as a file on disk.
# In that case, never assume the current working directory is a ppt checkout.
if [ -f "$SCRIPT_PATH" ]; then
  ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)
else
  ROOT_DIR=""
fi
PPT_HOME=${PPT_HOME:-$HOME/.local/ppt}
PPT_CONFIG_DIR=${PPT_CONFIG_DIR:-$HOME/.config/ppt}
APP_DIR="$PPT_HOME/app/current"
VENV_DIR="$PPT_HOME/venv"
BIN_DIR="$PPT_HOME/bin"
PPT_ARCHIVE_URL=${PPT_ARCHIVE_URL:-https://gitlab.com/perapp/ppt/-/archive/main/ppt-main.tar.gz}

if ! command -v python3 >/dev/null 2>&1; then
  printf 'python3 is required to install ppt\n' >&2
  exit 1
fi

mkdir -p "$PPT_HOME" "$PPT_CONFIG_DIR" "$BIN_DIR"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"

if [ -n "$ROOT_DIR" ] && [ -f "$ROOT_DIR/install.sh" ] && [ -f "$ROOT_DIR/src/ppt/__main__.py" ]; then
  cp -R "$ROOT_DIR/src" "$APP_DIR/src"
else
  if ! command -v curl >/dev/null 2>&1; then
    printf 'curl is required for hosted installs of ppt\n' >&2
    exit 1
  fi

  if ! command -v tar >/dev/null 2>&1; then
    printf 'tar is required for hosted installs of ppt\n' >&2
    exit 1
  fi

  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' EXIT
  curl -fsSL "$PPT_ARCHIVE_URL" | tar -xz -C "$tmp_dir"
  cp -R "$tmp_dir"/*/src "$APP_DIR/src"
fi

cat > "$BIN_DIR/ppt" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PPT_HOME="${PPT_HOME}"
export PPT_CONFIG_DIR="${PPT_CONFIG_DIR}"
export PYTHONPATH="${APP_DIR}/src"
exec "${VENV_DIR}/bin/python" -m ppt "\$@"
EOF

chmod 755 "$BIN_DIR/ppt"

printf 'Installed ppt to %s\n' "$BIN_DIR/ppt"
printf 'Add %s to PATH if needed:\n' "$BIN_DIR"
printf '  export PATH="%s:\$PATH"\n' "$BIN_DIR"
