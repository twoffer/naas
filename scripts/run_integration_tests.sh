#!/usr/bin/env bash
# run_integration_tests.sh — one-command local integration test runner.
#
# Usage: bash scripts/run_integration_tests.sh
#
# What it does:
#   1. Activates .venv if present (so system Python is not used by mistake).
#   2. Ensures .env exists — copies from .env.example if absent.
#   3. Installs harness dependencies (requirements-dev.txt + demo/requirements.txt).
#      demo/demo_normalization.py is run via sys.executable inside the suite, so
#      rich, httpx, and psycopg must be available in the invoking environment.
#   4. Runs the integration suite with pytest --integration.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── 1. Activate virtualenv if present ──────────────────────────────────────
if [ -f "${REPO_ROOT}/.venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "${REPO_ROOT}/.venv/bin/activate"
fi

# ── 2. Ensure .env exists ───────────────────────────────────────────────────
if [ ! -f "${REPO_ROOT}/.env" ]; then
    if [ -f "${REPO_ROOT}/.env.example" ]; then
        cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
        echo "Copied .env.example → .env"
    else
        echo "ERROR: Neither .env nor .env.example found at ${REPO_ROOT}" >&2
        exit 1
    fi
fi

# ── 3. Install harness dependencies ─────────────────────────────────────────
pip install \
    -r "${REPO_ROOT}/requirements-dev.txt" \
    -r "${REPO_ROOT}/demo/requirements.txt" \
    -e "${REPO_ROOT}/shared/"

# ── 4. Run integration suite ─────────────────────────────────────────────────
python -m pytest "${REPO_ROOT}/tests/integration" --integration "$@"
