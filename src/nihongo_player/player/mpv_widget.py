"""PySide6 QWidget embedding the MPV video player engine."""

from __future__ import annotations

import locale
import os
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QWidget

from nihongo_player.player.libmpv_loader import ensure_libmpv

# Ensure libmpv is located and configured before mpv import
ensure_libmpv()
try:
    import mpv
except (ImportError, OSError):
    mpv = None  # type: ignore[assignment]


class MpvWidget(QWidget):
    """Qt widget wrapping an embedded mpv player instance.

    Uses Qt native window ID (wid) to render video frames directly via
    GPU/X11/Wayland into the widget surface. Subtitle rendering in mpv is disabled
    to allow custom Japanese overlay layers.
    """

    position_changed = Signal(float)
    duration_changed = Signal(float)
    pause_changed = Signal(bool)
    end_reached = Signal()
    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize MpvWidget with native window attributes and mpv backend.

        Args:
            parent: Optional parent QWidget.
        """
        super().__init__(parent)

        self._is_shut_down = False
        self._current_file: str | None = None
        self._video_zoom: float = 0.0
        self._aspect_override: str = "-1"
        self._stretch: bool = False
        self._panscan: float = 0.0
        self._brightness: int = 0

        # Request native window handle from Qt
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.setStyleSheet("background-color: black;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Ensure LC_NUMERIC is 'C' before instantiating MPV
        try:
            locale.setlocale(locale.LC_NUMERIC, "C")
        except Exception:
            pass

        wid = str(int(self.winId()))

        # Recommended mpv options:
        # - vo: gpu with fallbacks (x11, xv, null)
        # - keep_open: yes
        # - hr_seek: yes
        # - osc: False (custom UI is provided in Qt)
        # - sub_visibility: False / sub_auto: no (Nihongo Player renders subs/furigana)
        # - input_default_bindings: False, input_vo_keyboard: False (Qt handles keys)
        if mpv is None:
            raise RuntimeError("libmpv is not available on this system")

        vo_opt = os.environ.get("NIHONGO_MPV_VO") or "gpu,wlshm,x11,xv,null"

        self._mpv = mpv.MPV(
            wid=wid,
            vo=vo_opt,
            keep_open="yes",
            hr_seek="yes",
            osc=False,
            sub_visibility=False,
            sub_auto="no",
            input_default_bindings=False,
            input_vo_keyboard=False,
        )

        self._register_property_observers()

    def _register_property_observers(self) -> None:
        """Attach property observers to bridge mpv events to Qt signals."""
        if self._mpv is None:
            return

        @self._mpv.property_observer("time-pos")
        def _on_time_pos(_name: str, value: Any) -> None:
            if value is not None and not self._is_shut_down:
                try:
                    self.position_changed.emit(float(value))
                except RuntimeError:
                    pass

        @self._mpv.property_observer("duration")
        def _on_duration(_name: str, value: Any) -> None:
            if value is not None and not self._is_shut_down:
                try:
                    self.duration_changed.emit(float(value))
                except RuntimeError:
                    pass

        @self._mpv.property_observer("pause")
        def _on_pause(_name: str, value: Any) -> None:
            if value is not None and not self._is_shut_down:
                try:
                    self.pause_changed.emit(bool(value))
                except RuntimeError:
                    pass

        @self._mpv.property_observer("eof-reached")
        def _on_eof(_name: str, value: Any) -> None:
            if value and not self._is_shut_down:
                try:
                    self.end_reached.emit()
                except RuntimeError:
                    pass

    def load(self, path: str) -> None:
        """Load and start playback of a media file.

        Args:
            path: Absolute or relative filesystem path to the media file.
        """
        self._current_file = path
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.play(str(path))
                self.pause_changed.emit(False)
            except Exception:
                pass

    def load_file(self, path: str) -> None:
        """Alias for load()."""
        self.load(path)

    def play(self) -> None:
        """Resume or start media playback."""
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.pause = False
                self.pause_changed.emit(False)
            except Exception:
                pass

    def pause(self) -> None:
        """Pause media playback."""
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.pause = True
                self.pause_changed.emit(True)
            except Exception:
                pass

    def toggle_pause(self) -> None:
        """Toggle between playing and paused playback states."""
        if self._mpv is not None and not self._is_shut_down:
            try:
                new_state = not bool(self._mpv.pause)
                self._mpv.pause = new_state
                self.pause_changed.emit(new_state)
            except Exception:
                pass

    def is_paused(self) -> bool:
        """Check if playback is currently paused.

        Returns:
            True if paused, False otherwise.
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                return bool(self._mpv.pause)
            except Exception:
                return False
        return False

    def seek_absolute(self, seconds: float) -> None:
        """Seek to an absolute timestamp.

        Args:
            seconds: Target timestamp in seconds (non-negative).
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.seek(max(0.0, float(seconds)), reference="absolute+exact")
            except Exception:
                try:
                    self._mpv.seek(max(0.0, float(seconds)), reference="absolute")
                except Exception:
                    pass

    def seek_relative(self, delta: float) -> None:
        """Seek by a relative time delta.

        Args:
            delta: Positive or negative offset in seconds.
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.seek(float(delta), reference="relative")
            except Exception:
                pass

    def seek(self, seconds: float, relative: bool = False) -> None:
        """Seek playback position.

        Args:
            seconds: Target timestamp or relative delta in seconds.
            relative: If True, seek relative to current time; otherwise absolute.
        """
        if relative:
            self.seek_relative(seconds)
        else:
            self.seek_absolute(seconds)

    def position(self) -> float:
        """Get current playback timestamp in seconds.

        Returns:
            Current position in seconds (0.0 if not available).
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                val = self._mpv.time_pos
                return float(val) if val is not None else 0.0
            except Exception:
                return 0.0
        return 0.0

    def get_time_pos(self) -> float:
        """Alias for position()."""
        return self.position()

    def duration(self) -> float:
        """Get total media duration in seconds.

        Returns:
            Duration in seconds (0.0 if not available).
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                val = self._mpv.duration
                return float(val) if val is not None else 0.0
            except Exception:
                return 0.0
        return 0.0

    def get_duration(self) -> float:
        """Alias for duration()."""
        return self.duration()

    def set_volume(self, volume: float | int) -> None:
        """Set player audio volume.

        Args:
            volume: Volume level between 0 and 100.
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.volume = max(0.0, min(100.0, float(volume)))
            except Exception:
                pass

    def get_volume(self) -> float:
        """Get current player audio volume.

        Returns:
            Volume level between 0.0 and 100.0.
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                val = self._mpv.volume
                return float(val) if val is not None else 100.0
            except Exception:
                return 100.0
        return 100.0

    def set_speed(self, speed: float | int) -> None:
        """Set playback speed multiplier.

        Args:
            speed: Speed multiplier (e.g. 0.5 to 2.0).
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.speed = max(0.1, min(10.0, float(speed)))
            except Exception:
                pass

    def get_speed(self) -> float:
        """Get current playback speed multiplier.

        Returns:
            Speed multiplier (default 1.0).
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                val = self._mpv.speed
                return float(val) if val is not None else 1.0
            except Exception:
                return 1.0
        return 1.0

    def set_video_zoom(self, z: float) -> float:
        """Set mpv video-zoom level (log2 scale, clamped between -2.0 and 2.0).

        Args:
            z: Zoom level exponent in log2 scale.

        Returns:
            Clamped zoom level applied.
        """
        self._video_zoom = max(-2.0, min(2.0, float(z)))
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv["video-zoom"] = self._video_zoom
            except Exception:
                pass
        return self._video_zoom

    def get_video_zoom(self) -> float:
        """Get current video-zoom value.

        Returns:
            Current zoom exponent (default 0.0).
        """
        if self._mpv is not None and not self._is_shut_down:
            try:
                val = self._mpv["video-zoom"]
                if val is not None:
                    return float(val)
            except Exception:
                pass
        return self._video_zoom

    def zoom_by(self, delta: float) -> float:
        """Adjust video-zoom by a relative delta.

        Args:
            delta: Increment or decrement to zoom exponent.

        Returns:
            New zoom exponent after adjustment.
        """
        return self.set_video_zoom(self._video_zoom + float(delta))

    def reset_zoom(self) -> None:
        """Reset video zoom exponent back to 0.0 (1.0x)."""
        self.set_video_zoom(0.0)

    def set_aspect_override(self, val: str) -> None:
        """Set mpv video aspect ratio override ('-1'=default, '16:9', '4:3', '2.35:1').

        Args:
            val: Aspect ratio string representation.
        """
        self._aspect_override = str(val) if val is not None else "-1"
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv["video-aspect-override"] = self._aspect_override
            except Exception:
                pass

    def get_aspect_override(self) -> str:
        """Get current video aspect ratio override string."""
        return self._aspect_override

    def set_stretch(self, on: bool) -> None:
        """Set video stretch mode (ignoring aspect ratio to fill window when True).

        Args:
            on: True to disable aspect ratio preservation (keepaspect=False).
        """
        self._stretch = bool(on)
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv["keepaspect"] = not self._stretch
            except Exception:
                pass

    def get_stretch(self) -> bool:
        """Get current stretch mode."""
        if self._mpv is not None and not self._is_shut_down:
            try:
                val = self._mpv["keepaspect"]
                if val is not None:
                    return not bool(val)
            except Exception:
                pass
        return self._stretch

    def set_panscan(self, p: float) -> None:
        """Set mpv panscan value (0.0 to 1.0; 1.0 = zoom/crop to fill window).

        Args:
            p: Panscan fraction (0.0 to 1.0).
        """
        self._panscan = max(0.0, min(1.0, float(p)))
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv["panscan"] = self._panscan
            except Exception:
                pass

    def get_panscan(self) -> float:
        """Get current panscan value."""
        if self._mpv is not None and not self._is_shut_down:
            try:
                val = self._mpv["panscan"]
                if val is not None:
                    return float(val)
            except Exception:
                pass
        return self._panscan

    def set_brightness(self, v: int | float) -> int:
        """Set video display brightness (-100 to 100, clamped) using lavfi eq filter.

        Args:
            v: Brightness level between -100 and 100.

        Returns:
            Clamped brightness level applied.
        """
        self._brightness = max(-100, min(100, int(round(float(v)))))
        if self._mpv is not None and not self._is_shut_down:
            try:
                if self._brightness == 0:
                    self._mpv["vf"] = ""
                else:
                    bf = self._brightness / 200.0
                    self._mpv["vf"] = f"lavfi=[eq=brightness={bf:.4f}]"
                try:
                    self._mpv.command("show-text", f"Brightness: {self._brightness}")
                except Exception:
                    pass
            except Exception:
                pass
        return self._brightness

    def get_brightness(self) -> int:
        """Get current video display brightness.

        Returns:
            Brightness level between -100 and 100 (default 0).
        """
        return self._brightness

    def adjust_brightness(self, delta: int | float) -> int:
        """Adjust video brightness by delta.

        Args:
            delta: Positive or negative brightness adjustment.

        Returns:
            New brightness level.
        """
        return self.set_brightness(self.get_brightness() + delta)

    def mousePressEvent(self, event: Any) -> None:
        """Handle Qt mouse press event on widget."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        """Handle Qt mouse double-click event on widget."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def stop(self) -> None:
        """Stop playback of the current media file."""
        if self._mpv is not None and not self._is_shut_down:
            try:
                self._mpv.stop()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Terminate the mpv backend cleanly without crashing."""
        self._is_shut_down = True
        if self._mpv is not None:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None

    def closeEvent(self, event: Any) -> None:
        """Handle Qt widget close event."""
        self.shutdown()
        super().closeEvent(event)


# Backward-compatibility alias
MPVWidget = MpvWidget

__all__ = ["MpvWidget", "MPVWidget"]
