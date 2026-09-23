# Nihongo Player (日本語プレイヤー)

**Nihongo Player** is an open-source, desktop video player crafted specifically for Japanese language learners. Powered by PySide6 (Qt), libmpv, and offline natural language processing models, it provides real-time furigana (ruby readings) above kanji compounds, instant rewind into study mode, word-by-word dictionary breakdowns, and offline neural sentence translations.

---

## Features

- **High-Performance Video Playback**: Embedded hardware-accelerated media engine powered by `libmpv`.
- **Automatic Subtitle Discovery**: Automatically detects sidecar Japanese subtitles (`.srt`, `.ass`, `.vtt`) sharing the same file name as your media.
- **Dynamic Furigana (Ruby) Subtitle Overlay**: Renders Japanese subtitles with accurate furigana readings positioned directly above kanji glyphs, formatted with high-contrast stroked text and customizable font scaling.
- **The Zero-Friction Learning Loop**:
  - Press <kbd>◄</kbd> (Left-Arrow) at any time to rewind to the start of the subtitle line you just heard, pause video playback, and open the interactive study panel.
  - View word-by-word morphological analysis with lemmas and pitch/reading forms (via Fugashi & UniDic-lite).
  - Inspect comprehensive English dictionary definitions and glosses (via Jamdict & JMdict).
  - Read offline neural machine translations into English (via Helsinki-NLP Opus-MT on CTranslate2).
  - Press <kbd>Space</kbd> to dismiss the study overlay and resume immersion instantly.
- **Persistent User Settings**: Remembers your furigana toggle state, kanji accent coloring, subtitle font scale, subtitle sync timing offset, neural translation preference, volume, and window geometry across sessions.
- **100% Offline & Private**: All tokenizers, dictionaries, and translation models run locally on CPU without sending audio, video, or text to external servers.

---

## Keyboard Shortcuts

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| <kbd>Space</kbd> | Play / Pause / Study Resume | Toggle playback, or dismiss study panel and resume video |
| <kbd>◄</kbd> (Left Arrow) | Study Prev Line | Rewind to start of preceding/current subtitle cue, pause, and open study panel (or seek -5s when no subtitles) |
| <kbd>►</kbd> (Right Arrow) | Study Next Line | Jump directly to next subtitle cue (or seek +5s when no subtitles) |
| <kbd>▲</kbd> / <kbd>▼</kbd> (Up / Down) | Brightness ±5 | Adjust video display brightness up or down |
| <kbd>Shift</kbd> + <kbd>▲</kbd> / <kbd>▼</kbd> | Volume ±5% | Adjust playback audio volume up or down |
| <kbd>+</kbd> / <kbd>=</kbd> | Video Zoom In | Zoom video frame in |
| <kbd>-</kbd> | Video Zoom Out | Zoom video frame out |
| <kbd>0</kbd> | Reset Zoom & Aspect | Reset video zoom level and aspect ratio to default |
| <kbd>W</kbd> / <kbd>Ctrl</kbd>+<kbd>+</kbd> | Increase Subtitle Size | Increase subtitle font scale (+10%) |
| <kbd>S</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd> | Decrease Subtitle Size | Decrease subtitle font scale (-10%) |
| <kbd>.</kbd> / <kbd>Ctrl</kbd> + <kbd>►</kbd> | Subtitle Sync Later (+0.1s) | Nudge subtitle timing offset forward by +0.1s |
| <kbd>,</kbd> / <kbd>Ctrl</kbd> + <kbd>◄</kbd> | Subtitle Sync Earlier (-0.1s) | Nudge subtitle timing offset backward by -0.1s |
| <kbd>F</kbd> | Toggle Furigana | Toggle furigana ruby annotations above kanji |
| <kbd>F11</kbd> | Fullscreen | Toggle fullscreen display mode |
| <kbd>O</kbd> | Open File | Open video or audio file dialog |
| <kbd>Q</kbd> | Quit | Close and exit application |
| <kbd>Esc</kbd> | Dismiss / Exit | Dismiss study panel or exit fullscreen mode |

> [!TIP]
> **View Menu & Subtitle Sync**: If an external subtitle file's timings run slightly early or late, use the Subtitle Sync offset (<kbd>,</kbd> / <kbd>.</kbd> or **View &rarr; Subtitle Sync**) to nudge timings in 0.1s increments with an on-screen display readout. AI-generated subtitles (Anime-Whisper) have accurate timing out-of-the-box. You can also toggle **Color Kanji** (highlights kanji in subtitle overlay and vocabulary table with customizable accent color), choose aspect ratios under the **Aspect Ratio** submenu (*Default*, *16:9*, *4:3*, *2.35:1*, *Stretch to Window*, *Zoom to Fill*), or adjust subtitle font scaling directly.

---

## Downloads & Releases

Pre-built binary packages are automatically generated and published by GitHub Actions upon pushing a release tag (e.g. `v0.1.0`). Download the latest release asset for your operating system and hardware architecture from the [Releases](https://github.com/nihongo-player/nihongo-player/releases) page:

| Operating System | Architecture | Release Asset | Runtime Requirements |
| :--- | :--- | :--- | :--- |
| **Windows** | x64 (64-bit) | `NihongoPlayer-windows-x64.zip` | None (bundled `libmpv-2.dll`) |
| **macOS** | Apple Silicon (M1/M2/M3/M4) | `NihongoPlayer-macos-arm64.dmg` | Homebrew `mpv` (`brew install mpv`) |
| **macOS** | Intel (x86_64) | `NihongoPlayer-macos-x64.dmg` | Homebrew `mpv` (`brew install mpv`) |
| **Linux** | x64 (glibc) | `NihongoPlayer-linux-x64.tar.gz` | System `libmpv2` |

---

### Per-OS Setup & Launch Instructions

#### Windows (x64)
1. Download `NihongoPlayer-windows-x64.zip` from [Releases](https://github.com/nihongo-player/nihongo-player/releases).
2. Extract the `.zip` archive to a folder of your choice.
3. Run `NihongoPlayer.exe`.
> [!NOTE]
> **Windows SmartScreen**: Because GitHub Actions builds are unsigned, Windows SmartScreen may display a warning on initial launch. Click **"More info"** &rarr; **"Run anyway"** to start the app. The self-contained `libmpv-2.dll` is bundled directly inside the archive, so no additional setup or dependencies are required.

#### macOS (Apple Silicon & Intel)
1. Install `mpv` via [Homebrew](https://brew.sh/) (macOS releases utilize the system Homebrew `libmpv.dylib`):
   ```bash
   brew install mpv
   ```
2. Download the `.dmg` matching your Mac architecture (`arm64` for Apple Silicon, `x64` for Intel).
3. Open the `.dmg` disk image and drag `NihongoPlayer.app` into `/Applications`.
4. **First Launch (Gatekeeper)**: Because the app is unsigned and un-notarized:
   - **Option A**: Right-click (or Control-click) `NihongoPlayer.app` in `/Applications`, select **Open**, and click **Open** in the security confirmation dialog.
   - **Option B**: Remove the quarantine flag via Terminal:
     ```bash
     xattr -dr com.apple.quarantine /Applications/NihongoPlayer.app
     ```

#### Linux (x64)

##### Option A: One-Script Automated Installer (Recommended)
Run the automated installer script to install `libmpv`, set up the virtual environment, compile the neural translation model, install the desktop launcher, and add desktop menu entries:
```bash
# Basic installation (ASR model downloads on first use)
bash scripts/install-linux.sh

# Or pre-download the Anime ASR model for 100% offline use:
bash scripts/install-linux.sh --with-asr-model
```
To uninstall the desktop launcher and menu shortcuts:
```bash
bash scripts/uninstall-linux.sh
```

##### Option B: Manual Package Manager / Release Archive
1. Install the system `libmpv` library via your distribution package manager:
   ```bash
   # Ubuntu / Debian / Pop!_OS / Linux Mint
   sudo apt update && sudo apt install -y libmpv2

   # Arch Linux / Manjaro
   sudo pacman -S mpv

   # Fedora / RHEL
   sudo dnf install mpv-libs
   ```
2. Download `NihongoPlayer-linux-x64.tar.gz` and extract:
   ```bash
   tar -xzf NihongoPlayer-linux-x64.tar.gz
   cd NihongoPlayer
   ./NihongoPlayer
   ```

---

## Installing From Source

**Prerequisites**:
- Python 3.11 or 3.12
- System `libmpv` shared library installed (see instructions above)

**Setup Steps**:
```bash
# 1. Clone repository
git clone https://github.com/nihongo-player/nihongo-player.git
cd nihongo-player

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies (including ASR speech-to-text extra)
pip install -e ".[asr]"
pip install -r requirements-dev.txt

# 4. Download and convert Opus-MT translation model (int8 quantized)
python scripts/fetch_models.py

# 5. Launch Nihongo Player
nihongo-player
# Or launch directly with a video file:
nihongo-player /path/to/anime_episode.mp4
```

---

## Usage Guide

1. **Prepare Your Media**:
   Place your video file (`.mp4`, `.mkv`, `.webm`) and Japanese subtitle file (`.srt`, `.ass`, `.vtt`) in the same directory with matching names:
   ```text
   anime_ep01.mp4
   anime_ep01.srt
   ```
2. **Open the Video**:
   Launch Nihongo Player and press <kbd>O</kbd> (or `File -> Open Video...`) to select your media file. Nihongo Player will automatically locate and load the matching subtitle file. You can also specify subtitles explicitly via command-line:
   ```bash
   nihongo-player video.mp4 --sub subtitles_ja.srt
   ```
3. **Immerse & Study**:
   - Subtitles will appear near the bottom with furigana rendered above kanji characters.
   - When you hear a line you want to review, press <kbd>◄</kbd> (Left-Arrow).
   - Review vocabulary definitions in the dictionary table and the full sentence translation.
   - Press <kbd>Space</kbd> to continue watching.

---

## Generating Subtitles for Videos Without a .srt

For videos that have no subtitle file, Nihongo Player can automatically transcribe Japanese speech directly from the audio using Automatic Speech Recognition (ASR):

## Generating Subtitles for Videos Without a .srt

For videos that have no subtitle file, Nihongo Player can automatically transcribe Japanese speech directly from the audio using Automatic Speech Recognition (ASR):

- **First-Run Downloads & Offline Architecture**:
  - **Bundled Offline**: Dictionaries (`jamdict-data`, `unidic-lite`) and the neural MT model (`models/opus-ja-en-ct2`) are fully bundled and function 100% offline out of the box.
  - **Downloaded On First Use**: On a new machine, `pip install -e .[asr]` (or the automated installer `scripts/install-linux.sh`) gets all Python dependencies + bundled dict/MT. The ASR speech recognition model(s) download automatically on first **Generate Japanese Subtitles (AI)** via the `huggingface_hub` Python library (over HTTPS; no `huggingface-cli` or user account/login required) and are cached offline in `~/.cache/huggingface` (or `NIHONGO_WHISPER_MODELS`). Alternatively, you can pre-fetch them for 100% offline use with `bash scripts/install-linux.sh --with-asr-model`.

- **Three ASR Modes & Trade-offs**:
  1. **Maximum coverage — contiguous fixed windows (`coverage`, Default)**:
     - **Trade-off**: Maximum dialogue recall/completeness (catches music-buried lines and shouts like ちくしょう over loud BGM), but timing is coarser (~window-granular, default 5.0s) and may include background sound effects or minor hallucinations during instrumental sequences.
     - **How it Works**: Transcribes the entire audio track in contiguous fixed windows (default 5.0s, configurable via `NIHONGO_WHISPER_WINDOW`) using Anime-Whisper (`quantumcookie/anime-whisper-ct2-int8`), merges adjacent cues with overlap/continuation matching, deduplicates hallucination repeats, and caps durations with `post_process_cues`.
     - *Note on Frame-Accurate Anime Subtitles*: Achieving true 100% complete *and* frame-accurate subtitle timing over heavy anime action BGM requires deep vocal stem separation (e.g. Demucs / MDX-Net), which is intentionally out of scope due to multi-gigabyte models and heavy CPU/GPU overhead.
  2. **Accurate — anime + kotoba hybrid (`hybrid`, slower)**:
     - **Trade-off**: Best word accuracy + tight subtitle timing, but ~2x slower and can occasionally miss dialogue completely buried in loud action music (inherited from acoustic VAD/kotoba segmentation limits).
     - **How it Works**: Transcribes full audio with Kotoba-Whisper (`kotoba-tech/kotoba-whisper-v2.0-faster`) to extract acoustic speech windows, frees timing model RAM, and transcribes each window with Anime-Whisper (`quantumcookie/anime-whisper-ct2-int8`) using `clip_timestamps`.
  3. **Fast — Single-Model Pass (`single`)**:
     - **Trade-off**: Fastest single-pass execution (~1x time), but either timing is coarse (Anime-Whisper) or specialized anime slang vocabulary accuracy is lower (Kotoba-Whisper / large-v3).

- **GUI Model Selection (File &rarr; Speech Recognition Model)**:
  Select your desired speech recognition mode directly from the GUI menu. Your preference is persisted across application sessions in `QSettings`:
  - **Maximum coverage — catches all lines incl. over music (default)**: Mode `coverage` (~768MB download; fixed 5.0s windows).
  - **Accurate — anime + kotoba hybrid (slower)**: Mode `hybrid` (downloads ~600MB + ~768MB on first use).
  - **Fast — kotoba only**: Mode `single` with `kotoba-tech/kotoba-whisper-v2.0-faster` (~600MB download, fast single pass).
  - **Anime only (experimental timing)**: Mode `single` with `quantumcookie/anime-whisper-ct2-int8` (~768MB download, fine-tuned on anime/VN dialogue).
  - **High accuracy — large-v3 (~3GB, slow)**: Mode `single` with `Systran/faster-whisper-large-v3` (~3GB download, maximum multi-speaker accuracy, higher RAM usage).
  - *Selecting a model in the menu shows its download size and does NOT trigger a download until subtitle generation is started.*

- **Environment Variable Overrides**:
  - `NIHONGO_WHISPER_MODE`: Force pipeline mode (`coverage`, `hybrid`, or `single`).
  - `NIHONGO_WHISPER_WINDOW`: Sliding window length in seconds for coverage mode (default `5.0`).
  - `NIHONGO_WHISPER_TEXT_MODEL`: Override text model ID for hybrid and coverage modes (default `quantumcookie/anime-whisper-ct2-int8`).
  - `NIHONGO_WHISPER_TIMING_MODEL`: Override timing model ID for hybrid mode (default `kotoba-tech/kotoba-whisper-v2.0-faster`).
  - `NIHONGO_WHISPER_MODEL`: Override single-model ID (default `kotoba-tech/kotoba-whisper-v2.0-faster`).
  - `NIHONGO_WHISPER_MODELS`: Custom model cache directory (defaults to `~/.cache/huggingface`).
  - `NIHONGO_WHISPER_VAD`: Set `1` to enable Silero VAD in single mode.

- **Accurate Timing & Gap Handling**: Generated subtitle cues are automatically post-processed and timing-tightened:
  - Cue on-screen durations are capped according to dialogue length (`max(1.5s, min(7.0s, len * 0.35s))`) and clamped to the start of subsequent cues so subtitles do not linger across silent gaps or instrumental breaks.
  - Consecutive hallucination repeats and split-sentence boundary overlaps are automatically detected, merged, and deduplicated.
  - The subtitle overlay cleanly clears during speech pauses and silence.

- **Manual Timing Nudge**: If AI or external subtitle timing runs slightly off-sync, press <kbd>,</kbd> / <kbd>.</kbd> (or use **View &rarr; Subtitle Sync**) to adjust the sync offset in real-time by ±0.1s increments.

- **How to Use**:
  1. Open your video or audio file in Nihongo Player (`File -> Open Video...`).
  2. Choose your speech mode in **File &rarr; Speech Recognition Model** (optional; defaults to Maximum coverage).
  3. Select **File &rarr; Generate Japanese Subtitles (AI)…**.
  4. The background worker will process the audio, showing progress and mode-specific status indicators (*Transcribing all audio (max coverage)…*, *Analyzing timing…*, or *Transcribing (accurate)…*).
  5. Once generated, the `.srt` is saved alongside your video and automatically loaded into the player with furigana annotations and English translations.

---

## Licenses & Credits

Nihongo Player is free software licensed under the **GNU General Public License v3.0 (GPL-3.0)**.

### Third-Party Components & Datasets

- **Application Code**: Licensed under the [GNU General Public License v3.0](LICENSE).
- **Application Icon**: App icon designed and created by the project owner; bundled with the application.
- **Anime-Whisper & Kotoba-Whisper & faster-whisper**: Japanese speech recognition models (`quantumcookie/anime-whisper-ct2-int8`, `kotoba-tech/kotoba-whisper-v2.0-faster`) and faster-whisper inference engine, licensed under Apache License 2.0 / MIT License.
- **Helsinki-NLP Opus-MT (`Helsinki-NLP/opus-mt-ja-en`)**: Neural machine translation model converted to CTranslate2 format, licensed under the **Apache License 2.0**.
- **EDRDG Dictionaries (JMdict, JMnedict, KANJIDIC2)**:
  > *This package uses the JMdict, JMnedict, and KANJIDIC dictionary files. These files are the property of the Electronic Dictionary Research and Development Group, and are used in conformance with the Group's licence.*
  Licensed under **Creative Commons Attribution-ShareAlike 3.0 / 4.0 (CC-BY-SA)**.
- **UniDic-lite**: Morphological dictionary database licensed under **BSD-3-Clause** / MeCab license.
- **Fugashi & MeCab**: Japanese morphological analyzer bindings licensed under **MIT License**.
- **PySide6 (Qt6 for Python)**: Cross-platform GUI toolkit licensed under **GNU Lesser General Public License v3.0 (LGPL-3.0)**.
- **libmpv / python-mpv**: Video playback engine licensed under **GPL-2.0+ / LGPL-2.1+**.
- **pysubs2**: Subtitle parsing library licensed under **BSD-3-Clause**.

See the [NOTICE](NOTICE) file for full copyright notices and license texts.
