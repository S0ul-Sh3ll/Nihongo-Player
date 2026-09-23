"""Timeline transport bar and playback synchronization widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QWidget,
)

if TYPE_CHECKING:
    from nihongo_player.player.mpv_widget import MpvWidget


class ClickSeekSlider(QSlider):
    """QSlider that jumps directly to the clicked track position on mouse press."""

    def mousePressEvent(self, event: Any) -> None:
        """Jump slider to mouse position immediately on click."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos_x = event.position().x() if hasattr(event, "position") else event.x()
            pos_y = event.position().y() if hasattr(event, "position") else event.y()
            if self.orientation() == Qt.Orientation.Horizontal:
                val = QStyle.sliderValueFromPosition(
                    self.minimum(),
                    self.maximum(),
                    int(round(pos_x)),
                    self.width(),
                    self.invertedAppearance(),
                )
            else:
                val = QStyle.sliderValueFromPosition(
                    self.minimum(),
                    self.maximum(),
                    int(round(pos_y)),
                    self.height(),
                    not self.invertedAppearance(),
                )
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(event)


def format_time(seconds: float) -> str:
    """Format a timestamp in seconds to 'mm:ss' or 'hh:mm:ss'.

    Args:
        seconds: Time offset in seconds.

    Returns:
        Formatted time string.
    """
    if seconds < 0 or seconds != seconds:  # Handle negative or NaN
        seconds = 0.0
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class TimelineWidget(QWidget):
    """Transport bar providing seek slider, time display, play/pause, volume, and playback speed."""

    seek_requested = Signal(float)
    play_pause_clicked = Signal()
    prev_line_requested = Signal()
    next_line_requested = Signal()
    volume_changed = Signal(int)
    speed_changed = Signal(float)

    def __init__(
        self,
        parent: QWidget | None = None,
        player: MpvWidget | None = None,
    ) -> None:
        """Initialize transport bar controls.

        Args:
            parent: Optional parent QWidget.
            player: Optional MpvWidget instance to bind to.
        """
        super().__init__(parent)
        self._duration: float = 0.0
        self._is_dragging: bool = False
        self._connected_player: MpvWidget | None = None

        self._setup_ui()

        if player is not None:
            self.connect_player(player)

    def _setup_ui(self) -> None:
        """Construct and style timeline UI elements."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Previous subtitle line button
        self._prev_btn = QPushButton("⏮", self)
        self._prev_btn.setFixedWidth(36)
        self._prev_btn.setToolTip("Previous Subtitle Line")
        self._prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._prev_btn.clicked.connect(self._on_prev_line_clicked)
        layout.addWidget(self._prev_btn)

        # Play / Pause button
        self._play_btn = QPushButton("▶", self)
        self._play_btn.setFixedWidth(40)
        self._play_btn.setToolTip("Play / Pause (Space)")
        self._play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._play_btn.clicked.connect(self._on_play_pause_clicked)
        layout.addWidget(self._play_btn)

        # Next subtitle line button
        self._next_btn = QPushButton("⏭", self)
        self._next_btn.setFixedWidth(36)
        self._next_btn.setToolTip("Next Subtitle Line")
        self._next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._next_btn.clicked.connect(self._on_next_line_clicked)
        layout.addWidget(self._next_btn)

        # Current time label
        self._time_label = QLabel("00:00", self)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._time_label)

        # Separator label
        self._sep_label = QLabel("/", self)
        layout.addWidget(self._sep_label)

        # Total duration label
        self._dur_label = QLabel("00:00", self)
        self._dur_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._dur_label)

        # Seek slider (resolution in milliseconds)
        self._seek_slider = ClickSeekSlider(Qt.Orientation.Horizontal, self)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setValue(0)
        self._seek_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._seek_slider.sliderMoved.connect(self._on_seek_moved)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)
        layout.addWidget(self._seek_slider, stretch=1)

        # Playback speed label & slider (0.50x to 2.00x in 0.05 steps)
        self._speed_label = QLabel("1.00x", self)
        self._speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._speed_label.setStyleSheet("color: #d8dee9; font-size: 11px;")
        layout.addWidget(self._speed_label)

        self._speed_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._speed_slider.setRange(10, 40)
        self._speed_slider.setValue(20)
        self._speed_slider.setFixedWidth(65)
        self._speed_slider.setToolTip("Playback Speed (0.5x - 2.0x)")
        self._speed_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        layout.addWidget(self._speed_slider)

        # Volume icon / label
        self._vol_label = QLabel("🔊", self)
        layout.addWidget(self._vol_label)

        # Volume slider (0 - 100)
        self._vol_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(80)
        self._vol_slider.setToolTip("Volume (Up/Down)")
        self._vol_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._vol_slider.valueChanged.connect(self._on_volume_slider_changed)
        layout.addWidget(self._vol_slider)

    def connect_player(self, player: MpvWidget) -> None:
        """Bind timeline signals and slots with an MpvWidget instance.

        Args:
            player: Target MpvWidget player instance.
        """
        self._connected_player = player
        player.position_changed.connect(self.set_position)
        player.duration_changed.connect(self.set_duration)
        player.pause_changed.connect(self.set_paused)
        self.seek_requested.connect(player.seek_absolute)
        self.play_pause_clicked.connect(player.toggle_pause)
        self.volume_changed.connect(player.set_volume)
        self.speed_changed.connect(player.set_speed)
        self.set_paused(player.is_paused())

    def _on_prev_line_clicked(self) -> None:
        """Handle user clicking previous subtitle line button."""
        self.prev_line_requested.emit()

    def _on_play_pause_clicked(self) -> None:
        """Handle user clicking play/pause button."""
        self.play_pause_clicked.emit()

    def _on_next_line_clicked(self) -> None:
        """Handle user clicking next subtitle line button."""
        self.next_line_requested.emit()

    def _on_seek_pressed(self) -> None:
        """Handle user pressing down on seek slider."""
        self._is_dragging = True

    def _on_seek_moved(self, value: int) -> None:
        """Handle user dragging seek slider."""
        pos_sec = value / 1000.0
        self._time_label.setText(format_time(pos_sec))

    def _on_seek_released(self) -> None:
        """Handle user releasing seek slider."""
        target_sec = self._seek_slider.value() / 1000.0
        self._is_dragging = False
        self.seek_requested.emit(target_sec)

    def _on_volume_slider_changed(self, value: int) -> None:
        """Handle volume slider movement."""
        self.volume_changed.emit(value)

    def _on_speed_slider_changed(self, value: int) -> None:
        """Handle speed slider movement."""
        speed = round(value * 0.05, 2)
        self._speed_label.setText(f"{speed:.2f}x")
        self.speed_changed.emit(speed)

    def set_position(self, position_sec: float) -> None:
        """Update current position UI without interrupting active slider drag.

        Args:
            position_sec: Current playback position in seconds.
        """
        if self._is_dragging:
            return
        slider_val = int(position_sec * 1000)
        self._seek_slider.blockSignals(True)
        self._seek_slider.setValue(slider_val)
        self._seek_slider.blockSignals(False)
        self._time_label.setText(format_time(position_sec))

    def set_duration(self, duration_sec: float) -> None:
        """Update media duration and seek slider range.

        Args:
            duration_sec: Total duration in seconds.
        """
        self._duration = max(0.0, duration_sec)
        max_slider = max(1, int(self._duration * 1000))
        self._seek_slider.setRange(0, max_slider)
        self._dur_label.setText(format_time(self._duration))

    def set_paused(self, is_paused: bool) -> None:
        """Update play/pause button icon state.

        Args:
            is_paused: True if paused, False if playing.
        """
        if is_paused:
            self._play_btn.setText("▶")
        else:
            self._play_btn.setText("⏸")

    def set_volume(self, volume: int | float) -> None:
        """Set volume slider value programmatically.

        Args:
            volume: Volume level between 0 and 100.
        """
        vol_int = max(0, min(100, int(volume)))
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(vol_int)
        self._vol_slider.blockSignals(False)

    def set_speed(self, speed: float | int) -> None:
        """Set speed slider value programmatically.

        Args:
            speed: Speed multiplier between 0.5 and 2.0.
        """
        spd = max(0.5, min(2.0, float(speed)))
        val = int(round(spd / 0.05))
        self._speed_slider.blockSignals(True)
        self._speed_slider.setValue(val)
        self._speed_slider.blockSignals(False)
        self._speed_label.setText(f"{spd:.2f}x")

    def get_speed(self) -> float:
        """Get current speed slider value as float multiplier.

        Returns:
            Playback speed multiplier (0.5 to 2.0).
        """
        return round(self._speed_slider.value() * 0.05, 2)


class TimelineController:
    """Coordinates video playback timeline, seeking, and subtitle synchronization.

    Maintained for backward compatibility with callback-driven synchronization.
    """

    def __init__(self, player_widget: Any = None) -> None:
        """Initialize the timeline controller.

        Args:
            player_widget: Reference to the MPVWidget instance.
        """
        self._player = player_widget
        self._callbacks: list[Callable[[float], None]] = []

    def register_tick_callback(self, callback: Callable[[float], None]) -> None:
        """Register a callback to be invoked on time position updates.

        Args:
            callback: Callable accepting current timestamp in seconds.
        """
        self._callbacks.append(callback)

    def on_time_update(self, current_time: float) -> None:
        """Handle time update events from the media backend.

        Args:
            current_time: Current playback position in seconds.
        """
        for cb in self._callbacks:
            cb(current_time)

    def seek_to(self, seconds: float) -> None:
        """Seek the media player to a specific timestamp.

        Args:
            seconds: Target timestamp in seconds.
        """
        if self._player is not None:
            self._player.seek(seconds, relative=False)


__all__ = ["TimelineWidget", "TimelineController", "ClickSeekSlider", "format_time"]
