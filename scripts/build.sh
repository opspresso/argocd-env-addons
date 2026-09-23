#!/bin/bash
#
# Renders the shared chart template into charts/<chart>/<platform>/values-*.yaml.

set -euo pipefail

SHELL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

cd "${SHELL_DIR}/.."

# find charts
for CHART_DIR in charts/*/; do
  CHART=$(basename "${CHART_DIR}")
  for PLATFORM in eks k3s local; do
    if [ -f "${CHART_DIR}/values-template.yaml.j2" ] && [ -d "${CHART_DIR}/${PLATFORM}" ]; then
      echo
      echo "Processing.. ${CHART}/${PLATFORM}"
      python3 "${SHELL_DIR}/gen_values.py" -p "${PLATFORM}" -r "${CHART}"
    fi
  done
done
