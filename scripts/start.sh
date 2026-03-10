#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Virtual environment not found. Running build first..."
  "$ROOT_DIR/scripts/build.sh"
fi

source "$VENV_DIR/bin/activate"
export PYTHONPATH="$ROOT_DIR"

exec uvicorn src.main:app --host 0.0.0.0 --port 4000
