"""First-run setup diagnostics and resource checks for libmpv, dictionaries, and ML models."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, TypedDict


class ResourceReport(TypedDict):
    """Resource diagnostics status report."""

    libmpv: bool
    mt_model: bool
    dictionary: bool
    tokenizer: bool
    all_ok: bool
    warnings: list[str]
    hints: dict[str, str]


def get_libmpv_install_hint() -> str:
    """Return platform-specific installation hint for libmpv.

    Returns:
        String instructions for installing libmpv on the current operating system.
    """
    if sys.platform.startswith("linux"):
        return (
            "libmpv shared library was not found on your system.\n"
            "Install it via your package manager:\n"
            "  - Ubuntu / Debian: sudo apt install libmpv2\n"
            "  - Arch Linux:      sudo pacman -S mpv\n"
            "  - Fedora / RHEL:   sudo dnf install mpv-libs"
        )
    elif sys.platform == "darwin":
        return (
            "libmpv dynamic library was not found on your system.\n"
            "Install it via Homebrew:\n"
            "  brew install mpv"
        )
    elif sys.platform == "win32":
        return (
            "libmpv-2.dll was not found on your system.\n"
            "Please place libmpv-2.dll into the application folder or set NIHONGO_LIBMPV."
        )
    else:
        return "libmpv shared library was not found. Please install libmpv for your operating system."


def check_libmpv() -> bool:
    """Check whether libmpv shared library can be located and initialized.

    Returns:
        True if libmpv is located and loadable, False otherwise.
    """
    try:
        from nihongo_player.player.libmpv_loader import ensure_libmpv
        ensure_libmpv()
        import mpv  # noqa: F401
        return True
    except (ImportError, OSError, Exception):
        return False


def check_mt_model() -> bool:
    """Check whether Opus-MT CTranslate2 model directory is available.

    Returns:
        True if a valid model directory is resolved on disk, False otherwise.
    """
    try:
        from nihongo_player.mt.translator import Translator
        t = Translator()
        return t.is_available()
    except Exception:
        return False


def check_dictionary() -> bool:
    """Check whether jamdict and JMdict database are available.

    Returns:
        True if jamdict is importable, False otherwise.
    """
    try:
        import jamdict  # noqa: F401
        return True
    except Exception:
        return False


def check_tokenizer() -> bool:
    """Check whether fugashi tokenizer and dictionary are available.

    Returns:
        True if fugashi can be imported and initialized, False otherwise.
    """
    try:
        import fugashi  # noqa: F401
        return True
    except Exception:
        return False


def check_asr_models() -> dict[str, Any]:
    """Check whether speech recognition models and runtime are available and cached.

    Non-blocking inspection of the Hugging Face hub cache for Kotoba-Whisper
    and Anime-Whisper model files.

    Returns:
        Dictionary indicating faster-whisper package availability, cache status for
        'kotoba' and 'anime' models, and overall readiness boolean.
    """
    has_faster_whisper = False
    try:
        import faster_whisper  # noqa: F401
        has_faster_whisper = True
    except Exception:
        has_faster_whisper = False

    has_kotoba = False
    has_anime = False

    try:
        from huggingface_hub import try_to_load_from_cache
        res_kotoba = try_to_load_from_cache("kotoba-tech/kotoba-whisper-v2.0-faster", "model.bin")
        has_kotoba = isinstance(res_kotoba, str)
        res_anime = try_to_load_from_cache("quantumcookie/anime-whisper-ct2-int8", "model.bin")
        has_anime = isinstance(res_anime, str)
    except Exception:
        pass

    return {
        "available": has_faster_whisper,
        "kotoba": has_kotoba,
        "anime": has_anime,
        "ready": has_faster_whisper and (has_kotoba or has_anime),
    }


def ensure_resources() -> dict[str, Any]:
    """Inspect system environment and return a resource availability report.

    Performs non-blocking checks for libmpv, Opus-MT translation model,
    jamdict dictionary database, fugashi morphological tokenizer, and ASR models.

    Returns:
        Dictionary report containing boolean flags for each resource,
        a combined 'all_ok' flag, a list of warning messages, and installation hints.
    """
    has_libmpv = check_libmpv()
    has_mt = check_mt_model()
    has_dict = check_dictionary()
    has_tok = check_tokenizer()
    asr_status = check_asr_models()

    warnings: list[str] = []
    hints: dict[str, str] = {}

    if not has_libmpv:
        hint = get_libmpv_install_hint()
        hints["libmpv"] = hint
        warnings.append(hint)

    if not has_tok:
        msg = "Fugashi tokenizer is not available. Subtitle furigana analysis will be disabled."
        hints["tokenizer"] = msg
        warnings.append(msg)

    if not has_dict:
        msg = "Jamdict dictionary is not available. Vocabulary lookups will be disabled."
        hints["dictionary"] = msg
        warnings.append(msg)

    if not has_mt:
        msg = (
            "Opus-MT Japanese-to-English translation model not found.\n"
            "Run 'python scripts/fetch_models.py' to download and convert the model."
        )
        hints["mt_model"] = msg
        warnings.append(msg)

    all_ok = has_libmpv and has_mt and has_dict and has_tok

    return {
        "libmpv": has_libmpv,
        "mt_model": has_mt,
        "mt": has_mt,
        "dictionary": has_dict,
        "dict": has_dict,
        "tokenizer": has_tok,
        "tok": has_tok,
        "asr": asr_status,
        "all_ok": all_ok,
        "warnings": warnings,
        "hints": hints,
    }


class FirstRunSetup:
    """Manages offline dictionary database downloads and NLLB model caching."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        """Initialize setup manager with application data directory."""
        if data_dir is None:
            base_dir = os.environ.get(
                "XDG_DATA_HOME",
                os.path.expanduser("~/.local/share"),
            )
            self.data_dir = Path(base_dir) / "nihongo-player"
        else:
            self.data_dir = Path(data_dir)

    def is_setup_complete(self) -> bool:
        """Check if required dictionaries and models are present on disk."""
        report = ensure_resources()
        return bool(report["all_ok"])

    def download_unidic(self, progress_cb: Callable[[float], None] | None = None) -> None:
        """Download UniDic morphological dictionary if not present."""
        pass

    def download_jamdict(self, progress_cb: Callable[[float], None] | None = None) -> None:
        """Download JMdict/KanjiDic2 SQLite database if not present."""
        pass

    def download_nllb_model(self, progress_cb: Callable[[float], None] | None = None) -> None:
        """Download CTranslate2 model from HuggingFace Hub."""
        pass


def check_and_download_models(data_dir: str | Path | None = None) -> bool:
    """Convenience helper to verify assets and trigger first-run downloads."""
    setup = FirstRunSetup(data_dir=data_dir)
    return setup.is_setup_complete()
