# cable_core/app_config.py
"""
Application constants, version, and shared configuration values.
"""

import os
import sys
from typing import Optional

from PyQt6.QtGui import QIcon

# --- Application Version ---
APP_VERSION = "0.10.9"

# --- Shared Constants ---
EDIT_LIST_TEXT = "Edit List..."


def _extra_icon_paths() -> list[str]:
    """Return additional icon search directories for packaged installations.

    Covers Flatpak (``/app/share/…``), and standard system paths
    (``/usr/share/…``, ``/usr/local/share/…``) that are not on the
    script's own directory.
    """
    paths: list[str] = []
    if os.path.exists("/.flatpak-info"):
        paths.append("/app/share/icons/hicolor/scalable/apps")
    # Standard system icon paths (Debian, Arch, RPM, etc.)
    paths.append("/usr/share/icons/hicolor/scalable/apps")
    paths.append("/usr/local/share/icons/hicolor/scalable/apps")
    return paths


def load_app_icon(
    icon_name: str = "jack-plug.svg", theme_name: str = "jack-plug"
) -> Optional[QIcon]:
    """Load the application icon, checking frozen/script dir then theme."""
    app_icon = None

    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None) is not None:
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))

    local_icon_path = os.path.join(base_path, icon_name)
    if os.path.exists(local_icon_path):
        app_icon = QIcon(local_icon_path)
        if app_icon.isNull():
            app_icon = None

    # Fallback: check packaged icon directories (Flatpak, Debian, Arch, etc.)
    if app_icon is None:
        for extra_dir in _extra_icon_paths():
            extra_path = os.path.join(extra_dir, icon_name)
            if os.path.exists(extra_path):
                app_icon = QIcon(extra_path)
                if not app_icon.isNull():
                    break
                app_icon = None

    if app_icon is None:
        theme_icon = QIcon.fromTheme(theme_name)
        if not theme_icon.isNull():
            app_icon = theme_icon

    return app_icon


def _detect_dark_mode_from_config() -> Optional[bool]:
    """Read dark-mode setting from KDE/GNOME config files.

    Returns ``True`` (dark), ``False`` (light), or ``None`` (unknown).
    """
    # KDE Plasma: kdeglobals ColorScheme key
    kdeglobals_path = os.path.expanduser("~/.config/kdeglobals")
    if os.path.exists(kdeglobals_path):
        try:
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read(kdeglobals_path, encoding="utf-8")
            scheme = cfg.get("KDE", "ColorScheme", fallback="")
            if scheme:
                return "dark" in scheme.lower()
        except Exception:
            pass

    # GNOME: gtk-application-prefer-dark-theme
    gtk_settings_path = os.path.expanduser("~/.config/gtk-3.0/settings.ini")
    if os.path.exists(gtk_settings_path):
        try:
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read(gtk_settings_path, encoding="utf-8")
            prefer_dark = cfg.getboolean(
                "Settings", "gtk-application-prefer-dark-theme", fallback=False
            )
            return prefer_dark  # True=dark, False=light
        except Exception:
            pass

    return None


def _detect_dark_mode() -> bool:
    """Detect whether the system is using a dark theme.

    Inside a Flatpak sandbox the Qt palette can be stale after a live
    theme switch, so we prioritise reading KDE/GNOME config files first.
    Outside Flatpak the Qt palette is the most reliable source.
    """
    from cable_core.theme import get_theme_manager
    return get_theme_manager().is_dark_mode()


def load_and_apply_theme(config_path: str) -> None:
    """Read force_theme from config.ini and apply a forced Qt palette at startup.

    Called immediately after QApplication creation, before any widgets are built.
    When set to 'dark' or 'light', the Fusion style is activated with a custom
    palette, which causes all :func:`is_dark_mode()` checks that inspect
    ``QApplication.palette().window().color().lightness()`` to return the forced
    value automatically.
    """
    from cable_core import config_keys as _keys
    from cable_core.theme import get_theme_manager

    force_theme = FORCE_THEME_AUTO
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read(config_path, encoding="utf-8")
        force_theme = cfg.get("DEFAULT", _keys.FORCE_THEME, fallback=FORCE_THEME_AUTO)
    except Exception:
        pass

    theme_mgr = get_theme_manager()
    theme_mgr.initialize_theme(force_theme)


def load_tray_icon(monochrome: bool = False, invert: bool = False) -> Optional[QIcon]:
    """Load tray icon, using monochrome variants if enabled.

    When *invert* is ``True`` (and *monochrome* is also ``True``), the icon
    colours are swapped — useful when the auto-detected theme choice does not
    provide enough contrast on the user's desktop environment.
    """
    if not monochrome:
        return load_app_icon()

    # Detect dark mode (with Flatpak fallback)
    is_dark_mode = _detect_dark_mode()

    if invert:
        icon_file = "jack-plug-light.svg" if is_dark_mode else "jack-plug-dark.svg"
        icon_theme_name = "jack-plug-light" if is_dark_mode else "jack-plug-dark"
    else:
        icon_file = "jack-plug-dark.svg" if is_dark_mode else "jack-plug-light.svg"
        icon_theme_name = "jack-plug-dark" if is_dark_mode else "jack-plug-light"
    app_icon = None

    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None) is not None:
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))

    local_icon_path = os.path.join(base_path, icon_file)
    if os.path.exists(local_icon_path):
        app_icon = QIcon(local_icon_path)
        if app_icon.isNull():
            app_icon = None

    # Fallback: check packaged icon directories (Flatpak, Debian, Arch, etc.)
    if app_icon is None:
        for extra_dir in _extra_icon_paths():
            extra_path = os.path.join(extra_dir, icon_file)
            if os.path.exists(extra_path):
                app_icon = QIcon(extra_path)
                if not app_icon.isNull():
                    break
                app_icon = None

    # Check system icon theme before falling back
    if app_icon is None:
        theme_icon = QIcon.fromTheme(icon_theme_name)
        if not theme_icon.isNull():
            app_icon = theme_icon

    # Final fallback to default icon if monochrome not found
    if app_icon is None:
        app_icon = load_app_icon()

    return app_icon


# Main App Window (Cable.py) — first-launch defaults
MAIN_WINDOW_INITIAL_WIDTH = 474
MAIN_WINDOW_INITIAL_HEIGHT = 855

# Connection Manager Window (cables/connection_manager.py) — first-launch defaults
CONN_MANAGER_INITIAL_WIDTH = 1368
CONN_MANAGER_INITIAL_HEIGHT = 1000


# Connection View Width (cables/ui/tab_ui_manager.py)
CONNECTION_VIEW_INITIAL_WIDTH = 250

# PW-Top Tab Font Size (cables/ui/tab_ui_manager.py)
PWTOP_FONT_SIZE_PT = 13

# Connection Line Thickness (cables/connection_visualizer.py)
CONNECTION_LINE_THICKNESS = 2

# Graph View Settings (graph/main_window.py)
DEFAULT_UNTANGLE_VALUES = [2, 3, 4]

# Colour theme constants
FORCE_THEME_AUTO = "auto"
FORCE_THEME_DARK = "dark"
FORCE_THEME_LIGHT = "light"
FORCE_THEME_OPTIONS = [FORCE_THEME_AUTO, FORCE_THEME_DARK, FORCE_THEME_LIGHT]
FORCE_THEME_LABELS = ["Automatic", "Force dark theme", "Force light theme"]

# Quantum/Sample Rate Confirmation Dialog Duration (milliseconds)
QUANTUM_SAMPLE_RATE_CONFIRMATION_DURATION_MS = 1500
