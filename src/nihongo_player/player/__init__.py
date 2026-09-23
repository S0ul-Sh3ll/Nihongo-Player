"""Player package for media playback and MPV integration."""

from nihongo_player.player.libmpv_loader import ensure_libmpv
from nihongo_player.player.mpv_widget import MPVWidget, MpvWidget
from nihongo_player.player.timeline import TimelineController, TimelineWidget, format_time

__all__ = [
    "MpvWidget",
    "MPVWidget",
    "TimelineWidget",
    "TimelineController",
    "ensure_libmpv",
    "format_time",
]
