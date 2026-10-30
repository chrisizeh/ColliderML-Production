#!/usr/bin/env bash
# Generate a fresh two-event source and run DDSim with standalone truth output.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PRODUCTION_DIR="$REPO_ROOT/../data/production"
export CONTAINER_IMAGE="${CONTAINER_IMAGE:-colliderml/acts-arrow:0.2.2-arrow-dev}"
export OUTPUT_DIR="${OUTPUT_DIR:-$PRODUCTION_DIR/runs/truth_smoke_seed42}"
export COLLIDERML_CACHE="${COLLIDERML_CACHE:-$PRODUCTION_DIR}"
export SEED="${SEED:-42}"
export RUN_ID=0

if [ -e "$OUTPUT_DIR/runs/0" ]; then
    echo "ERROR: Output already exists. Set OUTPUT_DIR to a fresh sample directory."
    exit 1
fi
mkdir -p "$OUTPUT_DIR/runs/0"
docker run --rm --platform linux/amd64 --network none --entrypoint bash \
    -v "$REPO_ROOT:/workspace:ro" -v "$OUTPUT_DIR:/output" -v "$COLLIDERML_CACHE:/cache:ro" \
    -e COLLIDERML_CACHE=/cache "$CONTAINER_IMAGE" -c '
        source /workspace/scripts/cli/setup_container_env.sh
        if [ -f /opt/acts-arrow/setup.sh ]; then source /opt/acts-arrow/setup.sh; fi
        cd /workspace/scripts/simulation
        python3 -m truth.smoke_input /output/runs/0/merged_events.hepmc3
    '
exec bash "$SCRIPT_DIR/run_docker.sh" simulation/ddsim_run.py \
    configs_development/docker_test/truth_smoke/simulation_config.yaml
