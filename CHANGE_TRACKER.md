# Nihongo Player — Change Tracker

## 1. Overview

**Nihongo Player (日本語プレイヤー)** is an offline-first, cross-platform desktop video player crafted specifically for Japanese language immersion and acquisition. Designed for non-commercial language learners, it bridges the gap between passive video watching and active vocabulary acquisition by combining hardware-accelerated media playback with deeply integrated natural language processing.

### Key Philosophy & Core Experience
- **Always-On Furigana Overlay**: Subtitles render with crystal-clear ruby furigana positioned directly above kanji compounds, typeset with high-contrast outlines for legibility against any video backdrop.
- **The Zero-Friction Study Loop**:
  1. While watching Japanese media, press <kbd>◄</kbd> (Left-Arrow) at any moment.
  2. The player instantly rewinds to the beginning of the subtitle line you just heard, pauses playback, and presents an interactive study panel.
  3. The study panel provides a complete word-by-word morphological breakdown, dictionary definitions, and an offline neural machine translation of the full sentence.
  4. Press <kbd>Space</kbd> to dismiss the study panel and immediately resume video immersion.
- **100% Offline & Private**: All tokenizers, dictionaries, neural translation models, and speech recognition engines run entirely locally on CPU without sending user media, audio, or queries over the network.
- **License**: Free and open-source software licensed under the **GNU General Public License v3.0 (GPL-3.0)**.

---

## 2. Architecture & Tech Stack

Nihongo Player is built with Python 3.11+ using a modular architecture that separates UI presentation, media rendering, natural language processing, speech recognition, and data export.

```
nihongo-player/
├── src/nihongo_player/
│   ├── __init__.py           # Package root & version information
│   ├── __main__.py           # CLI invocation entry point
│   ├── app.py                # Main application window, central coordinator & event dispatch
│   ├── resources.py          # Icon and asset loaders
│   ├── player/               # Video playback & libmpv integration
│   │   ├── __init__.py
│   │   ├── libmpv_loader.py  # Dynamic libmpv loading with NIHONGO_LIBMPV override
│   │   ├── mpv_widget.py     # Qt OpenGL/native widget wrapping libmpv + eq filter
│   │   └── timeline.py       # Custom seek slider with click-to-seek & hover preview
│   ├── subs/                 # Subtitle loading & cue tracking
│   │   ├── __init__.py
│   │   ├── loader.py         # Multi-format parser (SRT/ASS/VTT) + sidecar auto-discovery
│   │   ├── tracker.py        # Active cue tracking & runtime sync offset adjustment
│   │   └── text_clean.py     # Strips caption markers ([Music], speaker names, tags)
│   ├── ja/                   # Japanese text processing & dictionary lookups
│   │   ├── __init__.py
│   │   ├── tokenizer.py      # Fugashi + UniDic-lite morphological segmentation & lemma cleaning
│   │   ├── furigana.py       # Kanji-kana alignment & ruby HTML generation
│   │   ├── dictionary.py     # Jamdict wrapper (JMdict, JMnedict, KANJIDIC2) + reading hints
│   │   └── annotate.py       # High-level sentence annotator (tokens, readings, glosses)
│   ├── mt/                   # Neural Machine Translation
│   │   ├── __init__.py
│   │   └── translator.py     # CTranslate2 + SentencePiece offline Opus-MT ja->en engine
│   ├── asr/                  # Automatic Speech Recognition
│   │   ├── __init__.py
│   │   └── subgen.py         # faster-whisper ASR (Hybrid Kotoba timing + Anime-Whisper text default / single models)
│   ├── export/               # Vocabulary list & flashcard generation
│   │   ├── __init__.py
│   │   ├── frequency.py      # Subtitle frequency analyzer & lemma ranker
│   │   ├── furigana_text.py  # Anki/bracket furigana text generator [漢字|かんじ]
│   │   ├── pdf_export.py     # Printable vocabulary PDF generator via ReportLab
│   │   └── anki_export.py    # Anki .apkg deck & .tsv exporter via genanki
│   ├── ui/                   # Specialized UI components & overlays
│   │   ├── __init__.py
│   │   ├── overlay.py        # Top-level translucent subtitle & furigana overlay window & click surface
│   │   ├── study_panel.py    # Top-level interactive study overlay & dictionary breakdown
│   │   └── progress_dialog.py# Non-modal circular progress dialog tracking parent geometry
│   └── setup/                # Setup & first-run initialization
│       ├── __init__.py
│       └── first_run.py      # First-run detection & welcome prompts
├── tests/                    # Comprehensive unit and GUI test suite (pytest + xvfb)
├── models/                   # Pre-quantized offline neural models (Opus-MT CT2)
├── assets/                   # Multi-platform application icons (.png, .ico, .icns)
├── scripts/                  # Model conversion and build automation scripts
└── packaging/                # PyInstaller specification & distribution configuration
```

### Core Technologies
- **Python 3.11+**: Modern Python runtime with strict typing and dataclasses.
- **PySide6 (Qt6 for Python)**: Cross-platform GUI framework providing custom top-level window compositing, styling, event handling, and thread synchronization.
- **libmpv / python-mpv**: Embedded hardware-accelerated video playback supporting all common audio/video containers and codecs (H.264, HEVC, AV1, VP9, AAC, Opus, FLAC).
- **pysubs2**: Robust parser for SubRip (`.srt`), Advanced SubStation Alpha (`.ass`/`.ssa`), and WebVTT (`.vtt`) subtitle formats.
- **Fugashi & UniDic-lite**: High-speed Japanese morphological tokenizer wrapping MeCab with UniDic-lite dictionary for accurate parts of speech, lemma extraction, and phonological readings.
- **jaconv**: Fast Hiragana, Katakana, and half-width/full-width character conversions.
- **Jamdict & Jamdict-data**: Complete offline dictionary database querying JMdict (words & glosses), JMnedict (proper names), and KANJIDIC2 (kanji stroke counts, meanings, readings) without internet connectivity (~560MB offline data).
- **CTranslate2 & SentencePiece**: High-performance inference engine running an int8-quantized `Helsinki-NLP/opus-mt-ja-en` Transformer model for offline sentence translation.
- **faster-whisper & Hybrid Kotoba-Anime Pipeline**: Two-pass hybrid speech recognition combining Kotoba-Whisper's precise acoustic segment timing (`kotoba-tech/kotoba-whisper-v2.0-faster`) with Anime-Whisper's high word accuracy (`quantumcookie/anime-whisper-ct2-int8`) using `clip_timestamps`, with one model loaded in RAM at a time.
- **ReportLab**: Programmatic PDF engine rendering high-density, multi-page frequency-ranked Japanese vocabulary cheat-sheets.
- **genanki**: Generates ready-to-import Anki flashcard decks (`.apkg`) formatted with ruby furigana, contextual dialogue sentences, and English translations.

---

## 3. Feature List

### Playback & Video Engine
- **Embedded libmpv Playback**: High-performance video rendering with hardware decoding and smooth audio-video sync.
- **Media Transport Controls**: Play, pause, step-frame, precise timestamp seeking, and elapsed/total duration display.
- **Interactive Speed Slider**: Smooth playback rate adjustment from `0.5x` to `2.0x` in real time.
- **Zoom & Aspect Ratio Control**: Zoom in/out (`+`/`-`), reset (`0`), and preset aspect ratios (*Default*, *16:9*, *4:3*, *2.35:1*, *Stretch to Window*, *Zoom to Fill*).
- **Brightness Adjustment via FFmpeg `eq` Filter**: Hardware-independent brightness adjustment (<kbd>▲</kbd>/<kbd>▼</kbd>) implemented using FFmpeg's video equalization filter, ensuring full functionality even in headless VMs or environments where 3D hardware acceleration is unavailable.
- **Direct Video Interaction**: Click directly on video surface to toggle play/pause; double-click to toggle fullscreen; click anywhere on the timeline slider to jump instantly to that position.
- **Fullscreen Mode**: Clean, immersive distraction-free fullscreen mode (<kbd>F11</kbd> / <kbd>Esc</kbd>).

### Subtitles & Text Processing
- **Sidecar Auto-Discovery**: Automatically matches and loads subtitle files (`.srt`, `.ass`, `.vtt`) sharing the same file stem as the video.
- **Subtitle File Import**: Manual subtitle import dialog (`File -> Import Subtitles...`) to link external subtitle files.
- **Caption Marker Stripping**: Intelligently removes sound effect brackets (e.g. `[Music]`, `(Laughter)`, `【ため息】`) and speaker names so they do not pollute vocabulary lists or study cards.
- **Real-Time Subtitle Sync Offset**: Adjust subtitle synchronization on the fly in ±0.1s increments (<kbd>,</kbd> / <kbd>.</kbd>) with an on-screen display (OSD) feedback banner.

### Furigana Overlay
- **Real-Time Furigana (Ruby) Text**: Always-visible furigana aligned directly above kanji characters.
- **Kanji Compound Accent Coloring**: Highlights kanji characters in a customizable accent color (default warm amber) to clearly distinguish kanji compounds from surrounding kana.
- **Custom Font Scaling**: Subtitle text size can be dynamically adjusted up/down (<kbd>W</kbd>/<kbd>S</kbd>) with immediate visual feedback.
- **Top-Level Window Compositing**: Subtitle overlay is rendered in a dedicated transparent top-level Qt window positioned over the native mpv surface, eliminating widget clipping and visual artifacts.

### Study Mode & Natural Language Processing
- **Zero-Friction Immersion Flow**: Pressing <kbd>◄</kbd> (Left-Arrow) rewinds to the start of the current/preceding line, pauses video playback, and opens the study panel. Pressing <kbd>►</kbd> (Right-Arrow) navigates to the next subtitle line.
- **Word-by-Word Morphological Breakdown**: Breaks down Japanese dialogue into individual words, displaying surface form, reading furigana, dictionary lemma, part-of-speech tag, and full English definitions.
- **Offline Sentence Translation**: Instant English neural machine translation for the complete sentence.
- **Smart Homograph & Reading Hints**: Resolves homographs (such as 僕 disambiguated to ぼく rather than rare readings) using contextual reading hints.
- **Visual Resume Hint**: A highlighted on-screen hint reminds the user to press <kbd>Space</kbd> to dismiss study mode and resume watching immediately.

### AI Subtitle Generation (ASR)
- **Hybrid Accurate Subtitle Pipeline (Default & Recommended)**: Two-phase transcription combining Kotoba-Whisper's acoustic segment boundaries (`kotoba-tech/kotoba-whisper-v2.0-faster`) with Anime-Whisper's high-accuracy text recognition (`quantumcookie/anime-whisper-ct2-int8`):
  1. *Phase 1 (Timing)*: Transcribes audio with Kotoba-Whisper to extract accurate dialogue segment start and end windows.
  2. *Phase 2 (Text)*: Frees the timing model from RAM and loads Anime-Whisper, transcribing each window independently with `clip_timestamps` for maximum vocabulary fidelity without high peak RAM.
- **GUI Speech Recognition Mode Picker**: Select from 4 modes (*Accurate Hybrid [default]*, *Fast Kotoba only*, *Anime only experimental*, *High Accuracy Large-v3*) directly under the **File &rarr; Speech Recognition Model** menu with automatic `QSettings` persistence (`asr_mode`, `asr_model`).
- **Phase-Aware Circular Progress Dialog**: Displays real-time phase progression (*Analyzing timing… 0..40%* then *Transcribing (accurate)… 40..100%*).
- **Intelligent Cue Post-Processing & Timing Tightening**:
  - Automatically caps cue on-screen durations according to dialogue length (`max(1.5s, min(7.0s, len * 0.35s))`).
  - Clamps cue ends to subsequent cue starts, ensuring subtitles do not linger over silent gaps or background music.
  - Automatically detects and deduplicates consecutive hallucination loops.
- **Configurable Whisper Models & Precedence**: Resolves mode via `NIHONGO_WHISPER_MODE` (`hybrid` or `single`), `NIHONGO_WHISPER_TIMING_MODEL`, `NIHONGO_WHISPER_TEXT_MODEL`, `NIHONGO_WHISPER_MODEL` env overrides > `QSettings` > default hybrid.
- **Single-Model Fallback**: Setting `export NIHONGO_WHISPER_MODE=single` reverts to fast single-pass transcription.

### Vocabulary Export
- **Frequency-Ranked Extraction**: Aggregates all words across the entire subtitle file, ranking lemmas by occurrence frequency.
- **Cleaned Lemma Representation**: Normalizes words flagged as "usually kana" (`uk`) into their natural kana spelling (e.g. この instead of 此の), while strictly preserving katakana loanwords (e.g. バー).
- **Printable PDF Cheat-Sheets**: Exports multi-page, formatted PDF study sheets via ReportLab containing word rankings, furigana readings, parts of speech, and English definitions.
- **Anki Flashcard Export**: Generates `.apkg` decks and `.tsv` files via genanki containing ruby furigana bracket notation (`[漢字|かんじ]`), contextual anime dialogue sentences, and full English translations.

### Application Shell & Distribution
- **Custom Application Icon**: Polished Japanese torii/player icon embedded across desktop window headers, taskbars, macOS `.icns`, and Windows `.ico` formats.
- **Automated Linux Installer Script**: One-step idempotent installer (`scripts/install-linux.sh`) with `--with-asr-model` pre-download flag, local `runtime-libs` fallback, desktop launcher, and desktop menu integration.
- **Settings Persistence**: Remembers user preferences across sessions using `QSettings` (ASR model, furigana toggle, kanji coloring, subtitle scale, sync offset, MT toggle, audio volume, and window geometry).

---

## 4. Keyboard Shortcuts

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| <kbd>Space</kbd> | Play / Pause / Resume | Toggle video playback, or dismiss study panel and resume video |
| <kbd>◄</kbd> (Left Arrow) | Study Prev Line | Rewind to start of previous/current line, pause, and open study panel (or seek -5s when no subtitles) |
| <kbd>►</kbd> (Right Arrow) | Study Next Line | Jump directly to next subtitle cue (or seek +5s when no subtitles) |
| <kbd>▲</kbd> / <kbd>▼</kbd> (Up / Down) | Brightness ±5 | Adjust video brightness up or down via FFmpeg `eq` video filter |
| <kbd>Shift</kbd> + <kbd>▲</kbd> / <kbd>▼</kbd> | Volume ±5% | Adjust audio volume up or down |
| <kbd>+</kbd> / <kbd>=</kbd> | Video Zoom In | Zoom video frame in |
| <kbd>-</kbd> | Video Zoom Out | Zoom video frame out |
| <kbd>0</kbd> | Reset Zoom & Aspect | Reset video zoom level and aspect ratio to default |
| <kbd>W</kbd> / <kbd>Ctrl</kbd>+<kbd>+</kbd> | Increase Subtitle Size | Increase subtitle font scale (+10%) |
| <kbd>S</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd> | Decrease Subtitle Size | Decrease subtitle font scale (-10%) |
| <kbd>F</kbd> | Toggle Furigana | Toggle furigana ruby annotations above kanji |
| <kbd>F11</kbd> | Fullscreen | Toggle fullscreen display mode |
| <kbd>Esc</kbd> | Dismiss / Exit | Dismiss study panel or exit fullscreen mode |
| <kbd>,</kbd> / <kbd>Ctrl</kbd> + <kbd>◄</kbd> | Subtitle Sync Earlier (-0.1s) | Nudge subtitle timing offset backward by -0.1s |
| <kbd>.</kbd> / <kbd>Ctrl</kbd> + <kbd>►</kbd> | Subtitle Sync Later (+0.1s) | Nudge subtitle timing offset forward by +0.1s |
| <kbd>O</kbd> | Open File | Open video or audio file dialog |
| <kbd>Q</kbd> | Quit | Close and exit application |
| *Mouse Left-Click (Video)* | Play / Pause | Click anywhere on the video area to toggle playback |
| *Mouse Double-Click (Video)* | Fullscreen | Double-click video to toggle fullscreen mode |
| *Mouse Left-Click (Timeline)* | Instant Seek | Click anywhere on the progress bar to jump to that timestamp |

---

## 5. Milestone History (M0–M21)

- **M0** (`a070775`): `feat(scaffold): initialize milestone M0 project structure and stubs`
- **M1** (`e81667a`): `feat(player): M1 Qt window + embedded mpv video core + transport + smoke test`
- **M2** (`d044311`): `feat(subs): M2 subtitle loader + cue tracker + tests (real Dragon Ball SRT)`
- **M3** (`eafc2c0`): `feat(ja): M3 tokenizer + furigana alignment engine + tests (unidic-lite)`
- **M4a** (`0d6a210`): `feat(ja): M4a dictionary/gloss engine (jamdict) + tests`
- **M4b** (`b27f285`): `feat(ui): M4b furigana overlay + study mode + Left/Right/Space integration + tests`
- **M4c** (`53618c9`): `fix(ui): M4c render furigana overlay + study panel as top-level windows over mpv`
- **M5** (`91c3c51`): `feat(mt): M5 offline CTranslate2 ja->en translator + tests (opus-mt)`
- **M6** (`7dbda13`): `feat(ship): M6 settings + first-run + PyInstaller packaging + CI + docs`
- **M6b** (`6499fae`): `perf(packaging): M6b exclude WebEngine + unused Qt modules to slim the bundle`
- **M7** (`661a469`): `ci(release): M7 Windows + macOS + Linux release pipeline + per-OS packaging`
- **M8** (`483ec6b`): `feat(ux): M8 study nav + space-pause-meaning + speed slider + import subs + panel follows window + highlight resume`
- **M9** (`b11e15f`): `feat(asr): M9 AI subtitle generation via kotoba-whisper (faster-whisper) + tests + docs`
- **M10** (`300d1cf`): `feat(display): M10 kanji coloring + zoom/aspect/stretch + brightness keys + subtitle size + focus-loss panel fix`
- **M11** (`64de3ca`): `feat(export): M11 frequency vocab list -> PDF + Anki (apkg/tsv) + tests`
- **M12** (`6ca407f`): `feat(subs): M12 strip caption markers + clean loanword lemmas for a cleaner vocab list`
- **M13** (`18e7202`): `feat(ui): M13 application icon (window + Windows/macOS bundle)`
- **M14** (`854bec6`): `fix(ux): M14 play-button sync, word-cell furigana, brightness, W/S/F keys, perf, autoload AI subs, circular progress`
- **M15** (`acd26db`): `feat(export): M15 example EN translations + bigger centered fields + export progress popup`
- **M16** (`9338317`): `fix(export+ux): M16 clean lemmas + kana spelling + example furigana + F key + brightness keys`
- **M17** (`ccd6335`): `fix(export): M17 keep katakana words as katakana (kana-normalize only usually-kana)`
- **M18** (`73b0735`): `feat(ux): M18 brightness via eq-filter, 僕->ぼく reading, click-to-play, click-to-seek, progress-popup follows app, AI-sync`
- **M19** (`ee574b3`): `test(subs): M19 make sidecar-match test hermetic (use tmp dir, not real Downloads)`
- **M20** (`c4a61ec`): `fix(asr): M20 tighten subtitle timing (cap+clamp+dedup) + configurable whisper model`
- **M21** (`7474d26`): `docs(asr): M21 anime-whisper default + comprehensive CHANGE_TRACKER.md`
- **M22** (`e14dced`): `feat(asr+dist): M22 File-menu ASR model picker + Linux installer script + download docs`
- **M23** (`3ce9f8b`): `fix(ux): M23 kotoba default, space-pause-in-place, click-to-play via overlay, prev/next-line buttons`
- **M24** (`96e5398`): `feat(asr): M24 hybrid accurate subtitles (kotoba timing + anime text) as default`
- **M25** (`b465132`): `feat(asr): M25 maximum-coverage mode (contiguous anime windows) for music-buried dialogue`
- **M26** (`HEAD`): `feat(asr+ux): M26 coverage default + progress-dialog modal/topmost + fresh-install download hardening`

---

## 6. Key Technical Decisions & Gotchas

1. **`libmpv` Dynamic Loading & Platform Portability**:
   - `python-mpv` relies on `ctypes.util.find_library` to locate the native `mpv` shared library. On Linux distributions and packaged environments, standard discovery often fails to find `libmpv.so.2` or custom runtime builds.
   - We patch `ctypes.util.find_library` dynamically in `libmpv_loader.py` before `mpv` is imported, checking `NIHONGO_LIBMPV`, bundled libraries in `runtime-libs/` or `_libs/`, and known system paths.
   - On Windows, `libmpv-2.dll` is bundled directly with the application; on macOS, Homebrew's `libmpv.dylib` is discovered automatically.

2. **Video Brightness in Headless / VM Environments**:
   - In virtual machine environments without hardware 3D acceleration (e.g. standard Linux cloud instances and VMs), mpv's video output falls back from `gpu` to `x11`.
   - The `x11` video output driver completely ignores mpv's native `brightness` property.
   - To provide reliable brightness adjustment across all systems, Nihongo Player applies brightness via an FFmpeg `eq` video filter (`vf="eq=brightness=<val>"`) applied directly into mpv's video filter chain.

3. **CTranslate2 Opus-MT Translation Stability**:
   - Running Helsinki-NLP's `opus-mt-ja-en` Transformer model on CTranslate2 requires appending the sentence-ending token (`</s>`) to the source text.
   - Without this delimiter and strict repetition penalties (`repetition_penalty=1.2`, `no_repeat_ngram_size=3`), the decoder can easily degenerate into repetitive hallucination loops on colloquial or short dialogue phrases.

4. **Top-Level Window Compositing Over Native Video Surfaces & Focus Handling**:
   - Embedded native video engines (like libmpv using an X11 Window ID `wid` or Win32 HWND) paint directly to the hardware framebuffer, occluding standard child Qt widgets and swallowing mouse clicks.
   - To ensure subtitles, the study panel, and mouse interactions remain interactive, they are implemented as borderless, translucent top-level windows (`Qt.WindowType.Tool` / `Qt.WindowType.Window`).
   - The `SubtitleOverlay` acts as a translucent click surface over the video canvas with a ~250ms disambiguation timer to cleanly handle single-click (toggle play/pause) and double-click (toggle fullscreen) events.
   - Companion windows strictly hide when the application loses focus (`ApplicationInactive`), and the overlay reappears when focused (`ApplicationActive`), ensuring floating subtitles do not obscure other desktop applications.
   - Progress dialogs (`CircularProgressDialog`) are application-modal (`ApplicationModal`) and topmost, dismissing study panels prior to opening and preventing obscured modal deadlock.

5. **ASR Speech-to-Text Architecture & Three Generation Modes**:
   - **Mode 1: Maximum Coverage Contiguous Windows (`coverage`, default)**:
     - *The Problem*: High-action anime scenes with loud background music (e.g. shouts like ちくしょう over battle BGM) are missed by acoustic segmentation and Silero VAD.
     - *The Solution*: Transcribes the entire audio in contiguous fixed windows (default 5.0s, env `NIHONGO_WHISPER_WINDOW`) using Anime-Whisper (`quantumcookie/anime-whisper-ct2-int8`).
     - *Window Merging & Post-Processing*: Merges adjacent windows via suffix/prefix overlap matching and strict continuation concatenation (`merge_coverage_cues`), drops hallucination repeats, and caps/clamps on-screen duration (`post_process_cues`).
     - *Scope Note on Complete + Frame-Accurate Anime Subs*: True frame-accurate *and* complete anime subtitle extraction over loud action music requires deep vocal stem separation (e.g. Demucs / MDX-Net), which is intentionally out of scope due to massive model footprint and CPU/GPU compute constraints.
   - **Mode 2: Accurate Hybrid (`hybrid`, slower)**:
     1. *Phase 1*: Transcribe audio with `kotoba-tech/kotoba-whisper-v2.0-faster` to produce well-timed `(start, end)` speech windows.
     2. *Memory Release*: Release the timing model (`del` + `gc.collect()`) BEFORE loading the text model, keeping peak RAM minimal (critical on CPU and low-RAM environments).
     3. *Phase 2*: For each timing window, transcribe that window with `quantumcookie/anime-whisper-ct2-int8` using `clip_timestamps='<start>,<end>'` to recover accurate text.
     4. *Post-Processing*: Run `post_process_cues` (duration capping, next-cue clamping, dedup) and output valid SRT.
   - **Mode 3: Fast Single Pass (`single`)**:
     - Single-pass transcription using a single model (`kotoba-whisper`, `anime-whisper`, or `large-v3`).
   - All modes are switchable via GUI (**File &rarr; Speech Recognition Model**) and environment variables (`NIHONGO_WHISPER_MODE`, `NIHONGO_WHISPER_WINDOW`, `NIHONGO_WHISPER_TEXT_MODEL`, `NIHONGO_WHISPER_TIMING_MODEL`, `NIHONGO_WHISPER_MODEL`).

6. **Morphological Lemma & Reading Normalization**:
   - UniDic-lite produces internal morphological annotations that include technical suffixes (e.g. `-代名詞`, `-bar`, `-一般`). These are cleanly stripped in `tokenizer.py`.
   - Words flagged as "usually written in kana" (`uk` in JMdict) are normalized to kana (e.g. 此の &rarr; この), while katakana loanwords are strictly preserved (e.g. バー).
   - Homograph readings (e.g. 僕 disambiguated to ぼく rather than しもべ) are resolved via reading-hints passed to the Jamdict dictionary engine.

7. **Hermetic Test Suite Under Headless Xvfb**:
   - All GUI and video player unit/integration tests run headlessly using `NIHONGO_MPV_VO=null` and `xvfb-run -a -s "-screen 0 1280x720x24" pytest`.
   - Sidecar subtitle matching tests use isolated temporary directories rather than querying the host's actual `~/Downloads` directory.

---

## 7. Known Limitations

- **Acoustic Speech Recognition Limits**: Speech-to-text recognition is not 100% accurate on scenes with loud background music, explosions, overlapping dialogue, or heavy vocal distortions. Anime-Whisper may also transcribe non-verbal emotional vocalizations (gasps, grunts, sighs).
- **Rare Homograph / Proper Noun Ambiguities**: Statistical morphological analysis using UniDic-lite may occasionally misread rare fantasy proper nouns, invented character names, or archaic grammar constructs without broad context.
- **Offline Dictionary Storage Footprint**: The bundled offline dictionary database (JMdict, JMnedict, KANJIDIC2) requires approximately ~560MB of uncompressed storage, establishing a baseline footprint for standalone application bundles.
- **Platform Packaging & Cross-Compilation**: Standalone macOS (`.dmg`) and Windows (`.zip`) binary releases must be built in native operating system environments (via GitHub Actions runners) due to platform-specific C/C++ bindings in Qt6 and libmpv.

---

## 8. Build, Run, and Distribution

### Running From Source (Development)
```bash
# 1. Clone the repository
git clone https://github.com/nihongo-player/nihongo-player.git
cd nihongo-player

# 2. Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -e .
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. (Optional) Install ASR dependencies
pip install -e .[asr]

# 5. Fetch and quantize offline neural MT model
python scripts/fetch_models.py

# 6. Launch Nihongo Player
nihongo-player
# Or launch directly with a video:
nihongo-player /path/to/anime_episode.mp4
```

### Running Tests
```bash
# Run complete test suite with headless Xvfb
NIHONGO_MPV_VO=null xvfb-run -a -s "-screen 0 1280x720x24" pytest -q

# Or using Makefile helper
make test
```

### Building Standalone Binaries (PyInstaller)
```bash
# Build standalone desktop bundle
pyinstaller packaging/nihongo_player.spec
```
The PyInstaller specification strips unused Qt modules (`QtWebEngine`, `Qt3D`, `QtQuick3D`, `QtDesigner`) and packages pre-quantized translation models into the distribution folder.

### CI/CD & Multi-Platform Release Pipeline
- Automated GitHub Actions release workflow triggers upon pushing semantic version tags (e.g. `git push origin v0.1.0`).
- Build Matrix:
  - **Linux x64**: `ubuntu-latest` &rarr; `NihongoPlayer-linux-x64.tar.gz`
  - **Windows x64**: `windows-latest` &rarr; `NihongoPlayer-windows-x64.zip` (bundles `libmpv-2.dll`)
  - **macOS Apple Silicon**: `macos-latest` (arm64) &rarr; `NihongoPlayer-macos-arm64.dmg`
  - **macOS Intel**: `macos-13` (x86_64) &rarr; `NihongoPlayer-macos-x64.dmg`
- Models Provenance:
  - Neural Translation: Quantized int8 CTranslate2 model generated from `Helsinki-NLP/opus-mt-ja-en` via `scripts/fetch_models.py`.
  - ASR: `kotoba-tech/kotoba-whisper-v2.0-faster` (default) cached on-demand from Hugging Face Hub to `~/.cache/huggingface/hub` (or `NIHONGO_WHISPER_MODELS`).
  - Dictionaries: `jamdict-data` and `unidic-lite` bundled as pre-built offline Python data packages.
