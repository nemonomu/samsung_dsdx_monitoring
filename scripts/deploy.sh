#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$DEPLOY_ROOT"
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo 'Deployment stopped: commit or resolve tracked local changes first.' >&2
    exit 1
fi
git pull --ff-only
# Execute the newly pulled implementation, including on the first upgrade.
exec "$DEPLOY_ROOT/venv/bin/python" "$DEPLOY_ROOT/scripts/deploy_monitoring.py"
