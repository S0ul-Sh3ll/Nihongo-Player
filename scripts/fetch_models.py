#!/usr/bin/env python3
"""Model acquisition script for Nihongo Player.

Downloads the pre-converted CTranslate2 Japanese->English translation model
(gaudi/opus-mt-ja-en-ctranslate2, derived from Helsinki-NLP/opus-mt-ja-en) from
the Hugging Face Hub into models/opus-ja-en-ct2. No PyTorch/conversion required.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MODEL_FILES = [
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "source.spm",
    "target.spm",
    "vocab.json",
    "tokenizer_config.json",
]
REQUIRED = ["model.bin", "source.spm", "target.spm"]


def is_model_present(model_dir: Path) -> bool:
    """Return True if the required CTranslate2 model files already exist."""
    return model_dir.is_dir() and all((model_dir / f).is_file() for f in REQUIRED)


def _ensure_hf_hub():
    """Import huggingface_hub, installing it on the fly if missing."""
    try:
        from huggingface_hub import snapshot_download  # noqa: F401
    except ImportError:
        import subprocess

        print("Installing huggingface_hub...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "huggingface-hub"], check=True
        )
    from huggingface_hub import snapshot_download

    return snapshot_download


def fetch_model(
    output_dir: Path,
    model_name: str = "gaudi/opus-mt-ja-en-ctranslate2",
    force: bool = False,
) -> None:
    """Download the pre-converted CT2 translation model into output_dir."""
    output_dir = output_dir.resolve()
    if is_model_present(output_dir) and not force:
        print(f"Model already present at {output_dir}. Skipping (use --force to re-download).")
        return

    snapshot_download = _ensure_hf_hub()
    print(f"Downloading pre-converted CT2 model '{model_name}' from Hugging Face...")
    src = Path(snapshot_download(model_name))

    output_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in MODEL_FILES:
        s = src / name
        if s.is_file():
            shutil.copy2(s, output_dir / name)
            copied += 1
    print(f"Copied {copied} files to {output_dir}")

    if not is_model_present(output_dir):
        raise RuntimeError(
            f"Download completed but required files are missing in {output_dir} "
            f"(need: {', '.join(REQUIRED)})"
        )
    print(f"Translation model ready at {output_dir}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    project_root = Path(__file__).resolve().parent.parent
    default_output = project_root / "models" / "opus-ja-en-ct2"
    parser = argparse.ArgumentParser(
        prog="fetch_models.py",
        description="Download the pre-converted Opus-MT ja->en CTranslate2 model (no PyTorch needed).",
    )
    parser.add_argument("--output-dir", dest="output_dir", type=Path, default=default_output,
                        help=f"Target directory for the CT2 model (default: {default_output}).")
    parser.add_argument("--model", dest="model_name", type=str,
                        default="gaudi/opus-mt-ja-en-ctranslate2",
                        help="Hugging Face repo id of the pre-converted CT2 model.")
    parser.add_argument("--force", action="store_true",
                        help="Force re-download even if the model is already present.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint."""
    args = parse_args(argv)
    try:
        fetch_model(output_dir=args.output_dir, model_name=args.model_name, force=args.force)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Error fetching model: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
