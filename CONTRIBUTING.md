# Contributing to Nihongo Player

Thank you for your interest in contributing to Nihongo Player!

## Development Setup

1. **Prerequisites**:
   - Python 3.11+
   - `libmpv` installed on your system (e.g. `sudo apt install libmpv2 xvfb` on Debian/Ubuntu, `brew install mpv` on macOS)

2. **Clone and Install**:
   ```bash
   git clone https://github.com/nihongo-player/nihongo-player.git
   cd nihongo-player
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **Obtain or Regenerate Translation Models**:
   The Opus-MT CTranslate2 translation model is not committed directly to git to keep the repository lightweight.
   To fetch or regenerate the int8-quantized CTranslate2 model from HuggingFace (`Helsinki-NLP/opus-mt-ja-en`), run:
   ```bash
   python scripts/fetch_models.py
   # To force re-generation:
   python scripts/fetch_models.py --force
   ```
   This script creates an isolated throwaway virtual environment, installs the required conversion dependencies, and outputs the model to `models/opus-ja-en-ct2/`.

4. **Running Tests**:
   Run the test suite under xvfb:
   ```bash
   NIHONGO_MPV_VO=null xvfb-run -a pytest -q
   # Or using make:
   make test
   ```

5. **Building Release Packages**:
   To build a standalone desktop distribution using PyInstaller:
   ```bash
   pyinstaller packaging/nihongo_player.spec
   # Or using make:
   make dist
   ```

## Pull Request Guidelines

- Ensure all existing and new tests pass cleanly.
- Maintain clean code formatting and type annotations.
- Do NOT commit files inside `models/` or temporary build artifacts.
