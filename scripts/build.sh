#!/usr/bin/env bash
# Build standalone distribution package using PyInstaller
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

echo "==> [1/2] Verifying / generating translation model..."
python scripts/fetch_models.py

echo "==> [2/2] Running PyInstaller with packaging/nihongo_player.spec..."
pyinstaller --clean -y packaging/nihongo_player.spec

echo "==> Build complete! Standalone application directory: dist/NihongoPlayer/"
