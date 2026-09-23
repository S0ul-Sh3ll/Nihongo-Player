#!/usr/bin/env bash
# ==============================================================================
# Nihongo Player — Linux Uninstaller
#
# This script removes Nihongo Player desktop integration from Linux:
#  1. Removes the launcher script (~/.local/bin/nihongo-player).
#  2. Removes the desktop file (~/.local/share/applications/nihongo-player.desktop).
#  3. Updates desktop database cache.
#  4. Optionally removes virtual environment / local files (--purge).
#
# Usage:
#   bash scripts/uninstall-linux.sh [OPTIONS]
#
# Options:
#   --purge, --remove-venv     Remove the Python virtual environment (.venv).
#   -h, --help                 Show this help message.
# ==============================================================================

set -euo pipefail

# ANSI color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_step() {
    printf "${BLUE}==>${NC} ${GREEN}%s${NC}\n" "$1"
}

log_info() {
    printf "    %s\n" "$1"
}

PURGE=false

for arg in "$@"; do
    case "$arg" in
        --purge|--remove-venv)
            PURGE=true
            ;;
        -h|--help)
            cat << 'EOF'
Nihongo Player — Linux Uninstaller

Usage:
  bash scripts/uninstall-linux.sh [OPTIONS]

Options:
  --purge, --remove-venv     Remove the Python virtual environment (.venv).
  -h, --help                 Show this help message.
EOF
            exit 0
            ;;
        *)
            printf "${RED}Error:${NC} Unknown option: %s\n" "$arg" >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log_step "Uninstalling Nihongo Player..."

# 1. Remove launcher script
LAUNCHER="$HOME/.local/bin/nihongo-player"
if [ -f "$LAUNCHER" ]; then
    rm -f "$LAUNCHER"
    log_info "Removed launcher: $LAUNCHER"
else
    log_info "Launcher not found at $LAUNCHER (skipped)"
fi

# 2. Remove desktop entry
DESKTOP_FILE="$HOME/.local/share/applications/nihongo-player.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    log_info "Removed desktop file: $DESKTOP_FILE"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
else
    log_info "Desktop file not found at $DESKTOP_FILE (skipped)"
fi

# 3. Optional purge of venv
if [ "$PURGE" = true ]; then
    VENV_DIR="$REPO_ROOT/.venv"
    if [ -d "$VENV_DIR" ]; then
        log_step "Removing virtual environment ($VENV_DIR)..."
        rm -rf "$VENV_DIR"
        log_info "Removed virtual environment."
    fi
fi

echo ""
printf "${GREEN}Nihongo Player desktop launcher and shortcuts uninstalled successfully.${NC}\n"
