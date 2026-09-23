"""Resource resolver and asset loading helpers for Nihongo Player.

Supports resolving bundled static assets across development environments,
standard package installations, and PyInstaller one-dir/one-file bundles.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon


def asset_path(relpath: str) -> str:
    """Resolve an absolute path to a bundled asset.

    Works both in dev (relative to the project root or package directory)
    and under PyInstaller runtime (via sys._MEIPASS).

    Search order:
    1. getattr(sys, '_MEIPASS', None) / <relpath> (PyInstaller runtime bundle)
    2. <project_root> / <relpath> (project_root = two levels up from this file's package)
    3. <package_dir> / <relpath> (package-relative directory)

    Returns:
        Absolute path to the first existing location, or best-guess path if not found.
    """
    clean_rel = relpath.lstrip("/\\")

    # 1. PyInstaller bundled temporary directory
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        candidate = Path(meipass) / clean_rel
        if candidate.exists():
            return str(candidate.resolve())

    # Package directory: src/nihongo_player
    package_dir = Path(__file__).resolve().parent
    # Project root: two levels up from package directory (src/nihongo_player -> src -> nihongo-player)
    project_root = package_dir.parent.parent

    # 2. Project root relative (dev mode)
    candidate_project = project_root / clean_rel
    if candidate_project.exists():
        return str(candidate_project.resolve())

    # 3. Package-relative
    candidate_pkg = package_dir / clean_rel
    if candidate_pkg.exists():
        return str(candidate_pkg.resolve())

    # Fallback / best-guess path if not found
    if meipass is not None:
        return str((Path(meipass) / clean_rel).resolve())
    return str(candidate_project.resolve())


def get_app_icon() -> QIcon:
    """Construct and return the application QIcon with multi-resolution PNG pixmaps.

    Adds 512x512, 256x256, and 1024x1024 icon assets for multi-resolution crispness.
    Guarded so missing files or lack of a GUI application context will never crash,
    returning an empty QIcon fallback.
    """
    try:
        from PySide6.QtGui import QGuiApplication, QIcon

        icon = QIcon()
        if QGuiApplication.instance() is None:
            return icon

        for rel in ("assets/icons/icon.png", "assets/icons/icon-256.png", "assets/icons/icon-1024.png"):
            p = asset_path(rel)
            if os.path.isfile(p):
                icon.addFile(p)
        return icon
    except Exception:
        try:
            from PySide6.QtGui import QIcon

            return QIcon()
        except Exception:
            return None  # type: ignore[return-value]
