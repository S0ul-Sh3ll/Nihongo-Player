"""Offline Japanese-English dictionary lookup using Jamdict (JMdict/JMnedict)."""

from __future__ import annotations

from dataclasses import dataclass
import functools
from typing import Any, Iterable, Sequence
import unicodedata


@dataclass(frozen=True)
class Gloss:
    """Dictionary sense gloss and part-of-speech info.

    Attributes:
        senses: List of definition strings (each sense is a '; '-joined gloss).
        pos: List of part-of-speech tags.
    """

    senses: list[str]
    pos: list[str]


@dataclass(frozen=True)
class WordEntry:
    """Dictionary lookup result for a Japanese word or token.

    Attributes:
        query: Searched query string (surface or lemma).
        found: True if at least one definition or name entry was found.
        reading: Phonetic kana reading if available.
        senses: List of definition senses (each sense = '; '-joined glosses).
        pos: List of part-of-speech tags.
        is_name: True if entry was found in JMnedict name dictionary.
        is_usually_kana: True if the matched entry/sense is usually written using kana alone (uk).
    """

    query: str
    found: bool
    reading: str | None
    senses: list[str]
    pos: list[str]
    is_name: bool = False
    is_usually_kana: bool = False


# Backwards-compatibility dataclass for M0 stubs
@dataclass(frozen=True)
class DictEntry:
    """Dictionary entry definition (backwards compatibility).

    Attributes:
        kanji: List of kanji spellings.
        kana: List of kana readings.
        senses: List of English glosses / definitions.
        pos: Parts of speech tags.
    """

    kanji: list[str]
    kana: list[str]
    senses: list[str]
    pos: list[str]


def _is_ignorable_surface(surface: str) -> bool:
    """Check if surface consists purely of punctuation, whitespace, or ASCII digits."""
    if not surface or not surface.strip():
        return True
    return all(
        unicodedata.category(c).startswith(("P", "Z", "C", "S"))
        or (c.isascii() and c.isdigit())
        for c in surface
    )


import threading

_local_storage = threading.local()


def _get_jamdict(db_path: str | None = None) -> Any:
    """Lazily load and return Jamdict instance (thread-local for default db)."""
    if db_path is not None:
        from jamdict import Jamdict

        return Jamdict(db_file=db_path)

    jam = getattr(_local_storage, "jamdict", None)
    if jam is None:
        from jamdict import Jamdict

        jam = Jamdict()
        _local_storage.jamdict = jam
    return jam


def _match_reading_hint(entries: Sequence[Any], reading_hint: str | None) -> Sequence[Any]:
    """Reorder entries so the first entry whose kana reading matches reading_hint in hiragana comes first."""
    if not reading_hint or not entries:
        return entries
    import jaconv

    hint_hira = jaconv.kata2hira(str(reading_hint).strip())
    if not hint_hira:
        return entries

    for i, entry in enumerate(entries):
        kana_forms = getattr(entry, "kana_forms", None) or []
        for k in kana_forms:
            k_text = getattr(k, "text", None) or (str(k) if k else "")
            if k_text and jaconv.kata2hira(k_text) == hint_hira:
                if i == 0:
                    return entries
                return [entry] + [e for j, e in enumerate(entries) if j != i]
    return entries


def _extract_reading(
    entry: Any,
    query: str | None = None,
    reading_hint: str | None = None,
) -> str | None:
    """Extract phonetic kana or kanji reading from jamdict entry."""
    kana_forms = getattr(entry, "kana_forms", None)
    if kana_forms:
        kana_texts = [
            getattr(k, "text", None) or (str(k) if k else "") for k in kana_forms
        ]
        kana_texts = [k for k in kana_texts if k]
        if reading_hint:
            import jaconv

            hint_hira = jaconv.kata2hira(str(reading_hint).strip())
            for k in kana_texts:
                if jaconv.kata2hira(k) == hint_hira:
                    return k
        if query and query in kana_texts:
            return query
        if kana_texts:
            return kana_texts[0]

    kanji_forms = getattr(entry, "kanji_forms", None)
    if kanji_forms:
        kanji_texts = [
            getattr(k, "text", None) or (str(k) if k else "") for k in kanji_forms
        ]
        kanji_texts = [k for k in kanji_texts if k]
        if query and query in kanji_texts:
            return query
        if kanji_texts:
            return kanji_texts[0]

    return None


def _extract_senses_and_pos(
    entries: Sequence[Any], max_senses: int = 3
) -> tuple[list[str], list[str], bool]:
    """Extract up to max_senses gloss strings, POS tags, and is_usually_kana from jamdict entries."""
    senses: list[str] = []
    pos: list[str] = []
    is_usually_kana = False

    for entry in entries[:2]:
        for s in getattr(entry, "senses", []):
            # Extract glosses
            gloss_objs = getattr(s, "gloss", []) or []
            gloss_texts = [
                getattr(g, "text", None) or str(g)
                for g in gloss_objs
                if getattr(g, "text", None) or str(g)
            ]
            if gloss_texts:
                joined = "; ".join(gloss_texts)
                if joined not in senses and len(senses) < max_senses:
                    senses.append(joined)
                    # Check misc on accepted sense for 'uk' / 'usually written using kana'
                    misc_objs = getattr(s, "misc", []) or []
                    for m in misc_objs:
                        m_text = getattr(m, "text", None) or str(m)
                        if m_text:
                            m_lower = m_text.lower()
                            if "usually written using kana" in m_lower or m_lower == "uk":
                                is_usually_kana = True

            # Extract POS / name_type
            pos_objs = getattr(s, "pos", []) or []
            if not pos_objs:
                pos_objs = getattr(s, "name_type", []) or []
            for p in pos_objs:
                p_text = getattr(p, "text", None) or str(p)
                if p_text and p_text not in pos:
                    pos.append(p_text)

            if len(senses) >= max_senses:
                break
        if len(senses) >= max_senses:
            break

    return senses, pos, is_usually_kana


@functools.lru_cache(maxsize=8192)
def _lookup_cached(
    surface: str,
    lemma: str | None,
    reading_hint: str | None = None,
    db_path: str | None = None,
) -> WordEntry:
    """Internal cached lookup logic."""
    if _is_ignorable_surface(surface):
        return WordEntry(
            query=surface,
            found=False,
            reading=None,
            senses=[],
            pos=[],
            is_name=False,
            is_usually_kana=False,
        )

    try:
        jam = _get_jamdict(db_path)
    except Exception:
        return WordEntry(
            query=surface,
            found=False,
            reading=None,
            senses=[],
            pos=[],
            is_name=False,
            is_usually_kana=False,
        )

    def _do_lookup(target: str) -> Any:
        nonlocal jam
        try:
            return jam.lookup(target)
        except Exception:
            if db_path is None:
                try:
                    from jamdict import Jamdict

                    jam = Jamdict()
                    _local_storage.jamdict = jam
                    return jam.lookup(target)
                except Exception:
                    return None
            return None

    # 1. Try surface in JMdict
    res_surface = _do_lookup(surface)

    if res_surface and getattr(res_surface, "entries", None):
        entries = _match_reading_hint(res_surface.entries, reading_hint)
        reading = _extract_reading(entries[0], query=surface, reading_hint=reading_hint)
        senses, pos, is_uk = _extract_senses_and_pos(entries, max_senses=3)
        if senses:
            return WordEntry(
                query=surface,
                found=True,
                reading=reading,
                senses=senses,
                pos=pos,
                is_name=False,
                is_usually_kana=is_uk,
            )

    # 2. Try lemma if different from surface and provided
    res_lemma = None
    if lemma and lemma != surface and not _is_ignorable_surface(lemma):
        res_lemma = _do_lookup(lemma)

        if res_lemma and getattr(res_lemma, "entries", None):
            entries = _match_reading_hint(res_lemma.entries, reading_hint)
            reading = _extract_reading(entries[0], query=lemma, reading_hint=reading_hint)
            senses, pos, is_uk = _extract_senses_and_pos(entries, max_senses=3)
            if senses:
                return WordEntry(
                    query=surface,
                    found=True,
                    reading=reading,
                    senses=senses,
                    pos=pos,
                    is_name=False,
                    is_usually_kana=is_uk,
                )

    # 3. Try names (JMnedict) on surface, then lemma
    if res_surface and getattr(res_surface, "names", None):
        names = _match_reading_hint(res_surface.names, reading_hint)
        reading = _extract_reading(names[0], query=surface, reading_hint=reading_hint)
        senses, pos, is_uk = _extract_senses_and_pos(names, max_senses=3)
        if senses:
            return WordEntry(
                query=surface,
                found=True,
                reading=reading,
                senses=senses,
                pos=pos,
                is_name=True,
                is_usually_kana=False,
            )

    if res_lemma and getattr(res_lemma, "names", None):
        names = _match_reading_hint(res_lemma.names, reading_hint)
        reading = _extract_reading(names[0], query=lemma, reading_hint=reading_hint)
        senses, pos, is_uk = _extract_senses_and_pos(names, max_senses=3)
        if senses:
            return WordEntry(
                query=surface,
                found=True,
                reading=reading,
                senses=senses,
                pos=pos,
                is_name=True,
                is_usually_kana=False,
            )

    return WordEntry(
        query=surface,
        found=False,
        reading=None,
        senses=[],
        pos=[],
        is_name=False,
        is_usually_kana=False,
    )


class Dictionary:
    """Offline Japanese dictionary and gloss engine using Jamdict (JMdict/JMnedict)."""

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize dictionary engine.

        Args:
            db_path: Optional custom path to jamdict sqlite database file.
        """
        self._db_path = db_path

    def lookup(
        self,
        surface: str,
        lemma: str | None = None,
        reading_hint: str | None = None,
    ) -> WordEntry:
        """Look up definitions for a word surface or lemma.

        Args:
            surface: Surface form of the word (as in text).
            lemma: Optional dictionary base form / lemma.
            reading_hint: Optional phonetic kana reading hint to prioritize matching homograph entries.

        Returns:
            WordEntry with definitions, reading, pos, and found status.
        """
        if not surface:
            return WordEntry(
                query=surface or "",
                found=False,
                reading=None,
                senses=[],
                pos=[],
                is_name=False,
            )
        norm_lemma = lemma if (lemma and lemma != surface) else None
        norm_hint = (
            str(reading_hint).strip()
            if (reading_hint and str(reading_hint).strip())
            else None
        )
        return _lookup_cached(surface, norm_lemma, norm_hint, self._db_path)

    def gloss_tokens(self, tokens: Iterable[Any]) -> list[WordEntry]:
        """Look up definitions for a sequence of tokens.

        Args:
            tokens: Sequence of Token objects or strings.

        Returns:
            List of WordEntry objects matching the tokens in order.
        """
        results: list[WordEntry] = []
        for token in tokens:
            surface = getattr(token, "surface", None)
            if surface is None:
                surface = str(token)
            lemma = getattr(token, "lemma", None)
            reading_hint = (
                getattr(token, "reading_hira", None)
                or getattr(token, "reading_kata", None)
                or getattr(token, "reading", None)
            )
            results.append(
                self.lookup(
                    surface=surface,
                    lemma=lemma,
                    reading_hint=reading_hint,
                )
            )
        return results


class JMdictLookup:
    """Offline dictionary lookup interface for JMdict (backwards compatibility)."""

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize JMdictLookup wrapper."""
        self._dict = Dictionary(db_path=db_path)

    def lookup(self, term: str) -> list[DictEntry]:
        """Look up term in JMdict."""
        entry = self._dict.lookup(term)
        if not entry.found:
            return []
        return [
            DictEntry(
                kanji=[entry.query] if not entry.is_name else [],
                kana=[entry.reading] if entry.reading else [],
                senses=entry.senses,
                pos=entry.pos,
            )
        ]
