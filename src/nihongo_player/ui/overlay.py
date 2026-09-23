"""Furigana subtitle overlay widget rendered over the video canvas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from PySide6.QtCore import QRect, QTimer, Qt, Signal
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
from PySide6.QtWidgets import QSizePolicy, QWidget

from nihongo_player.ja.annotate import annotate_cue
from nihongo_player.ja.furigana import is_kanji


@dataclass
class _SegmentMetrics:
    base_text: str
    ruby_text: str
    base_w: float
    ruby_w: float
    seg_w: float


@dataclass
class _TokenMetrics:
    segments: list[_SegmentMetrics]
    width: float


def _draw_stroked_text(
    painter: QPainter,
    font: QFont,
    text: str,
    x: float,
    y: float,
    outline_width: float,
    text_color: QColor = QColor(255, 255, 255),
    outline_color: QColor = QColor(0, 0, 0, 230),
) -> None:
    """Draw anti-aliased text with a dark stroke outline for maximum contrast."""
    if not text:
        return
    path = QPainterPath()
    path.addText(x, y, font, text)

    pen = QPen(outline_color, outline_width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.strokePath(path, pen)
    painter.fillPath(path, QBrush(text_color))


class SubtitleOverlay(QWidget):
    """Transparent overlay window rendering Japanese subtitle text with ruby/furigana above kanji.

    Top-level companion window that sits directly over the native video canvas and acts
    as the primary mouse surface for play/pause and fullscreen toggles.
    """

    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize transparent overlay window.

        Args:
            parent: Optional parent QWidget (typically MainWindow).
        """
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(250)
        self._click_timer.timeout.connect(self._on_click_timeout)

        self._font_scale: float = 1.0
        self._custom_base_pt: int | None = None
        self._furigana_visible: bool = True
        self._kanji_colored: bool = True
        self._kanji_color: str = "#ffd54a"
        self._tokens_segments: list[list[tuple[str, str]]] = []
        self._raw_text: str = ""

    def mousePressEvent(self, event: Any) -> None:
        """Handle mouse press event, scheduling single-click emission if not cancelled by double-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.start()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        """Handle mouse double-click event, cancelling single-click timer and emitting double_clicked."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _on_click_timeout(self) -> None:
        """Emit single-click signal after timer expiration."""
        self.clicked.emit()

    @property
    def raw_text(self) -> str:
        """Return currently loaded raw subtitle text."""
        return self._raw_text

    def has_content(self) -> bool:
        """Return True if overlay contains active subtitle segments."""
        return bool(self._tokens_segments and self._raw_text)

    def sync_to(self, global_rect: QRect) -> None:
        """Align overlay geometry to the video rectangle in screen coordinates."""
        if self.geometry() != global_rect:
            self.setGeometry(global_rect)
            self.update()

    def show_over(self) -> None:
        """Show overlay window without taking focus."""
        if not self.isVisible():
            self.show()
        self.raise_()

    @property
    def furigana_visible(self) -> bool:
        """Return whether ruby furigana annotations are visible."""
        return self._furigana_visible

    @furigana_visible.setter
    def furigana_visible(self, value: bool) -> None:
        self.set_furigana_visible(value)

    def set_furigana_visible(self, visible: bool) -> None:
        """Toggle furigana visibility above kanji glyphs."""
        if self._furigana_visible != visible:
            self._furigana_visible = bool(visible)
            self.update()

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
        """Return current accent color for kanji glyphs."""
        return self._kanji_color

    @kanji_color.setter
    def kanji_color(self, color: str) -> None:
        self.set_kanji_color(color)

    def set_kanji_color(self, color: str) -> None:
        """Set accent color for kanji glyphs (e.g. '#ffd54a')."""
        if self._kanji_color != str(color):
            self._kanji_color = str(color)
            self.update()

    def set_font_scale(self, scale: float) -> None:
        """Set scaling multiplier for subtitle text and ruby annotations."""
        self._font_scale = max(0.2, float(scale))
        self.update()

    def set_font_size(self, size_pt: int) -> None:
        """Set base font size in points."""
        self._custom_base_pt = max(8, int(size_pt))
        self.update()

    def set_cue(self, text: str | None) -> None:
        """Annotate Japanese subtitle text with furigana and update display.

        Args:
            text: Japanese subtitle line or None to clear.
        """
        if not text or not str(text).strip():
            self.clear()
            return

        cleaned_text = str(text).strip()
        if cleaned_text == self._raw_text and self._tokens_segments:
            return

        self._raw_text = cleaned_text
        token_views = annotate_cue(cleaned_text)
        self._tokens_segments = [tv.segments for tv in token_views if tv.segments]
        self.update()

    def set_segments_per_token(
        self, token_segments: Sequence[Sequence[tuple[str, str]]]
    ) -> None:
        """Set segmented furigana data grouped by token.

        Args:
            token_segments: List of tokens, each containing list of (base, ruby) tuples.
        """
        self._tokens_segments = [
            [tuple(seg) for seg in tok]  # type: ignore[misc]
            for tok in token_segments
            if tok
        ]
        self._raw_text = "".join(
            base for tok in self._tokens_segments for base, _ in tok
        )
        self.update()

    def set_furigana_segments(self, segments: Sequence[tuple[str, str]]) -> None:
        """Backwards-compatibility helper setting flat list of furigana segments."""
        if not segments:
            self.clear()
            return
        self._tokens_segments = [[(str(b), str(r))] for b, r in segments if b]
        self._raw_text = "".join(base for tok in self._tokens_segments for base, _ in tok)
        self.update()

    def clear(self) -> None:
        """Clear subtitle display."""
        self._tokens_segments = []
        self._raw_text = ""
        self.update()

    def to_html(self) -> str:
        """Return HTML ruby markup representation of current subtitle text."""
        import html

        parts = []
        for tok in self._tokens_segments:
            for base, ruby in tok:
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

                if ruby and self._furigana_visible:
                    parts.append(f"<ruby>{colored_base}<rt>{html.escape(ruby)}</rt></ruby>")
                else:
                    parts.append(colored_base)
        return "".join(parts)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render Japanese subtitle text with positioned ruby annotations."""
        if not self._tokens_segments:
            return

        w = max(100, self.width())
        h = max(100, self.height())

        # Determine font sizes
        if self._custom_base_pt is not None:
            base_pt = int(self._custom_base_pt * self._font_scale)
        else:
            base_pt = max(14, int(min(w / 35.0, h / 20.0) * self._font_scale))

        ruby_pt = max(8, int(base_pt * 0.45))

        base_font = QFont("Noto Sans CJK JP", base_pt, QFont.Weight.Bold)
        ruby_font = QFont("Noto Sans CJK JP", ruby_pt, QFont.Weight.Bold)
        base_font.setStyleHint(QFont.StyleHint.SansSerif)
        ruby_font.setStyleHint(QFont.StyleHint.SansSerif)

        base_fm = QFontMetrics(base_font)
        ruby_fm = QFontMetrics(ruby_font)

        # Measure tokens and segments
        measured_tokens: list[_TokenMetrics] = []
        for tok in self._tokens_segments:
            seg_metrics: list[_SegmentMetrics] = []
            tok_w = 0.0
            for base, ruby in tok:
                if not base:
                    continue
                base_w = float(base_fm.horizontalAdvance(base))
                has_ruby = bool(ruby and self._furigana_visible)
                ruby_w = float(ruby_fm.horizontalAdvance(ruby)) if has_ruby else 0.0
                seg_w = max(base_w, ruby_w)
                tok_w += seg_w
                seg_metrics.append(
                    _SegmentMetrics(
                        base_text=base,
                        ruby_text=ruby if has_ruby else "",
                        base_w=base_w,
                        ruby_w=ruby_w,
                        seg_w=seg_w,
                    )
                )
            if seg_metrics:
                measured_tokens.append(_TokenMetrics(segments=seg_metrics, width=tok_w))

        if not measured_tokens:
            return

        # Line wrap tokens
        margin_x = max(24.0, w * 0.05)
        max_line_w = max(60.0, float(w - 2 * margin_x))

        lines: list[list[_TokenMetrics]] = [[]]
        cur_w = 0.0

        for t in measured_tokens:
            if cur_w + t.width > max_line_w and len(lines[-1]) > 0:
                lines.append([t])
                cur_w = t.width
            else:
                lines[-1].append(t)
                cur_w += t.width

        # Vertical metrics
        ruby_h = float(ruby_fm.height()) if self._furigana_visible else 0.0
        base_h = float(base_fm.height())
        line_spacing = max(4.0, base_pt * 0.15)
        line_height = ruby_h + base_h + line_spacing
        total_block_h = len(lines) * line_height

        margin_bottom = max(20.0, h * 0.06)
        block_top_y = float(h) - margin_bottom - total_block_h

        # Paint tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # Draw semi-opaque dark strip behind text block for readability & non-composited fallback
        max_rendered_line_w = max((sum(t.width for t in line) for line in lines), default=0.0)
        if max_rendered_line_w > 0:
            pad_x = 16.0
            pad_y = 6.0
            strip_w = max_rendered_line_w + pad_x * 2
            strip_h = total_block_h + pad_y * 2
            strip_x = (float(w) - strip_w) / 2.0
            strip_y = block_top_y - pad_y
            strip_path = QPainterPath()
            strip_path.addRoundedRect(strip_x, strip_y, strip_w, strip_h, 8.0, 8.0)
            painter.fillPath(strip_path, QBrush(QColor(0, 0, 0, 160)))

        outline_base = max(2.5, base_pt * 0.14)
        outline_ruby = max(1.5, ruby_pt * 0.14)

        for line_idx, line in enumerate(lines):
            line_w = sum(t.width for t in line)
            x = (float(w) - line_w) / 2.0
            line_top_y = block_top_y + line_idx * line_height

            ruby_baseline_y = line_top_y + ruby_fm.ascent()
            base_baseline_y = line_top_y + ruby_h + base_fm.ascent()

            for t in line:
                for seg in t.segments:
                    # Center base within segment
                    base_x = x + (seg.seg_w - seg.base_w) / 2.0

                    if self._kanji_colored:
                        cur_bx = base_x
                        runs: list[tuple[str, bool]] = []
                        for ch in seg.base_text:
                            k = is_kanji(ch)
                            if runs and runs[-1][1] == k:
                                runs[-1] = (runs[-1][0] + ch, k)
                            else:
                                runs.append((ch, k))

                        for run_text, is_k in runs:
                            run_w = float(base_fm.horizontalAdvance(run_text))
                            text_color = QColor(self._kanji_color) if is_k else QColor(255, 255, 255)
                            _draw_stroked_text(
                                painter,
                                base_font,
                                run_text,
                                cur_bx,
                                base_baseline_y,
                                outline_width=outline_base,
                                text_color=text_color,
                                outline_color=QColor(0, 0, 0, 230),
                            )
                            cur_bx += run_w
                    else:
                        _draw_stroked_text(
                            painter,
                            base_font,
                            seg.base_text,
                            base_x,
                            base_baseline_y,
                            outline_width=outline_base,
                            text_color=QColor(255, 255, 255),
                            outline_color=QColor(0, 0, 0, 230),
                        )

                    # Center ruby above base
                    if seg.ruby_text:
                        ruby_x = x + (seg.seg_w - seg.ruby_w) / 2.0
                        _draw_stroked_text(
                            painter,
                            ruby_font,
                            seg.ruby_text,
                            ruby_x,
                            ruby_baseline_y,
                            outline_width=outline_ruby,
                            text_color=QColor(245, 245, 245),
                            outline_color=QColor(0, 0, 0, 230),
                        )

                    x += seg.seg_w

        painter.end()
