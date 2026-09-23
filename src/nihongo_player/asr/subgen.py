"""AI subtitle generation for videos without subtitles using faster-whisper and Anime-Whisper / Kotoba-Whisper."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_TIMING_MODEL = "kotoba-tech/kotoba-whisper-v2.0-faster"
DEFAULT_TEXT_MODEL = "quantumcookie/anime-whisper-ct2-int8"
DEFAULT_MODEL_NAME = "kotoba-tech/kotoba-whisper-v2.0-faster"
DEFAULT_ASR_MODE = "coverage"
DEFAULT_WINDOW_SECONDS = 5.0

ASR_MODEL_PRESETS: list[tuple[str, str, str]] = [
    ("kotoba-tech/kotoba-whisper-v2.0-faster", "Fast — kotoba only", "~600MB"),
    ("quantumcookie/anime-whisper-ct2-int8", "Anime only (experimental timing)", "~768MB"),
    ("Systran/faster-whisper-large-v3", "High accuracy — large-v3 (~3GB, slow)", "~3GB"),
]

ASR_MODE_PRESETS: list[tuple[str, str, str, str, str | None, str]] = [
    (
        "coverage",
        "Maximum coverage — catches all lines incl. over music (default)",
        "Transcribes the whole audio in fixed windows so nothing is missed (incl. shouts over music); timing is ~window-granular and it may include some sound effects.",
        "coverage",
        "quantumcookie/anime-whisper-ct2-int8",
        "~768MB",
    ),
    (
        "hybrid",
        "Accurate — anime + kotoba hybrid (slower)",
        "Best accuracy with correct timing; downloads two models on first use (~600MB + ~768MB), transcribes twice so it's slower.",
        "hybrid",
        None,
        "~1.4GB",
    ),
    (
        "kotoba",
        "Fast — kotoba only",
        "Fast and well-timed using Kotoba-Whisper (~600MB download).",
        "single",
        "kotoba-tech/kotoba-whisper-v2.0-faster",
        "~600MB",
    ),
    (
        "anime",
        "Anime only (experimental timing)",
        "Best word accuracy but timing is coarse in this build.",
        "single",
        "quantumcookie/anime-whisper-ct2-int8",
        "~768MB",
    ),
    (
        "large-v3",
        "High accuracy — large-v3 (~3GB, slow)",
        "Maximum accuracy for complex dialogue (~3GB download, slow).",
        "single",
        "Systran/faster-whisper-large-v3",
        "~3GB",
    ),
]



def is_available() -> bool:
    """Check if faster-whisper package is installed and importable."""
    try:
        import faster_whisper  # noqa: F401

        return True
    except (ImportError, Exception):
        return False


def srt_timestamp(seconds: float) -> str:
    """Format seconds float into standard SRT timestamp format: HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    ms_total = int(round(seconds * 1000.0))
    hours = ms_total // 3600000
    minutes = (ms_total % 3600000) // 60000
    secs = (ms_total % 60000) // 1000
    ms = ms_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def merge_coverage_cues(raw_cues: Iterable[Any]) -> list[tuple[float, float, str]]:
    """Merge adjacent cues and deduplicate hallucination repeats in coverage mode.

    - Drops empty/whitespace-only cues.
    - Dedupes adjacent cues with identical text (hallucination repeats across contiguous windows).
    - Merges a cue into previous if previous cue ends with the prefix of the next cue
      (avoiding split-sentence duplication across window boundaries).
    - Merges strict prefix/substring continuations.

    Args:
        raw_cues: Ordered iterable of (start, end, text) tuples or segment objects.

    Returns:
        List of merged (start, end, text) tuples.
    """
    if raw_cues is None:
        return []

    filtered: list[tuple[float, float, str]] = []
    for item in raw_cues:
        if isinstance(item, (tuple, list)) and len(item) >= 3:
            s_val = item[0]
            e_val = item[1]
            t_val = item[2]
        else:
            s_val = getattr(item, "start", 0.0)
            e_val = getattr(item, "end", 0.0)
            t_val = getattr(item, "text", "")

        text = str(t_val or "").strip()
        if not text:
            continue
        start = float(s_val or 0.0)
        end = float(e_val or 0.0)
        filtered.append((start, end, text))

    if not filtered:
        return []

    merged: list[tuple[float, float, str]] = []
    last_seen_end = 0.0
    for start, end, text in filtered:
        if not merged:
            merged.append((start, end, text))
            last_seen_end = end
            continue

        prev_start, prev_end, prev_text = merged[-1]
        is_adjacent = (start <= max(prev_end, last_seen_end) + 1.0)

        if is_adjacent:
            # 1. Dedup exact-equal adjacent text (hallucination repeats across windows)
            if text == prev_text:
                last_seen_end = max(last_seen_end, end)
                continue

            # 2. If prev_text already contains text
            if text in prev_text:
                merged[-1] = (prev_start, max(prev_end, end), prev_text)
                last_seen_end = max(last_seen_end, end)
                continue

            # 3. If text is a strict extension of prev_text
            if text.startswith(prev_text):
                merged[-1] = (prev_start, max(prev_end, end), text)
                last_seen_end = max(last_seen_end, end)
                continue

            # 4. Suffix/prefix overlap: prev_text ends with text[:k]
            overlap_found = False
            max_k = min(len(prev_text), len(text))
            for k in range(max_k, 1, -1):
                if prev_text.endswith(text[:k]):
                    combined = prev_text + text[k:]
                    merged[-1] = (prev_start, max(prev_end, end), combined)
                    last_seen_end = max(last_seen_end, end)
                    overlap_found = True
                    break

            if overlap_found:
                continue

        merged.append((start, end, text))
        last_seen_end = end

    return merged


def post_process_cues(raw_cues: Iterable[Any]) -> list[tuple[float, float, str]]:
    """Clean, deduplicate, cap duration, and clamp ASR subtitle cues.

    Performs robust post-processing on speech recognition segments:
    - Drops empty/whitespace-only cues.
    - Deduplicates consecutive hallucination repeats when text is identical
      and starts within ~1.0s of the previous end.
    - Caps on-screen duration based on text length:
        cap = max(1.5, min(7.0, len(text) * 0.35))
        end = min(orig_end, start + cap, next_start)
        if end < start + 0.4: end = start + 0.4

    Args:
        raw_cues: Ordered iterable of (start, end, text) tuples or objects
                  with start, end, and text attributes.

    Returns:
        List of cleaned (start, end, text) tuples with accurate timing.
    """
    if raw_cues is None:
        return []

    # 1. Strip text and drop cues with empty/whitespace-only text
    filtered: list[tuple[float, float, str]] = []
    for item in raw_cues:
        if isinstance(item, (tuple, list)) and len(item) >= 3:
            s_val = item[0]
            e_val = item[1]
            t_val = item[2]
        else:
            s_val = getattr(item, "start", 0.0)
            e_val = getattr(item, "end", 0.0)
            t_val = getattr(item, "text", "")

        text = str(t_val or "").strip()
        if not text:
            continue
        start = float(s_val or 0.0)
        end = float(e_val or 0.0)
        filtered.append((start, end, text))

    if not filtered:
        return []

    # 2. Dedup consecutive hallucination repeats:
    # If a cue's text == previous kept cue's text AND it starts within ~1.0s of previous end
    deduped: list[tuple[float, float, str]] = []
    last_seen_end = 0.0
    for start, orig_end, text in filtered:
        if deduped:
            prev_start, prev_orig_end, prev_text = deduped[-1]
            if text == prev_text and (start - max(prev_orig_end, last_seen_end)) <= 1.0:
                last_seen_end = max(last_seen_end, orig_end)
                continue
        deduped.append((start, orig_end, text))
        last_seen_end = orig_end

    if not deduped:
        return []

    # 3. Cap each cue's on-screen duration and clamp to the next cue's start
    processed: list[tuple[float, float, str]] = []
    n = len(deduped)
    for i, (start, orig_end, text) in enumerate(deduped):
        cap = max(1.5, min(7.0, len(text) * 0.35))
        if i + 1 < n:
            next_start = deduped[i + 1][0]
            end = min(orig_end, start + cap, next_start)
        else:
            end = min(orig_end, start + cap)

        if end < start + 0.4:
            end = start + 0.4

        processed.append((start, end, text))

    return processed


def segments_to_srt(segments_iterable: Iterable[Any]) -> str:
    """Build a valid SRT formatted string from an iterable of segment objects or tuples.

    Each segment must have start (float seconds), end (float seconds), and text (str)
    attributes or be a (start, end, text) tuple/list. Empty or whitespace-only text
    segments are skipped. Cues are numbered 1-based and separated by blank lines.

    Args:
        segments_iterable: Iterable of segment objects or (start, end, text) tuples.

    Returns:
        Formatted SRT string, or empty string if no valid cues exist.
    """
    cues: list[str] = []
    cue_index = 1
    for seg in segments_iterable:
        if isinstance(seg, (tuple, list)) and len(seg) >= 3:
            start_sec = float(seg[0] or 0.0)
            end_sec = float(seg[1] or 0.0)
            raw_text = seg[2]
        else:
            start_sec = float(getattr(seg, "start", 0.0) or 0.0)
            end_sec = float(getattr(seg, "end", 0.0) or 0.0)
            raw_text = getattr(seg, "text", "")

        if raw_text is None:
            continue
        text_str = str(raw_text).strip()
        if not text_str:
            continue
        start_ts = srt_timestamp(start_sec)
        end_ts = srt_timestamp(end_sec)
        cues.append(f"{cue_index}\n{start_ts} --> {end_ts}\n{text_str}")
        cue_index += 1

    if not cues:
        return ""
    return "\n\n".join(cues) + "\n\n"


def get_default_output_path(media_path: str | Path) -> Path:
    """Compute default subtitle output path for a given media file.

    Defaults to <media_dir>/<media_stem>.srt. If that file already exists,
    returns <media_dir>/<media_stem>.ja.srt to avoid clobbering existing subtitles.

    Args:
        media_path: Path to the media file.

    Returns:
        Path to the target output .srt file.
    """
    media = Path(media_path)
    primary = media.with_suffix(".srt")
    if primary.exists():
        return media.with_name(f"{media.stem}.ja.srt")
    return primary


class SubtitleGenerator:
    """Japanese subtitle generator using faster-whisper and Anime-Whisper / Kotoba-Whisper."""

    default_output_path = staticmethod(get_default_output_path)

    def __init__(
        self,
        model_name: str | None = None,
        mode: str | None = None,
        timing_model: str | None = None,
        text_model: str | None = None,
        window_seconds: float | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: str | None = None,
    ) -> None:
        """Initialize SubtitleGenerator with model configurations.

        mode resolution order:
        1. Explicit constructor argument
        2. Environment variable NIHONGO_WHISPER_MODE
        3. Default DEFAULT_ASR_MODE ('coverage')

        timing_model resolution order (hybrid mode):
        1. Explicit constructor argument
        2. Environment variable NIHONGO_WHISPER_TIMING_MODEL
        3. Default DEFAULT_TIMING_MODEL ('kotoba-tech/kotoba-whisper-v2.0-faster')

        text_model resolution order (hybrid/coverage mode):
        1. Explicit constructor argument
        2. Environment variable NIHONGO_WHISPER_TEXT_MODEL
        3. Default DEFAULT_TEXT_MODEL ('quantumcookie/anime-whisper-ct2-int8')

        model_name resolution order (single mode):
        1. Explicit constructor argument
        2. Environment variable NIHONGO_WHISPER_MODEL
        3. Default DEFAULT_MODEL_NAME ('kotoba-tech/kotoba-whisper-v2.0-faster')

        window_seconds resolution order (coverage mode):
        1. Explicit constructor argument
        2. Environment variable NIHONGO_WHISPER_WINDOW
        3. Default DEFAULT_WINDOW_SECONDS (5.0)

        download_root resolution order:
        1. Explicit download_root argument
        2. Environment variable NIHONGO_WHISPER_MODELS
        3. None (defaults to Hugging Face hub cache ~/.cache/huggingface)

        Args:
            model_name: HuggingFace model repository ID for single mode.
            mode: Pipeline mode ('hybrid', 'coverage', or 'single').
            timing_model: Timing model ID for hybrid mode.
            text_model: Text recognition model ID for hybrid / coverage mode.
            window_seconds: Sliding window length in seconds for coverage mode.
            device: Inference device ('cpu', 'cuda', or 'auto').
            compute_type: Computation quantization type ('int8', 'float16', 'float32').
            download_root: Optional custom directory to download/load models.
        """
        resolved_mode = mode or os.environ.get("NIHONGO_WHISPER_MODE") or DEFAULT_ASR_MODE
        self.mode = resolved_mode.strip().lower()

        resolved_timing = (
            timing_model
            or os.environ.get("NIHONGO_WHISPER_TIMING_MODEL")
            or DEFAULT_TIMING_MODEL
        )
        self.timing_model = resolved_timing.strip()

        resolved_text = (
            text_model
            or os.environ.get("NIHONGO_WHISPER_TEXT_MODEL")
            or DEFAULT_TEXT_MODEL
        )
        self.text_model = resolved_text.strip()

        resolved_model = (
            model_name
            or os.environ.get("NIHONGO_WHISPER_MODEL")
            or DEFAULT_MODEL_NAME
        )
        self.model_name = resolved_model.strip()

        if window_seconds is not None:
            self.window_seconds = float(window_seconds)
        else:
            env_win = os.environ.get("NIHONGO_WHISPER_WINDOW")
            if env_win and env_win.strip():
                try:
                    self.window_seconds = float(env_win.strip())
                except ValueError:
                    self.window_seconds = DEFAULT_WINDOW_SECONDS
            else:
                self.window_seconds = DEFAULT_WINDOW_SECONDS

        if download_root is None:
            download_root = os.environ.get("NIHONGO_WHISPER_MODELS") or None
        self.download_root = download_root

        self.device = device
        self.compute_type = compute_type
        self._model: Any = None
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if faster-whisper is installed and importable."""
        return is_available()

    def _create_model(self, model_id: str) -> Any:
        """Instantiate a new WhisperModel instance for the given model ID."""
        if not self.is_available():
            raise RuntimeError(
                "faster-whisper is not installed. Install with 'pip install faster-whisper' or 'pip install -e .[asr]'."
            )
        from faster_whisper import WhisperModel

        return WhisperModel(
            model_id,
            device=self.device,
            compute_type=self.compute_type,
            download_root=self.download_root,
        )

    def _load_model(self) -> Any:
        """Lazily instantiate and cache the single WhisperModel instance."""
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is None:
                self._model = self._create_model(self.model_name)
        return self._model

    def release_model(self) -> None:
        """Release cached WhisperModel instance and garbage collect resources."""
        with self._lock:
            if self._model is not None:
                del self._model
                self._model = None
            import gc
            gc.collect()

    def generate(
        self,
        media_path: str | Path,
        out_srt_path: str | Path | None = None,
        language: str = "ja",
        progress_cb: Callable[[float, float], None] | None = None,
        cancel_cb: Callable[[], bool] | None = None,
        status_cb: Callable[[str], None] | None = None,
    ) -> str:
        """Transcribe media file and write Japanese subtitles to an SRT file.

        Args:
            media_path: Path to input audio or video file.
            out_srt_path: Destination .srt path. If None, defaults to <media>.srt (or <media>.ja.srt).
            language: Speech language code (default 'ja').
            progress_cb: Optional callback receiving (done_seconds, total_seconds).
            cancel_cb: Optional callback returning True if cancellation is requested.
            status_cb: Optional callback receiving status message string.

        Returns:
            String path to the written .srt file.

        Raises:
            RuntimeError: If faster-whisper is missing or transcription fails.
            FileNotFoundError: If the input media file cannot be found.
            InterruptedError: If generation is cancelled via cancel_cb.
        """
        media = Path(media_path).resolve()
        if not media.is_file():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        if out_srt_path is None:
            dest_path = get_default_output_path(media)
        else:
            dest_path = Path(out_srt_path).resolve()

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if cancel_cb is not None and cancel_cb():
            raise InterruptedError("Subtitle generation cancelled.")

        if self.mode == "hybrid":
            return self._generate_hybrid(
                media=media,
                dest_path=dest_path,
                language=language,
                progress_cb=progress_cb,
                cancel_cb=cancel_cb,
                status_cb=status_cb,
            )
        elif self.mode == "coverage":
            return self._generate_coverage(
                media=media,
                dest_path=dest_path,
                language=language,
                progress_cb=progress_cb,
                cancel_cb=cancel_cb,
                status_cb=status_cb,
            )
        else:
            return self._generate_single(
                media=media,
                dest_path=dest_path,
                language=language,
                progress_cb=progress_cb,
                cancel_cb=cancel_cb,
                status_cb=status_cb,
            )

    def _generate_single(
        self,
        media: Path,
        dest_path: Path,
        language: str = "ja",
        progress_cb: Callable[[float, float], None] | None = None,
        cancel_cb: Callable[[], bool] | None = None,
        status_cb: Callable[[str], None] | None = None,
    ) -> str:
        if status_cb is not None:
            status_cb("Loading speech model…")

        model = self._load_model()

        if cancel_cb is not None and cancel_cb():
            raise InterruptedError("Subtitle generation cancelled.")

        use_vad = os.environ.get("NIHONGO_WHISPER_VAD") == "1"
        transcribe_kwargs: dict[str, Any] = {
            "language": language,
            "condition_on_previous_text": False,
            "beam_size": 5,
            "no_speech_threshold": 0.6,
            "vad_filter": use_vad,
        }
        if use_vad:
            transcribe_kwargs["vad_parameters"] = dict(
                min_silence_duration_ms=400,
                speech_pad_ms=150,
            )

        segments_gen, info = model.transcribe(
            str(media),
            **transcribe_kwargs,
        )

        total_duration = float(getattr(info, "duration", 0.0) or 0.0)
        temp_dest = dest_path.with_name(f"{dest_path.name}.tmp.{os.getpid()}")

        try:
            raw_segments: list[tuple[float, float, str]] = []
            for seg in segments_gen:
                if cancel_cb is not None and cancel_cb():
                    raise InterruptedError("Subtitle generation cancelled.")

                start_val = float(getattr(seg, "start", 0.0) or 0.0)
                end_val = float(getattr(seg, "end", 0.0) or 0.0)
                text_val = str(getattr(seg, "text", "") or "")
                raw_segments.append((start_val, end_val, text_val))

                if progress_cb is not None:
                    done_sec = min(end_val, total_duration) if total_duration > 0.0 else end_val
                    progress_cb(done_sec, total_duration)

            if cancel_cb is not None and cancel_cb():
                raise InterruptedError("Subtitle generation cancelled.")

            cleaned_cues = post_process_cues(raw_segments)
            srt_content = segments_to_srt(cleaned_cues)

            with open(temp_dest, "w", encoding="utf-8") as f:
                f.write(srt_content)

            temp_dest.replace(dest_path)
            return str(dest_path.resolve())
        except Exception:
            if temp_dest.exists():
                try:
                    temp_dest.unlink()
                except Exception:
                    pass
            raise

    def _generate_hybrid(
        self,
        media: Path,
        dest_path: Path,
        language: str = "ja",
        progress_cb: Callable[[float, float], None] | None = None,
        cancel_cb: Callable[[], bool] | None = None,
        status_cb: Callable[[str], None] | None = None,
    ) -> str:
        temp_dest = dest_path.with_name(f"{dest_path.name}.tmp.{os.getpid()}")
        try:
            # -------------------------------------------------------------
            # Phase 1: Timing model (kotoba-whisper) -> segment windows
            # -------------------------------------------------------------
            if cancel_cb is not None and cancel_cb():
                raise InterruptedError("Subtitle generation cancelled.")

            if status_cb is not None:
                status_cb("Analyzing timing… 0%")

            timing_model = self._create_model(self.timing_model)
            windows: list[tuple[float, float]] = []
            total_duration = 0.0

            try:
                segments_gen, info = timing_model.transcribe(
                    str(media),
                    language=language,
                    condition_on_previous_text=False,
                    beam_size=5,
                    no_speech_threshold=0.6,
                    vad_filter=False,
                )
                total_duration = float(getattr(info, "duration", 0.0) or 0.0)

                for seg in segments_gen:
                    if cancel_cb is not None and cancel_cb():
                        raise InterruptedError("Subtitle generation cancelled.")

                    start_val = float(getattr(seg, "start", 0.0) or 0.0)
                    end_val = float(getattr(seg, "end", 0.0) or 0.0)

                    # Keep only non-trivial windows (skip shorter than ~0.3s)
                    if (end_val - start_val) >= 0.3:
                        windows.append((start_val, end_val))

                    if progress_cb is not None:
                        if total_duration > 0.0:
                            done_sec = min(end_val, total_duration) * 0.40
                            progress_cb(done_sec, total_duration)
                        else:
                            progress_cb(end_val * 0.40, 100.0)

                    if status_cb is not None:
                        pct = int(min(end_val, total_duration) / total_duration * 40.0) if total_duration > 0 else 0
                        status_cb(f"Analyzing timing… {pct}%")
            finally:
                # Release timing model BEFORE loading text model
                del timing_model
                import gc
                gc.collect()

            if cancel_cb is not None and cancel_cb():
                raise InterruptedError("Subtitle generation cancelled.")

            if not windows:
                # No speech windows detected -> write empty SRT
                with open(temp_dest, "w", encoding="utf-8") as f:
                    f.write("")
                temp_dest.replace(dest_path)
                return str(dest_path.resolve())

            # -------------------------------------------------------------
            # Phase 2: Text model (anime-whisper) -> accurate window text
            # -------------------------------------------------------------
            if status_cb is not None:
                status_cb("Transcribing (accurate)… 40%")

            text_model = self._create_model(self.text_model)
            raw_cues: list[tuple[float, float, str]] = []
            num_windows = len(windows)

            try:
                for idx, (w_start, w_end) in enumerate(windows):
                    if cancel_cb is not None and cancel_cb():
                        raise InterruptedError("Subtitle generation cancelled.")

                    clip_ts = f"{w_start},{w_end}"
                    w_segments_gen, _ = text_model.transcribe(
                        str(media),
                        language=language,
                        condition_on_previous_text=False,
                        clip_timestamps=clip_ts,
                        beam_size=5,
                        no_speech_threshold=0.6,
                        vad_filter=False,
                    )

                    seg_texts: list[str] = []
                    for w_seg in w_segments_gen:
                        t_val = getattr(w_seg, "text", "")
                        if t_val:
                            seg_texts.append(str(t_val).strip())

                    window_text = "".join(seg_texts).strip()
                    if window_text:
                        raw_cues.append((w_start, w_end, window_text))

                    frac = (idx + 1) / float(num_windows)
                    pct = 40.0 + 60.0 * frac
                    if progress_cb is not None:
                        if total_duration > 0.0:
                            done_sec = (0.40 + 0.60 * frac) * total_duration
                            progress_cb(done_sec, total_duration)
                        else:
                            progress_cb(pct, 100.0)

                    if status_cb is not None:
                        status_cb(f"Transcribing (accurate)… {int(pct)}%")
            finally:
                # Release text model
                del text_model
                import gc
                gc.collect()

            if cancel_cb is not None and cancel_cb():
                raise InterruptedError("Subtitle generation cancelled.")

            # -------------------------------------------------------------
            # Phase 3: Post-processing and SRT generation
            # -------------------------------------------------------------
            cleaned_cues = post_process_cues(raw_cues)
            srt_content = segments_to_srt(cleaned_cues)

            with open(temp_dest, "w", encoding="utf-8") as f:
                f.write(srt_content)

            temp_dest.replace(dest_path)
            return str(dest_path.resolve())
        except Exception:
            if temp_dest.exists():
                try:
                    temp_dest.unlink()
                except Exception:
                    pass
            raise

    def _generate_coverage(
        self,
        media: Path,
        dest_path: Path,
        language: str = "ja",
        progress_cb: Callable[[float, float], None] | None = None,
        cancel_cb: Callable[[], bool] | None = None,
        status_cb: Callable[[str], None] | None = None,
    ) -> str:
        temp_dest = dest_path.with_name(f"{dest_path.name}.tmp.{os.getpid()}")
        try:
            if cancel_cb is not None and cancel_cb():
                raise InterruptedError("Subtitle generation cancelled.")

            if status_cb is not None:
                status_cb("Transcribing all audio (max coverage)… 0%")

            text_model = self._create_model(self.text_model)
            raw_cues: list[tuple[float, float, str]] = []
            t = 0.0
            total_duration = 0.0
            win_sec = max(0.5, self.window_seconds)

            try:
                while True:
                    if cancel_cb is not None and cancel_cb():
                        raise InterruptedError("Subtitle generation cancelled.")

                    w_start = t
                    w_end = t + win_sec
                    if total_duration > 0.0 and w_end > total_duration:
                        w_end = total_duration

                    clip_ts = f"{w_start},{w_end}"
                    w_segments_gen, info = text_model.transcribe(
                        str(media),
                        language=language,
                        condition_on_previous_text=False,
                        clip_timestamps=clip_ts,
                        beam_size=5,
                        no_speech_threshold=0.6,
                        vad_filter=False,
                    )

                    if total_duration == 0.0:
                        total_duration = float(getattr(info, "duration", 0.0) or 0.0)
                        if total_duration > 0.0 and w_end > total_duration:
                            w_end = total_duration

                    seg_texts: list[str] = []
                    for w_seg in w_segments_gen:
                        if cancel_cb is not None and cancel_cb():
                            raise InterruptedError("Subtitle generation cancelled.")
                        t_val = getattr(w_seg, "text", "")
                        if t_val:
                            seg_texts.append(str(t_val).strip())

                    window_text = "".join(seg_texts).strip()
                    if window_text:
                        raw_cues.append((w_start, w_end, window_text))

                    if progress_cb is not None:
                        if total_duration > 0.0:
                            done_sec = min(w_end, total_duration)
                            progress_cb(done_sec, total_duration)
                        else:
                            progress_cb(w_end, w_end)

                    if status_cb is not None:
                        pct = int((min(w_end, total_duration) / total_duration) * 100.0) if total_duration > 0.0 else 0
                        status_cb(f"Transcribing all audio (max coverage)… {pct}%")

                    t += win_sec
                    if total_duration > 0.0 and t >= total_duration:
                        break
                    if total_duration == 0.0:
                        break
            finally:
                del text_model
                import gc
                gc.collect()

            if cancel_cb is not None and cancel_cb():
                raise InterruptedError("Subtitle generation cancelled.")

            merged_cues = merge_coverage_cues(raw_cues)
            cleaned_cues = post_process_cues(merged_cues)
            srt_content = segments_to_srt(cleaned_cues)

            with open(temp_dest, "w", encoding="utf-8") as f:
                f.write(srt_content)

            temp_dest.replace(dest_path)
            return str(dest_path.resolve())
        except Exception:
            if temp_dest.exists():
                try:
                    temp_dest.unlink()
                except Exception:
                    pass
            raise
