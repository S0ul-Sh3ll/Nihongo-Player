"""Frequency-ranked vocabulary list extractor for Japanese subtitles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
import re
import unicodedata

import jaconv

from nihongo_player.ja.dictionary import Dictionary
from nihongo_player.ja.tokenizer import Tagger, _is_all_kana
from nihongo_player.subs.text_clean import clean_subtitle_text

CONTENT_POS: frozenset[str] = frozenset(
    {"名詞", "動詞", "形容詞", "副詞", "連体詞", "形状詞", "代名詞"}
)

EXCLUDED_POS: frozenset[str] = frozenset(
    {
        "助詞",
        "助動詞",
        "記号",
        "補助記号",
        "接続詞",
        "接頭辞",
        "接尾辞",
        "フィラー",
        "感動詞",
        "感嘆詞",
        "空白",
    }
)


def clean_lemma(lemma: str) -> str:
    """Clean UniDic lemma disambiguation suffixes (e.g. '私-代名詞' -> '私', 'バー-bar' -> 'バー').

    Strips everything from the first '-' onward whenever there is a hyphen
    and the prefix before it is non-empty. Preserves lemmas without hyphens untouched.
    """
    if not lemma:
        return ""
    if "-" in lemma:
        prefix = lemma.split("-", 1)[0]
        if prefix:
            return prefix
    return lemma


# Backwards compatibility alias
clean_lemma_base = clean_lemma


@dataclass
class VocabEntry:
    """Represents a vocabulary entry with frequency count, definition, and sample sentences.

    Attributes:
        base: Dictionary/lemma base form (preserving kanji).
        reading: Phonetic reading in Hiragana.
        english: Primary English definition gloss (or empty string).
        count: Total frequency count across the loaded subtitles.
        examples: Up to 5 unique full cue sentences where the word appears (first-seen order).
    """

    base: str
    reading: str
    english: str
    count: int
    examples: list[str] = field(default_factory=list)
    examples_en: list[str] = field(default_factory=list)


def translate_examples(
    entries: Sequence[VocabEntry],
    translator: Any | None,
    *,
    progress_cb: Any | None = None,
    cancel_cb: Any | None = None,
) -> Sequence[VocabEntry]:
    """Translate example sentences for vocabulary entries into English.

    Collects the unique example sentences across all entries, translates each unique
    sentence once via the translator, and populates entry.examples_en.

    Args:
        entries: Sequence of VocabEntry objects.
        translator: Translator instance or None.
        progress_cb: Optional callback callable as progress_cb(done_count, total_count).
        cancel_cb: Optional callback returning True if processing should be cancelled.

    Returns:
        The updated entries sequence.
    """
    if not entries:
        if progress_cb is not None:
            try:
                progress_cb(0, 0)
            except Exception:
                pass
        return entries

    if translator is None:
        for entry in entries:
            entry.examples_en = []
        if progress_cb is not None:
            try:
                progress_cb(0, 0)
            except Exception:
                pass
        return entries

    if hasattr(translator, "is_available") and not translator.is_available():
        for entry in entries:
            entry.examples_en = []
        if progress_cb is not None:
            try:
                progress_cb(0, 0)
            except Exception:
                pass
        return entries

    # Collect unique non-empty example sentences in first-seen order
    unique_examples: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        for ex in (entry.examples or []):
            st = ex.strip()
            if st and st not in seen:
                seen.add(st)
                unique_examples.append(st)

    total = len(unique_examples)
    if total == 0:
        for entry in entries:
            entry.examples_en = []
        if progress_cb is not None:
            try:
                progress_cb(0, 0)
            except Exception:
                pass
        return entries

    translations_map: dict[str, str] = {}
    chunk_size = 8
    done = 0

    if progress_cb is not None:
        try:
            progress_cb(0, total)
        except Exception:
            pass

    for i in range(0, total, chunk_size):
        if cancel_cb is not None and cancel_cb():
            break
        chunk = unique_examples[i : i + chunk_size]
        if hasattr(translator, "translate_many"):
            chunk_results = translator.translate_many(chunk)
        elif hasattr(translator, "translate"):
            chunk_results = [translator.translate(item) for item in chunk]
        else:
            chunk_results = [str(item) for item in chunk]

        for s, trans in zip(chunk, chunk_results):
            translations_map[s] = trans

        done += len(chunk)
        if progress_cb is not None:
            try:
                progress_cb(done, total)
            except Exception:
                pass

    for entry in entries:
        if not entry.examples:
            entry.examples_en = []
        else:
            entry.examples_en = [
                translations_map.get(ex.strip(), "") for ex in entry.examples
            ]

    return entries


def _has_kanji(text: str) -> bool:
    """Check if text contains any kanji characters."""
    return any(
        ("\u4e00" <= c <= "\u9fff") or ("\u3400" <= c <= "\u4dbf")
        for c in text
    )


SMALL_KANA: frozenset[str] = frozenset("ぁぃぅぇぉァィゥェォっッゃゅょゎャュョヮゕゖヵヶ")
PROLONGED_MARKS: frozenset[str] = frozenset("ー〜～-")


def is_onomatopoeia(surface: str, reading: str | None = None) -> bool:
    """Check if a word/token is an onomatopoeia, SFX, interjection, or non-lexical sound.

    Conservative: Keeps legitimate dictionary words (e.g. 大丈夫, 興味, 主人, 風呂,
    攻撃, 惑星, この, 俺, 食べる, バー, もっと, ずっと, コーヒー), while dropping non-lexical
    vocalizations and anime SFX (e.g. じゅるるるるる, はぁ, んっ, くっ, はっ, ちゅ, ー, ぁぁ).

    Args:
        surface: Token surface string or base form.
        reading: Optional phonetic reading string.

    Returns:
        True if the token is identified as onomatopoeic/SFX/non-lexical.
    """
    if not surface or not surface.strip():
        return True

    text = surface.strip()

    # Legitimate words containing kanji are preserved
    if _has_kanji(text):
        return False

    # Single-character non-kanji tokens (punctuation, isolated kana, long vowel marks)
    if len(text) <= 1:
        return True

    # Tokens consisting purely of prolonged sound marks (e.g. 'ー', 'ーー')
    if all(c in PROLONGED_MARKS for c in text):
        return True

    # Multiple consecutive long-vowel marks (e.g. 'ーー', '〜〜')
    if any(p * 2 in text for p in ("ー", "〜", "～", "-")):
        return True

    # Run of the exact same character repeated >= 3 times (e.g. じゅるるるるる, あああ)
    if re.search(r"(.)\1{2,}", text):
        return True

    # Pure small kana (e.g. ぁぁ, っっ)
    if all(c in SMALL_KANA for c in text):
        return True

    # Short 2-char tokens containing small kana / single mora yoon (e.g. はぁ, んっ, くっ, はっ, ちゅ)
    if len(text) <= 2 and any(c in SMALL_KANA for c in text):
        return True

    # Tokens ending in trailing small vowels or sokuon (e.g. はぁぁ, んーっ, ふーっ, 痛くっ)
    if text.endswith(tuple("ぁぃぅぇぉァィゥェォっッ")):
        return True

    # Check reading if provided and kana-only
    if reading and not _has_kanji(reading):
        r_text = reading.strip()
        if re.search(r"(.)\1{2,}", r_text):
            return True
        if any(p * 2 in r_text for p in ("ー", "〜", "～", "-")):
            return True

    return False


def _is_japanese_char(c: str) -> bool:
    """Check if character is a Japanese kanji or kana."""
    # Kanji CJK Unified Ideographs + Extension A
    if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf":
        return True
    # Hiragana
    if "\u3040" <= c <= "\u309f":
        return True
    # Katakana + Phonetic Extensions + Halfwidth Katakana
    if (
        "\u30a0" <= c <= "\u30ff"
        or "\u31f0" <= c <= "\u31ff"
        or "\uff66" <= c <= "\uff9f"
    ):
        return True
    return False


def _is_pure_punct_latin_digit(text: str) -> bool:
    """Check if text contains only punctuation, latin characters, digits, or symbols."""
    if not text or not text.strip():
        return True
    return not any(_is_japanese_char(c) for c in text)


def build_frequency_list(
    cues: Sequence[Any] | Iterable[Any],
    *,
    content_only: bool = True,
    max_examples: int = 5,
    min_count: int = 1,
) -> list[VocabEntry]:
    """Build a frequency-ranked vocabulary study list from subtitle cues.

    Args:
        cues: Sequence of Cue objects or text strings.
        content_only: If True, include only content words (nouns, verbs, adjectives, etc.)
            and exclude particles, auxiliaries, 1-char kana, punctuation, and latin/digits.
        max_examples: Maximum unique example sentences per vocabulary entry (default 5).
        min_count: Minimum frequency threshold to include in output (default 1).

    Returns:
        List of VocabEntry objects sorted descending by count, then by base form.
    """
    tagger = Tagger()
    dictionary = Dictionary()

    # Aggregators: key -> {count: int, reading: str, examples: list[str]}
    vocab_counts: dict[str, int] = {}
    vocab_readings: dict[str, str] = {}
    vocab_examples: dict[str, list[str]] = {}

    for cue in cues:
        if hasattr(cue, "text"):
            cue_text = clean_subtitle_text(str(cue.text))
        else:
            cue_text = clean_subtitle_text(str(cue))

        if not cue_text:
            continue

        tokens = tagger.tokenize(cue_text)

        for tok in tokens:
            pos = tok.pos or ""
            surface = tok.surface or ""
            lemma = tok.lemma or surface
            cleaned_base = clean_lemma(lemma) if lemma else surface

            if content_only:
                # Exclude non-content POS
                if pos in EXCLUDED_POS or (pos and pos not in CONTENT_POS):
                    continue

                # Exclude 1-character kana (drops stray particles)
                if _is_all_kana(surface) and len(surface) <= 1:
                    continue

                # Exclude pure punctuation / latin / digit tokens
                if _is_pure_punct_latin_digit(surface):
                    continue

                # Exclude onomatopoeia and SFX tokens
                if is_onomatopoeia(surface, tok.reading_hira) or is_onomatopoeia(cleaned_base, tok.reading_hira):
                    continue

            key = cleaned_base if cleaned_base else surface
            if not key:
                continue

            # Update count
            vocab_counts[key] = vocab_counts.get(key, 0) + 1

            # Store reading from first occurrence
            if key not in vocab_readings:
                reading = tok.reading_hira or ""
                if not reading and _is_all_kana(key):
                    reading = jaconv.kata2hira(key)
                vocab_readings[key] = reading

            # Add example sentence (deduped, capped at max_examples)
            if key not in vocab_examples:
                vocab_examples[key] = [cue_text]
            else:
                ex_list = vocab_examples[key]
                if len(ex_list) < max_examples and cue_text not in ex_list:
                    ex_list.append(cue_text)

    # Perform dictionary lookups and build VocabEntry items
    entries: list[VocabEntry] = []
    dict_cache: dict[str, tuple[str, str, bool]] = {}

    for key, count in vocab_counts.items():
        if count < min_count:
            continue

        context_reading = vocab_readings.get(key, "")
        if key in dict_cache:
            english, dict_reading, is_uk = dict_cache[key]
        else:
            dict_res = dictionary.lookup(key, reading_hint=context_reading)
            english = dict_res.senses[0] if (dict_res.found and dict_res.senses) else ""
            dict_reading = (
                jaconv.kata2hira(dict_res.reading)
                if (dict_res.found and dict_res.reading)
                else ""
            )
            is_uk = dict_res.is_usually_kana if dict_res.found else False
            dict_cache[key] = (english, dict_reading, is_uk)

        # Prefer context reading from token first, dictionary reading only as fallback
        reading = vocab_readings.get(key, "") or dict_reading
        if not reading and _is_all_kana(key):
            reading = jaconv.kata2hira(key)

        # Natural kana spelling: display hiragana reading only for usually-kana (uk) words
        if is_uk and reading:
            display_base = reading
        else:
            display_base = key

        examples = vocab_examples.get(key, [])

        entries.append(
            VocabEntry(
                base=display_base,
                reading=reading,
                english=english,
                count=count,
                examples=examples,
            )
        )

    # Sort descending by count, then ascending by base for stable ties
    entries.sort(key=lambda e: (-e.count, e.base))
    return entries
