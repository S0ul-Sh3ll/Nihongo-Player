"""Subtitle parser and loader supporting SRT, ASS, SSA, and WebVTT formats."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence

from nihongo_player.subs.text_clean import clean_subtitle_text, strip_formatting_tags

_JA_LANG_TAG_RE = re.compile(
    r"(?:^|[._\-\[\(\s])(?:ja|jp|jpn|japanese|nihongo|日本語)(?:$|[._\-\]\)\s])",
    re.IGNORECASE,
)

SUBTITLE_EXTENSIONS: frozenset[str] = frozenset({".srt", ".ass", ".ssa", ".vtt"})

_EXT_TO_FORMAT: dict[str, str] = {
    ".srt": "srt",
    ".ass": "ass",
    ".ssa": "ssa",
    ".vtt": "vtt",
    ".sub": "microdvd",
}


@dataclass(frozen=True)
class Cue:
    """Represents a single timed subtitle cue.

    Attributes:
        index: Zero-based sequential index of the cue.
        start: Start time in seconds (float, matching mpv time-pos).
        end: End time in seconds (float, matching mpv time-pos).
        text: Cleaned display text (formatting and caption markers stripped).
        raw: Original display text before marker cleaning (formatting tags stripped).
    """

    index: int
    start: float
    end: float
    text: str
    raw: str = ""

    @property
    def duration(self) -> float:
        """Duration of the cue in seconds."""
        return max(0.0, self.end - self.start)

    def __contains__(self, t: object) -> bool:
        """Check if timestamp t falls within [start, end), i.e., start <= t < end."""
        if isinstance(t, (int, float)):
            return self.start <= t < self.end
        return False


def load_subtitles(path: str | Path) -> list[Cue]:
    """Parse .srt/.ass/.ssa/.vtt files via pysubs2 (lazy import) into a sorted list of Cue objects.

    - Detects encoding with UTF-8 BOM fallback
    - Strips formatting and caption markers
    - Skips comment events
    - Preserves cues (even if text becomes empty after marker stripping) to maintain timing
    - Sorts by start timestamp and reindexes to 0..n-1
    """
    import pysubs2

    path_obj = Path(path)
    if not path_obj.is_file():
        raise FileNotFoundError(f"Subtitle file not found: {path}")

    path_str = str(path_obj)
    fmt = _EXT_TO_FORMAT.get(path_obj.suffix.lower())
    encodings_to_try = ["utf-8-sig", "utf-8", "shift_jis", "cp932", "latin-1"]
    subs: pysubs2.SSAFile | None = None
    last_err: Exception | None = None

    for enc in encodings_to_try:
        try:
            # Try with format hint if known from extension, then fallback to auto
            try:
                subs = pysubs2.load(path_str, encoding=enc, format_=fmt)
            except Exception:
                subs = pysubs2.load(path_str, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError) as err:
            last_err = err
            continue
        except Exception as err:
            last_err = err
            continue

    if subs is None:
        if last_err is not None:
            raise last_err
        subs = pysubs2.load(path_str, format_=fmt)

    parsed: list[tuple[float, float, str, str]] = []
    for event in subs:
        if getattr(event, "is_comment", False):
            continue
        event_raw = event.text or ""
        display_raw = strip_formatting_tags(event_raw)
        cleaned = clean_subtitle_text(display_raw)
        start_sec = max(0.0, event.start / 1000.0)
        end_sec = max(start_sec, event.end / 1000.0)
        parsed.append((start_sec, end_sec, cleaned, display_raw))

    # Sort primarily by start timestamp, secondarily by end timestamp
    parsed.sort(key=lambda item: (item[0], item[1]))

    return [
        Cue(
            index=i,
            start=item[0],
            end=item[1],
            text=item[2],
            raw=item[3],
        )
        for i, item in enumerate(parsed)
    ]


class SubtitleLoader:
    """Loads and normalizes subtitle files across various formats (convenience class)."""

    load = staticmethod(load_subtitles)
    clean_text = staticmethod(clean_subtitle_text)


def find_sidecar_subtitle(video_path: str | Path) -> str | None:
    """Find the best matching sidecar subtitle file adjacent to a video file.

    Ranking heuristic:
    1. Looks next to the video for subtitle files (.srt, .ass, .ssa, .vtt).
    2. If only one subtitle file is present in the directory, matches it.
    3. If multiple subtitle files are present, scores them preferring:
       - Japanese language tags (.ja, .jp, .jpn, japanese)
       - Exact video stem match
       - Starts-with video stem
       - Contains video stem (e.g. DownSub download pattern)
       - Extension preference (.srt, .ass, .ssa, .vtt)

    Returns:
        Absolute path string of the best matching subtitle file, or None.
    """
    v_path = Path(video_path)
    parent_dir = v_path.parent
    if not parent_dir.is_dir():
        return None

    # Collect all subtitle files in the same directory
    sub_files: list[Path] = [
        f for f in parent_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUBTITLE_EXTENSIONS
    ]

    if not sub_files:
        return None

    # If only one subtitle file is present in the folder, return it immediately
    if len(sub_files) == 1:
        return str(sub_files[0].resolve())

    v_stem = v_path.stem.lower()

    # Score candidate files
    candidates: list[tuple[int, Path]] = []
    ext_priority = {".srt": 40, ".ass": 30, ".ssa": 20, ".vtt": 10}

    for f in sub_files:
        f_stem = f.stem.lower()
        score = 0

        # Match video stem relation
        if f_stem == v_stem:
            score += 500
        elif f_stem.startswith(v_stem):
            score += 400
        elif v_stem in f_stem:
            score += 300
        elif f_stem in v_stem:
            score += 200

        # Language preference (Japanese tagged)
        if _JA_LANG_TAG_RE.search(f_stem):
            score += 1000

        # Extension priority
        score += ext_priority.get(f.suffix.lower(), 0)

        if score > 0:
            candidates.append((score, f))

    if not candidates:
        return None

    # Sort descending by score, and then alphabetically for deterministic order
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    return str(candidates[0][1].resolve())
