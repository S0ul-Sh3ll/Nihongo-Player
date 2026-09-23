"""Subtitle text cleaning and marker stripping for Japanese subtitles."""

from __future__ import annotations

import re

# Formatting and style tags
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Caption / annotation bracket markers
_ASCII_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_LENTICULAR_BRACKET_RE = re.compile(r"【[^】]*】")
_FULLWIDTH_BRACKET_RE = re.compile(r"［[^］]*］")

# Music runs and musical note characters
_MUSIC_RUN_RE = re.compile(r"[♪♫♬♩]+[^♪♫♬♩]*[♪♫♬♩]*")
_RESIDUAL_MUSIC_RE = re.compile(r"[♪♫♬♩]")

# Parenthetical SFX & Dialogue
_PAREN_RE = re.compile(r"\(([^)]*)\)|（([^）]*)）")
_SFX_KEYWORD_RE = re.compile(
    r"(音楽|拍手|笑|泣|ため息|咳|くしゃみ|効果音|BGM|ざわめき|歓声|溜め息|鼻歌|Music|Applause|Laughter|SFX|sigh|cough|laugh)",
    re.IGNORECASE,
)

# Leading standalone punctuation/colon residue after stripping a leading marker
_LEADING_COLON_RE = re.compile(r"^[：:\s]+")


def strip_formatting_tags(raw_text: str | None) -> str:
    """Strip ASS/SSA override tags and HTML tags, normalize line breaks and whitespace.

    Preserves caption markers and bracketed text.
    """
    if not raw_text:
        return ""
    # Strip ASS override tags {...}
    text = _ASS_TAG_RE.sub("", raw_text)
    # Convert ASS line breaks and hard spaces
    text = text.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ")
    # Convert standard newline / carriage return / tab characters
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # Strip HTML tags
    text = _HTML_TAG_RE.sub("", text)
    # Collapse multiple whitespace characters into single space and strip
    return _WHITESPACE_RE.sub(" ", text).strip()


def clean_subtitle_text(text: str | None) -> str:
    """Clean subtitle text by stripping formatting tags, caption markers, SFX, and music.

    Rules applied:
    - Strips ASS/SSA override tags and inline HTML tags.
    - Strips square brackets [...], fullwidth brackets ［...］, and lenticular brackets 【...】.
    - Strips music runs (♪...♪) and residual musical note symbols (♪♫♬♩).
    - Removes parenthetical SFX (...) / （...） when matching SFX keywords or when
      the parenthetical spans the entire cue text.
    - Preserves parenthetical dialogue that is not an SFX marker.
    - Collapses consecutive whitespace and strips leading/trailing whitespace.
    - Idempotent: clean_subtitle_text(clean_subtitle_text(x)) == clean_subtitle_text(x).
    """
    if not text:
        return ""

    # 1. Format tag stripping & basic whitespace normalization
    text = strip_formatting_tags(text)
    if not text:
        return ""

    # 2. Strip bracket caption markers
    text = _ASCII_BRACKET_RE.sub("", text)
    text = _LENTICULAR_BRACKET_RE.sub("", text)
    text = _FULLWIDTH_BRACKET_RE.sub("", text)

    # 3. Strip music runs and residual music symbols
    text = _MUSIC_RUN_RE.sub("", text)
    text = _RESIDUAL_MUSIC_RE.sub("", text)

    # 4. Parenthetical SFX vs Dialogue
    stripped = text.strip()
    if not stripped:
        return ""

    # Check if the entire remaining cue text is a single parenthetical
    if _PAREN_RE.fullmatch(stripped) is not None:
        return ""

    def _replace_paren(match: re.Match[str]) -> str:
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        if inner and _SFX_KEYWORD_RE.search(inner):
            return ""
        return match.group(0)

    text = _PAREN_RE.sub(_replace_paren, text)

    # 5. Clean leading colon / punctuation residue left after marker stripping
    text = _LEADING_COLON_RE.sub("", text)

    # 6. Final whitespace collapse and strip
    return _WHITESPACE_RE.sub(" ", text).strip()
