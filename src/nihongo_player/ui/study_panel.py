"""Study panel displaying Japanese cue with furigana, dictionary glosses, and translation."""

from __future__ import annotations

import html
from typing import Any, Sequence

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nihongo_player.ja.annotate import TokenView, annotate_cue
from nihongo_player.ja.dictionary import DictEntry, Dictionary, WordEntry
from nihongo_player.ja.furigana import is_kanji


class FuriganaHeaderWidget(QWidget):
    """Header widget rendering a Japanese sentence with furigana ruby above kanji."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens: list[TokenView] = []
        self._font_scale: float = 1.0
        self._base_pt = 18
        self._ruby_pt = 9
        self._kanji_colored: bool = True
        self._kanji_color: str = "#ffd54a"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    @property
    def kanji_colored(self) -> bool:
        """Return whether kanji glyphs are rendered in accent color."""
        return self._kanji_colored

    @kanji_colored.setter
    def kanji_colored(self, value: bool) -> None:
        self.set_kanji_colored(value)

    def set_kanji_colored(self, colored: bool) -> None:
        """Toggle accent coloring for kanji glyphs."""
        if self._kanji_colored != bool(colored):
            self._kanji_colored = bool(colored)
            self.update()

    @property
    def kanji_color(self) -> str:
        """Return accent color string for kanji glyphs."""
        return self._kanji_color

    @kanji_color.setter
    def kanji_color(self, color: str) -> None:
        self.set_kanji_color(color)

    def set_kanji_color(self, color: str) -> None:
        """Set accent color for kanji glyphs."""
        if self._kanji_color != str(color):
            self._kanji_color = str(color)
            self.update()

    def set_font_scale(self, scale: float) -> None:
        """Set font scale multiplier for base and ruby text."""
        self._font_scale = max(0.5, min(3.0, float(scale)))
        self._base_pt = max(9, int(18 * self._font_scale))
        self._ruby_pt = max(5, int(9 * self._font_scale))
        self.updateGeometry()
        self.update()

    def set_tokens(self, tokens: Sequence[TokenView]) -> None:
        """Update header with annotated token views."""
        self._tokens = list(tokens)
        self.updateGeometry()
        self.update()

    def set_text(self, text: str) -> None:
        """Annotate and set text."""
        self.set_tokens(annotate_cue(text))

    def clear(self) -> None:
        """Clear header content."""
        self._tokens = []
        self.updateGeometry()
        self.update()

    def to_html(self) -> str:
        """Return rich HTML representation of furigana header."""
        parts = []
        for tok in self._tokens:
            for base, ruby in tok.segments:
                if not base:
                    continue
                if self._kanji_colored:
                    runs: list[tuple[str, bool]] = []
                    for c in base:
                        k = is_kanji(c)
                        if runs and runs[-1][1] == k:
                            runs[-1] = (runs[-1][0] + c, k)
                        else:
                            runs.append((c, k))
                    colored_base = "".join(
                        f'<span style="color: {self._kanji_color};">{html.escape(r_text)}</span>'
                        if is_k
                        else html.escape(r_text)
                        for r_text, is_k in runs
                    )
                else:
                    colored_base = html.escape(base)

                if ruby:
                    parts.append(f"<ruby>{colored_base}<rt>{html.escape(ruby)}</rt></ruby>")
                else:
                    parts.append(colored_base)
        return "".join(parts)

    def sizeHint(self):
        base_font = QFont("Noto Sans CJK JP", self._base_pt, QFont.Weight.Bold)
        base_fm = QFontMetrics(base_font)
        ruby_font = QFont("Noto Sans CJK JP", self._ruby_pt, QFont.Weight.Bold)
        ruby_fm = QFontMetrics(ruby_font)
        h = base_fm.height() + ruby_fm.height() + 16
        return self.minimumSizeHint().expandedTo(self.size()).expandedTo(
            self.rect().size()
        ) if self._tokens else super().sizeHint()

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        h = max(40, int(52 * self._font_scale))
        return QSize(200, h)

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._tokens:
            return

        w = max(100, self.width())
        h = max(40, self.height())

        base_font = QFont("Noto Sans CJK JP", self._base_pt, QFont.Weight.Bold)
        ruby_font = QFont("Noto Sans CJK JP", self._ruby_pt, QFont.Weight.Bold)
        base_font.setStyleHint(QFont.StyleHint.SansSerif)
        ruby_font.setStyleHint(QFont.StyleHint.SansSerif)

        base_fm = QFontMetrics(base_font)
        ruby_fm = QFontMetrics(ruby_font)

        # Measure segments
        measured_segs: list[tuple[str, str, float, float, float]] = []
        total_w = 0.0
        for tok in self._tokens:
            for base, ruby in tok.segments:
                if not base:
                    continue
                bw = float(base_fm.horizontalAdvance(base))
                rw = float(ruby_fm.horizontalAdvance(ruby)) if ruby else 0.0
                sw = max(bw, rw)
                total_w += sw
                measured_segs.append((base, ruby, bw, rw, sw))

        if not measured_segs:
            return

        ruby_h = float(ruby_fm.height())
        base_h = float(base_fm.height())
        line_h = ruby_h + base_h

        # Center or left-align
        start_x = max(12.0, (float(w) - total_w) / 2.0)
        start_y = max(4.0, (float(h) - line_h) / 2.0)

        ruby_baseline = start_y + ruby_fm.ascent()
        base_baseline = start_y + ruby_h + base_fm.ascent()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        x = start_x
        for base, ruby, bw, rw, sw in measured_segs:
            base_x = x + (sw - bw) / 2.0

            if self._kanji_colored:
                cur_bx = base_x
                runs: list[tuple[str, bool]] = []
                for ch in base:
                    k = is_kanji(ch)
                    if runs and runs[-1][1] == k:
                        runs[-1] = (runs[-1][0] + ch, k)
                    else:
                        runs.append((ch, k))

                for run_text, is_k in runs:
                    path = QPainterPath()
                    path.addText(cur_bx, base_baseline, base_font, run_text)
                    color = QColor(self._kanji_color) if is_k else QColor(255, 255, 255)
                    painter.fillPath(path, QBrush(color))
                    cur_bx += float(base_fm.horizontalAdvance(run_text))
            else:
                path = QPainterPath()
                path.addText(base_x, base_baseline, base_font, base)
                painter.fillPath(path, QBrush(QColor(255, 255, 255)))

            if ruby:
                ruby_x = x + (sw - rw) / 2.0
                rpath = QPainterPath()
                rpath.addText(ruby_x, ruby_baseline, ruby_font, ruby)
                painter.fillPath(rpath, QBrush(QColor(200, 225, 255)))

            x += sw

        painter.end()


class StudyPanel(QWidget):
    """Study panel presenting Japanese sentence analysis, vocabulary glosses, and translation."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize study panel top-level window with header, translation label, dictionary table, and hint."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._dict = Dictionary()
        self._cue: Any = None
        self._tokens: list[TokenView] = []
        self._translation: str = ""
        self._kanji_colored: bool = True
        self._kanji_color: str = "#ffd54a"
        self._font_scale: float = 1.0

        self._setup_ui()
        self.hide()

    @property
    def kanji_colored(self) -> bool:
        """Return whether kanji glyphs are rendered in accent color."""
        return self._kanji_colored

    @kanji_colored.setter
    def kanji_colored(self, value: bool) -> None:
        self.set_kanji_colored(value)

    def set_kanji_colored(self, colored: bool) -> None:
        """Toggle accent coloring for kanji in header and word table."""
        self._kanji_colored = bool(colored)
        self._header.set_kanji_colored(self._kanji_colored)
        if self._tokens:
            self._populate_table(self._tokens)

    @property
    def kanji_color(self) -> str:
        """Return accent color string for kanji glyphs."""
        return self._kanji_color

    @kanji_color.setter
    def kanji_color(self, color: str) -> None:
        self.set_kanji_color(color)

    def set_kanji_color(self, color: str) -> None:
        """Set accent color for kanji glyphs."""
        self._kanji_color = str(color)
        self._header.set_kanji_color(self._kanji_color)
        if self._tokens:
            self._populate_table(self._tokens)

    @property
    def font_scale(self) -> float:
        """Return subtitle font scaling factor."""
        return self._font_scale

    @font_scale.setter
    def font_scale(self, value: float) -> None:
        self.set_font_scale(value)

    def set_font_scale(self, scale: float) -> None:
        """Set font scaling factor for study panel header furigana."""
        self._font_scale = max(0.5, min(3.0, float(scale)))
        self._header.set_font_scale(self._font_scale)

    def get_header_html(self) -> str:
        """Return rich HTML formatted furigana header text."""
        return self._header.to_html()

    def get_word_html(self, row: int) -> str:
        """Return rich HTML text for Word column cell at row."""
        w = self.table.cellWidget(row, 0)
        if isinstance(w, QLabel):
            return w.text()
        item = self.table.item(row, 0)
        return item.text() if item else ""

    def sync_to(self, global_rect: QRect) -> None:
        """Position study panel centered within the video rectangle in screen coordinates."""
        pw = global_rect.width()
        ph = global_rect.height()
        w = max(360, min(760, int(pw * 0.88)))
        h = max(240, min(440, int(ph * 0.85)))
        x = global_rect.x() + (pw - w) // 2
        y = global_rect.y() + (ph - h) // 2
        self.setGeometry(x, y, w, h)
        self.raise_()

    def _setup_ui(self) -> None:
        """Build study panel widgets and layout."""
        self.setStyleSheet(
            """
            StudyPanel {
                background-color: #161820;
                border: 2px solid #3b4252;
                border-radius: 10px;
            }
            QLabel {
                color: #eceff4;
            }
            QTableWidget {
                background-color: #1e222c;
                color: #eceff4;
                gridline-color: #434c5e;
                border: 1px solid #434c5e;
                border-radius: 6px;
                selection-background-color: #5e81ac;
            }
            QHeaderView::section {
                background-color: #2e3440;
                color: #d8dee9;
                padding: 4px 8px;
                font-weight: bold;
                border: 1px solid #3b4252;
            }
            """
        )

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # 1. Header row: Japanese sentence rendered with furigana + close (X) button
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        self._header = FuriganaHeaderWidget(self)
        self._header.set_kanji_colored(self._kanji_colored)
        self._header.set_kanji_color(self._kanji_color)
        self._header.set_font_scale(self._font_scale)
        top_row.addWidget(self._header, stretch=1)

        self._close_btn = QPushButton("✕", self)
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("Close study panel (Esc)")
        self._close_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #717888;
                border: none;
                border-radius: 13px;
                font-size: 14px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #3b4252;
                color: #eceff4;
            }
            QPushButton:pressed {
                background-color: #2e3440;
                color: #d8dee9;
            }
            """
        )
        self._close_btn.clicked.connect(self._on_close_clicked)
        top_row.addWidget(self._close_btn, stretch=0, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        main_layout.addLayout(top_row)

        # Divider
        divider1 = QFrame(self)
        divider1.setFrameShape(QFrame.Shape.HLine)
        divider1.setFrameShadow(QFrame.Shadow.Sunken)
        divider1.setStyleSheet("color: #434c5e;")
        main_layout.addWidget(divider1)

        # 2. Meaning / Translation section
        meaning_container = QHBoxLayout()
        meaning_title = QLabel("<b>Meaning:</b>", self)
        meaning_title.setStyleSheet("color: #88c0d0; font-size: 14px;")
        meaning_title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._meaning_label = QLabel("translating…", self)
        self._meaning_label.setStyleSheet("color: #e5e9f0; font-size: 14px;")
        self._meaning_label.setWordWrap(True)
        meaning_container.addWidget(meaning_title)
        meaning_container.addWidget(self._meaning_label, stretch=1)
        main_layout.addLayout(meaning_container)

        # 3. Word-by-word dictionary table
        self.table = QTableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Word", "Dictionary Definition / Gloss"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        main_layout.addWidget(self.table, stretch=1)

        # 4. Footer hint - prominent high-contrast accent pill
        hint_layout = QHBoxLayout()
        hint_layout.setContentsMargins(0, 4, 0, 0)
        hint_layout.addStretch(1)

        self._hint_label = QLabel("Press Space to resume", self)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.setStyleSheet(
            """
            QLabel {
                background-color: #ffd54a;
                color: #161820;
                font-weight: bold;
                font-size: 13px;
                padding: 6px 20px;
                border-radius: 13px;
            }
            """
        )
        hint_layout.addWidget(self._hint_label)
        hint_layout.addStretch(1)
        main_layout.addLayout(hint_layout)

    def populate(
        self,
        cue: Any,
        token_views: Sequence[TokenView],
        sentence_en: str | None = None,
        translation_enabled: bool = True,
    ) -> None:
        """Populate the study panel with analyzed linguistic data.

        Args:
            cue: Subtitle Cue object or cue identifier.
            token_views: List of analyzed TokenView instances for the sentence.
            sentence_en: English neural machine translation, or None/empty if translating.
            translation_enabled: Whether neural machine translation is enabled in settings.
        """
        self._cue = cue
        self._tokens = list(token_views)

        # 1. Update header furigana
        self._header.set_tokens(self._tokens)

        # 2. Update meaning label
        if not translation_enabled:
            self._translation = ""
            self._meaning_label.setText("(translation disabled)")
            self._meaning_label.setStyleSheet("color: #717888; font-size: 13px; font-style: italic;")
        elif sentence_en and sentence_en.strip():
            self._translation = sentence_en.strip()
            self._meaning_label.setText(self._translation)
            self._meaning_label.setStyleSheet("color: #e5e9f0; font-size: 14px;")
        else:
            self._translation = ""
            self._meaning_label.setText("translating…")
            self._meaning_label.setStyleSheet("color: #d8dee9; font-size: 14px; font-style: italic;")

        # 3. Populate word-by-word table
        self._populate_table(self._tokens)

    def _populate_table(self, tokens: list[TokenView]) -> None:
        """Fill dictionary table with vocabulary items."""
        self.table.setRowCount(0)
        row = 0

        for tok in tokens:
            if not tok.is_content:
                continue

            entry = self._dict.lookup(tok.surface, tok.lemma, reading_hint=tok.reading_hira)
            senses_text = "; ".join(entry.senses[:3]) if entry.found and entry.senses else "(no dictionary entry)"

            # Plain text representation
            if tok.reading_hira and tok.reading_hira != tok.surface:
                word_repr = f"{tok.surface} ({tok.reading_hira})"
            else:
                word_repr = tok.surface

            # Rich HTML representation with kanji coloring
            if self._kanji_colored:
                runs: list[tuple[str, bool]] = []
                for c in tok.surface:
                    k = is_kanji(c)
                    if runs and runs[-1][1] == k:
                        runs[-1] = (runs[-1][0] + c, k)
                    else:
                        runs.append((c, k))
                colored_surface = "".join(
                    f'<span style="color: {self._kanji_color};">{html.escape(r_text)}</span>'
                    if is_k
                    else html.escape(r_text)
                    for r_text, is_k in runs
                )
            else:
                colored_surface = html.escape(tok.surface)

            if tok.reading_hira and tok.reading_hira != tok.surface:
                word_html = f'{colored_surface}<br><span style="color: #9aa5b8; font-size: 11px; font-weight: normal;">({html.escape(tok.reading_hira)})</span>'
            else:
                word_html = colored_surface

            self.table.insertRow(row)

            # Set transparent foreground so table does not paint duplicate text underneath QLabel cell widget
            word_item = QTableWidgetItem(word_repr)
            word_item.setForeground(QBrush(QColor(0, 0, 0, 0)))
            self.table.setItem(row, 0, word_item)

            word_label = QLabel(word_html, self.table)
            word_label.setFont(QFont("Noto Sans CJK JP", 12, QFont.Weight.Bold))
            word_label.setStyleSheet("padding: 2px 6px; background: transparent; color: #eceff4;")
            word_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.table.setCellWidget(row, 0, word_label)

            gloss_item = QTableWidgetItem(senses_text)
            gloss_item.setFont(QFont("Sans Serif", 11))
            gloss_item.setForeground(QBrush(QColor(216, 222, 233)))
            self.table.setItem(row, 1, gloss_item)

            if tok.reading_hira and tok.reading_hira != tok.surface:
                self.table.setRowHeight(row, 46)
            else:
                self.table.setRowHeight(row, 36)

            row += 1

    def set_translation(self, text: str | None) -> None:
        """Update translation text dynamically when asynchronous worker finishes.

        Args:
            text: Translated English string.
        """
        if text and text.strip():
            self._translation = text.strip()
            self._meaning_label.setText(self._translation)
            self._meaning_label.setStyleSheet("color: #e5e9f0; font-size: 14px;")
        else:
            self._translation = ""
            self._meaning_label.setText("translating…")
            self._meaning_label.setStyleSheet("color: #d8dee9; font-size: 14px; font-style: italic;")

    def get_translation(self) -> str:
        """Return currently displayed translation text."""
        return self._translation

    def is_visible(self) -> bool:
        """Check if study panel is currently visible."""
        return self.isVisible()

    def _on_close_clicked(self) -> None:
        """Handle clicking the close (X) button."""
        self.hide()
        self.closed.emit()

    def dismiss(self) -> None:
        """Dismiss study panel programmatically."""
        self.hide()
        self.closed.emit()

    def update_content(
        self,
        sentence: str,
        tokens: Sequence[Any],
        entries: Sequence[DictEntry],
        translation: str,
    ) -> None:
        """Backwards compatibility helper."""
        token_views = annotate_cue(sentence)
        self.populate(None, token_views, translation)
