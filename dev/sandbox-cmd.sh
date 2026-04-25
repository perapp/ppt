#!/usr/bin/env bash
set -euo pipefail

# mimic install from README.md
curl -fsSL file:///workspace/dist/install.sh | bash -s -- --shell-config yes

mkdir -p "$HOME/.config/ppt"
cat /tmp/ppt-sandbox-packages.toml >>"$HOME/.config/ppt/packages.toml"

"$HOME/.local/ppt/bin/ppt" sync

exec bash -li
