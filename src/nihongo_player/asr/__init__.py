"""Automatic Speech Recognition (ASR) subtitle generation module."""

from nihongo_player.asr.subgen import (
    ASR_MODE_PRESETS,
    ASR_MODEL_PRESETS,
    DEFAULT_ASR_MODE,
    DEFAULT_MODEL_NAME,
    DEFAULT_TEXT_MODEL,
    DEFAULT_TIMING_MODEL,
    DEFAULT_WINDOW_SECONDS,
    SubtitleGenerator,
    get_default_output_path,
    is_available,
    merge_coverage_cues,
    post_process_cues,
    segments_to_srt,
    srt_timestamp,
)

__all__ = [
    "ASR_MODE_PRESETS",
    "ASR_MODEL_PRESETS",
    "DEFAULT_ASR_MODE",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_TEXT_MODEL",
    "DEFAULT_TIMING_MODEL",
    "DEFAULT_WINDOW_SECONDS",
    "SubtitleGenerator",
    "get_default_output_path",
    "is_available",
    "merge_coverage_cues",
    "post_process_cues",
    "segments_to_srt",
    "srt_timestamp",
]
