#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

required=(
  "BUNDLE_MANIFEST.yaml"
  "AGENTS.md"
  "README_START_HERE.md"
  "PROMPT.md"
  "docs/KSQ/01_task_contract.md"
  "docs/KSQ/08_decisive_experiment_and_baselines.md"
  "docs/KSQ/09_novelty_attack_kill_criteria.md"
  "docs/KSQ/10_core_framework.md"
  "docs/KSQ/Research_Idea_Brief.md"
  "docs/experiment_setup/ADR-0001-apollo10-host-mode.md"
  "docs/experiment_setup/server_and_environment_plan.md"
  "docs/experiment_setup/STORAGE_LAYOUT.md"
  "project/Zhijia-Guardian/README.md"
  "project/Zhijia-Guardian/pyproject.toml"
  "project/Zhijia-Guardian/docs/adapter_contract.md"
  "project/Zhijia-Guardian/docs/schema_mapping_carla.md"
  "runtime_state/RUN_STATE.yaml"
  "runtime_state/storage_paths.yaml"
)

for relative_path in "${required[@]}"; do
  if [[ ! -f "${BUNDLE_ROOT}/${relative_path}" ]]; then
    echo "MISSING: ${relative_path}" >&2
    exit 1
  fi
done

forbidden_names="$(find "${BUNDLE_ROOT}" -type f \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' \) -print)"
if [[ -n "${forbidden_names}" ]]; then
  echo "FORBIDDEN SENSITIVE FILE NAMES:" >&2
  echo "${forbidden_names}" >&2
  exit 1
fi

if find "${BUNDLE_ROOT}" -type d \( -name '.git' -o -name '__pycache__' -o -name '.pytest_cache' \) -print -quit | grep -q .; then
  echo "FORBIDDEN CACHE OR GIT DIRECTORY FOUND" >&2
  exit 1
fi

if command -v rg >/dev/null 2>&1; then
  if rg -l --hidden --glob '!scripts/verify_bundle.sh' '(-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:OPENAI|ANTHROPIC|DEEPSEEK|DASHSCOPE)_API_KEY[[:space:]]*=[[:space:]]*(?:['"'"'][^$<{]|[^'"'"'$<{[:space:]]))' "${BUNDLE_ROOT}" | grep -q .; then
    echo "POSSIBLE EMBEDDED SECRET FOUND" >&2
    exit 1
  fi
fi

echo "Bundle verification: PASS"
echo "Bundle root: ${BUNDLE_ROOT}"
du -sh "${BUNDLE_ROOT}"
