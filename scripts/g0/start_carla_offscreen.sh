#!/usr/bin/env bash
set -euo pipefail

CAGE_RUNTIME_ROOT="${CAGE_RUNTIME_ROOT:?set CAGE_RUNTIME_ROOT to the preserved G0 runtime}"
CARLA_ROOT="${CARLA_ROOT:-${CAGE_RUNTIME_ROOT}/carla/0.9.15}"
CARLA_HOME="${CARLA_HOME:-${CAGE_RUNTIME_ROOT}/carla-home}"
CARLA_PORT="${CARLA_PORT:-2000}"
CARLA_BIN="${CARLA_ROOT}/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping"
CARLA_UID="${CARLA_RUN_UID:-$(stat -c %u "${CARLA_BIN}")}"
CARLA_GID="${CARLA_RUN_GID:-$(stat -c %g "${CARLA_BIN}")}"

if [[ "${CARLA_UID}" == "0" ]]; then
  echo "CARLA must run as a non-root UID; set CARLA_RUN_UID/CARLA_RUN_GID" >&2
  exit 1
fi
if ! command -v setfacl >/dev/null || ! command -v setpriv >/dev/null; then
  echo "Required launch tools are absent: install acl and util-linux" >&2
  exit 1
fi

# The bundle lives below /root on AutoDL. Grant only path traversal, not listing.
setfacl -m "u:${CARLA_UID}:x" /root
install -d -o "${CARLA_UID}" -g "${CARLA_GID}" -m 0700 "${CARLA_HOME}/run"

exec setpriv --reuid="${CARLA_UID}" --regid="${CARLA_GID}" --clear-groups \
  env HOME="${CARLA_HOME}" \
      XDG_RUNTIME_DIR="${CARLA_HOME}/run" \
      VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json \
      CARLA_ROOT="${CARLA_ROOT}" \
      CARLA_PORT="${CARLA_PORT}" \
      CARLA_RENDER_MODE=offscreen \
  "${CARLA_ROOT}/CarlaUE4.sh" \
    -RenderOffScreen \
    -vulkan \
    '-ini:[/Script/Engine.RendererSettings]:r.GraphicsAdapter=0' \
    "$@"
