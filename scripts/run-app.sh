#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -x .venv/bin/python && -f .local.json ]] || { echo 'Executa ./prepare.sh --skip-images primeiro.'; exit 1; }
python3 scripts/network.py
# Prevent the host sleeping while the event server runs; no permanent settings change.
if command -v caffeinate >/dev/null; then exec caffeinate -i .venv/bin/python scripts/serve.py; fi
exec .venv/bin/python scripts/serve.py
