#!/bin/bash

set -euo pipefail
script_dir="$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
PROJECT_HOME=$script_dir

if [[ ${1:-} == --build ]]; then
   rm $PROJECT_HOME/dev/.image.sandbox
   shift
fi

if [[ $PROJECT_HOME/dev/Containerfile.sandbox -nt $PROJECT_HOME/dev/.image.sandbox ]]; then
   podman build -f $PROJECT_HOME/dev/Containerfile.sandbox -t ppt:sandbox $PROJECT_HOME
   touch $PROJECT_HOME/dev/.image.sandbox
fi

podman run --rm -ti -v "$PROJECT_HOME:/workspace:Z" ppt:sandbox
