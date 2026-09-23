"""Robust dynamic locator and loader for libmpv.

This module ensures `python-mpv` can locate and load the libmpv shared library
across different deployment environments (system install, custom env overrides,
and bundled/frozen PyInstaller distributions).

Search Order:
    1. Environment variable override:
       - `NIHONGO_LIBMPV`: Explicit path to libmpv shared library.
       - `MPV_DYLIB_PATH`: Standard macOS/mpv override path.
       If either points to an existing file, it is prioritized.
    2. Bundled library search:
       - Looks for `_libs/` directory beside the running executable (`sys.executable`),
         inside PyInstaller bundle (`sys._MEIPASS`), or next to the package root.
       - Checks for platform-specific library filenames:
         * Linux: `libmpv.so.2`, `libmpv.so`
         * macOS: `libmpv.dylib`
         * Windows: `mpv-2.dll`, `libmpv-2.dll`, `libmpv.dll`, `mpv.dll`
    3. System lookup:
       - Leaves `ctypes.util.find_library` unmodified so standard system /
         package-manager paths (e.g., Homebrew, `/usr/lib`, `/usr/local/lib`) are used.

Usage:
    Must be called BEFORE `import mpv`:
    ```python
    from nihongo_player.player.libmpv_loader import ensure_libmpv
    ensure_libmpv()
    import mpv
    ```
"""

from __future__ import annotations

import ctypes.util
import locale
import os
import sys
from pathlib import Path
from typing import Callable

_initialized: bool = False
_resolved_lib_path: str | None = None
_orig_find_library: Callable[[str], str | None] | None = None


def get_resolved_libmpv_path() -> str | None:
    """Return the resolved path to libmpv, or None if system default is used."""
    return _resolved_lib_path


def ensure_libmpv() -> None:
    """Locate and configure libmpv before importing mpv.

    Patches ctypes.util.find_library if a custom or bundled libmpv is found,
    configures DLL directories on Windows, and ensures LC_NUMERIC is set to 'C'
    to prevent libmpv aborting on non-C locales.

    This function is idempotent.
    """
    global _initialized, _resolved_lib_path, _orig_find_library
    if _initialized:
        return

    # libmpv strictly requires LC_NUMERIC="C" to function without crashing/aborting
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except Exception:
        pass

    # On Windows, register bundle & executable directories for DLL resolution
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            try:
                os.add_dll_directory(str(sys._MEIPASS))
            except OSError:
                pass
        exec_dir = Path(sys.executable).resolve().parent
        for d in [exec_dir, exec_dir / "_internal", exec_dir / "_libs"]:
            if d.is_dir():
                try:
                    os.add_dll_directory(str(d))
                except OSError:
                    pass

    found_path: str | None = None

    # 1. Check environment variable overrides
    for env_var in ("NIHONGO_LIBMPV", "MPV_DYLIB_PATH"):
        val = os.environ.get(env_var)
        if val and os.path.isfile(val):
            found_path = str(Path(val).resolve())
            break

    # 2. Check bundled library locations
    if not found_path:
        search_dirs: list[Path] = []

        # PyInstaller temporary extraction directory / internal directory
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            meipass = Path(sys._MEIPASS)
            search_dirs.extend([
                meipass / "_libs",
                meipass,
                meipass / "_internal",
            ])

        # Beside the executable
        exec_dir = Path(sys.executable).resolve().parent
        search_dirs.extend([
            exec_dir / "_libs",
            exec_dir,
            exec_dir / "_internal",
            exec_dir / "_internal" / "_libs",
        ])

        # Beside the package / project root
        pkg_root = Path(__file__).resolve().parent.parent
        project_root = pkg_root.parent.parent
        search_dirs.extend([
            pkg_root / "_libs",
            project_root / "_libs",
            pkg_root,
        ])

        candidate_names = [
            "libmpv.so.2",
            "libmpv.so",
            "libmpv.dylib",
            "mpv-2.dll",
            "libmpv-2.dll",
            "libmpv.dll",
            "mpv.dll",
            "mpv-1.dll",
            "libmpv-1.dll",
        ]

        for s_dir in search_dirs:
            if s_dir.is_dir():
                for name in candidate_names:
                    candidate = s_dir / name
                    if candidate.is_file():
                        found_path = str(candidate.resolve())
                        break
            if found_path:
                break

    # If a specific library path was resolved, patch find_library and DLL search
    if found_path:
        _resolved_lib_path = found_path
        lib_dir = os.path.dirname(found_path)

        # On Windows, register directory for DLL loader resolution
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(lib_dir)
            except OSError:
                pass

        if _orig_find_library is None:
            _orig_find_library = ctypes.util.find_library

        orig = _orig_find_library

        def _patched_find_library(name: str) -> str | None:
            if name == "mpv":
                return found_path
            return orig(name)

        ctypes.util.find_library = _patched_find_library

    _initialized = True
