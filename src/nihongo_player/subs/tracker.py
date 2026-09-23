"""Subtitle cue indexer and timestamp tracker."""

from __future__ import annotations

import bisect
from typing import Iterator, Sequence

from nihongo_player.subs.loader import Cue


class CueTracker:
    """Tracks active and surrounding subtitle cues using binary search indexing.

    Semantics rationale:
        LEFT ARROW = "rewind to the start of the line I just heard and study it":
        app seeks to prev_cue(t).start and pauses; pressing LEFT again (now at that start)
        naturally walks one line further back because the comparison is STRICTLY < t.
        RIGHT ARROW = skip to next line via next_cue(t).start.
    """

    def __init__(self, cues: Sequence[Cue] | None = None) -> None:
        """Initialize tracker with a sequence of subtitle cues.

        Args:
            cues: Sequence of Cue instances.
        """
        self._cues: list[Cue] = sorted(cues, key=lambda c: (c.start, c.end)) if cues else []
        self._starts: list[float] = [c.start for c in self._cues]

    @property
    def cues(self) -> list[Cue]:
        """Return the sorted list of tracked cues."""
        return self._cues

    def __len__(self) -> int:
        return len(self._cues)

    def __getitem__(self, idx: int) -> Cue:
        return self._cues[idx]

    def __iter__(self) -> Iterator[Cue]:
        return iter(self._cues)

    def set_cues(self, cues: Sequence[Cue]) -> None:
        """Update the tracked cues list.

        Args:
            cues: Sequence of Cue instances.
        """
        self._cues = sorted(cues, key=lambda c: (c.start, c.end))
        self._starts = [c.start for c in self._cues]

    def active_cue(self, t: float) -> Cue | None:
        """Find the active cue spanning timestamp t (start <= t < end).

        If multiple cues overlap at timestamp t, returns the latest starting one.

        Args:
            t: Playback timestamp in seconds.

        Returns:
            Active Cue if found, otherwise None.
        """
        if not self._cues:
            return None

        # Rightmost cue with start <= t
        idx = bisect.bisect_right(self._starts, t) - 1
        if idx < 0:
            return None

        # Check latest starting cue first, then step backwards if earlier overlapping cue spans t
        for k in range(idx, -1, -1):
            c = self._cues[k]
            if c.start <= t < c.end:
                return c
        return None

    def last_started(self, t: float) -> Cue | None:
        """Find the cue with the greatest start timestamp <= t.

        Args:
            t: Playback timestamp in seconds.

        Returns:
            Cue with greatest start <= t, or None if none have started.
        """
        if not self._cues:
            return None

        idx = bisect.bisect_right(self._starts, t) - 1
        if 0 <= idx < len(self._cues):
            return self._cues[idx]
        return None

    def prev_cue(self, t: float) -> Cue | None:
        """Find the cue with the greatest start timestamp STRICTLY < t (LEFT ARROW target).

        Args:
            t: Playback timestamp in seconds.

        Returns:
            Cue with greatest start < t, or None.
        """
        if not self._cues:
            return None

        idx = bisect.bisect_left(self._starts, t) - 1
        if 0 <= idx < len(self._cues):
            return self._cues[idx]
        return None

    def next_cue(self, t: float) -> Cue | None:
        """Find the cue with the smallest start timestamp STRICTLY > t (RIGHT ARROW target).

        Args:
            t: Playback timestamp in seconds.

        Returns:
            Cue with smallest start > t, or None.
        """
        if not self._cues:
            return None

        idx = bisect.bisect_right(self._starts, t)
        if 0 <= idx < len(self._cues):
            return self._cues[idx]
        return None

    def index_of(self, cue: Cue) -> int:
        """Return the sequential index of a cue within this tracker.

        Args:
            cue: The Cue object to locate.

        Returns:
            Zero-based integer index of the cue.

        Raises:
            ValueError: If the cue is not present in this tracker.
        """
        if 0 <= cue.index < len(self._cues) and self._cues[cue.index] == cue:
            return cue.index
        return self._cues.index(cue)

    # Backwards compatibility methods
    def find_cue_at(self, timestamp: float) -> Cue | None:
        """Find cue active at timestamp (alias for active_cue)."""
        return self.active_cue(timestamp)

    def find_next_cue(self, timestamp: float) -> Cue | None:
        """Find next cue starting after timestamp (alias for next_cue)."""
        return self.next_cue(timestamp)

    def find_previous_cue(self, timestamp: float, threshold: float = 0.5) -> Cue | None:
        """Find preceding cue or rewind current cue if past threshold."""
        active = self.active_cue(timestamp)
        if active and (timestamp - active.start) > threshold:
            return active
        return self.prev_cue(timestamp)


SubtitleTracker = CueTracker
