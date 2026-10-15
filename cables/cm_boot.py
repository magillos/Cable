"""Boot-orchestration collaborator extracted from ``JackConnectionManager``.

This module hosts the Seam 1 methods documented in
``plans/connection-manager-method-map.md`` that are NOT constructors:
the ``_init_*`` family stays on ``JackConnectionManager`` because they
construct collaborators on ``self`` and are tightly coupled to the
``__init__`` boot sequence. Instead, this module moves:

  * ``_connect_internal_signals`` (CCN 14 brain method — decomposed into
    ``_connect_jack_signals``, ``_connect_ui_signals``, and
    ``_connect_action_signals``).
  * ``_post_init_cleanup`` — orphaned-sink cleanup + save_preset_action enable.
  * ``_recreate_virtual_sinks_if_autostart`` — delegates to UnifiedSinkManager.
  * ``_load_startup_preset_if_configured`` — gated preset load.
  * ``_init_interaction_handlers`` — constructs InteractionManager.
  * ``_activate_jack`` — activates the jack client.
  * ``_connect_action_manager_signals`` — wires ActionManager signals.

Bodies are byte-identical moves (only ``self.X`` → ``ctx.X``). No behaviour
change. Public-API methods on ``JackConnectionManager`` remain as
thin delegators.
"""

import logging

from cable_core import config_keys as keys

logger = logging.getLogger(__name__)


class BootOrchestrator:
    """Owns non-constructor boot behaviour (Seam 1 of ``JackConnectionManager``).

    The ``_init_*`` constructor methods stay on ``JackConnectionManager``
    because they create collaborators (``ConfigManager()``,
    ``jack.Client()``, ``UIManager()``, etc.) and assign them to ``self``.
    This controller handles only the post-construction wiring + cleanup.
    """

    def __init__(self, ctx):
        self.ctx = ctx

    def activate_jack(self):
        """Activate the JACK client."""
        self.ctx.client.activate()

    def post_init_cleanup(self):
        """Perform post-initialization cleanup tasks."""
        ctx = self.ctx
        orphaned_count = ctx.unified_sink_manager.cleanup_orphaned_unified_sinks(
            ctx._jack_service.get_ports()
        )
        if orphaned_count > 0:
            logger.info(
                f"Cleaned up {orphaned_count} orphaned unified sinks on startup."
            )

        save_preset_action = getattr(ctx.action_manager, "save_preset_action", None)
        if save_preset_action:
            save_preset_action.setEnabled(bool(ctx.preset_handler.current_preset_name))

    def recreate_virtual_sinks_if_autostart(self):
        """Recreate stored virtual sinks when running in autostart mode."""
        ctx = self.ctx
        ctx.unified_sink_manager.recreate_sinks_if_autostart(
            ctx.config_manager, ctx._load_startup_preset
        )

    def load_startup_preset_if_configured(self):
        """Load startup preset if configured and requested."""
        ctx = self.ctx
        if (
            ctx._load_startup_preset
            and ctx.preset_handler.startup_preset_name
            and ctx.preset_handler.startup_preset_name != "None"
        ):
            startup_preset = ctx.preset_handler.startup_preset_name
            logger.info(f"Loading startup preset '{startup_preset}'...")
            ctx.preset_handler.load_selected_preset(startup_preset, is_startup=True)

    def init_interaction_handlers(self):
        """Initialize interaction manager and connect tree click handlers."""
        ctx = self.ctx
        from cables.interaction_manager import InteractionManager

        ctx.interaction_manager = InteractionManager(
            highlight_manager=ctx.highlight_manager,
            update_connection_buttons_func=ctx.update_connection_buttons,
            update_midi_connection_buttons_func=ctx.update_midi_connection_buttons,
        )

    def connect_action_manager_signals(self):
        """Connect ActionManager signals to their handlers."""
        ctx = self.ctx
        am = ctx.action_manager
        if am is None:
            return

        am.connect_requested.connect(ctx._on_connect_requested)
        am.disconnect_requested.connect(ctx._on_disconnect_requested)
        am.refresh_requested.connect(
            lambda: ctx.refresh_ports(from_shortcut=True)
        )
        am.zoom_requested.connect(ctx.tab_manager.handle_zoom_request)
        am.tab_switch_requested.connect(
            ctx.tab_manager.handle_tab_switch_request
        )

    # ── _connect_internal_signals (CCN 14 → 3 sub-methods) ─────────────

    def connect_internal_signals(self):
        """Connect internal signals between components.

        Decomposed into 3 sub-stages:
        - ``_connect_jack_signals``: JackService signals (port_registered,
          port_unregistered, reconnected) + connection-view refresh.
        - ``_connect_ui_signals``: UI button toggles, pending-tab switch,
          visibility button, ui_elements dict.
        - ``_connect_action_signals``: ActionManager tab_changed +
          complete_setup + presets/visibility button wiring.
        """
        ctx = self.ctx
        self._connect_jack_signals(ctx)
        self._connect_ui_signals(ctx)
        self._connect_action_signals(ctx)

    def _connect_jack_signals(self, ctx):
        # Connect JackService signals directly for port registration UI updates
        ctx._jack_service.port_registered.connect(ctx._on_port_registered)
        ctx._jack_service.port_unregistered.connect(ctx._on_port_unregistered)

        # Connect JACK signals to connection view refresh
        ctx._connect_jack_signals_to_connection_views()

        # Connect JACK reconnection signal for recovery after PipeWire restart
        ctx._jack_service.reconnected.connect(ctx._on_jack_reconnected)

    def _connect_ui_signals(self, ctx):
        # Connect UI state manager signals
        collapse_btn = getattr(ctx.ui_manager, "collapse_all_button", None)
        if collapse_btn:
            collapse_btn.toggled.connect(ctx.ui_state_manager.toggle_collapse_all)
        untangle_btn = getattr(ctx.ui_manager, "untangle_button", None)
        if untangle_btn:
            untangle_btn.clicked.connect(ctx.ui_state_manager.toggle_untangle_sort)
        zoom_in_btn = getattr(ctx.ui_manager, "zoom_in_button", None)
        if zoom_in_btn:
            zoom_in_btn.clicked.connect(ctx.ui_state_manager.increase_font_size)
        zoom_out_btn = getattr(ctx.ui_manager, "zoom_out_button", None)
        if zoom_out_btn:
            zoom_out_btn.clicked.connect(ctx.ui_state_manager.decrease_font_size)

        tab_widget = getattr(ctx.ui_manager, "tab_widget", None)
        if tab_widget:
            ctx.tab_manager.switch_tab(tab_widget.currentIndex())

    def _connect_action_signals(self, ctx):
        # Connect TabManager tab_changed signal to ActionManager FIRST
        if ctx.tab_manager is not None and ctx.action_manager is not None:
            ctx.tab_manager.tab_changed.connect(ctx.action_manager.update_tab_state)

        # Handle any pending tab switch from initial setup
        pending_switch = getattr(ctx.tab_manager, "_pending_tab_switch", None)
        if pending_switch is not None:
            pending_index = pending_switch
            ctx.tab_manager._pending_tab_switch = None
            ctx.tab_manager.switch_tab(pending_index)

        # Update UI elements dictionary
        ctx.ui_elements.update(
            {
                "tab_widget": ctx.ui_manager.tab_widget,
                "connect_button": getattr(ctx, "connect_button", None),
                "disconnect_button": getattr(ctx, "disconnect_button", None),
                "midi_connect_button": getattr(ctx, "midi_connect_button", None),
                "midi_disconnect_button": getattr(ctx, "midi_disconnect_button", None),
                "bottom_presets_button": ctx.ui_manager.bottom_presets_button,
                "bottom_visibility_button": ctx.ui_manager.bottom_visibility_button,
                "collapse_all_checkbox": ctx.ui_manager.collapse_all_button,
                "output_tree": getattr(ctx, "output_tree", None),
                "input_tree": getattr(ctx, "input_tree", None),
                "midi_output_tree": getattr(ctx, "midi_output_tree", None),
                "midi_input_tree": getattr(ctx, "midi_input_tree", None),
                "graph_main_window": getattr(ctx, "graph_main_window", None),
                "midi_matrix_widget": getattr(ctx, "midi_matrix_widget", None),
            }
        )

        if ctx.action_manager is not None and ctx.ui_state_manager is not None:
            ctx.action_manager.complete_setup(
                state_manager=ctx.ui_state_manager, add_action_callback=ctx.addAction
            )

        ctx.update_undo_redo_buttons()

        if ctx.ui_manager.bottom_presets_button:
            presets_action = getattr(ctx.action_manager, "presets_action", None)
            if presets_action:
                ctx.ui_manager.bottom_presets_button.setDefaultAction(presets_action)
            ctx.ui_manager.bottom_presets_button.setPopupMode(
                __import__("PyQt6.QtWidgets", fromlist=["QToolButton"]).QToolButton.ToolButtonPopupMode.InstantPopup
            )
        if ctx.ui_manager.bottom_visibility_button:
            ctx.ui_manager.bottom_visibility_button.clicked.connect(
                lambda: ctx.show_node_visibility_dialog(
                    ctx._get_current_visibility_port_type()
                )
            )

        # Connect ActionManager signals to handlers
        ctx._connect_action_manager_signals()

        # Wire theme manager for automatic theme-switching propagation
        from cable_core.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(ctx._on_theme_changed)
