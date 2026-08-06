#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE="${BUNDLE_ROOT}/runtime/apollo/application-pnc"
COMMIT='d994e55fb3c3cf88222f8b4813fa5425cc7c1f56'

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER || true
export PATH='/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'

if ! dpkg-query -W -f='${Version}' apollo-neo-env-manager-dev 2>/dev/null | grep -qx '10.0.0-rc1-r4'; then
  echo 'Install the pinned Apollo APT source and apollo-neo-env-manager-dev=10.0.0-rc1-r4 first.' >&2
  exit 1
fi
if [[ ! -d "${WORKSPACE}/.git" ]]; then
  git clone https://github.com/ApolloAuto/application-pnc.git "${WORKSPACE}"
fi
git -C "${WORKSPACE}" fetch origin 10.0
git -C "${WORKSPACE}" switch --detach "${COMMIT}"
cd "${WORKSPACE}"
bash setup.sh
aem start -b host

