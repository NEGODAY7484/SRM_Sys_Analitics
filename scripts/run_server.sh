#!/usr/bin/env bash
set -euo pipefail

# CRM/SRM service center server runner (Linux)
#
# - creates venv if missing
# - installs dependencies
# - prepares folders
# - runs uvicorn

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

python -m pip install -U pip

if [[ -f requirements.txt ]]; then
  python -m pip install -r requirements.txt
else
  # fallback: editable + extras
  python -m pip install -e ".[dev,api,report]"
fi

mkdir -p data uploads outputs outputs/logs

# Environment
if [[ ! -f .env ]]; then
  echo "WARN: .env not found. Copy .env.example -> .env and edit for your server." >&2
fi

# DB init + default users are created on app startup.
exec uvicorn srm.api.app:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"

