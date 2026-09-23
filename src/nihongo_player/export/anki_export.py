"""Export vocabulary frequency list to Anki deck (.apkg) or TSV format."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Sequence

import genanki

from nihongo_player.export.frequency import VocabEntry
from nihongo_player.export.furigana_text import furigana_inline, furigana_ruby_html

# Fixed unique identifiers for Anki schema persistence across imports
NIHONGO_PLAYER_MODEL_ID: int = 1607392319
NIHONGO_PLAYER_DECK_ID: int = 2059400110

_ANKI_CSS: str = """
.card {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
    font-size: 20px;
    text-align: center;
    color: #2c3e50;
    background-color: #ffffff;
    padding: 20px;
}
.word {
    font-size: 32px;
    font-weight: bold;
    color: #1a237e;
    margin-bottom: 10px;
    text-align: center;
}
.reading {
    font-size: 18px;
    color: #5c6bc0;
    margin-bottom: 12px;
    text-align: center;
}
.meaning {
    font-size: 16px;
    color: #37474f;
    line-height: 1.4;
    margin-bottom: 16px;
    text-align: center;
}
.examples {
    font-size: 14px;
    color: #555555;
    line-height: 1.5;
    text-align: center;
    background-color: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 10px 14px;
    margin-top: 10px;
}
.freq {
    font-size: 12px;
    color: #9e9e9e;
    margin-top: 12px;
    text-align: center;
}
hr {
    border: none;
    border-top: 1px solid #e0e0e0;
    margin: 16px 0;
}
"""

_ANKI_MODEL = genanki.Model(
    NIHONGO_PLAYER_MODEL_ID,
    "Nihongo Player Vocabulary",
    fields=[
        {"name": "Word"},
        {"name": "Reading"},
        {"name": "Meaning"},
        {"name": "Examples"},
        {"name": "Frequency"},
    ],
    templates=[
        {
            "name": "Recognition",
            "qfmt": '<div class="word">{{Word}}</div>',
            "afmt": (
                '<div class="word">{{Word}}</div>'
                '<div class="reading">{{Reading}}</div>'
                "<hr>"
                '<div class="meaning">{{Meaning}}</div>'
                '{{#Examples}}<div class="examples">{{Examples}}</div>{{/Examples}}'
                '<div class="freq">Frequency: {{Frequency}}</div>'
            ),
        }
    ],
    css=_ANKI_CSS,
)


def export_anki_apkg(
    entries: Sequence[VocabEntry],
    out_path: str | Path,
    deck_name: str = "Nihongo Player Vocab",
) -> None:
    """Export vocabulary entries to an Anki package (.apkg) file.

    Args:
        entries: Sequence of VocabEntry objects to include in the deck.
        out_path: Destination path for the .apkg file.
        deck_name: Display name for the Anki deck.
    """
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    deck = genanki.Deck(NIHONGO_PLAYER_DECK_ID, deck_name)

    for entry in entries:
        word = html.escape(entry.base or "")
        reading = html.escape(entry.reading or "")
        meaning = html.escape(entry.english or "")

        examples_list = entry.examples or []
        examples_en_list = getattr(entry, "examples_en", []) or []

        examples_parts = []
        for idx, ex_ja in enumerate(examples_list[:5]):
            ex_ja_ruby = furigana_ruby_html(ex_ja)
            ex_en = examples_en_list[idx] if idx < len(examples_en_list) else ""
            if ex_en and ex_en.strip():
                ex_en_esc = html.escape(ex_en.strip())
                examples_parts.append(
                    f"{ex_ja_ruby}<br><span style='color:#666;font-size:12px'>{ex_en_esc}</span>"
                )
            else:
                examples_parts.append(ex_ja_ruby)

        examples_html = "<br><br>".join(examples_parts) if examples_parts else ""
        frequency = str(entry.count)

        note = genanki.Note(
            model=_ANKI_MODEL,
            fields=[word, reading, meaning, examples_html, frequency],
            # Use base word as unique guid seed to prevent duplicate cards across multiple exports
            guid=genanki.guid_for(entry.base),
        )
        deck.add_note(note)

    package = genanki.Package(deck)
    package.write_to_file(str(dest))


def _clean_tsv_field(text: str) -> str:
    """Clean a string field for TSV format by replacing tabs and line breaks with spaces."""
    if not text:
        return ""
    return text.replace("\t", " ").replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()


def export_anki_tsv(
    entries: Sequence[VocabEntry],
    out_path: str | Path,
) -> None:
    """Export vocabulary entries to a tab-separated values (TSV) file.

    Format: Word<TAB>Reading<TAB>Meaning<TAB>Examples(JA; EN pairs joined ' / ')<TAB>Frequency

    Args:
        entries: Sequence of VocabEntry objects to write.
        out_path: Destination path for the .tsv file.
    """
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for entry in entries:
        word = _clean_tsv_field(entry.base)
        reading = _clean_tsv_field(entry.reading)
        meaning = _clean_tsv_field(entry.english)

        ex_pairs: list[str] = []
        examples_en_list = getattr(entry, "examples_en", []) or []
        for idx, ex_ja in enumerate((entry.examples or [])[:5]):
            c_ja = _clean_tsv_field(furigana_inline(ex_ja))
            c_en = ""
            if idx < len(examples_en_list):
                c_en = _clean_tsv_field(examples_en_list[idx])
            if c_en:
                ex_pairs.append(f"{c_ja}; {c_en}")
            else:
                ex_pairs.append(c_ja)

        examples = " / ".join(ex_pairs)
        frequency = str(entry.count)

        row = f"{word}\t{reading}\t{meaning}\t{examples}\t{frequency}\n"
        lines.append(row)

    with open(dest, "w", encoding="utf-8") as f:
        f.writelines(lines)
