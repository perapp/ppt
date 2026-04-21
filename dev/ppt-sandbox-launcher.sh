#!/usr/bin/env bash

set -euo pipefail

# Sandbox launcher: run ppt from the mounted working tree.
# The sandbox.sh script mounts the local repo at /workspace.
export PYTHONPATH="/workspace/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m ppt "$@"
