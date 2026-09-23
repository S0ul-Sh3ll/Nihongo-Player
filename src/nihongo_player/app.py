"""CLI and main application window entrypoint for Nihongo Player."""

from __future__ import annotations

import argparse
import locale
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from nihongo_player import __version__
from nihongo_player.asr.subgen import ASR_MODEL_PRESETS, DEFAULT_MODEL_NAME
from nihongo_player.export import (
    build_frequency_list,
    export_anki_apkg,
    export_anki_tsv,
    export_pdf,
    translate_examples,
)
from nihongo_player.ja.annotate import annotate_cue
from nihongo_player.mt.translator import Translator
from nihongo_player.player.libmpv_loader import ensure_libmpv
from nihongo_player.player.mpv_widget import MpvWidget
from nihongo_player.player.timeline import TimelineWidget
from nihongo_player.resources import asset_path, get_app_icon
from nihongo_player.setup.first_run import ensure_resources
from nihongo_player.subs.loader import Cue, find_sidecar_subtitle, load_subtitles
from nihongo_player.subs.tracker import CueTracker
from nihongo_player.ui.overlay import SubtitleOverlay
from nihongo_player.ui.progress_dialog import CircularProgressDialog
from nihongo_player.ui.study_panel import StudyPanel


class ExportWorker(QThread):
    """Background worker thread extracting vocabulary, translating examples, and exporting to PDF/Anki."""

    progress = Signal(int, str)  # pct (0..100), status_message
    finished = Signal(str)  # exported file path
    error = Signal(str)  # error message
    canceled = Signal()

    # Aliases
    finished_success = finished
    failed = error
    cancelled = canceled

    def __init__(
        self,
        cues: Sequence[Any],
        export_type: str,
        out_path: str | Path,
        translator: Translator | None = None,
        source_name: str = "",
        deck_name: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cues = list(cues)
        self._export_type = export_type.lower()
        self._out_path = Path(out_path)
        self._translator = translator
        self._source_name = source_name
        self._deck_name = deck_name
        self._is_cancelled = False
        self.word_count = 0

    def cancel(self) -> None:
        """Signal worker to cancel execution."""
        self._is_cancelled = True

    def run(self) -> None:
        """Execute extraction, translation, and export in background."""
        try:
            if self._is_cancelled:
                self.canceled.emit()
                return

            self.progress.emit(5, "Preparing vocabulary…")
            entries = build_frequency_list(self._cues)
            if self._is_cancelled:
                self.canceled.emit()
                return

            if not entries:
                self.error.emit("No vocabulary entries found.")
                return

            self.word_count = len(entries)

            has_translator = (
                self._translator is not None
                and (not hasattr(self._translator, "is_available") or self._translator.is_available())
            )
            if has_translator:
                self.progress.emit(10, "Translating examples… 0%")

                def _prog_cb(done: int, total: int) -> None:
                    if total > 0:
                        pct = int(round(10 + (done / total) * 75))
                        done_pct = int(round((done / total) * 100))
                        self.progress.emit(pct, f"Translating examples… {done_pct}%")
                    else:
                        self.progress.emit(10, "Translating examples…")

                def _cancel_cb() -> bool:
                    return self._is_cancelled

                translate_examples(
                    entries,
                    self._translator,
                    progress_cb=_prog_cb,
                    cancel_cb=_cancel_cb,
                )
            else:
                self.progress.emit(60, "Writing file…")

            if self._is_cancelled:
                self.canceled.emit()
                return

            self.progress.emit(90, "Writing file…")

            if self._export_type == "pdf":
                export_pdf(entries, self._out_path, source_name=self._source_name)
            elif self._export_type == "apkg":
                deck_title = self._deck_name or "Nihongo Player Vocab"
                export_anki_apkg(entries, self._out_path, deck_name=deck_title)
            elif self._export_type == "tsv":
                export_anki_tsv(entries, self._out_path)
            else:
                raise ValueError(f"Unknown export type: {self._export_type}")

            if self._is_cancelled:
                self.canceled.emit()
                return

            self.progress.emit(100, "Complete!")
            self.finished.emit(str(self._out_path))

        except Exception as err:
            if self._is_cancelled:
                self.canceled.emit()
            else:
                self.error.emit(str(err))


class TranslationWorker(QThread):
    """Background worker thread translating all subtitle cues using CTranslate2."""

    progress = Signal(int, int)  # current, total
    cue_translated = Signal(int, str)  # cue_index, translation_text
    finished_all = Signal()

    def __init__(
        self,
        cues: Sequence[Cue],
        translator: Translator,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cues = list(cues)
        self._translator = translator
        self._is_cancelled = False

    def cancel(self) -> None:
        """Signal worker to stop processing."""
        self._is_cancelled = True

    def run(self) -> None:
        """Translate cues in small batches with sleeps between to avoid saturating CPU."""
        if not self._translator.is_available() or not self._cues:
            self.finished_all.emit()
            return

        total = len(self._cues)
        chunk_size = 8

        for i in range(0, total, chunk_size):
            if self._is_cancelled:
                break
            chunk = self._cues[i : i + chunk_size]
            texts = [c.text for c in chunk]
            translations = self._translator.translate_many(texts)

            for cue_obj, trans_text in zip(chunk, translations):
                if self._is_cancelled:
                    break
                self.cue_translated.emit(cue_obj.index, trans_text)

            self.progress.emit(min(total, i + len(chunk)), total)
            self.msleep(15)

        self.finished_all.emit()


class AsrWorker(QThread):
    """Background worker thread generating Japanese subtitles from video audio using faster-whisper."""

    progress = Signal(float, float)  # done_seconds, total_seconds
    status_changed = Signal(str)  # status message
    finished_success = Signal(str)  # produced srt path
    failed = Signal(str)  # error message
    cancelled = Signal()

    def __init__(
        self,
        media_path: str,
        generator: Any | None = None,
        out_srt_path: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_path = media_path
        if generator is None:
            from nihongo_player.asr.subgen import SubtitleGenerator

            self._generator = SubtitleGenerator()
        else:
            self._generator = generator
        self._out_srt_path = out_srt_path
        self._is_cancelled = False

    @property
    def mode(self) -> str:
        """Active subtitle generator pipeline mode ('hybrid', 'coverage', or 'single')."""
        return getattr(self._generator, "mode", "hybrid")

    def cancel(self) -> None:
        """Signal worker to stop processing."""
        self._is_cancelled = True

    def run(self) -> None:
        """Generate subtitles in background and emit progress and results."""
        try:
            if self.mode == "hybrid":
                self.status_changed.emit("Analyzing timing… 0%")
            elif self.mode == "coverage":
                self.status_changed.emit("Transcribing all audio (max coverage)… 0%")
            else:
                self.status_changed.emit("Loading speech model…")

            def _status_cb(msg: str) -> None:
                self.status_changed.emit(msg)

            def _progress_cb(done_s: float, total_s: float) -> None:
                self.progress.emit(done_s, total_s)

            def _cancel_cb() -> bool:
                return self._is_cancelled

            srt_path = self._generator.generate(
                media_path=self._media_path,
                out_srt_path=self._out_srt_path,
                language="ja",
                progress_cb=_progress_cb,
                cancel_cb=_cancel_cb,
                status_cb=_status_cb,
            )
            if self._is_cancelled:
                self.cancelled.emit()
            else:
                self.finished_success.emit(srt_path)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as err:
            if self._is_cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit(str(err))
        finally:
            if hasattr(self._generator, "release_model"):
                try:
                    self._generator.release_model()
                except Exception:
                    pass
            elif hasattr(self._generator, "_model"):
                self._generator._model = None
            self._generator = None



class MainWindow(QMainWindow):
    """Main Nihongo Player application window integrating video, subtitles, furigana, and study mode."""

    def __init__(
        self,
        media_path: str | Path | None = None,
        subtitle_path: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize main window, embedded mpv player, overlay, study panel, and menus.

        Args:
            media_path: Optional initial video/audio file path to open.
            subtitle_path: Optional explicit subtitle file path.
            parent: Optional parent QWidget.
        """
        super().__init__(parent)
        self.setWindowTitle("Nihongo Player")
        self.setWindowIcon(get_app_icon())
        self.resize(1024, 640)
        self.setMinimumSize(480, 320)

        self._current_file: str | None = None
        self._current_sub_file: str | None = None
        self.tracker: CueTracker | None = None
        self._trans: dict[int, str] = {}
        self._studying: Cue | None = None
        self.translator = Translator()
        self._translation_worker: TranslationWorker | None = None
        self._asr_worker: AsrWorker | None = None
        self._asr_info_dialog: QMessageBox | None = None
        self._progress_dialog: CircularProgressDialog | None = None
        self._export_worker: ExportWorker | None = None
        self._export_progress_dialog: CircularProgressDialog | None = None
        self._last_active_cue_index: int | None = None

        # State tracking for companion window visibility
        self._overlay_was_visible: bool = False
        self._study_was_visible: bool = False
        self._progress_was_visible: bool = False
        self._open_menu_count: int = 0
        self._dialog_open: bool = False

        # Settings state defaults
        self._furigana_visible: bool = True
        self._color_kanji: bool = True
        self._font_scale: float = 1.0
        self._subtitle_time_offset: float = 0.0
        self._mt_enabled: bool = True
        self._playback_speed: float = 1.0
        self._asr_mode: str = "coverage"
        self._asr_model: str = DEFAULT_MODEL_NAME

        self._setup_ui()
        self._setup_menus()
        self._setup_shortcuts()
        self.load_settings()

        # Connect application focus changes to hide top-level companion windows when losing focus
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.applicationStateChanged.connect(self._on_application_state_changed)

        # Non-blocking resource diagnostics
        self._report = ensure_resources()

        # Timer safety net to keep companion windows aligned during dragging/resizing
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(200)
        self._sync_timer.timeout.connect(self._sync_companion_windows)
        self._sync_timer.start()

        if media_path:
            self.open_file(str(media_path), subtitle_path=subtitle_path)

    def _is_text_input_focused(self) -> bool:
        """Check if any text input widget currently has keyboard focus."""
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit

        focus_w = QApplication.focusWidget()
        return isinstance(focus_w, (QLineEdit, QTextEdit, QPlainTextEdit))

    def _setup_ui(self) -> None:
        """Build central layout containing player widget, overlay, study panel, and timeline."""
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Core video player widget
        self.mpv_widget = MpvWidget(central)
        layout.addWidget(self.mpv_widget, stretch=1)

        # Subtitle overlay top-level companion window
        self.overlay = SubtitleOverlay(self)
        self.overlay.hide()

        # Study panel top-level companion window
        self.study_panel = StudyPanel(self)
        self.study_panel.hide()
        self.study_panel.closed.connect(self._on_study_panel_closed)

        # Connect position and pause observers
        self.mpv_widget.position_changed.connect(self._on_position_changed)
        self.mpv_widget.pause_changed.connect(self._on_pause_changed)

        # Connect overlay mouse clicks for play/pause and fullscreen
        self.overlay.clicked.connect(self.mpv_widget.toggle_pause)
        self.overlay.double_clicked.connect(self.toggle_fullscreen)

        # Transport bar (play/pause, prev/next line, seek, time, volume, speed)
        self.timeline = TimelineWidget(central)
        self.timeline.connect_player(self.mpv_widget)
        self.timeline.speed_changed.connect(self.set_playback_speed)
        self.timeline.prev_line_requested.connect(self._on_prev_line)
        self.timeline.next_line_requested.connect(self._on_next_line)
        layout.addWidget(self.timeline, stretch=0)

        self.setCentralWidget(central)
        self.statusBar()  # Ensure status bar exists

    def _setup_menus(self) -> None:
        """Construct application menu bar."""
        menu_bar = self.menuBar()

        # File Menu
        file_menu = menu_bar.addMenu("&File")

        open_action = QAction("&Open Video...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_action)

        open_sub_action = QAction("Open &Subtitle...", self)
        open_sub_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        open_sub_action.triggered.connect(self.open_subtitle_dialog)
        file_menu.addAction(open_sub_action)

        generate_sub_action = QAction("Generate &Japanese Subtitles (AI)…", self)
        generate_sub_action.triggered.connect(self.generate_subtitles_ai)
        file_menu.addAction(generate_sub_action)
        self._generate_sub_action = generate_sub_action

        # Speech Recognition Model submenu
        asr_menu = file_menu.addMenu("Speech &Recognition Model")
        self._asr_menu = asr_menu
        self._asr_group = QActionGroup(self)
        self._asr_group.setExclusive(True)
        self._asr_actions: dict[str, QAction] = {}

        mode_presets = [
            (
                "coverage",
                "Maximum coverage — catches all lines incl. over music (default)",
                "Transcribes the whole audio in fixed windows so nothing is missed (incl. shouts over music); timing is ~window-granular and it may include some sound effects.",
                "coverage",
                None,
            ),
            (
                "hybrid",
                "Accurate — anime + kotoba hybrid (slower)",
                "Best accuracy with correct timing; downloads two models on first use (~600MB + ~768MB), transcribes twice so it's slower.",
                "hybrid",
                None,
            ),
            (
                "kotoba-tech/kotoba-whisper-v2.0-faster",
                "Fast — kotoba only",
                "Downloads on first use (cached offline afterward).",
                "single",
                "kotoba-tech/kotoba-whisper-v2.0-faster",
            ),
            (
                "quantumcookie/anime-whisper-ct2-int8",
                "Anime only (experimental timing)",
                "Best word accuracy but timing is coarse in this build.",
                "single",
                "quantumcookie/anime-whisper-ct2-int8",
            ),
            (
                "Systran/faster-whisper-large-v3",
                "High accuracy — large-v3 (~3GB, slow)",
                "Downloads on first use (cached offline afterward).",
                "single",
                "Systran/faster-whisper-large-v3",
            ),
        ]

        for key, label, tip, mode, model_id in mode_presets:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(key)
            act.setToolTip(tip)
            act.setStatusTip(tip)
            act.triggered.connect(
                lambda checked=False, m=mode, mid=model_id: self.set_asr_mode(m, mid)
            )
            self._asr_group.addAction(act)
            asr_menu.addAction(act)
            self._asr_actions[key] = act

        asr_menu.addSeparator()
        self._asr_custom_action = QAction("Custom (set NIHONGO_WHISPER_MODEL)…", self)
        self._asr_custom_action.setCheckable(True)
        self._asr_custom_action.setEnabled(False)
        self._asr_group.addAction(self._asr_custom_action)
        asr_menu.addAction(self._asr_custom_action)

        file_menu.addSeparator()

        export_pdf_action = QAction("Export Vocabulary to &PDF…", self)
        export_pdf_action.triggered.connect(self.export_vocabulary_pdf)
        file_menu.addAction(export_pdf_action)
        self._export_pdf_action = export_pdf_action

        export_anki_action = QAction("Export Vocabulary to &Anki…", self)
        export_anki_action.triggered.connect(self.export_vocabulary_anki)
        file_menu.addAction(export_anki_action)
        self._export_anki_action = export_anki_action

        export_tsv_action = QAction("Export Vocabulary to Anki &TSV…", self)
        export_tsv_action.triggered.connect(self.export_vocabulary_tsv)
        file_menu.addAction(export_tsv_action)
        self._export_tsv_action = export_tsv_action

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View Menu
        view_menu = menu_bar.addMenu("&View")

        self._toggle_furigana_action = QAction("Toggle &Furigana (F)", self)
        self._toggle_furigana_action.setCheckable(True)
        self._toggle_furigana_action.setChecked(self._furigana_visible)
        self._toggle_furigana_action.triggered.connect(self.toggle_furigana)
        view_menu.addAction(self._toggle_furigana_action)

        self._toggle_color_kanji_action = QAction("&Color Kanji", self)
        self._toggle_color_kanji_action.setCheckable(True)
        self._toggle_color_kanji_action.setChecked(self._color_kanji)
        self._toggle_color_kanji_action.triggered.connect(self.toggle_color_kanji)
        view_menu.addAction(self._toggle_color_kanji_action)

        view_menu.addSeparator()

        # Aspect Ratio submenu
        aspect_menu = view_menu.addMenu("&Aspect Ratio")
        self._aspect_group = QActionGroup(self)
        self._aspect_group.setExclusive(True)
        self._aspect_actions: dict[str, QAction] = {}

        aspect_options = [
            ("default", "&Default", True),
            ("16:9", "16:&9", False),
            ("4:3", "&4:3", False),
            ("2.35:1", "&2.35:1", False),
            ("stretch", "&Stretch to Window", False),
            ("zoom_fill", "&Zoom to Fill", False),
        ]
        for mode_key, label, default_checked in aspect_options:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(default_checked)
            act.setData(mode_key)
            act.triggered.connect(lambda checked=False, m=mode_key: self.set_aspect_ratio_mode(m))
            self._aspect_group.addAction(act)
            aspect_menu.addAction(act)
            self._aspect_actions[mode_key] = act

        view_menu.addSeparator()

        inc_font_action = QAction("Increase Subtitle &Font (W)", self)
        inc_font_action.setShortcut(QKeySequence("Ctrl+="))
        inc_font_action.triggered.connect(lambda: self.increase_font_scale(0.1))
        view_menu.addAction(inc_font_action)

        dec_font_action = QAction("Decrease Subtitle Font (S)", self)
        dec_font_action.setShortcut(QKeySequence("Ctrl+-"))
        dec_font_action.triggered.connect(lambda: self.decrease_font_scale(0.1))
        view_menu.addAction(dec_font_action)

        view_menu.addSeparator()

        sync_plus_action = QAction("Subtitle Sync &+ (+0.1s)", self)
        sync_plus_action.setShortcut(QKeySequence("Ctrl+Right"))
        sync_plus_action.triggered.connect(lambda: self.nudge_subtitle_offset(0.1))
        view_menu.addAction(sync_plus_action)

        sync_minus_action = QAction("Subtitle Sync &- (-0.1s)", self)
        sync_minus_action.setShortcut(QKeySequence("Ctrl+Left"))
        sync_minus_action.triggered.connect(lambda: self.nudge_subtitle_offset(-0.1))
        view_menu.addAction(sync_minus_action)

        view_menu.addSeparator()

        self._toggle_mt_action = QAction("Enable Sentence &Translation", self)
        self._toggle_mt_action.setCheckable(True)
        self._toggle_mt_action.setChecked(self._mt_enabled)
        self._toggle_mt_action.triggered.connect(self.toggle_mt_enabled)
        view_menu.addAction(self._toggle_mt_action)

        # Store menu references and connect aboutToShow/aboutToHide to manage companion windows
        self._file_menu = file_menu
        self._view_menu = view_menu
        self._aspect_menu = aspect_menu

        for m in (file_menu, asr_menu, view_menu, aspect_menu):
            m.aboutToShow.connect(self._on_menu_about_to_show)
            m.aboutToHide.connect(self._on_menu_about_to_hide)

    def _setup_shortcuts(self) -> None:
        """Configure keyboard shortcuts for playback and study loop controls."""
        # Space: Resume study or toggle play/pause
        shortcut_space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        shortcut_space.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_space.activated.connect(self._on_spacebar)

        # Left: Rewind to previous line + pause + study mode
        shortcut_left = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        shortcut_left.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_left.activated.connect(self._on_left_arrow)

        # Right: Skip to next subtitle line
        shortcut_right = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        shortcut_right.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_right.activated.connect(self._on_right_arrow)

        # Up: Brightness up (+5)
        shortcut_up = QShortcut(QKeySequence(Qt.Key.Key_Up), self)
        shortcut_up.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_up.activated.connect(lambda: not self._is_text_input_focused() and self.adjust_brightness(5))

        # Down: Brightness down (-5)
        shortcut_down = QShortcut(QKeySequence(Qt.Key.Key_Down), self)
        shortcut_down.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_down.activated.connect(lambda: not self._is_text_input_focused() and self.adjust_brightness(-5))

        # Shift+Up: Volume up (+5)
        shortcut_shift_up = QShortcut(QKeySequence("Shift+Up"), self)
        shortcut_shift_up.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_shift_up.activated.connect(lambda: not self._is_text_input_focused() and self.change_volume(5))

        # Shift+Down: Volume down (-5)
        shortcut_shift_down = QShortcut(QKeySequence("Shift+Down"), self)
        shortcut_shift_down.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_shift_down.activated.connect(lambda: not self._is_text_input_focused() and self.change_volume(-5))

        # Video zoom: '+' or '=' => zoom in; '-' => zoom out; '0' => reset zoom + aspect
        shortcut_zoom_plus = QShortcut(QKeySequence(Qt.Key.Key_Plus), self)
        shortcut_zoom_plus.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_zoom_plus.activated.connect(lambda: not self._is_text_input_focused() and self.zoom_in())

        shortcut_zoom_equal = QShortcut(QKeySequence(Qt.Key.Key_Equal), self)
        shortcut_zoom_equal.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_zoom_equal.activated.connect(lambda: not self._is_text_input_focused() and self.zoom_in())

        shortcut_zoom_minus = QShortcut(QKeySequence(Qt.Key.Key_Minus), self)
        shortcut_zoom_minus.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_zoom_minus.activated.connect(lambda: not self._is_text_input_focused() and self.zoom_out())

        shortcut_zoom_zero = QShortcut(QKeySequence(Qt.Key.Key_0), self)
        shortcut_zoom_zero.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_zoom_zero.activated.connect(lambda: not self._is_text_input_focused() and self.reset_zoom_and_aspect())

        # Primary subtitle size: W (increase), S (decrease)
        shortcut_w = QShortcut(QKeySequence(Qt.Key.Key_W), self)
        shortcut_w.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_w.activated.connect(lambda: not self._is_text_input_focused() and self.increase_font_scale(0.1))

        shortcut_s = QShortcut(QKeySequence(Qt.Key.Key_S), self)
        shortcut_s.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_s.activated.connect(lambda: not self._is_text_input_focused() and self.decrease_font_scale(0.1))

        # F: Toggle furigana
        shortcut_f = QShortcut(QKeySequence(Qt.Key.Key_F), self)
        shortcut_f.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_f.activated.connect(lambda: not self._is_text_input_focused() and self.toggle_furigana())

        # F11: Toggle fullscreen
        shortcut_f11 = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        shortcut_f11.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_f11.activated.connect(self.toggle_fullscreen)

        # Secondary subtitle font scaling: Ctrl++ / Ctrl+= / Ctrl+-
        shortcut_sub_inc1 = QShortcut(QKeySequence("Ctrl++"), self)
        shortcut_sub_inc1.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_sub_inc1.activated.connect(lambda: self.increase_font_scale(0.1))

        shortcut_sub_inc2 = QShortcut(QKeySequence("Ctrl+="), self)
        shortcut_sub_inc2.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_sub_inc2.activated.connect(lambda: self.increase_font_scale(0.1))

        shortcut_sub_dec = QShortcut(QKeySequence("Ctrl+-"), self)
        shortcut_sub_dec.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_sub_dec.activated.connect(lambda: self.decrease_font_scale(0.1))

        # Subtitle sync nudge: ',' => -0.1s (earlier), '.' => +0.1s (later)
        shortcut_comma = QShortcut(QKeySequence(Qt.Key.Key_Comma), self)
        shortcut_comma.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_comma.activated.connect(lambda: not self._is_text_input_focused() and self.nudge_subtitle_offset(-0.1))

        shortcut_period = QShortcut(QKeySequence(Qt.Key.Key_Period), self)
        shortcut_period.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_period.activated.connect(lambda: not self._is_text_input_focused() and self.nudge_subtitle_offset(0.1))

        # Esc: Leave fullscreen or hide study panel
        shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_esc.activated.connect(self._on_escape)

        # O: Open file dialog
        shortcut_o = QShortcut(QKeySequence(Qt.Key.Key_O), self)
        shortcut_o.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_o.activated.connect(self.open_file_dialog)

        # Q: Quit application
        shortcut_q = QShortcut(QKeySequence(Qt.Key.Key_Q), self)
        shortcut_q.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut_q.activated.connect(self.close)

    def load_settings(self) -> None:
        """Load persistent application settings from QSettings."""
        settings = QSettings("nihongo-player", "nihongo-player")

        # Furigana visibility
        furigana_val = settings.value("furigana_visible", True)
        if isinstance(furigana_val, str):
            self._furigana_visible = furigana_val.lower() in ("true", "1", "yes")
        else:
            self._furigana_visible = bool(furigana_val)
        self.overlay.set_furigana_visible(self._furigana_visible)
        if hasattr(self, "_toggle_furigana_action"):
            self._toggle_furigana_action.setChecked(self._furigana_visible)

        # Color kanji
        color_kanji_val = settings.value("color_kanji", True)
        if isinstance(color_kanji_val, str):
            self._color_kanji = color_kanji_val.lower() in ("true", "1", "yes")
        else:
            self._color_kanji = bool(color_kanji_val)
        self.overlay.set_kanji_colored(self._color_kanji)
        self.study_panel.set_kanji_colored(self._color_kanji)
        if hasattr(self, "_toggle_color_kanji_action"):
            self._toggle_color_kanji_action.setChecked(self._color_kanji)

        # Subtitle font scale (check subtitle_font_scale, fallback to font_scale)
        font_scale_val = settings.value("subtitle_font_scale")
        if font_scale_val is None:
            font_scale_val = settings.value("font_scale", 1.0)
        try:
            self._font_scale = float(font_scale_val)
            self._font_scale = max(0.5, min(3.0, self._font_scale))
        except (ValueError, TypeError):
            self._font_scale = 1.0
        self.overlay.set_font_scale(self._font_scale)
        self.study_panel.set_font_scale(self._font_scale)

        # Subtitle time offset
        try:
            self._subtitle_time_offset = float(settings.value("subtitle_time_offset", 0.0))
        except (ValueError, TypeError):
            self._subtitle_time_offset = 0.0

        # Machine Translation enabled
        mt_val = settings.value("mt_enabled", True)
        if isinstance(mt_val, str):
            self._mt_enabled = mt_val.lower() in ("true", "1", "yes")
        else:
            self._mt_enabled = bool(mt_val)
        if hasattr(self, "_toggle_mt_action"):
            self._toggle_mt_action.setChecked(self._mt_enabled)

        # Playback speed
        try:
            self._playback_speed = float(settings.value("playback_speed", 1.0))
            self._playback_speed = max(0.5, min(2.0, self._playback_speed))
        except (ValueError, TypeError):
            self._playback_speed = 1.0
        self.mpv_widget.set_speed(self._playback_speed)
        self.timeline.set_speed(self._playback_speed)

        # Volume
        try:
            vol = int(float(settings.value("volume", 100)))
            vol = max(0, min(100, vol))
        except (ValueError, TypeError):
            vol = 100
        self.mpv_widget.set_volume(vol)
        self.timeline.set_volume(vol)

        # Window geometry
        geom = settings.value("geometry")
        if geom is not None:
            if isinstance(geom, (bytes, bytearray)):
                self.restoreGeometry(QByteArray(geom))
            elif hasattr(geom, "data") or hasattr(geom, "toByteArray"):
                self.restoreGeometry(geom)

        # ASR mode and model selection
        saved_mode = settings.value("asr_mode")
        if saved_mode and isinstance(saved_mode, str) and saved_mode.strip():
            self._asr_mode = saved_mode.strip().lower()
        else:
            self._asr_mode = "coverage"

        saved_asr = settings.value("asr_model")
        if saved_asr and isinstance(saved_asr, str) and saved_asr.strip():
            self._asr_model = saved_asr.strip()
        else:
            self._asr_model = DEFAULT_MODEL_NAME
        self._update_asr_menu_state()

    def save_settings(self) -> None:
        """Persist current application settings and geometry to QSettings."""
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("furigana_visible", self._furigana_visible)
        settings.setValue("color_kanji", self._color_kanji)
        settings.setValue("subtitle_font_scale", self._font_scale)
        settings.setValue("font_scale", self._font_scale)
        settings.setValue("subtitle_time_offset", self._subtitle_time_offset)
        settings.setValue("mt_enabled", self._mt_enabled)
        settings.setValue("playback_speed", self._playback_speed)
        settings.setValue("volume", int(self.mpv_widget.get_volume()))
        settings.setValue("asr_mode", getattr(self, "_asr_mode", "coverage"))
        settings.setValue("asr_model", getattr(self, "_asr_model", DEFAULT_MODEL_NAME))
        settings.setValue("geometry", self.saveGeometry())

    def _get_asr_mode_info(self, key: str) -> tuple[str, str]:
        """Look up display label and size string for a given ASR mode/preset key."""
        presets = [
            ("coverage", "Maximum coverage — catches all lines incl. over music (default)", "~768MB"),
            ("hybrid", "Accurate — anime + kotoba hybrid (slower)", "~1.4GB"),
            ("kotoba-tech/kotoba-whisper-v2.0-faster", "Fast — kotoba only", "~600MB"),
            ("quantumcookie/anime-whisper-ct2-int8", "Anime only (experimental timing)", "~768MB"),
            ("Systran/faster-whisper-large-v3", "High accuracy — large-v3 (~3GB, slow)", "~3GB"),
        ]
        for k, label, size_str in presets:
            if k == key:
                return label, size_str
        for mid, label, size_str in ASR_MODEL_PRESETS:
            if mid == key:
                return label, size_str
        return key, "size varies"

    def _get_asr_model_info(self, model_id: str) -> tuple[str, str]:
        """Look up display label and size string for a given ASR model ID."""
        return self._get_asr_mode_info(model_id)

    def _selected_asr_mode(self) -> str:
        """Resolve active speech recognition mode ('hybrid', 'coverage', or 'single').

        Resolution precedence:
        1. Environment variable NIHONGO_WHISPER_MODE (if set)
        2. Persisted QSettings 'asr_mode'
        3. Default 'coverage'
        """
        env_mode = os.environ.get("NIHONGO_WHISPER_MODE")
        if env_mode and env_mode.strip():
            return env_mode.strip().lower()
        settings = QSettings("nihongo-player", "nihongo-player")
        saved = settings.value("asr_mode")
        if saved and isinstance(saved, str) and saved.strip():
            return saved.strip().lower()
        return getattr(self, "_asr_mode", "coverage") or "coverage"

    def _selected_asr_model(self) -> str:
        """Resolve active single speech recognition model ID.

        Resolution precedence:
        1. Environment variable NIHONGO_WHISPER_MODEL (if set)
        2. Persisted QSettings 'asr_model'
        3. Default DEFAULT_MODEL_NAME ('kotoba-tech/kotoba-whisper-v2.0-faster')
        """
        env_model = os.environ.get("NIHONGO_WHISPER_MODEL")
        if env_model and env_model.strip():
            return env_model.strip()
        settings = QSettings("nihongo-player", "nihongo-player")
        saved = settings.value("asr_model")
        if saved and isinstance(saved, str) and saved.strip():
            return saved.strip()
        return getattr(self, "_asr_model", DEFAULT_MODEL_NAME) or DEFAULT_MODEL_NAME

    def set_asr_mode(self, mode: str, model_id: str | None = None, show_status: bool = True) -> None:
        """Set active speech recognition mode and optional model, persist, and update UI."""
        self._asr_mode = mode
        if model_id is not None:
            self._asr_model = model_id
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("asr_mode", self._asr_mode)
        if model_id is not None:
            settings.setValue("asr_model", self._asr_model)
        self._update_asr_menu_state()

        if show_status:
            env_mode = os.environ.get("NIHONGO_WHISPER_MODE")
            env_model = os.environ.get("NIHONGO_WHISPER_MODEL")
            if mode == "hybrid":
                label, _ = self._get_asr_mode_info("hybrid")
                if env_mode and env_mode.strip():
                    self.statusBar().showMessage(
                        f"Speech mode set to {label}, but overridden by NIHONGO_WHISPER_MODE={env_mode.strip()}.",
                        4000,
                    )
                else:
                    self.statusBar().showMessage(
                        f"Speech mode: {label} — downloads two models on first use (~600MB + ~768MB).",
                        4000,
                    )
            elif mode == "coverage":
                label, size_str = self._get_asr_mode_info("coverage")
                if env_mode and env_mode.strip():
                    self.statusBar().showMessage(
                        f"Speech mode set to {label}, but overridden by NIHONGO_WHISPER_MODE={env_mode.strip()}.",
                        4000,
                    )
                else:
                    self.statusBar().showMessage(
                        f"Speech mode: {label} — transcribes contiguous windows ({size_str}).",
                        4000,
                    )
            else:
                label, size_str = self._get_asr_mode_info(self._asr_model)
                if env_model and env_model.strip():
                    self.statusBar().showMessage(
                        f"Speech model set to {label}, but overridden by NIHONGO_WHISPER_MODEL={env_model.strip()}.",
                        4000,
                    )
                else:
                    self.statusBar().showMessage(
                        f"Speech model: {label} — will download on first use ({size_str}).",
                        4000,
                    )

    def set_asr_model(self, model_id: str, show_status: bool = True) -> None:
        """Set active speech recognition model or hybrid/coverage mode."""
        if model_id == "hybrid":
            self.set_asr_mode("hybrid", show_status=show_status)
        elif model_id == "coverage":
            self.set_asr_mode("coverage", show_status=show_status)
        else:
            self.set_asr_mode("single", model_id=model_id, show_status=show_status)

    def _update_asr_menu_state(self) -> None:
        """Synchronize Speech Recognition Model menu checked state with settings/env."""
        active_mode = self._selected_asr_mode()
        active_model = self._selected_asr_model()
        env_mode = os.environ.get("NIHONGO_WHISPER_MODE")
        env_model = os.environ.get("NIHONGO_WHISPER_MODEL")

        matched = False
        for key, act in getattr(self, "_asr_actions", {}).items():
            if key == "hybrid":
                is_match = (active_mode == "hybrid")
            elif key == "coverage":
                is_match = (active_mode == "coverage")
            else:
                is_match = (active_mode == "single" and key == active_model)

            act.setChecked(is_match)
            if is_match:
                matched = True

            base_tip = act.toolTip()
            if key in ("hybrid", "coverage") and env_mode and env_mode.strip():
                act.setStatusTip(f"{base_tip} [Env override active: NIHONGO_WHISPER_MODE={env_mode.strip()}]")
            elif key not in ("hybrid", "coverage") and env_model and env_model.strip():
                act.setStatusTip(f"{base_tip} [Env override active: NIHONGO_WHISPER_MODEL={env_model.strip()}]")
            else:
                act.setStatusTip(base_tip)

        if hasattr(self, "_asr_custom_action"):
            if env_model and env_model.strip() and not matched and active_mode == "single":
                self._asr_custom_action.setText(f"Custom ({env_model.strip()}) [env active]")
                self._asr_custom_action.setVisible(True)
                self._asr_custom_action.setChecked(True)
            elif env_model and env_model.strip() and active_mode == "single":
                self._asr_custom_action.setText(f"Custom (env active: {env_model.strip()})")
                self._asr_custom_action.setVisible(True)
                self._asr_custom_action.setChecked(False)
            else:
                self._asr_custom_action.setText("Custom (set NIHONGO_WHISPER_MODEL)…")
                self._asr_custom_action.setVisible(False)
                self._asr_custom_action.setChecked(False)

    def set_color_kanji(self, enabled: bool) -> None:
        """Enable or disable kanji accent coloring across overlay and study panel."""
        self._color_kanji = bool(enabled)
        self.overlay.set_kanji_colored(self._color_kanji)
        self.study_panel.set_kanji_colored(self._color_kanji)
        if hasattr(self, "_toggle_color_kanji_action"):
            self._toggle_color_kanji_action.setChecked(self._color_kanji)
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("color_kanji", self._color_kanji)
        self.statusBar().showMessage(
            f"Color Kanji: {'ON' if self._color_kanji else 'OFF'}", 2000
        )

    def toggle_color_kanji(self) -> None:
        """Toggle kanji accent coloring."""
        self.set_color_kanji(not self._color_kanji)

    def set_font_scale(self, scale: float) -> None:
        """Set subtitle font scale factor, update UI, and persist setting."""
        self._font_scale = max(0.5, min(3.0, round(float(scale), 2)))
        self.overlay.set_font_scale(self._font_scale)
        self.study_panel.set_font_scale(self._font_scale)
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("subtitle_font_scale", self._font_scale)
        settings.setValue("font_scale", self._font_scale)
        self.statusBar().showMessage(
            f"Subtitle size: {int(round(self._font_scale * 100))}%", 2000
        )

    def increase_font_scale(self, delta: float = 0.1) -> None:
        """Increase subtitle font scale factor by delta."""
        self.set_font_scale(self._font_scale + delta)

    def decrease_font_scale(self, delta: float = 0.1) -> None:
        """Decrease subtitle font scale factor by delta."""
        self.set_font_scale(self._font_scale - delta)

    def adjust_brightness(self, delta: int) -> None:
        """Adjust video brightness by delta and display in status bar."""
        val = self.mpv_widget.adjust_brightness(delta)
        self.statusBar().showMessage(f"Brightness: {val}", 2000)

    def zoom_in(self) -> None:
        """Zoom video display in."""
        self.mpv_widget.zoom_by(0.1)
        zoom_mult = 2.0 ** self.mpv_widget.get_video_zoom()
        self.statusBar().showMessage(f"Zoom: {zoom_mult:.2f}x", 2000)

    def zoom_out(self) -> None:
        """Zoom video display out."""
        self.mpv_widget.zoom_by(-0.1)
        zoom_mult = 2.0 ** self.mpv_widget.get_video_zoom()
        self.statusBar().showMessage(f"Zoom: {zoom_mult:.2f}x", 2000)

    def reset_zoom_and_aspect(self) -> None:
        """Reset video zoom exponent and aspect ratio to defaults."""
        self.mpv_widget.reset_zoom()
        self.set_aspect_ratio_mode("default")
        if hasattr(self, "_aspect_actions") and "default" in self._aspect_actions:
            self._aspect_actions["default"].setChecked(True)
        self.statusBar().showMessage("Zoom: 1.00x", 2000)

    def set_aspect_ratio_mode(self, mode: str) -> None:
        """Apply aspect ratio preset ('default', '16:9', '4:3', '2.35:1', 'stretch', 'zoom_fill')."""
        mode = mode.lower()
        if mode == "default":
            self.mpv_widget.set_panscan(0.0)
            self.mpv_widget.set_stretch(False)
            self.mpv_widget.set_aspect_override("-1")
            self.statusBar().showMessage("Aspect Ratio: Default", 2000)
        elif mode == "16:9":
            self.mpv_widget.set_panscan(0.0)
            self.mpv_widget.set_stretch(False)
            self.mpv_widget.set_aspect_override("16:9")
            self.statusBar().showMessage("Aspect Ratio: 16:9", 2000)
        elif mode == "4:3":
            self.mpv_widget.set_panscan(0.0)
            self.mpv_widget.set_stretch(False)
            self.mpv_widget.set_aspect_override("4:3")
            self.statusBar().showMessage("Aspect Ratio: 4:3", 2000)
        elif mode == "2.35:1":
            self.mpv_widget.set_panscan(0.0)
            self.mpv_widget.set_stretch(False)
            self.mpv_widget.set_aspect_override("2.35:1")
            self.statusBar().showMessage("Aspect Ratio: 2.35:1", 2000)
        elif mode == "stretch":
            self.mpv_widget.set_panscan(0.0)
            self.mpv_widget.set_aspect_override("-1")
            self.mpv_widget.set_stretch(True)
            self.statusBar().showMessage("Aspect Ratio: Stretch to Window", 2000)
        elif mode == "zoom_fill":
            self.mpv_widget.set_stretch(False)
            self.mpv_widget.set_aspect_override("-1")
            self.mpv_widget.set_panscan(1.0)
            self.statusBar().showMessage("Aspect Ratio: Zoom to Fill", 2000)

        if hasattr(self, "_aspect_actions") and mode in self._aspect_actions:
            self._aspect_actions[mode].setChecked(True)

    def set_playback_speed(self, speed: float | int) -> None:
        """Set playback speed, update player and timeline, and persist setting.

        Args:
            speed: Playback speed multiplier between 0.5 and 2.0.
        """
        self._playback_speed = max(0.5, min(2.0, round(float(speed), 2)))
        self.mpv_widget.set_speed(self._playback_speed)
        self.timeline.set_speed(self._playback_speed)
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("playback_speed", self._playback_speed)
        self.statusBar().showMessage(
            f"Playback speed: {self._playback_speed:.2f}x", 2000
        )

    def set_furigana_visible(self, visible: bool) -> None:
        """Set furigana visibility, update UI, and persist setting."""
        self._furigana_visible = bool(visible)
        self.overlay.set_furigana_visible(self._furigana_visible)
        if hasattr(self, "_toggle_furigana_action"):
            self._toggle_furigana_action.setChecked(self._furigana_visible)
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("furigana_visible", self._furigana_visible)
        self.statusBar().showMessage(
            f"Furigana: {'ON' if self._furigana_visible else 'OFF'}", 2000
        )

    def toggle_furigana(self) -> None:
        """Toggle furigana visibility on subtitle overlay."""
        self.set_furigana_visible(not self._furigana_visible)

    def set_subtitle_time_offset(self, offset: float) -> None:
        """Set subtitle timing synchronization offset in seconds and persist setting."""
        self._subtitle_time_offset = round(offset, 2)
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("subtitle_time_offset", self._subtitle_time_offset)
        msg = f"Subtitle sync offset: {self._subtitle_time_offset:+.1f}s"
        self.statusBar().showMessage(msg, 2000)
        if self.mpv_widget is not None and getattr(self.mpv_widget, "_mpv", None) is not None:
            try:
                self.mpv_widget._mpv.command("show-text", msg)
            except Exception:
                pass
        self._refresh_overlay_now()

    def nudge_subtitle_offset(self, delta: float) -> None:
        """Nudge subtitle timing synchronization offset by delta seconds."""
        self.set_subtitle_time_offset(self._subtitle_time_offset + delta)

    def set_mt_enabled(self, enabled: bool) -> None:
        """Enable or disable neural machine translation."""
        self._mt_enabled = bool(enabled)
        if hasattr(self, "_toggle_mt_action"):
            self._toggle_mt_action.setChecked(self._mt_enabled)
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("mt_enabled", self._mt_enabled)
        self.statusBar().showMessage(
            f"Translation: {'ON' if self._mt_enabled else 'OFF'}", 2000
        )
        if not self._mt_enabled and self._translation_worker is not None and self._translation_worker.isRunning():
            self._translation_worker.cancel()
            self._translation_worker = None
        elif self._mt_enabled and self._current_file and self.tracker is not None and self.translator.is_available():
            if self._translation_worker is None or not self._translation_worker.isRunning():
                self._start_translation_worker()

    def toggle_mt_enabled(self) -> None:
        """Toggle neural machine translation state."""
        self.set_mt_enabled(not self._mt_enabled)

    def _video_global_rect(self) -> QRect:
        """Compute video canvas geometry in global screen coordinates."""
        top_left = self.mpv_widget.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self.mpv_widget.size())

    def _dismiss_study_panel(self) -> None:
        """Dismiss study panel and clear active studying state without altering playback or seeking."""
        if hasattr(self, "study_panel"):
            self.study_panel.hide()
        self._studying = None
        self._study_was_visible = False

    def _hide_overlay(self) -> None:
        """Temporarily hide subtitle overlay window."""
        if hasattr(self, "overlay"):
            self.overlay.hide()

    def _restore_overlay(self) -> None:
        """Restore overlay visibility if video is loaded and application is active."""
        if (
            self.isVisible()
            and not self.isMinimized()
            and not getattr(self, "_app_inactive", False)
            and not getattr(self, "_dialog_open", False)
            and getattr(self, "_open_menu_count", 0) == 0
            and not (
                (self._progress_dialog is not None and self._progress_dialog.isVisible())
                or (self._export_progress_dialog is not None and self._export_progress_dialog.isVisible())
            )
            and (self._current_file is not None or self.overlay.has_content())
        ):
            vrect = self._video_global_rect()
            if vrect.isValid() and vrect.width() > 0 and vrect.height() > 0:
                self.overlay.sync_to(vrect)
            self.overlay.show_over()

    def _on_menu_about_to_show(self) -> None:
        """Handle menu popup: hide furigana overlay and dismiss study panel to avoid covering menus."""
        self._open_menu_count = getattr(self, "_open_menu_count", 0) + 1
        self._dismiss_study_panel()
        self._hide_overlay()

    def _on_menu_about_to_hide(self) -> None:
        """Handle menu dismissal: re-show overlay if video loaded and app active, without reopening study panel."""
        self._open_menu_count = max(0, getattr(self, "_open_menu_count", 0) - 1)
        if self._open_menu_count == 0:
            self._restore_overlay()

    def _sync_companion_windows(self) -> None:
        """Synchronize companion overlay and study panel positions with video geometry."""
        if not self.isVisible() or self.isMinimized() or getattr(self, "_app_inactive", False):
            if self.overlay.isVisible():
                self._overlay_was_visible = True
                self.overlay.hide()
            if self.study_panel.isVisible():
                self._study_was_visible = True
                self.study_panel.hide()
            return

        has_progress = (self._progress_dialog is not None and self._progress_dialog.isVisible()) or (
            self._export_progress_dialog is not None and self._export_progress_dialog.isVisible()
        )
        if has_progress or getattr(self, "_dialog_open", False) or getattr(self, "_open_menu_count", 0) > 0:
            if self.study_panel.isVisible():
                self.study_panel.hide()
                self._studying = None
            if self.overlay.isVisible():
                self.overlay.hide()
            if self._progress_dialog is not None and self._progress_dialog.isVisible():
                self._progress_dialog.raise_()
            if self._export_progress_dialog is not None and self._export_progress_dialog.isVisible():
                self._export_progress_dialog.raise_()
            return

        vrect = self._video_global_rect()
        if vrect.isValid() and vrect.width() > 0 and vrect.height() > 0:
            self.overlay.sync_to(vrect)
            if self._current_file is not None and not self.overlay.isVisible():
                self.overlay.show_over()
            if self.study_panel.isVisible():
                self.study_panel.sync_to(vrect)
                self.study_panel.raise_()

    def _on_study_panel_closed(self) -> None:
        """Handle StudyPanel close (X) button: dismiss panel and clear study state without altering playback."""
        self._dismiss_study_panel()

    def _on_pause_changed(self, paused: bool) -> None:
        """Handle mpv pause/play state changes: dismiss study panel whenever playback resumes."""
        if not paused:
            if self.study_panel.isVisible() or self._studying is not None:
                self._dismiss_study_panel()

    def _refresh_overlay_now(self) -> None:
        """Reset active cue cache and immediately evaluate overlay for current player position."""
        self._last_active_cue_index = None
        pos = self.mpv_widget.position()
        self._on_position_changed(pos)

    def _on_position_changed(self, pos: float) -> None:
        """Update subtitle overlay display with active cue matching playback timestamp."""
        if self.tracker is not None:
            adjusted_pos = pos - self._subtitle_time_offset
            active = self.tracker.active_cue(adjusted_pos)
            if active is not None:
                if active.index == self._last_active_cue_index:
                    return
                self._last_active_cue_index = active.index
                self.overlay.set_cue(active.text)
                if self.isVisible() and not self.isMinimized() and not self.overlay.isVisible():
                    self.overlay.sync_to(self._video_global_rect())
                    self.overlay.show_over()
            else:
                if self._last_active_cue_index is None:
                    return
                self._last_active_cue_index = None
                self.overlay.clear()
        else:
            if self._last_active_cue_index is None:
                return
            self._last_active_cue_index = None
            self.overlay.clear()

    def _study_cue(self, cue: Cue, seek: bool = True) -> None:
        """Enter study mode on the given subtitle cue, optionally seek, and populate study panel.

        Args:
            cue: Target subtitle Cue to study.
            seek: If True, seek to cue.start (adjusted for offset). If False, stay at current position.
        """
        self.mpv_widget.pause()
        if seek:
            self.mpv_widget.seek_absolute(cue.start + self._subtitle_time_offset)

        token_views = annotate_cue(cue.text)
        trans_text: str | None = None

        if self._mt_enabled:
            trans_text = self._trans.get(cue.index)
            # If translation not yet completed in background worker, check fast-cache or translate on-demand
            if trans_text is None and self.translator.is_available():
                with self.translator._lock:
                    if cue.text.strip() in self.translator._cache:
                        trans_text = self.translator._cache[cue.text.strip()]
                        self._trans[cue.index] = trans_text
                if trans_text is None:
                    try:
                        trans_text = self.translator.translate(cue.text)
                        if trans_text:
                            self._trans[cue.index] = trans_text
                    except Exception:
                        trans_text = None
        else:
            trans_text = None

        self.study_panel.populate(
            cue, token_views, trans_text, translation_enabled=self._mt_enabled
        )
        self.overlay.set_cue(cue.text)
        if self.isVisible() and not self.isMinimized():
            vrect = self._video_global_rect()
            self.overlay.sync_to(vrect)
            self.overlay.show_over()
            self.study_panel.sync_to(vrect)
            self.study_panel.show()
            self.study_panel.raise_()
        self._studying = cue

    def _on_left_arrow(self) -> None:
        """Handle Left-Arrow: navigate to previous cue in study mode or enter study mode on previous line."""
        if self.study_panel.isVisible():
            if self.tracker is None or len(self.tracker.cues) == 0:
                return
            if self._studying is not None:
                try:
                    curr_idx = self.tracker.index_of(self._studying)
                    idx = curr_idx - 1
                except ValueError:
                    idx = 0
            else:
                pos = self.mpv_widget.position() - self._subtitle_time_offset
                active = self.tracker.active_cue(pos) or self.tracker.last_started(pos)
                if active is not None:
                    try:
                        idx = self.tracker.index_of(active) - 1
                    except ValueError:
                        idx = 0
                else:
                    idx = 0
            idx = max(0, min(len(self.tracker.cues) - 1, idx))
            self._study_cue(self.tracker.cues[idx], seek=True)
        else:
            if self.tracker is None or len(self.tracker.cues) == 0:
                self.mpv_widget.seek_relative(-5.0)
                return

            pos = self.mpv_widget.position()
            adjusted_pos = pos - self._subtitle_time_offset
            target = self.tracker.prev_cue(adjusted_pos)
            if target is None:
                return
            self._study_cue(target, seek=True)

    def _on_right_arrow(self) -> None:
        """Handle Right-Arrow: navigate to next cue in study mode or skip forward to next line during playback."""
        if self.study_panel.isVisible():
            if self.tracker is None or len(self.tracker.cues) == 0:
                return
            if self._studying is not None:
                try:
                    curr_idx = self.tracker.index_of(self._studying)
                    idx = curr_idx + 1
                except ValueError:
                    idx = len(self.tracker.cues) - 1
            else:
                pos = self.mpv_widget.position() - self._subtitle_time_offset
                active = self.tracker.active_cue(pos) or self.tracker.last_started(pos)
                if active is not None:
                    try:
                        idx = self.tracker.index_of(active) + 1
                    except ValueError:
                        idx = len(self.tracker.cues) - 1
                else:
                    idx = 0
            idx = max(0, min(len(self.tracker.cues) - 1, idx))
            self._study_cue(self.tracker.cues[idx], seek=True)
        else:
            if self.tracker is None or len(self.tracker.cues) == 0:
                self.mpv_widget.seek_relative(5.0)
                return

            pos = self.mpv_widget.position()
            adjusted_pos = pos - self._subtitle_time_offset
            target = self.tracker.next_cue(adjusted_pos)
            if target is not None:
                self.mpv_widget.seek_absolute(target.start + self._subtitle_time_offset)

    def _on_spacebar(self) -> None:
        """Handle Spacebar: toggle playback / study mode.

        - If study panel is visible: dismiss study panel, clear study state, and resume playback.
        - Elif currently playing: pause playback in place (no seek); if active cue exists, show study panel without seeking.
        - Else (paused without study panel): resume playback.
        """
        if self.study_panel.isVisible():
            self.study_panel.hide()
            self._studying = None
            self.mpv_widget.play()
        elif not self.mpv_widget.is_paused():
            self.mpv_widget.pause()
            if self.tracker is not None and len(self.tracker.cues) > 0:
                pos = self.mpv_widget.position()
                adjusted_pos = pos - self._subtitle_time_offset
                cue = self.tracker.active_cue(adjusted_pos)
                if cue is not None:
                    self._study_cue(cue, seek=False)
        else:
            self.mpv_widget.play()

    def _on_prev_line(self) -> None:
        """Seek to start of previous subtitle cue without changing play state or entering study mode."""
        if self.tracker is None or not self.tracker.cues:
            return
        pos = self.mpv_widget.position()
        adjusted_pos = pos - self._subtitle_time_offset
        target = self.tracker.prev_cue(adjusted_pos)
        if target is not None:
            self.mpv_widget.seek_absolute(target.start + self._subtitle_time_offset)

    def _on_next_line(self) -> None:
        """Seek to start of next subtitle cue without changing play state or entering study mode."""
        if self.tracker is None or not self.tracker.cues:
            return
        pos = self.mpv_widget.position()
        adjusted_pos = pos - self._subtitle_time_offset
        target = self.tracker.next_cue(adjusted_pos)
        if target is not None:
            self.mpv_widget.seek_absolute(target.start + self._subtitle_time_offset)

    def _on_escape(self) -> None:
        """Handle Escape: dismiss study panel if open; otherwise exit fullscreen."""
        if self.study_panel.isVisible():
            self._dismiss_study_panel()
        else:
            self.exit_fullscreen()

    def _on_seek_forward(self) -> None:
        """Seek forward wrapper (alias for Right-Arrow)."""
        self._on_right_arrow()

    def _on_seek_backward(self) -> None:
        """Seek backward wrapper (alias for Left-Arrow)."""
        self._on_left_arrow()

    def _reposition_study_panel(self) -> None:
        """Center study panel within the MpvWidget canvas."""
        self.study_panel.sync_to(self._video_global_rect())

    def showEvent(self, event: Any) -> None:
        """Handle show event, synchronizing companion overlays."""
        super().showEvent(event)
        if not self.isMinimized():
            self._sync_companion_windows()
            if getattr(self, "_overlay_was_visible", False) or self._current_file is not None or (self.overlay.has_content() and not self.isMinimized()):
                self.overlay.show_over()
            if getattr(self, "_study_was_visible", False) or (self._studying is not None):
                self.study_panel.show()
                self.study_panel.raise_()

    def moveEvent(self, event: Any) -> None:
        """Handle window move event, repositioning companion windows."""
        super().moveEvent(event)
        self._sync_companion_windows()

    def resizeEvent(self, event: Any) -> None:
        """Handle window resize event, keeping overlay and study panel properly framed."""
        super().resizeEvent(event)
        self._sync_companion_windows()

    def changeEvent(self, event: Any) -> None:
        """Handle window state changes (minimize, restore, fullscreen) and activation."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized() or not self.isVisible():
                self._overlay_was_visible = self.overlay.isVisible()
                self._study_was_visible = self.study_panel.isVisible()
                self._progress_was_visible = any(
                    pd is not None and pd.isVisible()
                    for pd in (self._progress_dialog, self._export_progress_dialog)
                )
                self.overlay.hide()
                self.study_panel.hide()
                for pd in (self._progress_dialog, self._export_progress_dialog):
                    if pd is not None:
                        pd.hide()
            else:
                self._sync_companion_windows()
                if getattr(self, "_overlay_was_visible", False) or self._current_file is not None or self.overlay.has_content():
                    self.overlay.show_over()
                if getattr(self, "_study_was_visible", False) or self._studying is not None:
                    self.study_panel.show()
                    self.study_panel.raise_()
                if getattr(self, "_progress_was_visible", False):
                    for pd in (self._progress_dialog, self._export_progress_dialog):
                        if pd is not None:
                            pd.show()
                            pd.raise_()
                    self._progress_was_visible = False
        elif event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isMinimized():
                self._overlay_was_visible = self.overlay.isVisible()
                self._study_was_visible = self.study_panel.isVisible()
                self._progress_was_visible = any(
                    pd is not None and pd.isVisible()
                    for pd in (self._progress_dialog, self._export_progress_dialog)
                )
                self.overlay.hide()
                self.study_panel.hide()
                for pd in (self._progress_dialog, self._export_progress_dialog):
                    if pd is not None:
                        pd.hide()

    def _on_application_state_changed(self, state: Qt.ApplicationState) -> None:
        """Handle application-level focus gain/loss so top-level companion windows don't float over other apps."""
        if state in (
            Qt.ApplicationState.ApplicationInactive,
            Qt.ApplicationState.ApplicationHidden,
            Qt.ApplicationState.ApplicationSuspended,
        ):
            self._app_inactive = True
            if self.overlay.isVisible():
                self._overlay_was_visible = True
                self.overlay.hide()
            if self.study_panel.isVisible():
                self._study_was_visible = True
                self.study_panel.hide()
            self._progress_was_visible = False
            for pd in (self._progress_dialog, self._export_progress_dialog):
                if pd is not None and pd.isVisible():
                    self._progress_was_visible = True
                    pd.hide()
        elif state == Qt.ApplicationState.ApplicationActive:
            self._app_inactive = False
            if self.isVisible() and not self.isMinimized():
                self._sync_companion_windows()
                if (
                    getattr(self, "_overlay_was_visible", False)
                    or self._current_file is not None
                    or (self.overlay.has_content() and not self.isMinimized())
                ):
                    self.overlay.show_over()
                    self._overlay_was_visible = False
                self._study_was_visible = False
                if getattr(self, "_progress_was_visible", False):
                    for pd in (self._progress_dialog, self._export_progress_dialog):
                        if pd is not None:
                            pd.show()
                            pd.raise_()
                    self._progress_was_visible = False

    def hideEvent(self, event: Any) -> None:
        """Hide companion windows when main window is hidden."""
        self._overlay_was_visible = self.overlay.isVisible()
        self._study_was_visible = self.study_panel.isVisible()
        self._progress_was_visible = any(
            pd is not None and pd.isVisible()
            for pd in (self._progress_dialog, self._export_progress_dialog)
        )
        self.overlay.hide()
        self.study_panel.hide()
        for pd in (self._progress_dialog, self._export_progress_dialog):
            if pd is not None:
                pd.hide()
        super().hideEvent(event)

    def _on_translation_progress(self, current: int, total: int) -> None:
        """Update status bar with background translation progress."""
        self.statusBar().showMessage(f"Translating {current}/{total}…")

    def _on_cue_translated(self, cue_index: int, trans_text: str) -> None:
        """Store translation and update study panel if currently reviewing this cue."""
        self._trans[cue_index] = trans_text
        if self._studying is not None and self._studying.index == cue_index:
            self.study_panel.set_translation(trans_text)

    def _on_translation_finished(self) -> None:
        """Clear translation status message upon batch completion."""
        self.statusBar().clearMessage()

    def change_volume(self, delta: int) -> None:
        """Adjust playback volume by delta percentage.

        Args:
            delta: Positive or negative volume adjustment.
        """
        current_vol = self.mpv_widget.get_volume()
        new_vol = max(0.0, min(100.0, current_vol + delta))
        self.mpv_widget.set_volume(new_vol)
        self.timeline.set_volume(new_vol)
        settings = QSettings("nihongo-player", "nihongo-player")
        settings.setValue("volume", int(new_vol))

    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen display mode."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._sync_companion_windows()

    def exit_fullscreen(self) -> None:
        """Exit fullscreen mode if active."""
        if self.isFullScreen():
            self.showNormal()
            self._sync_companion_windows()

    def _start_translation_worker(self) -> None:
        """Start background translation worker for tracked subtitle cues at low priority."""
        if (
            not self._mt_enabled
            or self.tracker is None
            or not self.tracker.cues
            or not self.translator.is_available()
        ):
            return
        self.statusBar().showMessage(f"Translating 0/{len(self.tracker.cues)}…")
        self._translation_worker = TranslationWorker(
            self.tracker.cues, self.translator, self
        )
        self._translation_worker.progress.connect(self._on_translation_progress)
        self._translation_worker.cue_translated.connect(self._on_cue_translated)
        self._translation_worker.finished_all.connect(self._on_translation_finished)
        self._translation_worker.start(QThread.Priority.LowestPriority)

    def load_subtitle_file(self, path: str | Path) -> bool:
        """Load and track an external Japanese subtitle file (.srt, .ass, .ssa, .vtt), replacing current subtitles.

        Args:
            path: Path to subtitle file.

        Returns:
            True if subtitles loaded successfully, False otherwise.
        """
        p = Path(path).resolve()
        if not p.is_file():
            self.statusBar().showMessage(f"Subtitle file not found: {path}", 3000)
            return False

        # Cancel any ongoing background translation
        if self._translation_worker is not None and self._translation_worker.isRunning():
            self._translation_worker.cancel()
            self._translation_worker.wait(1000)
            self._translation_worker = None

        # Cancel any ongoing ASR subtitle generation
        if self._asr_worker is not None and self._asr_worker.isRunning():
            self._asr_worker.cancel()
            self._asr_worker.wait(1000)
            self._asr_worker = None

        # Cancel any ongoing export worker
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.cancel()
            self._export_worker.wait(1000)
            self._export_worker = None
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None

        self._trans.clear()
        self._studying = None
        self._last_active_cue_index = None
        self.study_panel.hide()

        try:
            cues = load_subtitles(str(p))
            self.tracker = CueTracker(cues)
            self._current_sub_file = str(p)
        except Exception as err:
            self.tracker = None
            self._current_sub_file = None
            self.statusBar().showMessage(f"Failed to load subtitles: {err}", 3000)
            return False

        # Refresh overlay immediately for current position
        self._refresh_overlay_now()

        # Start background translation worker if model is available and MT is enabled
        if (
            self._mt_enabled
            and self.tracker is not None
            and self.translator.is_available()
            and len(self.tracker.cues) > 0
        ):
            self._start_translation_worker()

        self.statusBar().showMessage(f"Loaded {len(self.tracker.cues)} subtitles from {p.name}", 3000)
        return True

    def generate_subtitles_ai(self) -> None:
        """Trigger AI speech-to-text Japanese subtitle generation for the current video."""
        self._dismiss_study_panel()
        self._hide_overlay()

        from nihongo_player.asr.subgen import is_available as asr_is_available

        if not asr_is_available():
            self.statusBar().showMessage(
                "faster-whisper is not installed. Run: pip install -e .[asr]", 5000
            )
            dialog = QMessageBox(
                QMessageBox.Icon.Information,
                "AI Subtitles Unavailable",
                "faster-whisper is required for AI subtitle generation.\n\n"
                "To enable this feature, install the optional dependency:\n"
                "  pip install faster-whisper\n"
                "  (or: pip install -e .[asr])",
                QMessageBox.StandardButton.Ok,
                self,
            )
            dialog.setModal(False)
            dialog.show()
            self._asr_info_dialog = dialog
            return

        if not self._current_file:
            self.statusBar().showMessage(
                "No video loaded to generate subtitles for.", 4000
            )
            self._restore_overlay()
            return

        if self._asr_worker is not None and self._asr_worker.isRunning():
            self.statusBar().showMessage(
                "Subtitle generation already in progress…", 3000
            )
            self._restore_overlay()
            return

        self.statusBar().showMessage("Generating subtitles… 0%")

        selected_mode = self._selected_asr_mode()
        selected_model = self._selected_asr_model()

        # Show non-blocking circular progress popup
        self._progress_dialog = CircularProgressDialog(
            parent=self,
            title="Generating Japanese Subtitles (AI)…",
            cancellable=True,
        )
        self._progress_dialog.canceled.connect(self.cancel_asr)
        self._progress_dialog.set_progress(0.0)
        if selected_mode == "hybrid":
            self._progress_dialog.set_label("Analyzing timing… 0%")
        elif selected_mode == "coverage":
            self._progress_dialog.set_label("Transcribing all audio (max coverage)… 0%")
        else:
            self._progress_dialog.set_label("Loading speech model…")
        self._progress_dialog.show()

        from nihongo_player.asr.subgen import SubtitleGenerator

        generator = SubtitleGenerator(mode=selected_mode, model_name=selected_model)
        self._asr_worker = AsrWorker(
            self._current_file, generator=generator, parent=self
        )
        self._asr_worker.progress.connect(self._on_asr_progress)
        self._asr_worker.status_changed.connect(self._on_asr_status)
        self._asr_worker.finished_success.connect(self._on_asr_success)
        self._asr_worker.failed.connect(self._on_asr_failed)
        self._asr_worker.cancelled.connect(self._on_asr_cancelled)
        self._asr_worker.start()

    def cancel_asr(self) -> None:
        """Cancel ongoing speech recognition subtitle generation worker."""
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        if self._asr_worker is not None and self._asr_worker.isRunning():
            self._asr_worker.cancel()
        self._restore_overlay()

    def _on_asr_status(self, msg: str) -> None:
        """Update status bar and circular progress dialog with speech recognition state."""
        self.statusBar().showMessage(msg)
        if self._progress_dialog is not None:
            self._progress_dialog.set_label(msg)

    def _on_asr_progress(self, done_s: float, total_s: float) -> None:
        """Update status bar and circular progress dialog with generation progress percentage."""
        if total_s > 0.0:
            pct = min(100.0, max(0.0, (done_s / total_s) * 100.0))
            int_pct = int(pct)
            mode = getattr(self._asr_worker, "mode", "hybrid") if self._asr_worker else "hybrid"
            if mode == "hybrid":
                if int_pct < 40:
                    label = f"Analyzing timing… {int_pct}%"
                else:
                    label = f"Transcribing (accurate)… {int_pct}%"
            elif mode == "coverage":
                label = f"Transcribing all audio (max coverage)… {int_pct}%"
            else:
                label = f"Transcribing audio… {int_pct}%"

            self.statusBar().showMessage(f"Generating subtitles… {int_pct}%")
            if self._progress_dialog is not None:
                self._progress_dialog.set_progress(pct)
                self._progress_dialog.set_label(label)
        else:
            self.statusBar().showMessage("Generating subtitles…")

    def _on_asr_success(self, srt_path: str) -> None:
        """Handle successful subtitle generation, dismiss dialog, and auto-load the produced .srt."""
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        if self._asr_worker is not None:
            self._asr_worker.wait(1000)
            self._asr_worker = None
        p = Path(srt_path)
        self.statusBar().showMessage(f"Subtitles generated: {p.name}", 4000)
        self.load_subtitle_file(srt_path)

    def _on_asr_failed(self, err_msg: str) -> None:
        """Handle subtitle generation error and dismiss dialog."""
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        if self._asr_worker is not None:
            self._asr_worker.wait(1000)
            self._asr_worker = None
        self.statusBar().showMessage(f"Subtitle generation failed: {err_msg}", 5000)
        self._restore_overlay()

    def _on_asr_cancelled(self) -> None:
        """Handle subtitle generation cancellation and dismiss dialog."""
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        if self._asr_worker is not None:
            self._asr_worker.wait(1000)
            self._asr_worker = None
        self.statusBar().showMessage("Subtitle generation cancelled.", 3000)
        self._restore_overlay()

    def open_file(
        self,
        path: str | Path,
        subtitle_path: str | Path | None = None,
    ) -> None:
        """Open and play a media file and load corresponding subtitles.

        Args:
            path: Path to video or audio media file.
            subtitle_path: Optional explicit path to subtitle file.
        """
        p = Path(path).resolve()
        if not p.is_file():
            return

        self._current_file = str(p)
        self.setWindowTitle(f"{p.name} - Nihongo Player")

        # Cancel any ongoing ASR worker
        if self._asr_worker is not None and self._asr_worker.isRunning():
            self._asr_worker.cancel()
            self._asr_worker.wait(1000)
            self._asr_worker = None

        # Cancel any ongoing export worker
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.cancel()
            self._export_worker.wait(1000)
            self._export_worker = None
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None

        # Locate and load subtitles
        sub_file = str(subtitle_path) if subtitle_path else find_sidecar_subtitle(p)
        if sub_file:
            self.load_subtitle_file(sub_file)
        else:
            if self._translation_worker is not None and self._translation_worker.isRunning():
                self._translation_worker.cancel()
                self._translation_worker.wait(1000)
                self._translation_worker = None
            self.tracker = None
            self._current_sub_file = None
            self._trans.clear()
            self._studying = None
            self.study_panel.hide()
            self._refresh_overlay_now()

        self.mpv_widget.load(str(p))
        if self.isVisible() and not self.isMinimized():
            self.overlay.sync_to(self._video_global_rect())
            self.overlay.show_over()

    def open_file_dialog(self) -> None:
        """Open a file chooser dialog and start playback of selected file."""
        self._dismiss_study_panel()
        self._hide_overlay()
        self._dialog_open = True
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Video or Audio File",
                "",
                "Media Files (*.mp4 *.mkv *.webm *.avi *.mov *.mp3 *.flac *.wav *.m4a);;All Files (*)",
            )
        finally:
            self._dialog_open = False

        if file_path:
            self.open_file(file_path)
        else:
            self._restore_overlay()

    def open_subtitle_dialog(self) -> None:
        """Open a file chooser dialog and load selected subtitle file."""
        self._dismiss_study_panel()
        self._hide_overlay()
        self._dialog_open = True
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Subtitle File",
                "",
                "Subtitle Files (*.srt *.ass *.ssa *.vtt);;All Files (*)",
            )
        finally:
            self._dialog_open = False

        if file_path:
            self.load_subtitle_file(file_path)
        else:
            self._restore_overlay()

    def _get_default_export_stem(self) -> str:
        """Get sensible default file stem for vocabulary export."""
        if self._current_file:
            return Path(self._current_file).stem
        if self._current_sub_file:
            return Path(self._current_sub_file).stem
        return "vocabulary"

    def _start_export(self, export_type: str, file_path: str) -> None:
        """Start background vocabulary export worker with centered progress dialog."""
        if self._export_worker is not None and self._export_worker.isRunning():
            self.statusBar().showMessage("Export already in progress…", 3000)
            return

        if self.tracker is None or not self.tracker.cues:
            self.statusBar().showMessage("Load subtitles first", 3000)
            return

        # Dismiss study panel and hide overlay before showing progress dialog
        self._dismiss_study_panel()
        self._hide_overlay()

        stem = self._get_default_export_stem()
        src_name = Path(self._current_sub_file or self._current_file or "").name
        deck_name = (
            f"Nihongo: {stem}"
            if stem != "vocabulary"
            else "Nihongo Player Vocab"
        )

        self._export_progress_dialog = CircularProgressDialog(
            parent=self,
            title="Preparing vocabulary…",
            cancellable=True,
        )
        self._export_progress_dialog.canceled.connect(self.cancel_export)
        self._export_progress_dialog.set_progress(0.0)
        self._export_progress_dialog.set_label("Preparing vocabulary…")
        self._export_progress_dialog.show()

        self._export_worker = ExportWorker(
            cues=self.tracker.cues,
            export_type=export_type,
            out_path=file_path,
            translator=self.translator,
            source_name=src_name,
            deck_name=deck_name,
            parent=self,
        )
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_failed)
        self._export_worker.canceled.connect(self._on_export_cancelled)
        self._export_worker.start()

    def cancel_export(self) -> None:
        """Cancel ongoing vocabulary export worker."""
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.cancel()
        self._restore_overlay()

    def _on_export_progress(self, pct: int, msg: str) -> None:
        """Update status bar and circular progress dialog with export state."""
        self.statusBar().showMessage(msg)
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.set_progress(float(pct))
            self._export_progress_dialog.set_label(msg)

    def _on_export_finished(self, out_path: str) -> None:
        """Handle export completion, dismiss progress dialog, and show status message."""
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None
        count = getattr(self._export_worker, "word_count", 0)
        if self._export_worker is not None:
            self._export_worker.wait(1000)
            self._export_worker = None
        self.statusBar().showMessage(f"Exported {count} words to {out_path}", 4000)
        self._restore_overlay()

    def _on_export_failed(self, err_msg: str) -> None:
        """Handle export failure and dismiss dialog."""
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None
        if self._export_worker is not None:
            self._export_worker.wait(1000)
            self._export_worker = None
        self.statusBar().showMessage(f"Export failed: {err_msg}", 5000)
        self._restore_overlay()

    def _on_export_cancelled(self) -> None:
        """Handle export cancellation and dismiss dialog."""
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None
        if self._export_worker is not None:
            self._export_worker.wait(1000)
            self._export_worker = None
        self.statusBar().showMessage("Export cancelled.", 3000)
        self._restore_overlay()

    def export_vocabulary_pdf(self) -> None:
        """Export frequency-ranked vocabulary extracted from loaded subtitles to PDF."""
        self._dismiss_study_panel()
        self._hide_overlay()
        if self.tracker is None or not self.tracker.cues:
            self.statusBar().showMessage("Load subtitles first", 3000)
            self._restore_overlay()
            return

        stem = self._get_default_export_stem()
        default_name = f"{stem}_vocab.pdf"

        self._dialog_open = True
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Vocabulary to PDF",
                default_name,
                "PDF Files (*.pdf);;All Files (*)",
            )
        finally:
            self._dialog_open = False

        if not file_path:
            self._restore_overlay()
            return

        self._start_export("pdf", file_path)

    def export_vocabulary_anki(self) -> None:
        """Export frequency-ranked vocabulary extracted from loaded subtitles to Anki (.apkg)."""
        self._dismiss_study_panel()
        self._hide_overlay()
        if self.tracker is None or not self.tracker.cues:
            self.statusBar().showMessage("Load subtitles first", 3000)
            self._restore_overlay()
            return

        stem = self._get_default_export_stem()
        default_name = f"{stem}_vocab.apkg"

        self._dialog_open = True
        try:
            file_path, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Export Vocabulary to Anki",
                default_name,
                "Anki Package (*.apkg);;Anki TSV (*.tsv *.txt);;All Files (*)",
            )
        finally:
            self._dialog_open = False

        if not file_path:
            self._restore_overlay()
            return

        if file_path.lower().endswith((".tsv", ".txt")) or "TSV" in selected_filter:
            self._start_export("tsv", file_path)
        else:
            self._start_export("apkg", file_path)

    def export_vocabulary_tsv(self) -> None:
        """Export frequency-ranked vocabulary extracted from loaded subtitles to Anki TSV."""
        self._dismiss_study_panel()
        self._hide_overlay()
        if self.tracker is None or not self.tracker.cues:
            self.statusBar().showMessage("Load subtitles first", 3000)
            self._restore_overlay()
            return

        stem = self._get_default_export_stem()
        default_name = f"{stem}_vocab.tsv"

        self._dialog_open = True
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Vocabulary to Anki TSV",
                default_name,
                "Anki TSV (*.tsv *.txt);;All Files (*)",
            )
        finally:
            self._dialog_open = False

        if not file_path:
            self._restore_overlay()
            return

        self._start_export("tsv", file_path)

    def closeEvent(self, event: Any) -> None:
        """Cleanly terminate background workers, companion windows, and save settings."""
        self.save_settings()
        self.overlay.hide()
        self.overlay.close()
        self.study_panel.hide()
        self.study_panel.close()
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None
        if hasattr(self, "_sync_timer") and self._sync_timer.isActive():
            self._sync_timer.stop()
        if self._translation_worker is not None and self._translation_worker.isRunning():
            self._translation_worker.cancel()
            self._translation_worker.wait(1000)
            self._translation_worker = None
        if self._asr_worker is not None and getattr(self._asr_worker, "isRunning", lambda: False)():
            self._asr_worker.cancel()
            self._asr_worker.wait(1000)
            self._asr_worker = None
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.cancel()
            self._export_worker.wait(1000)
            self._export_worker = None
        self.mpv_widget.shutdown()
        event.accept()


def create_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser for the CLI.

    Returns:
        argparse.ArgumentParser configured for Nihongo Player.
    """
    parser = argparse.ArgumentParser(
        prog="nihongo-player",
        description="Cross-platform Japanese-learning desktop video player.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=__version__,
        help="Show program version and exit.",
    )
    parser.add_argument(
        "media_file",
        nargs="?",
        help="Path to video or audio media file to play.",
    )
    parser.add_argument(
        "--sub",
        dest="subtitle_file",
        help="Path to Japanese subtitle file (.srt, .ass, .vtt).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main application entrypoint.

    Args:
        argv: Optional sequence of command-line arguments. Defaults to sys.argv[1:].

    Returns:
        Exit code (0 for success).
    """
    parser = create_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    ensure_libmpv()
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except Exception:
        pass

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv if argv is None else [sys.argv[0]] + list(argv))

    app.setWindowIcon(get_app_icon())

    window = MainWindow()
    if args.media_file:
        window.open_file(args.media_file, subtitle_path=args.subtitle_file)

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
