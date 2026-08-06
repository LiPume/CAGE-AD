#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BRIDGE_ROOT="${BUNDLE_ROOT}/runtime/bridge/apollo-carla"
BRIDGE_PYTHON="${BUNDLE_ROOT}/runtime/bridge/python"

if (( $# == 0 )); then
  echo "usage: $0 COMMAND [ARG ...]" >&2
  exit 64
fi

export APOLLO_EXTRA_PYTHONPATH="${BRIDGE_PYTHON}:${BRIDGE_ROOT}"
exec "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" "$@"
