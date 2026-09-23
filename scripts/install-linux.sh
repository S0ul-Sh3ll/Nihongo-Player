#!/usr/bin/env bash
# ==============================================================================
# Nihongo Player — Automated Linux Installer
#
# This script sets up Nihongo Player on Linux distributions:
#  1. Validates Python >= 3.11 environment.
#  2. Ensures libmpv is available (via package manager or local runtime extraction).
#  3. Creates Python virtual environment and installs dependencies (with [asr]).
#  4. Fetches and quantizes offline MT translation model (Opus-MT CT2).
#  5. (Optional) Pre-downloads ASR speech model with --with-asr-model.
#  6. Installs desktop launcher (~/.local/bin/nihongo-player) and .desktop entry.
#
# Usage:
#   bash scripts/install-linux.sh [OPTIONS]
#
# Options:
#   --with-asr-model[=MODEL]   Pre-download speech recognition model for offline use
#                              (default: kotoba-tech/kotoba-whisper-v2.0-faster).
#                              Uses the huggingface_hub Python library; no CLI or login needed.
#   --install-dir=PATH         Custom install directory (default: repo root or ~/.local/share/nihongo-player).
#   -h, --help                 Show this help message.
# ==============================================================================

set -euo pipefail

# ANSI color codes for friendly terminal output
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

log_warn() {
    printf "${YELLOW}Warning:${NC} %s\n" "$1"
}

log_err() {
    printf "${RED}Error:${NC} %s\n" "$1" >&2
}

# ------------------------------------------------------------------------------
# 1. Parse Command-Line Arguments
# ------------------------------------------------------------------------------
WITH_ASR=false
ASR_MODEL="all"
CUSTOM_INSTALL_DIR=""

for arg in "$@"; do
    case "$arg" in
        --with-asr-model)
            WITH_ASR=true
            ASR_MODEL="all"
            ;;
        --with-asr-model=*)
            WITH_ASR=true
            ASR_MODEL="${arg#*=}"
            ;;
        --install-dir=*)
            CUSTOM_INSTALL_DIR="${arg#*=}"
            ;;
        -h|--help)
            cat << 'EOF'
Nihongo Player — Linux Installer

Usage:
  bash scripts/install-linux.sh [OPTIONS]

Options:
  --with-asr-model[=MODEL]   Pre-download speech recognition model(s) for offline use:
                             all (default): kotoba-whisper (~600MB) + anime-whisper (~768MB)
                             anime | coverage: anime-whisper (~768MB)
                             kotoba | clean: kotoba-whisper (~600MB)
                             large-v3: faster-whisper-large-v3 (~3GB)
                             Or any custom HuggingFace model repo ID.
                             Uses the huggingface_hub Python library; no CLI or login needed.
  --install-dir=PATH         Custom install directory (default: repository root or
                             ~/.local/share/nihongo-player).
  -h, --help                 Show this help message.

Examples:
  bash scripts/install-linux.sh
  bash scripts/install-linux.sh --with-asr-model
  bash scripts/install-linux.sh --with-asr-model=large-v3
  bash scripts/install-linux.sh --with-asr-model=Systran/faster-whisper-large-v3
EOF
            exit 0
            ;;
        *)
            log_err "Unknown option: $arg"
            log_info "Use --help for usage information."
            exit 1
            ;;
    esac
done

# ------------------------------------------------------------------------------
# 2. Determine Installation & Repository Directories
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -n "$CUSTOM_INSTALL_DIR" ]; then
    INSTALL_DIR="$CUSTOM_INSTALL_DIR"
elif [ -f "$REPO_ROOT/pyproject.toml" ]; then
    INSTALL_DIR="$REPO_ROOT"
else
    INSTALL_DIR="$HOME/.local/share/nihongo-player"
fi

mkdir -p "$INSTALL_DIR"
log_step "Installing Nihongo Player into: $INSTALL_DIR"

# ------------------------------------------------------------------------------
# 3. Detect Python >= 3.11
# ------------------------------------------------------------------------------
log_step "Checking Python version..."
if ! command -v python3 >/dev/null 2>&1; then
    log_err "python3 is not installed."
    log_info "Please install Python 3.11 or newer (e.g., sudo apt install python3 python3-venv python3-pip)."
    exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || echo "0.0.0")"
if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    log_err "Python 3.11 or newer is required (found: Python $PY_VERSION)."
    log_info "Please install/upgrade Python 3.11+ before running this script."
    exit 1
fi
log_info "Found Python $PY_VERSION (OK)"

# ------------------------------------------------------------------------------
# 4. Detect and Install libmpv
# ------------------------------------------------------------------------------
log_step "Checking libmpv dependency..."

has_system_libmpv() {
    # Check ldconfig cache
    if command -v ldconfig >/dev/null 2>&1 && ldconfig -p 2>/dev/null | grep -q 'libmpv\.so'; then
        return 0
    fi
    # Check common system library locations
    for p in \
        /usr/lib/libmpv.so* \
        /usr/lib64/libmpv.so* \
        /usr/lib/x86_64-linux-gnu/libmpv.so* \
        /usr/lib/aarch64-linux-gnu/libmpv.so* \
        /usr/local/lib/libmpv.so*; do
        if [ -e "$p" ]; then
            return 0
        fi
    done
    return 1
}

FALLBACK_LIBMPV=""
RUNTIME_LIBS_DIR="$INSTALL_DIR/runtime-libs"
USE_FALLBACK_LIBS=false

if has_system_libmpv; then
    log_info "System libmpv detected (OK)"
else
    log_info "System libmpv not found. Attempting package manager installation..."
    
    # Check if sudo is available and user has sudo privileges or is root
    SUDO_CMD=""
    if [ "$(id -u)" -eq 0 ]; then
        SUDO_CMD=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO_CMD="sudo"
    fi

    INSTALLED_PKG=false
    if [ -n "$SUDO_CMD" ] || [ "$(id -u)" -eq 0 ]; then
        if command -v apt-get >/dev/null 2>&1; then
            log_info "Detected Debian/Ubuntu: running '$SUDO_CMD apt-get install -y libmpv2'..."
            $SUDO_CMD apt-get update -y && ($SUDO_CMD apt-get install -y libmpv2 || $SUDO_CMD apt-get install -y libmpv1) && INSTALLED_PKG=true || true
        elif command -v dnf >/dev/null 2>&1; then
            log_info "Detected Fedora/RHEL: running '$SUDO_CMD dnf install -y mpv-libs'..."
            $SUDO_CMD dnf install -y mpv-libs && INSTALLED_PKG=true || true
        elif command -v pacman >/dev/null 2>&1; then
            log_info "Detected Arch Linux: running '$SUDO_CMD pacman -S --noconfirm mpv'..."
            $SUDO_CMD pacman -S --noconfirm mpv && INSTALLED_PKG=true || true
        elif command -v zypper >/dev/null 2>&1; then
            log_info "Detected openSUSE: running '$SUDO_CMD zypper install -y libmpv2'..."
            $SUDO_CMD zypper --non-interactive install libmpv2 && INSTALLED_PKG=true || true
        fi
    fi

    if has_system_libmpv; then
        log_info "System libmpv successfully installed (OK)"
    else
        # Fallback to no-sudo local extraction of runtime libraries
        log_warn "Could not install libmpv via system package manager."
        log_step "Falling back to no-sudo local library extraction into $RUNTIME_LIBS_DIR..."
        mkdir -p "$RUNTIME_LIBS_DIR"

        if command -v apt-get >/dev/null 2>&1 && command -v dpkg-deb >/dev/null 2>&1; then
            TMP_DEB_DIR="$(mktemp -d)"
            log_info "Downloading libmpv .deb packages..."
            (
                cd "$TMP_DEB_DIR"
                apt-get download libmpv2 libmpv1 libbluray2 libsixel1 2>/dev/null || true
                for deb in *.deb; do
                    if [ -f "$deb" ]; then
                        dpkg-deb -x "$deb" "$TMP_DEB_DIR/extracted" 2>/dev/null || true
                    fi
                done
                if [ -d "$TMP_DEB_DIR/extracted" ]; then
                    find "$TMP_DEB_DIR/extracted" -name "libmpv.so*" -exec cp -a {} "$RUNTIME_LIBS_DIR/" \;
                    find "$TMP_DEB_DIR/extracted" -name "libbluray.so*" -exec cp -a {} "$RUNTIME_LIBS_DIR/" \;
                    find "$TMP_DEB_DIR/extracted" -name "libsixel.so*" -exec cp -a {} "$RUNTIME_LIBS_DIR/" \;
                fi
            )
            rm -rf "$TMP_DEB_DIR"
        fi

        FOUND_SO="$(find "$RUNTIME_LIBS_DIR" -name "libmpv.so.2" -o -name "libmpv.so.1" -o -name "libmpv.so" 2>/dev/null | head -n 1 || true)"
        if [ -n "$FOUND_SO" ] && [ -f "$FOUND_SO" ]; then
            log_info "Local libmpv extracted to: $FOUND_SO"
            USE_FALLBACK_LIBS=true
            FALLBACK_LIBMPV="$FOUND_SO"
        else
            log_warn "Unable to extract local libmpv. If video playback fails, please manually install libmpv."
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 5. Create Virtual Environment and Install Nihongo Player
# ------------------------------------------------------------------------------
log_step "Setting up Python virtual environment..."
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    log_info "Created venv at $VENV_DIR"
else
    log_info "Existing venv found at $VENV_DIR"
fi

VENV_PIP="$VENV_DIR/bin/pip"
VENV_PYTHON="$VENV_DIR/bin/python"

log_step "Installing package dependencies (with [asr] speech recognition extra)..."
"$VENV_PIP" install --upgrade pip

if [ -f "$INSTALL_DIR/pyproject.toml" ]; then
    "$VENV_PIP" install -e "$INSTALL_DIR[asr]" || "$VENV_PIP" install "$INSTALL_DIR[asr]"
elif [ -f "$REPO_ROOT/pyproject.toml" ]; then
    "$VENV_PIP" install -e "$REPO_ROOT[asr]" || "$VENV_PIP" install "$REPO_ROOT[asr]"
else
    "$VENV_PIP" install "nihongo-player[asr]"
fi

# ------------------------------------------------------------------------------
# 6. Fetch Offline Neural Machine Translation Model (Opus-MT CT2)
# ------------------------------------------------------------------------------
MT_MODEL_DIR="$INSTALL_DIR/models/opus-ja-en-ct2"
if [ ! -f "$MT_MODEL_DIR/model.bin" ]; then
    log_step "Fetching offline Opus-MT translation model..."
    if [ -f "$INSTALL_DIR/scripts/fetch_models.py" ]; then
        "$VENV_PYTHON" "$INSTALL_DIR/scripts/fetch_models.py" --output-dir "$MT_MODEL_DIR"
    elif [ -f "$REPO_ROOT/scripts/fetch_models.py" ]; then
        "$VENV_PYTHON" "$REPO_ROOT/scripts/fetch_models.py" --output-dir "$MT_MODEL_DIR"
    fi
else
    log_info "Opus-MT translation model already present at $MT_MODEL_DIR (OK)"
fi

# ------------------------------------------------------------------------------
# 7. Optional Pre-download of ASR Speech Recognition Model
# ------------------------------------------------------------------------------
# Dictionaries (JMdict, UniDic-lite) and neural MT (Opus-MT) are BUNDLED offline.
# ASR models download ON FIRST USE using the huggingface_hub Python library
# (no CLI or account login required) and are cached in ~/.cache/huggingface.
# The --with-asr-model option downloads the model(s) now so the user is 100% offline.
if [ "$WITH_ASR" = true ]; then
    case "$ASR_MODEL" in
        all|hybrid|"")
            log_step "Pre-downloading ASR models for default & hybrid modes ('kotoba-whisper' ~600MB + 'anime-whisper' ~768MB)..."
            log_info "Using huggingface_hub library (no huggingface-cli or login required)..."
            "$VENV_PYTHON" -c "from huggingface_hub import snapshot_download; print('Downloading kotoba-whisper (~600MB)...'); snapshot_download('kotoba-tech/kotoba-whisper-v2.0-faster'); print('Downloading anime-whisper (~768MB)...'); snapshot_download('quantumcookie/anime-whisper-ct2-int8')"
            log_info "ASR models ('kotoba-whisper' and 'anime-whisper') cached successfully."
            ;;
        coverage|anime)
            log_step "Pre-downloading Anime ASR model for maximum coverage / anime mode (~768MB)..."
            log_info "Using huggingface_hub library (no huggingface-cli or login required)..."
            "$VENV_PYTHON" -c "from huggingface_hub import snapshot_download; snapshot_download('quantumcookie/anime-whisper-ct2-int8')"
            log_info "Anime ASR model (~768MB) cached successfully."
            ;;
        kotoba|clean)
            log_step "Pre-downloading Kotoba ASR model (~600MB)..."
            log_info "Using huggingface_hub library (no huggingface-cli or login required)..."
            "$VENV_PYTHON" -c "from huggingface_hub import snapshot_download; snapshot_download('kotoba-tech/kotoba-whisper-v2.0-faster')"
            log_info "Kotoba ASR model (~600MB) cached successfully."
            ;;
        large-v3)
            log_step "Pre-downloading large-v3 ASR model (~3GB)..."
            log_info "Using huggingface_hub library (no huggingface-cli or login required)..."
            "$VENV_PYTHON" -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-large-v3')"
            log_info "Large-v3 ASR model (~3GB) cached successfully."
            ;;
        *)
            log_step "Pre-downloading ASR model '$ASR_MODEL' for offline use..."
            log_info "Using huggingface_hub library (no huggingface-cli or login required)..."
            "$VENV_PYTHON" -c "from huggingface_hub import snapshot_download; snapshot_download('$ASR_MODEL')"
            log_info "ASR model '$ASR_MODEL' cached successfully."
            ;;
    esac
fi

# ------------------------------------------------------------------------------
# 8. Install Desktop Launcher & .desktop Entry
# ------------------------------------------------------------------------------
log_step "Installing launcher script and desktop entry..."
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/nihongo-player"

cat << EOF > "$LAUNCHER"
#!/usr/bin/env bash
# Nihongo Player Launcher
set -e
EOF

if [ "$USE_FALLBACK_LIBS" = true ] && [ -n "$FALLBACK_LIBMPV" ]; then
    cat << EOF >> "$LAUNCHER"
export NIHONGO_LIBMPV="$FALLBACK_LIBMPV"
export LD_LIBRARY_PATH="$RUNTIME_LIBS_DIR\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
EOF
fi

cat << EOF >> "$LAUNCHER"
exec "$VENV_DIR/bin/nihongo-player" "\$@"
EOF

chmod +x "$LAUNCHER"
log_info "Installed launcher to: $LAUNCHER"

# Desktop Entry
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
DESKTOP_FILE="$APPS_DIR/nihongo-player.desktop"

ICON_PATH="$INSTALL_DIR/assets/icons/icon.png"
if [ ! -f "$ICON_PATH" ] && [ -f "$REPO_ROOT/assets/icons/icon.png" ]; then
    ICON_PATH="$REPO_ROOT/assets/icons/icon.png"
fi

cat << EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Name=Nihongo Player
GenericName=Japanese Study Video Player
Comment=Desktop video player for Japanese language learning with dynamic furigana and study loop
Exec=$HOME/.local/bin/nihongo-player %F
Icon=$ICON_PATH
Terminal=false
Categories=AudioVideo;Player;Education;
MimeType=video/mp4;video/x-matroska;video/webm;video/quicktime;
StartupWMClass=nihongo-player
EOF

chmod +x "$DESKTOP_FILE"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi
log_info "Installed desktop entry to: $DESKTOP_FILE"

# ------------------------------------------------------------------------------
# 9. Check PATH & Completion Guidance
# ------------------------------------------------------------------------------
case ":$PATH:" in
    *":$HOME/.local/bin:"*)
        ;;
    *)
        echo ""
        log_warn "$HOME/.local/bin is not in your PATH environment variable."
        log_info "Add it to your PATH by adding the following line to ~/.bashrc or ~/.zshrc:"
        log_info "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo ""
printf "${GREEN}================================================================${NC}\n"
printf "${GREEN}  Nihongo Player has been successfully installed!${NC}\n"
printf "${GREEN}================================================================${NC}\n"
echo ""
echo "How to run Nihongo Player:"
echo "  1. From Terminal:"
echo "     nihongo-player /path/to/movie.mp4"
echo "  2. From Application Launcher / Menu:"
echo "     Search for 'Nihongo Player'"
echo ""
