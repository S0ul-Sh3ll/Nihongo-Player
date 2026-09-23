"""Center-screen circular progress dialog for long operations."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class CircularProgressWidget(QWidget):
    """Widget painting a circular progress ring with center percentage text."""

    def __init__(
        self,
        parent: QWidget | None = None,
        ring_color: str = "#ffd54a",
        track_color: str = "#2e3440",
    ) -> None:
        super().__init__(parent)
        self._progress: float = 0.0
        self._ring_color = ring_color
        self._track_color = track_color
        self.setFixedSize(130, 130)

    def set_progress(self, pct: float) -> None:
        """Set progress percentage (clamped between 0.0 and 100.0)."""
        self._progress = max(0.0, min(100.0, float(pct)))
        self.update()

    def get_progress(self) -> float:
        """Get current progress percentage."""
        return self._progress

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint circular track, progress arc, and centered percentage string."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())
        size = min(w, h)
        pen_width = 9.0
        margin = pen_width / 2.0 + 4.0
        ring_rect = QRectF(margin, margin, size - margin * 2, size - margin * 2)

        # 1. Background track ring
        track_pen = QPen(QColor(self._track_color), pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawEllipse(ring_rect)

        # 2. Progress arc
        if self._progress > 0.0:
            prog_pen = QPen(QColor(self._ring_color), pen_width)
            prog_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(prog_pen)
            # Start angle at 90 degrees (12 o'clock position), span clockwise
            start_angle = 90 * 16
            span_angle = int(-round((self._progress / 100.0) * 360.0 * 16))
            painter.drawArc(ring_rect, start_angle, span_angle)

        # 3. Center percentage text
        painter.setPen(QColor("#eceff4"))
        pct_font = QFont("Noto Sans CJK JP", 16, QFont.Weight.Bold)
        pct_font.setStyleHint(QFont.StyleHint.SansSerif)
        painter.setFont(pct_font)
        pct_text = f"{int(round(self._progress))}%"
        painter.drawText(ring_rect, Qt.AlignmentFlag.AlignCenter, pct_text)

        painter.end()


class CircularProgressDialog(QDialog):
    """Reusable center-screen circular progress popup for long operations.

    Frameless, semi-opaque rounded card that stays centered over the parent
    window without blocking code execution (shown via show(), not exec()).
    """

    canceled = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        title: str = "Generating subtitles…",
        cancellable: bool = True,
    ) -> None:
        """Initialize circular progress dialog.

        Args:
            parent: Parent QWidget to center over.
            title: Title / status message string.
            cancellable: Whether to include a Cancel button.
        """
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(280, 270)

        self._cancellable = cancellable
        self._setup_ui(title)

    def _setup_ui(self, title: str) -> None:
        """Construct card layout, title label, progress ring, and cancel button."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Title / status label
        self._label = QLabel(title, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            "color: #eceff4; font-size: 13px; font-weight: bold; background: transparent;"
        )
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._label)

        # Circular progress ring widget
        ring_container = QHBoxLayout()
        ring_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ring = CircularProgressWidget(self)
        ring_container.addWidget(self._ring)
        layout.addLayout(ring_container)

        # Cancel button
        if self._cancellable:
            btn_layout = QHBoxLayout()
            btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cancel_btn = QPushButton("Cancel", self)
            self._cancel_btn.setFixedWidth(100)
            self._cancel_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #3b4252;
                    color: #d8dee9;
                    border: 1px solid #4c566a;
                    border-radius: 4px;
                    padding: 5px 14px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #434c5e;
                    color: #eceff4;
                }
                QPushButton:pressed {
                    background-color: #2e3440;
                }
                """
            )
            self._cancel_btn.clicked.connect(self._on_cancel)
            btn_layout.addWidget(self._cancel_btn)
            layout.addLayout(btn_layout)

    def _on_cancel(self) -> None:
        """Handle user clicking cancel."""
        self.canceled.emit()
        self.reject()

    def set_progress(self, pct: float) -> None:
        """Set progress percentage (clamped between 0.0 and 100.0).

        Args:
            pct: Percentage value from 0.0 to 100.0.
        """
        self._ring.set_progress(pct)

    def get_progress(self) -> float:
        """Get current progress percentage.

        Returns:
            Current progress float (0.0 to 100.0).
        """
        return self._ring.get_progress()

    def set_label(self, text: str) -> None:
        """Set title/status message label.

        Args:
            text: New status message text.
        """
        self._label.setText(str(text))

    def get_label(self) -> str:
        """Get current title/status message text.

        Returns:
            Current status text.
        """
        return self._label.text()

    def recenter(self) -> None:
        """Center the dialog over the parent window or primary screen."""
        p = self.parentWidget()
        if p is not None and p.isVisible():
            p_geo = p.geometry()
            x = p_geo.x() + (p_geo.width() - self.width()) // 2
            y = p_geo.y() + (p_geo.height() - self.height()) // 2
            self.move(x, y)
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                s_geo = screen.geometry()
                x = (s_geo.width() - self.width()) // 2
                y = (s_geo.height() - self.height()) // 2
                self.move(x, y)

    def showEvent(self, event: Any) -> None:
        """Recenter over parent on show and ensure window is raised and active."""
        self.recenter()
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw semi-opaque dark card background with rounded corners and border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        card_path = QPainterPath()
        card_path.addRoundedRect(rect, 14.0, 14.0)

        # Card background
        painter.fillPath(card_path, QBrush(QColor(24, 27, 36, 245)))

        # Card border
        border_pen = QPen(QColor(67, 76, 94, 220), 1.5)
        painter.strokePath(card_path, border_pen)

        painter.end()


__all__ = ["CircularProgressDialog", "CircularProgressWidget"]
