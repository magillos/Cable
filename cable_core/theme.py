"""
Centralized ThemeManager for standardizing theme and color settings.
Handles dark/light mode detection heuristics and semantic color tokens.
"""

import os
import sys
import logging
from typing import Optional, Dict

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# Theme option constants
THEME_AUTO = "auto"
THEME_DARK = "dark"
THEME_LIGHT = "light"


class ThemeManager(QObject):
    """Singleton ThemeManager to provide central theme state and color tokens."""

    theme_changed = pyqtSignal()

    def __init__(self, config_manager=None) -> None:
        super().__init__()
        self.config_manager = config_manager
        self._forced_theme: str = THEME_AUTO
        self._last_is_dark: Optional[bool] = None
        self._detect_timer: Optional[QTimer] = None
        self._native_palette: Optional[QPalette] = None
        self._native_style: Optional[str] = None
        self._applying_palette: bool = False  # re-entrancy guard for paletteChanged recursion
        self._style_hints: Optional[QObject] = None  # Reference keeping styleHints alive to prevent segfaults
        logger.info("ThemeManager instance initialized.")

    def initialize_theme(self, forced_theme_val: str) -> None:
        """Initialize the forced theme setting and connect all detection paths."""
        logger.info(f"ThemeManager.initialize_theme starting. forced_theme_val={forced_theme_val}")
        
        # Capture native system palette/style exactly once, before any forced override.
        # This enables runtime restore when switching back to "Automatic".
        app = QApplication.instance()
        if app is not None and self._native_palette is None:
            logger.info("Capturing native QPalette...")
            self._native_palette = QPalette(app.palette())
            try:
                logger.info("Capturing native style name...")
                self._native_style = app.style().objectName()
                logger.info(f"Captured native style name: {self._native_style}")
            except Exception as e:
                logger.error(f"Error capturing native style name: {e}")
                self._native_style = None

        self._forced_theme = forced_theme_val

        if forced_theme_val != THEME_AUTO:
            logger.info("Forced theme is not AUTO. Applying theme palette...")
            self.apply_theme_palette()

        # Connect to auto-detection signals whenever an app instance is alive.
        app = QApplication.instance()
        if app is not None:
            # Qt 6.5+: colorSchemeChanged fires once per OS theme activation
            try:
                logger.info("Attempting to get QStyleHints from application...")
                self._style_hints = app.styleHints()
                logger.info("Attempting to connect colorSchemeChanged signal...")
                self._style_hints.colorSchemeChanged.connect(self._on_color_scheme_changed)
                logger.info("colorSchemeChanged signal connected successfully.")
            except Exception as e:
                logger.warning(f"Could not connect colorSchemeChanged signal: {e}")

            # paletteChanged is available since Qt 4 and fires whenever
            # QApplication::palette is replaced by the platform plugin.
            try:
                logger.info("Attempting to connect paletteChanged signal...")
                app.paletteChanged.connect(self._on_palette_changed)
                logger.info("paletteChanged signal connected successfully.")
            except Exception as e:
                logger.warning(f"Could not connect paletteChanged signal: {e}")

        # IMPORTANT: Do NOT call apply_theme_palette() again here.
        # The first call above (for forced themes) has already set the correct
        # palette.  Calling it a second time would cause _detect_system_dark_mode()
        # to read the already-overwritten palette instead of the real system
        # palette, making the "matches system" shortcut overwrite the forced
        # palette with the captured native one — breaking forced theme on startup.
        # For AUTO mode the native palette was just captured and is already
        # active, so no explicit re-application is needed either.

        # Snapshot initial state — does NOT emit
        logger.info("Capturing initial theme state snapshot...")
        if self._last_is_dark is None:
            self._last_is_dark = self.is_dark_mode()
            logger.info(f"Captured initial theme state snapshot: _last_is_dark={self._last_is_dark}")
        logger.info("ThemeManager.initialize_theme successfully completed.")

    def is_dark_mode(self) -> bool:
        """Central heuristic for dark mode detection.

        Checks forced overrides first, then falls back to desktop system settings.
        """
        if self._forced_theme == THEME_DARK:
            return True
        if self._forced_theme == THEME_LIGHT:
            return False

        # Fallback to system detection
        return self._detect_system_dark_mode()

    def _detect_system_dark_mode(self) -> bool:
        """Detect whether the system is using a dark theme."""
        # Primary source: Qt application palette (reflects colorSchemeChanged)
        app = QApplication.instance()
        if app is not None:
            palette = app.palette()
            if palette is not None:
                return palette.window().color().lightness() < 128

        # Fallback: config files (KDE, GNOME)
        return self._detect_dark_mode_from_config() or False

    def check_theme_changed(self) -> bool:
        """Idempotent: only emit :attr:`theme_changed` if the effective theme has changed.

        Calls :meth:`is_dark_mode` once immediately. If the result differs from
        :attr:`_last_is_dark`, starts a debounce timer and calls again to
        confirm — this avoids stale-palette false-positives on Wayland/Flatpak.
        Emits :attr:`theme_changed` exactly once per actual theme transition.
        """
        logger.debug("check_theme_changed() called")
        # --- lazy init guard (safe even if called before initialize_theme) ---
        if not hasattr(self, '_forced_theme'):
            logger.debug("check_theme_changed: no _forced_theme yet, returning False")
            return False
        if not hasattr(self, 'theme_changed'):
            logger.debug("check_theme_changed: no theme_changed signal yet, returning False")
            return False
        if self._last_is_dark is None:
            self._last_is_dark = self.is_dark_mode()
            logger.debug(f"check_theme_changed: initialized _last_is_dark = {self._last_is_dark}")
            return False

        current = self.is_dark_mode()
        logger.debug(f"check_theme_changed: current={current}, _last_is_dark={self._last_is_dark}")
        if current != self._last_is_dark:
            # Tentative change: start a confirm timer (but don't restart if already running)
            if self._detect_timer is None:
                self._detect_timer = QTimer(self)
                self._detect_timer.setSingleShot(True)
                self._detect_timer.timeout.connect(self._confirm_theme_change)
            if not self._detect_timer.isActive():
                logger.info(f"check_theme_changed: TENTATIVE theme change detected (dark={current}), starting debounce timer")
                self._detect_timer.start(200)
            else:
                logger.debug(f"check_theme_changed: TENTATIVE change detected but timer already running, ignoring")
        return False

    def _confirm_theme_change(self) -> None:
        """Confirm a pending theme change and emit :attr:`theme_changed` if still valid."""
        current = self.is_dark_mode()
        logger.info(f"_confirm_theme_change: current={current}, _last_is_dark={self._last_is_dark}")
        if current != self._last_is_dark:
            self._last_is_dark = current
            logger.info("_confirm_theme_change: EMITTING theme_changed signal")
            self.theme_changed.emit()
        else:
            logger.info("_confirm_theme_change: theme did not actually change, not emitting")

    def _on_color_scheme_changed(self, new_scheme: object) -> None:
        """Slot for QStyleHints.colorSchemeChanged — auto mode only."""
        logger.info(f"_on_color_scheme_changed called with new_scheme={new_scheme}, _forced_theme={self._forced_theme}")
        if self._forced_theme != THEME_AUTO:
            if self._palette_matches_forced():
                logger.info("_on_color_scheme_changed: forced theme active, palette already matches — skipping")
                return
            logger.info("_on_color_scheme_changed: forced theme active, platform overwrote palette — re-applying")
            self.apply_theme_palette()
            return
        logger.info("_on_color_scheme_changed: scheduling check_theme_changed in 200ms")
        QTimer.singleShot(200, self.check_theme_changed)

    def _on_palette_changed(self, new_palette: 'QPalette') -> None:
        """Slot for QApplication.paletteChanged — auto mode only.

        ``QApplication.paletteChanged`` is emitted when the platform plugin
        propagates a new native palette to the QApplication.  This is the
        broadest possible detection hook: it fires on Flatpak portal updates,
        X11 ``PropertyNotify`` events, Wayland ``xdg_decoration`` changes, and
        any other mechanism that ends up calling ``QApplication::setPalette``
        inside Qt's platform plugin.  Used here as a catch-all last resort.
        """
        logger.info(f"_on_palette_changed called, _forced_theme={self._forced_theme}")
        if not self._applying_palette:
            logger.info("Updating self._native_palette with system palette change...")
            self._native_palette = QPalette(new_palette)

        if self._forced_theme != THEME_AUTO:
            if self._palette_matches_forced():
                logger.info("_on_palette_changed: forced theme active, palette already matches — skipping")
                return
            logger.info("_on_palette_changed: forced theme active, platform overwrote palette — re-applying")
            self.apply_theme_palette()
            return
        logger.info("_on_palette_changed: scheduling check_theme_changed in 200ms")
        QTimer.singleShot(200, self.check_theme_changed)

    def _detect_dark_mode_from_config(self) -> Optional[bool]:
        """Read dark-mode setting from KDE/GNOME config files."""
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
                return prefer_dark
            except Exception:
                pass

        return None

    def _palette_matches_forced(self) -> bool:
        """Return True if the current QApplication palette and style already match
        the forced theme expectations, avoiding unnecessary re-application.
        """
        if self._forced_theme == THEME_AUTO:
            return True  # No forced palette to compare against

        app = QApplication.instance()
        if app is None:
            return True

        current_window = app.palette().color(QPalette.ColorRole.Window)
        current_style = app.style().objectName() if app.style() else ""
        system_is_dark = self._detect_system_dark_mode()

        # Check if the forced theme matches the system's current dark/light state
        if (self._forced_theme == THEME_DARK and system_is_dark) or (
            self._forced_theme == THEME_LIGHT and not system_is_dark
        ):
            # We expect the native style (if known) and a palette of matching lightness
            style_matches = True
            if self._native_style:
                style_matches = current_style.lower() == self._native_style.lower()
            
            palette_matches = False
            if self._forced_theme == THEME_DARK:
                palette_matches = current_window.lightness() < 128
            else:
                palette_matches = current_window.lightness() >= 128
                
            return style_matches and palette_matches
        else:
            # We expect Fusion style and our precise hardcoded fallback palette
            style_matches = current_style.lower() == "fusion"
            
            palette_matches = False
            if self._forced_theme == THEME_DARK:
                # Our dark palette uses Window = QColor(32, 35, 38)
                palette_matches = current_window == QColor(32, 35, 38)
            else:  # THEME_LIGHT
                # Our light palette uses Window = QColor(239, 240, 241)
                palette_matches = current_window == QColor(239, 240, 241)
                
            return style_matches and palette_matches

    def get_color(self, token: str) -> QColor:
        """Get the QColor corresponding to a semantic theme token.

        First attempts to query the active QApplication's QPalette to perfectly
        match system colors, falling back to meticulously tuned KDE Plasma 6
        Breeze Light & Dark theme color tokens.
        """
        is_dark = self.is_dark_mode()

        # If a QApplication instance is running, dynamically extract the colors
        # from its QPalette to ensure seamless system/style integration.
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            palette = app.palette()
            if token == "background":
                return palette.color(QPalette.ColorRole.Base)
            elif token == "text":
                return palette.color(QPalette.ColorRole.Text)
            elif token == "highlight":
                return palette.color(QPalette.ColorRole.Highlight)
            elif token == "button":
                return palette.color(QPalette.ColorRole.Button)
            elif token == "connection":
                return palette.color(QPalette.ColorRole.Link)
            elif token == "drag_highlight":
                alt = palette.color(QPalette.ColorRole.AlternateBase)
                if alt.isValid():
                    return alt
            elif token == "matrix_disconnected":
                return palette.color(QPalette.ColorRole.Window)
            elif token == "matrix_self_connection":
                return palette.color(QPalette.ColorRole.AlternateBase)
            elif token == "matrix_hover_highlight":
                highlight = palette.color(QPalette.ColorRole.Highlight)
                if is_dark:
                    return QColor(highlight.red(), highlight.green(), highlight.blue(), 60)
                else:
                    return QColor(highlight.red(), highlight.green(), highlight.blue(), 40)

        # Fallback values meticulously tuned to match KDE Plasma 6 Breeze Light & Dark
        tokens: Dict[str, QColor] = {
            # --- General Cables UI Colors ---
            "background": QColor(27, 30, 32) if is_dark else QColor(255, 255, 255),
            "text": QColor(252, 252, 252) if is_dark else QColor(35, 38, 41),
            "highlight": QColor(61, 174, 233) if is_dark else QColor(61, 174, 233),
            "button": QColor(49, 54, 59) if is_dark else QColor(252, 252, 252),
            "connection": QColor(29, 153, 243) if is_dark else QColor(0, 100, 200),
            "auto_highlight": QColor(246, 116, 0) if is_dark else QColor(255, 140, 0),
            "drag_highlight": QColor(41, 44, 48) if is_dark else QColor(227, 229, 231),

            # --- Matrix Custom Grid Square Colors ---
            "matrix_disconnected": QColor(32, 35, 38) if is_dark else QColor(239, 240, 241),
            "matrix_self_connection": QColor(41, 44, 48) if is_dark else QColor(227, 229, 231),
            "matrix_hover_highlight": QColor(61, 174, 233, 60) if is_dark else QColor(61, 174, 233, 40),
        }

        return tokens.get(token, QColor(128, 128, 128))

    def apply_theme_palette(self) -> None:
        """Apply a forced QPalette to Fusion style on startup or at runtime
        (e.g. when the Colour theme selector in Other Settings is Applied).
        """
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return

        # Guard against re-entrancy: apply_theme_palette() calls app.setPalette()
        # which triggers paletteChanged → _on_palette_changed → apply_theme_palette()
        # which would recurse indefinitely.
        if self._applying_palette:
            return
        self._applying_palette = True

        if self._forced_theme == THEME_AUTO:
            # Restore native palette/style captured at first initialize_theme.
            # This makes switching back to "Automatic" work without restart.
            if self._native_palette is not None:
                if self._native_style:
                    try:
                        app.setStyle(self._native_style)
                    except Exception:
                        pass
                app.setPalette(QPalette(self._native_palette))
            self._applying_palette = False
            return

        # Forced dark or light.
        # Prefer the captured native as "system" reference (correct at runtime
        # after previous forced palettes have been applied).
        if self._native_palette is not None:
            sys_palette = QPalette(self._native_palette)
            system_is_dark = self._detect_system_dark_mode()
        else:
            sys_palette = app.palette()
            system_is_dark = self._detect_system_dark_mode()

        # If the forced theme matches the system's current dark/light state,
        # reuse the system's native style (e.g. Breeze) and exact native palette.
        if (self._forced_theme == THEME_DARK and system_is_dark) or (
            self._forced_theme == THEME_LIGHT and not system_is_dark
        ):
            if self._native_style:
                current_style = app.style().objectName() if app.style() else ""
                if current_style.lower() != self._native_style.lower():
                    try:
                        app.setStyle(self._native_style)
                    except Exception as e:
                        logger.error(f"Error restoring native style in apply_theme_palette: {e}")
            app.setPalette(sys_palette)
            self._applying_palette = False
            return

        # Otherwise (mismatch), fall back to Fusion style and apply our beautiful
        # and precise KDE Plasma 6 Breeze hardcoded palettes.
        current_style = app.style().objectName() if app.style() else ""
        if current_style.lower() != "fusion":
            app.setStyle("Fusion")

        # Otherwise, fall back to our beautiful and precise KDE Plasma 6 Breeze palettes
        palette = QPalette()

        if self._forced_theme == THEME_DARK:
            # KDE Plasma 6 Breeze Dark Color Scheme
            palette.setColor(QPalette.ColorRole.Window, QColor(32, 35, 38))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(252, 252, 252))
            palette.setColor(QPalette.ColorRole.Base, QColor(27, 30, 32))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(41, 44, 48))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(41, 44, 48))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(252, 252, 252))
            palette.setColor(QPalette.ColorRole.Text, QColor(252, 252, 252))
            palette.setColor(QPalette.ColorRole.Button, QColor(49, 54, 59))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(252, 252, 252))
            palette.setColor(QPalette.ColorRole.BrightText, QColor(218, 68, 83))
            palette.setColor(QPalette.ColorRole.Link, QColor(29, 153, 243))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(61, 174, 233))
            palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
        else:  # THEME_LIGHT
            # KDE Plasma 6 Breeze Light Color Scheme
            palette.setColor(QPalette.ColorRole.Window, QColor(239, 240, 241))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(35, 38, 41))
            palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(227, 229, 231))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(35, 38, 41))
            palette.setColor(QPalette.ColorRole.Text, QColor(35, 38, 41))
            palette.setColor(QPalette.ColorRole.Button, QColor(252, 252, 252))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(35, 38, 41))
            palette.setColor(QPalette.ColorRole.BrightText, QColor(218, 68, 83))
            palette.setColor(QPalette.ColorRole.Link, QColor(29, 153, 243))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(61, 174, 233))
            palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)

        app.setPalette(palette)
        self._applying_palette = False

    def set_forced_theme(self, forced_theme_val: str) -> None:
        """Update forced theme at runtime and refresh the entire UI (no restart).

        Called from SettingsWidgetBuilder when the user Applies the Colour theme
        selector. Idempotent. Always emits theme_changed so every listener
        (graphs, DSP, stylesheets, matrices, tray, etc.) repaints.
        """
        if not hasattr(self, "_forced_theme") or self._forced_theme == forced_theme_val:
            return
        logger.info(
            f"ThemeManager.set_forced_theme: {self._forced_theme} -> {forced_theme_val}"
        )
        self._forced_theme = forced_theme_val
        self.apply_theme_palette()
        self._last_is_dark = self.is_dark_mode()
        self.theme_changed.emit()


_theme_manager_instance: Optional[ThemeManager] = None


def get_theme_manager(config_manager=None) -> ThemeManager:
    """Helper function to get the global singleton ThemeManager."""
    global _theme_manager_instance
    if _theme_manager_instance is None:
        logger.info("get_theme_manager: Creating global singleton ThemeManager instance...")
        _theme_manager_instance = ThemeManager(config_manager)
    elif config_manager is not None and _theme_manager_instance.config_manager is None:
        logger.info("get_theme_manager: Updating config_manager on existing singleton...")
        _theme_manager_instance.config_manager = config_manager
    return _theme_manager_instance
