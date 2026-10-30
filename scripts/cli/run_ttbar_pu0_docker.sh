#!/usr/bin/env bash
# Ten-event ttbar PU0 development run with native ACTS parquet.
# Invoke from any directory with: bash scripts/cli/run_ttbar_pu0_docker.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PRODUCTION_DIR="$REPO_ROOT/../data/production"

export CONTAINER_IMAGE="${CONTAINER_IMAGE:-colliderml/acts-arrow:0.2.2-arrow-dev}"
export SEED="${SEED:-42}"
export OUTPUT_DIR="${OUTPUT_DIR:-$PRODUCTION_DIR/runs/ttbar_pu0_dev_seed$SEED}"
# Existing dependencies were transferred directly into production/, not cache/.
export COLLIDERML_CACHE="${COLLIDERML_CACHE:-$PRODUCTION_DIR}"

exec bash "$SCRIPT_DIR/run_pipeline_docker.sh" --channel ttbar --skip-conversion
