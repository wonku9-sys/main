#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export UV_CACHE_DIR=/workspace/.cache/uv
export XDG_CACHE_HOME=/workspace/.cache
mkdir -p "$UV_CACHE_DIR" "$XDG_CACHE_HOME/fontconfig"
uv sync --frozen --extra dev
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pos2 --smoke-test
