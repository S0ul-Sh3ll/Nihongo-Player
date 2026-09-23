"""Japanese morphological tokenizer using Fugashi and UniDic-lite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Token:
    """Represents a morphological token from Japanese text analysis.

    Attributes:
        surface: The original surface text as it appears in the sentence.
        reading_kata: Phonetic reading in Katakana.
        reading_hira: Phonetic reading in Hiragana.
        lemma: Dictionary base form / lemma of the word.
        pos: Primary part-of-speech tag (pos1).
    """

    surface: str
    reading_kata: str
    reading_hira: str
    lemma: str
    pos: str

    @property
    def reading(self) -> str:
        """Backwards-compatibility property returning Katakana reading."""
        return self.reading_kata


def _is_all_kana(text: str) -> bool:
    """Check if text consists entirely of Japanese kana characters."""
    if not text:
        return False
    return all(
        ("\u3040" <= c <= "\u309F")
        or ("\u30A0" <= c <= "\u30FF")
        or ("\uFF66" <= c <= "\uFF9F")
        for c in text
    )


def _clean_feature(val: Any) -> str:
    """Clean feature value from unidic, treating None, '*', and empty as ''."""
    if val is None or val == "*":
        return ""
    return str(val)


_global_fugashi_tagger: Any = None


def _get_fugashi_tagger() -> Any:
    """Lazily load fugashi.Tagger singleton."""
    global _global_fugashi_tagger
    if _global_fugashi_tagger is None:
        import fugashi

        _global_fugashi_tagger = fugashi.Tagger()
    return _global_fugashi_tagger


class Tagger:
    """Japanese morphological analyzer wrapping Fugashi / UniDic-lite."""

    def __init__(self) -> None:
        """Initialize Tagger with lazy tagger instance."""
        pass

    def tokenize(self, text: str) -> list[Token]:
        """Tokenize Japanese text into morphological tokens.

        Args:
            text: Japanese input sentence or subtitle line.

        Returns:
            List of analyzed Token instances.
        """
        if not text:
            return []

        import jaconv

        tagger = _get_fugashi_tagger()
        tokens: list[Token] = []

        for word in tagger(text):
            surface = word.surface

            # Guard feature access (unidic-lite features can be None or '*')
            feature = getattr(word, "feature", None)
            raw_kana = _clean_feature(getattr(feature, "kana", None)) if feature else ""
            raw_pron = _clean_feature(getattr(feature, "pron", None)) if feature else ""
            reading_kata = raw_kana or raw_pron or ""

            surface_is_all_kana = _is_all_kana(surface)
            if not reading_kata and surface_is_all_kana:
                reading_kata = jaconv.hira2kata(surface)

            raw_lemma = _clean_feature(getattr(feature, "lemma", None)) if feature else ""
            lemma = raw_lemma or surface

            raw_pos1 = _clean_feature(getattr(feature, "pos1", None)) if feature else ""
            pos = raw_pos1 or ""

            if reading_kata:
                reading_hira = jaconv.kata2hira(reading_kata)
            else:
                reading_hira = surface if surface_is_all_kana else ""

            tokens.append(
                Token(
                    surface=surface,
                    reading_kata=reading_kata,
                    reading_hira=reading_hira,
                    lemma=lemma,
                    pos=pos,
                )
            )

        return tokens


# Alias for backwards-compatibility
Tokenizer = Tagger
