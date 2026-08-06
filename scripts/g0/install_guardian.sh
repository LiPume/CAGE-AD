#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="${BUNDLE_ROOT}"
CAGE_RUNTIME_ROOT="${CAGE_RUNTIME_ROOT:?set CAGE_RUNTIME_ROOT to the preserved G0 runtime}"
ENV_PREFIX="${CAGE_RUNTIME_ROOT}/envs/cage-ad-py310"
PKG_CACHE="${CAGE_RUNTIME_ROOT}/cache/conda/pkgs"

mkdir -p "${ENV_PREFIX}" "${PKG_CACHE}"
export CONDA_PKGS_DIRS="${PKG_CACHE}"

if [[ ! -x "${ENV_PREFIX}/bin/python" ]]; then
  conda create --yes --prefix "${ENV_PREFIX}" python=3.10 pip
fi

conda run --prefix "${ENV_PREFIX}" python -m pip install \
  -e "${REPO_ROOT}[dev]" \
  'carla==0.9.15'

conda run --prefix "${ENV_PREFIX}" python -c \
  'import carla, cage_ad; print("CAGE-AD and CARLA client imports: PASS")'
