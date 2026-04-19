#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PPT_HOME=${PPT_HOME:-$HOME/.local/ppt}
PPT_CONFIG_DIR=${PPT_CONFIG_DIR:-$HOME/.config/ppt}
APP_DIR="$PPT_HOME/app/current"
VENV_DIR="$PPT_HOME/venv"
BIN_DIR="$PPT_HOME/bin"

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
cp -R "$ROOT_DIR/src" "$APP_DIR/src"

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
