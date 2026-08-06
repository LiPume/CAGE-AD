#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
APOLLO_WORKSPACE="${APOLLO_WORKSPACE:-${BUNDLE_ROOT}/runtime/apollo/application-pnc}"
AEM_ENV_HOME="/root/.aem/envs/10.0.1_pkg"

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER PYTHONHOME
cd "${APOLLO_WORKSPACE}"

if [[ ! -f "${APOLLO_WORKSPACE}/.aem/inited" ]]; then
  echo "Apollo host environment is not fully initialized; run scripts/install_apollo_host.sh" >&2
  exit 1
fi
if [[ ! -f "${AEM_ENV_HOME}/inited" ]]; then
  ln -s "${APOLLO_WORKSPACE}/.aem/inited" "${AEM_ENV_HOME}/inited"
fi

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
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}apollo.baidu.com,.baidu.com,.bcebos.com"
export no_proxy="${NO_PROXY}"

if [[ ! -x "${APOLLO_ENV_ROOT}/opt/apollo/neo/bin/buildtool" ]]; then
  echo "AEM buildtool executable is missing after host activation" >&2
  exit 1
fi

exec "${APOLLO_ENV_ROOT}/opt/apollo/neo/bin/buildtool" build -p core
