#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
APOLLO_WORKSPACE="${APOLLO_WORKSPACE:-${BUNDLE_ROOT}/runtime/apollo/application-pnc}"
AEM_ENV_HOME="/root/.aem/envs/10.0.1_pkg"

if (( $# == 0 )); then
  echo "usage: $0 COMMAND [ARG ...]" >&2
  exit 64
fi
if [[ ! -f "${APOLLO_WORKSPACE}/.aem/inited" ]]; then
  echo "Apollo host environment is not fully initialized" >&2
  exit 1
fi

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER PYTHONHOME
cd "${APOLLO_WORKSPACE}"
set +e
set +u
# shellcheck source=/dev/null
source "${AEM_ENV_HOME}/env.config"
# shellcheck source=/dev/null
source "${APOLLO_WORKSPACE}/.aem/activate.sh"
set -u
set -e
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER PYTHONHOME
export PATH="${APOLLO_ENV_ROOT}/opt/apollo/neo/bin:${APOLLO_ENV_ROOT}/bin:${APOLLO_SYSROOT_DIR}/bin:/usr/local/cuda/bin:/usr/local/qt5/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PYTHONPATH="${APOLLO_ENV_ROOT}/opt/apollo/neo/lib/cyber/python/internal:${PYTHONPATH:-}"
if [[ -n "${APOLLO_EXTRA_PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${APOLLO_EXTRA_PYTHONPATH}:${PYTHONPATH}"
fi
APOLLO_LD_CONF="${APOLLO_ENV_ROOT}/etc/ld.so.conf.d/apollo.conf"
if [[ ! -f "${APOLLO_LD_CONF}" ]]; then
  APOLLO_LD_CONF="/etc/ld.so.conf.d/apollo.conf"
fi
if [[ -f "${APOLLO_LD_CONF}" ]]; then
  APOLLO_LD_PATH="$(grep -v -E '^\s*$|^\s*#' "${APOLLO_LD_CONF}" | tr '\n' ':')"
  export LD_LIBRARY_PATH="${APOLLO_LD_PATH}${LD_LIBRARY_PATH:-}"
fi
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}apollo.baidu.com,.baidu.com,.bcebos.com"
export no_proxy="${NO_PROXY}"

exec "$@"
