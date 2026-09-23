"""Furigana formatting helpers for export (inline text and ruby HTML)."""

from __future__ import annotations

import functools
import html
from typing import Any

from nihongo_player.ja.furigana import align_furigana
from nihongo_player.ja.tokenizer import Tagger

_global_tagger: Tagger | None = None


def _get_tagger() -> Tagger:
    """Lazily load Tagger instance."""
    global _global_tagger
    if _global_tagger is None:
        _global_tagger = Tagger()
    return _global_tagger


@functools.lru_cache(maxsize=4096)
def furigana_inline(text: str) -> str:
    """Format Japanese text with inline phonetic readings for kanji compounds.

    E.g. "もう大丈夫。治るよ" -> "もう大丈夫(だいじょうぶ)。治(なお)るよ"
    For segments without kanji / empty ruby, the original text is preserved without parentheses.

    Args:
        text: Japanese input sentence or token.

    Returns:
        Formatted string with inline phonetic readings.
    """
    if not text:
        return ""

    tagger = _get_tagger()
    tokens = tagger.tokenize(text)
    out: list[str] = []

    for tok in tokens:
        segments = align_furigana(tok.surface, tok.reading_hira)
        for base, ruby in segments:
            if ruby:
                out.append(f"{base}({ruby})")
            else:
                out.append(base)

    return "".join(out)


@functools.lru_cache(maxsize=4096)
def furigana_ruby_html(text: str) -> str:
    """Format Japanese text with HTML <ruby> annotations for kanji compounds.

    E.g. "攻撃" -> "<ruby>攻撃<rt>こうげき</rt></ruby>"
    Plain text segments are HTML-escaped.

    Args:
        text: Japanese input sentence or token.

    Returns:
        HTML string containing <ruby> and <rt> tags.
    """
    if not text:
        return ""

    tagger = _get_tagger()
    tokens = tagger.tokenize(text)
    out: list[str] = []

    for tok in tokens:
        segments = align_furigana(tok.surface, tok.reading_hira)
        for base, ruby in segments:
            if ruby:
                b_esc = html.escape(base)
                r_esc = html.escape(ruby)
                out.append(f"<ruby>{b_esc}<rt>{r_esc}</rt></ruby>")
            else:
                out.append(html.escape(base))

    return "".join(out)
