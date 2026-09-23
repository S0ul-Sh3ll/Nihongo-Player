"""Offline Japanese-to-English neural machine translation using CTranslate2."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any


def _get_user_data_dir() -> Path:
    """Return standard user data directory for application assets."""
    try:
        import platformdirs

        return Path(platformdirs.user_data_dir("nihongo-player"))
    except ImportError:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
            return Path(appdata) / "nihongo-player"
        elif sys.platform == "darwin":
            return Path(os.path.expanduser("~/Library/Application Support")) / "nihongo-player"
        else:
            xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            return Path(xdg_data) / "nihongo-player"


def _is_valid_model_dir(dir_path: Path | str | None) -> bool:
    """Check whether candidate directory contains required CTranslate2 and SPM model files."""
    if not dir_path:
        return False
    path = Path(dir_path).resolve()
    if not path.is_dir():
        return False
    return (
        (path / "model.bin").is_file()
        and (path / "source.spm").is_file()
        and (path / "target.spm").is_file()
    )


def resolve_model_dir(explicit: str | Path | None = None) -> str | None:
    """Resolve directory path containing Opus-MT CTranslate2 model files.

    Resolution order:
    1. Explicit path argument (if provided)
    2. NIHONGO_MT_MODEL environment variable
    3. Package data directory: <package_dir>/models/opus-ja-en-ct2
    4. Project root directory (development): <project_root>/models/opus-ja-en-ct2
    5. User data cache directory: platformdirs user_data_dir('nihongo-player')/models/opus-ja-en-ct2

    Returns:
        Absolute string path to model directory if valid (contains model.bin,
        source.spm, and target.spm), or None if not found.
    """
    if explicit is not None:
        p = Path(explicit)
        if _is_valid_model_dir(p):
            return str(p.resolve())
        return None

    # 2. NIHONGO_MT_MODEL env var
    env_path = os.environ.get("NIHONGO_MT_MODEL")
    if env_path and _is_valid_model_dir(env_path):
        return str(Path(env_path).resolve())

    # 3. PyInstaller bundle directory (sys._MEIPASS)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_model_dir = Path(meipass) / "models" / "opus-ja-en-ct2"
        if _is_valid_model_dir(meipass_model_dir):
            return str(meipass_model_dir.resolve())

    # 4. Beside executable (PyInstaller onedir distribution)
    try:
        exec_model_dir = Path(sys.executable).resolve().parent / "models" / "opus-ja-en-ct2"
        if _is_valid_model_dir(exec_model_dir):
            return str(exec_model_dir.resolve())
    except Exception:
        pass

    # 5. Package data directory (<package_dir>/models/opus-ja-en-ct2)
    pkg_dir = Path(__file__).resolve().parent.parent
    pkg_model_dir = pkg_dir / "models" / "opus-ja-en-ct2"
    if _is_valid_model_dir(pkg_model_dir):
        return str(pkg_model_dir.resolve())

    # 6. Project root directory (<project_root>/models/opus-ja-en-ct2)
    try:
        project_root = Path(__file__).resolve().parents[3]
        dev_model_dir = project_root / "models" / "opus-ja-en-ct2"
        if _is_valid_model_dir(dev_model_dir):
            return str(dev_model_dir.resolve())
    except IndexError:
        pass

    cwd_model_dir = Path.cwd() / "models" / "opus-ja-en-ct2"
    if _is_valid_model_dir(cwd_model_dir):
        return str(cwd_model_dir.resolve())

    # 7. User data cache directory
    user_cache_dir = _get_user_data_dir() / "models" / "opus-ja-en-ct2"
    if _is_valid_model_dir(user_cache_dir):
        return str(user_cache_dir.resolve())

    return None


class Translator:
    """Offline Japanese-to-English neural machine translator using CTranslate2."""

    def __init__(
        self,
        model_dir: str | Path | None = None,
        intra_threads: int = 4,
    ) -> None:
        """Initialize translator with optional custom model path.

        Args:
            model_dir: Path to model directory containing model.bin, source.spm, and target.spm.
            intra_threads: Number of CPU threads to use for CTranslate2 inference.
        """
        self._model_dir: str | None = resolve_model_dir(model_dir)
        self._intra_threads = intra_threads
        self.available: bool = self._model_dir is not None
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

        self._translator: Any = None
        self._source_sp: Any = None
        self._target_sp: Any = None

    def is_available(self) -> bool:
        """Return True if model is found and available for translation."""
        return self.available

    def _ensure_loaded(self) -> None:
        """Lazily load CTranslate2 and SentencePiece models."""
        if not self.available or self._model_dir is None:
            return
        if self._translator is not None:
            return

        with self._lock:
            if self._translator is not None:
                return

            import ctranslate2
            import sentencepiece as spm

            model_path = Path(self._model_dir)
            sp_src = spm.SentencePieceProcessor()
            sp_src.load(str(model_path / "source.spm"))

            sp_tgt = spm.SentencePieceProcessor()
            sp_tgt.load(str(model_path / "target.spm"))

            translator = ctranslate2.Translator(
                str(model_path),
                device="cpu",
                intra_threads=self._intra_threads,
            )

            self._source_sp = sp_src
            self._target_sp = sp_tgt
            self._translator = translator

    def translate(self, text: str) -> str:
        """Translate a single Japanese text string into English.

        Args:
            text: Japanese source text.

        Returns:
            Translated English string, or empty string if text is empty or model unavailable.
        """
        stripped = text.strip()
        if not stripped or not self.available:
            return ""

        with self._lock:
            if stripped in self._cache:
                return self._cache[stripped]

        results = self.translate_many([stripped])
        return results[0] if results else ""

    def translate_many(self, texts: list[str]) -> list[str]:
        """Translate multiple Japanese text strings in an efficient batch.

        Args:
            texts: List of Japanese source strings.

        Returns:
            List of translated English strings in the same order as input.
        """
        if not texts:
            return []

        if not self.available:
            return ["" for _ in texts]

        self._ensure_loaded()

        with self._lock:
            # Determine uncached unique texts
            uncached: list[str] = []
            for t in texts:
                st = t.strip()
                if st and st not in self._cache and st not in uncached:
                    uncached.append(st)

            # If there are uncached items, run translation batch
            if uncached and self._translator is not None:
                tokenized_batch = [
                    self._source_sp.encode(item, out_type=str) + ["</s>"]
                    for item in uncached
                ]

                batch_results = self._translator.translate_batch(
                    tokenized_batch,
                    beam_size=4,
                    max_decoding_length=200,
                    repetition_penalty=1.2,
                    no_repeat_ngram_size=3,
                )

                for item, res in zip(uncached, batch_results):
                    hyp = res.hypotheses[0] if res.hypotheses else []
                    if hyp and hyp[-1] == "</s>":
                        hyp = hyp[:-1]
                    out = self._target_sp.decode(hyp)
                    self._cache[item] = out

            # Construct results preserving original ordering and blank handling
            output: list[str] = []
            for t in texts:
                st = t.strip()
                if not st:
                    output.append("")
                else:
                    output.append(self._cache.get(st, ""))

            return output


# Backward compatibility alias
NLLBTranslator = Translator
