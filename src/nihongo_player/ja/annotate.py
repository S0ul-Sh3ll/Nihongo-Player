"""Linguistic annotation pipeline for subtitle cues and Japanese text."""

from __future__ import annotations

from dataclasses import dataclass
import functools
import unicodedata

from nihongo_player.ja.furigana import align_furigana
from nihongo_player.ja.tokenizer import Tagger


@dataclass(frozen=True)
class TokenView:
    """Represents an annotated token view for UI rendering and study dictionary lookup.

    Attributes:
        surface: The original token surface string.
        reading_hira: Hiragana phonetic reading.
        segments: List of (base_text, ruby_text) furigana alignment tuples.
        pos: Part-of-speech tag string.
        lemma: Dictionary base form / lemma.
        is_content: True if token carries lexical content; False for grammatical particles/auxiliaries/punct.
    """

    surface: str
    reading_hira: str
    segments: list[tuple[str, str]]
    pos: str
    lemma: str
    is_content: bool


_NON_CONTENT_POS = frozenset({"助詞", "助動詞", "補助記号", "空白", "記号"})


def _has_japanese_chars(text: str) -> bool:
    """Check if string contains any Japanese Kana or CJK Ideographs."""
    return any(
        ("\u3040" <= c <= "\u309F")  # Hiragana
        or ("\u30A0" <= c <= "\u30FF")  # Katakana
        or ("\uFF66" <= c <= "\uFF9F")  # Half-width kana
        or (0x4E00 <= ord(c) <= 0x9FFF)  # CJK Ideographs
        or (0x3400 <= ord(c) <= 0x4DBF)
        or (0xF900 <= ord(c) <= 0xFAFF)
        for c in text
    )


def _is_content_token(pos: str, surface: str) -> bool:
    """Determine if a token represents lexical content rather than grammatical glue or punctuation."""
    pos_main = pos.split("-")[0] if pos else ""
    if pos_main in _NON_CONTENT_POS:
        return False

    if not surface or not surface.strip():
        return False

    if not _has_japanese_chars(surface):
        return False

    if all(unicodedata.category(c).startswith(("P", "Z", "C", "S")) for c in surface):
        return False

    return True


@functools.lru_cache(maxsize=4096)
def annotate_cue(text: str) -> list[TokenView]:
    """Analyze a Japanese subtitle cue text into a list of TokenView objects.

    Tokenizes text with Fugashi/UniDic, computes furigana alignment segments for kanji,
    and identifies lexical content words for dictionary study. Results are cached in LRU.

    Args:
        text: Raw or normalized Japanese subtitle line.

    Returns:
        List of TokenView objects corresponding to the input text.
    """
    if not text:
        return []

    tagger = Tagger()
    tokens = tagger.tokenize(text)
    views: list[TokenView] = []

    for tok in tokens:
        segments = align_furigana(tok.surface, tok.reading_hira)
        content_flag = _is_content_token(tok.pos, tok.surface)
        views.append(
            TokenView(
                surface=tok.surface,
                reading_hira=tok.reading_hira,
                segments=segments,
                pos=tok.pos,
                lemma=tok.lemma,
                is_content=content_flag,
            )
        )

    return views
