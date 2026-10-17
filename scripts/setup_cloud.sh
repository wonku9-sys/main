#!/usr/bin/env bash
set -euo pipefail
cd /workspace/main
export UV_CACHE_DIR=/workspace/.cache/uv
export XDG_CACHE_HOME=/workspace/.cache
mkdir -p "$UV_CACHE_DIR" "$XDG_CACHE_HOME/fontconfig"
uv sync --frozen --extra dev
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m seoyoung_pos --demo --smoke-test
