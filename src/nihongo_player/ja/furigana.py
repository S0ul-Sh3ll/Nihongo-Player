"""Furigana alignment algorithms mapping phonetic readings to kanji compounds."""

from __future__ import annotations

from typing import Any, Iterable


def _kata_to_hira_char(c: str) -> str:
    """Fold a single Katakana character to Hiragana."""
    code = ord(c)
    if 0x30A1 <= code <= 0x30F6:
        return chr(code - 0x60)
    return c


def _fold_kana(s: str) -> str:
    """Fold Katakana characters in a string to Hiragana for comparison."""
    return "".join(_kata_to_hira_char(c) for c in s)


def _is_kana(c: str) -> bool:
    """Check if character is Hiragana or Katakana (including prolonged sound mark)."""
    code = ord(c)
    return (0x3040 <= code <= 0x309F) or (0x30A0 <= code <= 0x30FF) or (0xFF66 <= code <= 0xFF9F)


def is_kanji(ch: str) -> bool:
    """Check if character is a CJK ideograph (kanji)."""
    if not ch or len(ch) != 1:
        return False
    code = ord(ch)
    return (
        (0x4E00 <= code <= 0x9FFF)
        or (0x3400 <= code <= 0x4DBF)
        or (0xF900 <= code <= 0xFAFF)
        or (0x20000 <= code <= 0x2A6DF)
        or (0x2A700 <= code <= 0x2B73F)
        or (0x2B740 <= code <= 0x2B81F)
        or (0x2B820 <= code <= 0x2CEAF)
        or (0x2CEB0 <= code <= 0x2EBEF)
        or (0x30000 <= code <= 0x3134F)
        or (0x31350 <= code <= 0x323AF)
        or (0x2F800 <= code <= 0x2FA1F)
    )


def _is_cjk_ideograph(c: str) -> bool:
    """Check if character is a CJK ideograph (kanji). Backwards compatibility alias."""
    return is_kanji(c)


def _has_cjk_ideograph(s: str) -> bool:
    """Check if string contains at least one CJK ideograph (kanji)."""
    return any(is_kanji(c) for c in s)


def align_furigana(surface: str, reading_hira: str) -> list[tuple[str, str]]:
    """Align surface Japanese text with its phonetic reading to produce furigana annotations.

    Segments the input string into contiguous chunks where:
    - Pure kana segments have ruby="" (no furigana needed).
    - Kanji compounds or mixed runs have ruby assigned to the corresponding kanji.

    Invariant: "".join(base for base, _ in segments) == surface

    Algorithm (shared-kana stripping to put ruby only over kanji runs):
    1. For comparison only, fold surface katakana to hiragana; never alter emitted base text.
    2. If surface has no CJK ideograph -> [(surface, "")].
    3. Strip longest common kana PREFIX (surface vs reading) -> emit (prefix, "").
    4. Strip longest common kana SUFFIX of the remainders -> hold to emit LAST as (suffix, "").
    5. Middle: (mid_surface, mid_reading); if mid_reading=="" emit (mid_surface, "").
    6. Emit held suffix. Drop empty segments.

    Args:
        surface: The original surface text (e.g., '食べる', '日本語').
        reading_hira: The phonetic reading in Hiragana (or Katakana).

    Returns:
        A list of tuples: (base_text, ruby_text). For pure kana, ruby_text is empty string "".
    """
    if not surface:
        return []

    if not _has_cjk_ideograph(surface):
        return [(surface, "")]

    surf_fold = _fold_kana(surface)
    read_fold = _fold_kana(reading_hira)

    # 1. Strip longest common kana PREFIX (surface vs reading)
    i = 0
    max_prefix = min(len(surface), len(reading_hira))
    while i < max_prefix and surf_fold[i] == read_fold[i] and _is_kana(surf_fold[i]):
        i += 1
    prefix_len = i

    prefix_surf = surface[:prefix_len]
    rem_surf = surface[prefix_len:]
    rem_read = reading_hira[prefix_len:]
    rem_surf_fold = surf_fold[prefix_len:]
    rem_read_fold = read_fold[prefix_len:]

    # 2. Strip longest common kana SUFFIX of the remainders
    j = 0
    max_suffix = min(len(rem_surf), len(rem_read))
    while (
        j < max_suffix
        and rem_surf_fold[-(j + 1)] == rem_read_fold[-(j + 1)]
        and _is_kana(rem_surf_fold[-(j + 1)])
    ):
        j += 1
    suffix_len = j

    suffix_surf = rem_surf[len(rem_surf) - suffix_len :] if suffix_len > 0 else ""
    mid_surf = rem_surf[: len(rem_surf) - suffix_len] if suffix_len > 0 else rem_surf
    mid_read = rem_read[: len(rem_read) - suffix_len] if suffix_len > 0 else rem_read

    # 3. Middle & 4. Emit held suffix, dropping empty segments
    segments: list[tuple[str, str]] = []
    if prefix_surf:
        segments.append((prefix_surf, ""))
    if mid_surf:
        if mid_read == "":
            segments.append((mid_surf, ""))
        else:
            segments.append((mid_surf, mid_read))
    if suffix_surf:
        segments.append((suffix_surf, ""))

    return segments


def annotate(tokens: Iterable[Any]) -> list[list[tuple[str, str]]]:
    """Annotate a sequence of tokens with furigana segmentations.

    Args:
        tokens: Sequence of Token objects (or objects with surface and reading_hira attributes).

    Returns:
        List of segmented furigana tuples for each token.
    """
    result: list[list[tuple[str, str]]] = []
    for t in tokens:
        if hasattr(t, "surface") and hasattr(t, "reading_hira"):
            result.append(align_furigana(t.surface, t.reading_hira))
        elif isinstance(t, (tuple, list)) and len(t) >= 2:
            result.append(align_furigana(t[0], t[1]))
        else:
            raise TypeError(f"Cannot annotate item of type {type(t)}")
    return result
