#!/usr/bin/env python3
"""Model acquisition and conversion script for Nihongo Player.

Reproducibly converts Helsinki-NLP/opus-mt-ja-en to int8-quantized CTranslate2 format
using an isolated throwaway virtual environment.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def is_model_present(model_dir: Path) -> bool:
    """Check if valid CTranslate2 model files are already present."""
    required_files = ["model.bin", "source.spm", "target.spm"]
    return model_dir.is_dir() and all((model_dir / f).is_file() for f in required_files)


def fetch_and_convert_model(
    output_dir: Path,
    model_name: str = "Helsinki-NLP/opus-mt-ja-en",
    quantization: str = "int8",
    force: bool = False,
) -> None:
    """Download and convert Helsinki-NLP translation model to CTranslate2 format.

    Args:
        output_dir: Destination directory for converted CT2 model.
        model_name: HuggingFace model identifier.
        quantization: Quantization type (e.g. 'int8', 'float16', 'float32').
        force: Force re-download and re-conversion even if model is already present.
    """
    output_dir = output_dir.resolve()

    if is_model_present(output_dir) and not force:
        print(f"Model already present at {output_dir}. Skipping (use --force to re-generate).")
        return

    print(f"Generating CTranslate2 model from '{model_name}' (quantization: {quantization})...")
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="nihongo_model_venv_") as tmpdir:
        venv_path = Path(tmpdir)
        print(f"Creating isolated throwaway virtual environment in {venv_path}...")
        venv.create(venv_path, with_pip=True)

        if sys.platform == "win32":
            venv_python = venv_path / "Scripts" / "python.exe"
            venv_pip = venv_path / "Scripts" / "pip.exe"
        else:
            venv_python = venv_path / "bin" / "python"
            venv_pip = venv_path / "bin" / "pip"

        print("Installing transformers, torch, ctranslate2, sentencepiece in throwaway environment...")
        subprocess.run(
            [str(venv_pip), "install", "--upgrade", "pip"],
            check=True,
        )
        subprocess.run(
            [
                str(venv_pip),
                "install",
                "transformers",
                "torch",
                "ctranslate2",
                "sentencepiece",
            ],
            check=True,
        )

        print(f"Running ct2-transformers-converter -> {output_dir}...")
        converter_cmd = [
            str(venv_python),
            "-m",
            "ctranslate2.converters.transformers",
            "--model",
            model_name,
            "--output_dir",
            str(output_dir),
            "--quantization",
            quantization,
            "--copy_files",
            "source.spm",
            "target.spm",
            "vocab.json",
            "tokenizer_config.json",
            "--force",
        ]
        subprocess.run(converter_cmd, check=True)

    if is_model_present(output_dir):
        print(f"Successfully generated CT2 model at {output_dir}")
    else:
        raise RuntimeError(f"Model conversion completed but missing expected files at {output_dir}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    project_root = Path(__file__).resolve().parent.parent
    default_output = project_root / "models" / "opus-ja-en-ct2"

    parser = argparse.ArgumentParser(
        prog="fetch_models.py",
        description="Download and convert Opus-MT translation model to CTranslate2 int8 format.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=default_output,
        help=f"Target directory for converted CT2 model files (default: {default_output}).",
    )
    parser.add_argument(
        "--model",
        dest="model_name",
        type=str,
        default="Helsinki-NLP/opus-mt-ja-en",
        help="HuggingFace model ID to convert (default: Helsinki-NLP/opus-mt-ja-en).",
    )
    parser.add_argument(
        "--quantization",
        dest="quantization",
        type=str,
        default="int8",
        help="Quantization format: int8, float16, or float32 (default: int8).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-generation even if model files are already present.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entrypoint for fetch_models script."""
    args = parse_args(argv)
    try:
        fetch_and_convert_model(
            output_dir=args.output_dir,
            model_name=args.model_name,
            quantization=args.quantization,
            force=args.force,
        )
        return 0
    except Exception as exc:
        print(f"Error fetching model: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
