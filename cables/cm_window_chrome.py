"""Window-chrome collaborator extracted from ``JackConnectionManager``.

This module hosts the Seam 4 methods documented in
``plans/connection-manager-method-map.md``:

  * ``toggle_fullscreen`` — flips ``_is_fullscreen`` and delegates the heavy
    lifting to :mod:`cables.fullscreen_controller` (which was already
    extracted as a pure-function helper module).
  * ``restore_window_geometry`` / ``save_window_geometry`` — already-thin
    delegates to :func:`cables.window_state.restore_window_geometry` /
    :func:`save_window_geometry`; kept here for cohesion.
  * ``show_node_visibility_dialog`` — opens the visibility dialog via the
    ``NodeVisibilityManager`` collaborator (when present) and propagates the
    manager to the graph scene.
  * ``get_current_visibility_port_type`` — derives the visibility port-type
    string from the current tab text.
  * ``on_activation_change`` — the ``QEvent.Type.ActivationChange`` branch of
    ``changeEvent``; the PaletteChange branch lives on ``ThemeSyncController``
    where the theme watcher/timers reside.

Bodies are byte-identical moves from ``cables/connection_manager.py`` (only
``self.X`` → ``ctx.X`` parameterisation). No behaviour change. The frozen
public-API methods on ``JackConnectionManager`` remain as thin delegators
that call into this controller so existing callers (``cables/tab_manager.py``,
``cables/features/node_visibility_manager.py``, the Qt framework) need no
edits.
"""

import logging
import os
import types
from typing import Any, Optional

from cable_core import config_keys as keys
from cables import fullscreen_controller as fs_ctrl
from cables import window_state as win_state

logger = logging.getLogger(__name__)


class WindowChromeController:
    """Owns window-chrome state and methods Seam 4 of ``JackConnectionManager``.

    Construction is cheap — the controller holds no Qt widgets itself; it
    receives a ``ctx`` namespace exposing the attrs the moved methods read
    (``main_window``, ``ui_manager``, ``tab_manager``,
    ``node_visibility_manager``, ``config_manager``,
    ``_widgets_original_visibility``, ``_is_fullscreen``, and the 6 frozen-API
    private accessors ``_get_graph_main_window`` / ``_get_graph_scene`` /
    etc. set as bound methods on the ``JackConnectionManager`` instance).

    The controller mutates ``ctx._is_fullscreen`` and
    ``ctx._widgets_original_visibility`` in place so the host's state stays
    consistent with what external callers expect (e.g. ``tab_manager`` reads
    ``connection_manager._is_fullscreen`` indirectly via ``fs_ctrl``).
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    # ── Fullscreen toggle ──────────────────────────────────────────────────

    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen on the current tab widget.

        Mirrors the body that lived on ``JackConnectionManager.toggle_fullscreen``
        verbatim except for parameterisation via ``self.ctx`` (which is the
        host ``JackConnectionManager`` instance in production). The host
        retains the ``@pyqtSlot()``-decorated public delegator so Qt slot
        wiring is unaffected.
        """
        ctx = self.ctx
        tab_widget = getattr(ctx.ui_manager, "tab_widget", None)
        if not tab_widget:
            logger.error("Error: Tab widget not found.")
            return

        current_tab_widget = tab_widget.currentWidget()
        if not current_tab_widget:
            logger.debug("Fullscreen toggle requested, but no active tab found.")
            return

        ctx._is_fullscreen = not ctx._is_fullscreen

        # Build a lightweight context the fullscreen helpers operate over.
        # Graph-tab internal-control toggling is supplied here so the helpers
        # stay decoupled from graph_main_window.
        graph_window = ctx._get_graph_main_window()
        graph_toggle = (
            getattr(graph_window, "toggle_internal_controls", None)
            if graph_window else None
        )

        fs_ctx = types.SimpleNamespace(
            main_window=ctx,
            ui_manager=ctx.ui_manager,
            visibility_map=ctx._widgets_original_visibility,
            tab_manager=ctx.tab_manager,
            toggle_graph_internal_controls=graph_toggle,
        )

        if ctx._is_fullscreen:
            fs_ctrl.enter_fullscreen(fs_ctx, current_tab_widget)
            ctx.showFullScreen()
        else:
            ctx.showNormal()
            fs_ctrl.exit_fullscreen(fs_ctx, current_tab_widget)

        if ctx.centralWidget() and ctx.centralWidget().layout():
            ctx.centralWidget().layout().activate()
        if (
            current_tab_widget
            and current_tab_widget.layout()
        ):
            current_tab_widget.layout().activate()

    # ── Window geometry delegates ─────────────────────────────────────────

    def restore_window_geometry(self) -> None:
        """Restore saved window geometry, or apply first-launch defaults."""
        win_state.restore_window_geometry(self.ctx, self.ctx.config_manager)

    def save_window_geometry(self) -> None:
        """Persist current window geometry to config."""
        win_state.save_window_geometry(self.ctx, self.ctx.config_manager)

    # ── Node visibility dialog ────────────────────────────────────────────

    def show_node_visibility_dialog(self, tab_type: str = "graph") -> None:
        """Show the node visibility configuration dialog."""
        ctx = self.ctx
        if ctx.node_visibility_manager is not None:
            ctx.node_visibility_manager.show_configuration_dialog(ctx, tab_type)

            # After dialog closes, pass node visibility manager to graph_main_window.scene if needed
            scene = ctx._get_graph_scene()
            if scene:
                scene.set_node_visibility_manager(ctx.node_visibility_manager)
                # Refresh the graph view
                scene.full_graph_refresh()

    def get_current_visibility_port_type(self) -> str:
        """Get the port type for the current tab's visibility dialog."""
        ctx = self.ctx
        if ctx.ui_manager is None or not ctx.ui_manager.tab_widget:
            return keys.TAB_AUDIO
        current_index = ctx.ui_manager.tab_widget.currentIndex()
        tab_text = ctx.ui_manager.tab_widget.tabText(current_index)
        return keys.TAB_DISPLAY_MAP.get(tab_text, keys.TAB_AUDIO)

    # ── changeEvent ActivationChange branch ───────────────────────────────

    def on_activation_change(self) -> None:
        """Handle ``QEvent.Type.ActivationChange``.

        Extracted verbatim from the ActivationChange branch of
        ``JackConnectionManager.changeEvent``. The ``PaletteChange`` branch is
        handled by ``ThemeSyncController.on_palette_change``; the host's
        ``changeEvent`` dispatches to both.
        """
        ctx = self.ctx
        is_focused = ctx.isActiveWindow()
        if ctx.ui_state_manager is not None:
            ctx.ui_state_manager.handle_focus_change(is_focused)
        if is_focused and ctx.cable_widget is not None:
            current_tab_index = ctx.ui_manager.tab_widget.currentIndex()
            current_tab_text = ctx.ui_manager.tab_widget.tabText(current_tab_index)
            if current_tab_text == "Cable":
                ctx.cable_widget._apply_current_settings()
                ctx.cable_widget._apply_devices()
                ctx.cable_widget._apply_nodes()
                ctx.cable_widget.update_latency_display()
        # Manage ALSA mixer updates based on focus and active tab
        tab_widget = getattr(ctx.ui_manager, "tab_widget", None)
        alsa_mixer_tab = getattr(ctx.ui_manager, "alsa_mixer_tab_widget", None)
        if tab_widget and alsa_mixer_tab and ctx.alsa_mixer_app is not None:
            current_tab_index = tab_widget.currentIndex()
            current_widget = tab_widget.widget(current_tab_index)
            is_alsa_mixer_tab_active = current_widget == alsa_mixer_tab
            if is_alsa_mixer_tab_active:
                if is_focused:
                    ctx.alsa_mixer_app.start_updates()
                else:
                    ctx.alsa_mixer_app.stop_updates()
