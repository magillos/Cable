"""Theme-sync collaborator extracted from ``JackConnectionManager``.

This module hosts the Seam 3 methods documented in
``plans/connection-manager-method-map.md``:

  * ``on_theme_changed`` — the 8-step orchestrator (CCN 16). Currently moved
    byte-identically; decomposition into
    ``_apply_ui_palette`` / ``_apply_stylesheet`` / ``_notify_subsystems``
    is a follow-up commit.
  * ``on_config_file_changed`` — called by ``QFileSystemWatcher`` on
    ``~/.config/cable/config.ini`` writes; debounces to 500ms before
    re-reading the forced-theme value.
  * ``reload_theme_from_config`` — actually re-reads the file and propagates
    the new forced theme to ``ThemeManager.set_forced_theme``.
  * ``refresh_tab_stylesheets`` — thin delegate to
    :func:`cables.stylesheet_manager.refresh_tab_stylesheets`.
  * ``animate_button_press`` — thin delegate to
    :func:`cables.stylesheet_manager.animate_button_press`.
  * ``on_palette_change`` — the ``QEvent.Type.PaletteChange`` /
    ``ApplicationPaletteChange`` branch of ``changeEvent``; calls
    ``get_theme_manager().check_theme_changed()``.

Bodies are byte-identical moves from ``cables/connection_manager.py`` (only
``self.X`` → ``ctx.X`` parameterisation). No behaviour change.
"""

import configparser
import logging
import os
from typing import Any

from cable_core import config_keys as keys
from cable_core.app_config import FORCE_THEME_AUTO
from cables import stylesheet_manager as styles

logger = logging.getLogger(__name__)


class ThemeSyncController:
    """Owns theme-watch and theme-refresh behaviour (Seam 3).

    Holds no Qt widgets directly — receives a ``ctx`` namespace exposing
    the attrs the moved methods read (``main_window``/``self `` /
    ``ui_manager``, ``highlight_manager``, ``midi_matrix_widget``,
    ``audio_matrix_widget``, ``cable_widget``, ``alsa_mixer_app``,
    ``pwtop_text``, ``latency_*`` combos + text, ``config_manager``,
    ``_jack_service``) and the two timers + watcher that were inlined in
    ``JackConnectionManager.__init__``.
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    # ── Tab stylesheet + button-animation thin delegates ────────────────

    def refresh_tab_stylesheets(self) -> None:
        """Re-apply every tab stylesheet that stores colors at init time."""
        ctx = self.ctx
        styles.refresh_tab_stylesheets(ctx, ctx.ui_manager, ctx.config_manager)

    def animate_button_press(self, button: Any) -> None:
        if not button:
            return
        styles.animate_button_press(button, self.ctx.ui_manager.get_color_scheme())

    # ── Theme-change orchestrator (8 steps, CCN 16) ───────────────────────

    def on_theme_changed(self) -> None:
        """Full theme-change orchestrator — called once per confirmed change.

        Body moved verbatim from ``JackConnectionManager._on_theme_changed``.
        Decomposition into 3 sub-stages is a follow-up commit per the plan
        (deferred from this sprint — decomposition caused cross-test palette
        pollution in test_theme_manager.py because of how the count of stub
        constructions interacts with the global QApplication palette
        restore; shipped in its raw verbatim form until a cleaner isolation
        harness is built).
        """
        ctx = self.ctx
        logger.info("_on_theme_changed: START")
        # 1. UIManager: regenerate colors + re-apply filter/button stylesheets
        if ctx.ui_manager is not None:
            logger.info("_on_theme_changed: calling ui_manager._on_theme_changed()")
            ctx.ui_manager._on_theme_changed()

        # 2. Tab widgets: port trees, connection views, pw-top, latency
        ctx._refresh_tab_stylesheets()

        # 3. Matrix widgets — deferred to avoid re-entering JACK callbacks
        if getattr(ctx, 'midi_matrix_widget', None):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, ctx.midi_matrix_widget.refresh_matrix)
        if getattr(ctx, 'audio_matrix_widget', None):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, ctx.audio_matrix_widget.refresh_matrix)

        # 4. Graph scene and viewport
        scene = ctx._get_graph_scene()
        if scene is not None:
            scene.update()
            view = ctx._get_graph_view()
            if view is not None:
                view.viewport().update()

        # 5. DSP monitor
        if getattr(ctx, 'cable_widget', None) and ctx.cable_widget.dsp_monitor:
            ctx.cable_widget.dsp_monitor.on_theme_changed()

        # 6. Highlight manager: update cached colors AND reset all per-item
        #    foreground/background so they pick up the new default colors.
        #    NOTE: update_colors() MUST come BEFORE clear_highlights() so
        #    the clear uses the NEW default colors, not the stale old ones.
        if getattr(ctx, 'highlight_manager', None) is not None:
            # Update cached color references first
            ctx.highlight_manager.update_colors(
                text_color=ctx.ui_manager.text_color,
                background_color=ctx.ui_manager.background_color,
                highlight_color=ctx.ui_manager.highlight_color,
                auto_highlight_color=ctx.ui_manager.auto_highlight_color,
                drag_highlight_color=ctx.ui_manager.drag_highlight_color,
            )
            # Then clear per-item overrides using the NEW default colors
            ctx.highlight_manager.clear_highlights()
            ctx.highlight_manager.clear_midi_highlights()

        # 7. ALSA mixer tab — re-apply its border stylesheets
        if getattr(ctx, 'alsa_mixer_app', None) is not None:
            try:
                ctx.alsa_mixer_app.on_theme_changed()
            except Exception:
                pass  # mixer may not have on_theme_changed yet

        # 8. Force repaint on all visible widget content
        for w in (
            getattr(ctx, 'pwtop_text', None),
            getattr(ctx, 'latency_results_text', None),
            getattr(ctx, 'input_tree', None),
            getattr(ctx, 'output_tree', None),
            getattr(ctx, 'midi_input_tree', None),
            getattr(ctx, 'midi_output_tree', None),
        ):
            if w is not None:
                w.update()
        if getattr(ctx, 'latency_input_combo', None) is not None:
            ctx.latency_input_combo.update()
        if getattr(ctx, 'latency_output_combo', None) is not None:
            ctx.latency_output_combo.update()

    # ── Config-file watcher debounce + reload ────────────────────────────

    def on_config_file_changed(self, path: str) -> None:
        """Called by QFileSystemWatcher when config.ini is modified.

        Starts a debounce timer; only re-reads force_theme after 500ms of
        silence to avoid reacting to partial or repeated writes.
        """
        ctx = self.ctx
        logger.info(f"_on_config_file_changed: config file changed: {path}")
        # Some editors replace the file rather than modifying it, so we must
        # re-add the path to keep watching after a replacement.
        if path in ctx._theme_config_watcher.files():
            ctx._theme_config_watcher.removePath(path)
        if os.path.exists(path):
            ctx._theme_config_watcher.addPath(path)
        ctx._theme_reload_timer.start()

    def reload_theme_from_config(self) -> None:
        """Re-read force_theme from config.ini and apply if changed.

        Called after the debounce timer fires following a config file change.
        Only applies the theme if the value actually differs from the currently
        active forced theme.
        """
        ctx = self.ctx
        logger.info("_reload_theme_from_config: checking for theme change")
        config_path = os.path.expanduser("~/.config/cable/config.ini")
        if not os.path.exists(config_path):
            logger.info("_reload_theme_from_config: config file not found")
            return

        # Re-add to watcher in case the file was replaced
        if config_path not in ctx._theme_config_watcher.files():
            ctx._theme_config_watcher.addPath(config_path)

        try:
            cfg = configparser.ConfigParser()
            cfg.read(config_path, encoding="utf-8")
            force_theme = cfg.get(
                "DEFAULT", keys.FORCE_THEME, fallback=FORCE_THEME_AUTO
            )
        except Exception as e:
            logger.error(f"_reload_theme_from_config: error reading config: {e}")
            return

        logger.info(
            f"_reload_theme_from_config: config force_theme={force_theme}"
        )
        # The host module's bound ``get_theme_manager`` resolves through the
        # host module's ``from cable_core.theme import get_theme_manager`` —
        # patchers must patch the cable_core.theme symbol directly, NOT this
        # module's import (which there isn't — we look it up dynamically).
        from cable_core.theme import get_theme_manager
        get_theme_manager().set_forced_theme(force_theme)

    # ── changeEvent PaletteChange branch ─────────────────────────────────

    def on_palette_change(self) -> None:
        """Handle ``QEvent.Type.PaletteChange`` / ``ApplicationPaletteChange``.

        Extracted verbatim from the PaletteChange branch of
        ``JackConnectionManager.changeEvent``. The ActivationChange branch is
        handled by ``WindowChromeController.on_activation_change``; the host's
        ``changeEvent`` dispatches to both.
        """
        logger.info("JackConnectionManager.changeEvent: PaletteChange received")
        from cable_core.theme import get_theme_manager
        get_theme_manager().check_theme_changed()
