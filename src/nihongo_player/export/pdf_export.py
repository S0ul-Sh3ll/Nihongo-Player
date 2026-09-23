"""Export frequency vocabulary list to PDF using ReportLab platypus."""

from __future__ import annotations

from datetime import datetime
import html
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from nihongo_player.export.frequency import VocabEntry
from nihongo_player.export.furigana_text import furigana_inline

_CID_FONT_NAME = "HeiseiKakuGo-W5"
_CID_FONT_REGISTERED = False


def _ensure_cid_font() -> str:
    """Register built-in Unicode CID font for Japanese text rendering in ReportLab."""
    global _CID_FONT_REGISTERED
    if not _CID_FONT_REGISTERED:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(_CID_FONT_NAME))
            _CID_FONT_REGISTERED = True
        except Exception:
            pass
    return _CID_FONT_NAME


def get_pdf_styles(font_name: str) -> dict[str, ParagraphStyle]:
    """Return dictionary of configured paragraph styles for vocabulary PDF export."""
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "NPVocabTitle",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1a237e"),
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "NPVocabMeta",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#555555"),
            spaceAfter=12,
        ),
        "header": ParagraphStyle(
            "NPVocabHdr",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=11,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.white,
        ),
        "rank": ParagraphStyle(
            "NPVocabRank",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#555555"),
        ),
        "word": ParagraphStyle(
            "NPVocabWord",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0d47a1"),
        ),
        "reading": ParagraphStyle(
            "NPVocabReading",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=13,
            leading=17,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"),
        ),
        "english": ParagraphStyle(
            "NPVocabEnglish",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=11,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#212121"),
        ),
        "example": ParagraphStyle(
            "NPVocabExample",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"),
        ),
    }


def build_pdf_table_style() -> TableStyle:
    """Construct TableStyle for vocabulary PDF document."""
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#283593")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#f8f9fa")],
            ),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def export_pdf(
    entries: Sequence[VocabEntry],
    out_path: str | Path,
    title: str = "Nihongo Player — Vocabulary",
    source_name: str = "",
) -> None:
    """Export vocabulary entries to a styled PDF document.

    Args:
        entries: Sequence of VocabEntry objects to include in the document.
        out_path: Destination path for the exported .pdf file.
        title: Document header title.
        source_name: Optional name of the media or subtitle file source.
    """
    font_name = _ensure_cid_font()
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(dest),
        pagesize=landscape(A4),
        leftMargin=28,
        rightMargin=28,
        topMargin=28,
        bottomMargin=28,
    )

    pdf_styles = get_pdf_styles(font_name)
    title_style = pdf_styles["title"]
    meta_style = pdf_styles["meta"]
    hdr_style = pdf_styles["header"]
    rank_style = pdf_styles["rank"]
    word_style = pdf_styles["word"]
    reading_style = pdf_styles["reading"]
    english_style = pdf_styles["english"]
    example_style = pdf_styles["example"]

    elements = []

    # Title & Metadata
    elements.append(Paragraph(html.escape(title), title_style))
    gen_date = datetime.now().strftime("%Y-%m-%d")
    src_info = f"Source: {html.escape(source_name)} | " if source_name else ""
    meta_text = f"{src_info}Generated: {gen_date} | Total Words: {len(entries)}"
    elements.append(Paragraph(meta_text, meta_style))

    # Table Header
    headers = [
        Paragraph("<b># (Freq)</b>", hdr_style),
        Paragraph("<b>Word</b>", hdr_style),
        Paragraph("<b>Reading</b>", hdr_style),
        Paragraph("<b>English</b>", hdr_style),
        Paragraph("<b>Examples</b>", hdr_style),
    ]
    table_data = [headers]

    for idx, entry in enumerate(entries, start=1):
        rank_text = f"#{idx} ({entry.count}×)"
        word_html = html.escape(entry.base or "")
        reading_html = html.escape(entry.reading or "")
        english_html = html.escape(entry.english or "")

        examples_list = entry.examples or []
        examples_en_list = getattr(entry, "examples_en", []) or []

        if examples_list:
            parts = []
            for ex_i, ex_ja in enumerate(examples_list[:5]):
                ex_ja_furi = furigana_inline(ex_ja)
                ex_ja_esc = html.escape(ex_ja_furi)
                ex_en = examples_en_list[ex_i] if ex_i < len(examples_en_list) else ""
                if ex_en and ex_en.strip():
                    ex_en_esc = html.escape(ex_en.strip())
                    parts.append(
                        f"{ex_ja_esc}<br/><font color=\"#666666\" size=\"8.5\"><i>{ex_en_esc}</i></font>"
                    )
                else:
                    parts.append(ex_ja_esc)
            examples_html = "<br/><br/>".join(parts)
        else:
            examples_html = ""

        row = [
            Paragraph(rank_text, rank_style),
            Paragraph(word_html, word_style),
            Paragraph(reading_html, reading_style),
            Paragraph(english_html, english_style),
            Paragraph(examples_html, example_style),
        ]
        table_data.append(row)

    # Column widths summing to 785 pt (landscape A4 width 841.89 pt - 56 pt margins)
    col_widths = [60, 110, 105, 180, 330]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(build_pdf_table_style())
    elements.append(table)

    doc.build(elements)
