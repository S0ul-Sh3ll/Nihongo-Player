# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for Nihongo Player desktop application.

Cross-platform spec configured for Linux, macOS, and Windows.
Collects PySide6 Qt bindings, UniDic/Fugashi Japanese tokenizer, Jamdict dictionaries,
CTranslate2 neural machine translation runtime and quantized Opus-MT model.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

spec_path = Path(SPECPATH).resolve()
project_root = spec_path.parent

# Read application version from __init__.py
app_version = "0.1.0"
init_file = project_root / "src" / "nihongo_player" / "__init__.py"
if init_file.is_file():
    for line in init_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            app_version = line.split("=")[1].strip().strip("\"'")
            break

datas = []
binaries = []
hiddenimports = [
    "mpv",
    "pysubs2",
    "jaconv",
    "nihongo_player",
    "nihongo_player.__main__",
    "nihongo_player.app",
    "nihongo_player.subs.loader",
    "nihongo_player.subs.tracker",
    "nihongo_player.player.mpv_widget",
    "nihongo_player.player.libmpv_loader",
    "nihongo_player.player.timeline",
    "nihongo_player.ja.annotate",
    "nihongo_player.ja.tokenizer",
    "nihongo_player.ja.furigana",
    "nihongo_player.ja.dictionary",
    "nihongo_player.mt.translator",
    "nihongo_player.setup.first_run",
    "nihongo_player.ui.overlay",
    "nihongo_player.ui.study_panel",
    "nihongo_player.resources",
]

# 1. Collect PySide6 minimal (rely on PyInstaller's PySide6 hook, do not collect_all("PySide6"))
hiddenimports.extend(["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"])

# 2. Collect unidic_lite dictionary data
datas.extend(collect_data_files("unidic_lite"))
hiddenimports.extend(collect_submodules("unidic_lite"))

# 3. Collect fugashi
fugashi_datas, fugashi_bins, fugashi_hidden = collect_all("fugashi")
datas.extend(fugashi_datas)
binaries.extend(fugashi_bins)
hiddenimports.extend(fugashi_hidden)

# 4. Collect jamdict and jamdict_data
datas.extend(collect_data_files("jamdict"))
datas.extend(collect_data_files("jamdict_data"))
hiddenimports.extend(collect_submodules("jamdict"))
hiddenimports.extend(collect_submodules("jamdict_data"))

# 5. Collect ctranslate2
ct2_datas, ct2_bins, ct2_hidden = collect_all("ctranslate2")
datas.extend(ct2_datas)
binaries.extend(ct2_bins)
hiddenimports.extend(ct2_hidden)

# 6. Collect sentencepiece
sp_datas, sp_bins, sp_hidden = collect_all("sentencepiece")
datas.extend(sp_datas)
binaries.extend(sp_bins)
hiddenimports.extend(sp_hidden)

# 7. Bundle offline Opus-MT translation model directory if present
model_dir = project_root / "models" / "opus-ja-en-ct2"
if model_dir.is_dir():
    datas.append((str(model_dir), "models/opus-ja-en-ct2"))

# 8. Bundle application icon assets for runtime window icon
icons_dir = project_root / "assets" / "icons"
if icons_dir.is_dir():
    datas.append((str(icons_dir), "assets/icons"))
else:
    datas.append(("assets/icons", "assets/icons"))

# 9. Windows: bundle self-contained libmpv DLL at bundle ROOT if NIHONGO_LIBMPV_DLL is set
if sys.platform == "win32":
    libmpv_dll = os.environ.get("NIHONGO_LIBMPV_DLL")
    if libmpv_dll and os.path.isfile(libmpv_dll):
        binaries.append((libmpv_dll, "."))
    else:
        print("WARNING: NIHONGO_LIBMPV_DLL not set on Windows. libmpv-2.dll will not be bundled.")

excludes = [
    # PySide6 unused modules
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickTest",
    "PySide6.QtQml",
    "PySide6.QtQmlModels",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtRemoteObjects",
    "PySide6.QtTest",
    "PySide6.QtWebSockets",
    "PySide6.QtSql",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtLocation",
    "PySide6.QtHttpServer",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtWebView",
    # Unused heavy third-party packages
    "torch",
    "transformers",
    "tkinter",
    "matplotlib",
    "scipy",
    "pytest",
    "PyQt5",
    "PyQt6",
    "IPython",
    "pandas",
    "numpy",
]

a = Analysis(
    [str(project_root / "src" / "nihongo_player" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(list(set(hiddenimports))),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 9. Prune leftover heavy Qt binaries, plugins, and data files
UNWANTED_PATTERNS = [
    "QtWebEngine",
    "WebEngine",
    "Qt6WebEngine",
    "Qt6Quick",
    "Qt6Qml",
    "Qt63D",
    "Qt6Multimedia",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Pdf",
    "Qt6Designer",
    "Qt6Help",
    "Qt6UiTools",
    "Qt6SpatialAudio",
    "Qt6TextToSpeech",
    "Qt6Scxml",
    "Qt6StateMachine",
    "Qt6Network",
    "Qt6Bluetooth",
    "Qt6Nfc",
    "Qt6Positioning",
    "Qt6Sensors",
    "Qt6SerialPort",
    "Qt6SerialBus",
    "Qt6RemoteObjects",
    "Qt6WebSockets",
    "Qt6Sql",
    "Qt6Test",
    "Qt6VirtualKeyboard",
    "qml/",
    "qml\\",
    "/qml",
    "\\qml",
    "translations",
    "PySide6/assistant",
    "PySide6/designer",
    "PySide6/linguist",
    "PySide6/lrelease",
    "PySide6/lupdate",
    "PySide6/qmlformat",
    "PySide6/qmllint",
    "PySide6/qmlls",
    "PySide6/svgtoqml",
]


def should_keep(entry) -> bool:
    dest = entry[0] if len(entry) > 0 else ""
    src = str(entry[1]) if len(entry) > 1 else ""
    for pat in UNWANTED_PATTERNS:
        if pat in dest or pat in src:
            return False
    return True


a.binaries = [entry for entry in a.binaries if should_keep(entry)]
a.datas = [entry for entry in a.datas if should_keep(entry)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

win_icon = str(project_root / "assets" / "icons" / "icon.ico") if (project_root / "assets" / "icons" / "icon.ico").is_file() else os.path.join("assets", "icons", "icon.ico")
mac_icon = str(project_root / "assets" / "icons" / "icon.icns") if (project_root / "assets" / "icons" / "icon.icns").is_file() else os.path.join("assets", "icons", "icon.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NihongoPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=win_icon if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NihongoPlayer",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="NihongoPlayer.app",
        icon=mac_icon,
        bundle_identifier="dev.nihongoplayer.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
            "CFBundleShortVersionString": app_version,
            "CFBundleIdentifier": "dev.nihongoplayer.app",
            "CFBundleIconFile": "icon.icns",
        },
    )
