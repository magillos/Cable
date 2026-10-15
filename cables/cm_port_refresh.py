"""Port-refresh collaborator extracted from ``JackConnectionManager``.

This module hosts the Seam 2 methods documented in
``plans/connection-manager-method-map.md``:

  * ``refresh_ports`` — dispatches single- vs full-refresh of port trees.
  * ``_refresh_single_port_type`` — audio vs MIDI tree rebuild (CCN 10).
  * ``refresh_visualizations`` — dispatches update_connections vs
    update_midi_connections based on current port_type.
  * ``_on_port_registered`` / ``_on_port_unregistered`` — JACK callback
    handlers that trigger refresh_ports(refresh_all=True).
  * ``_on_jack_reconnected`` — propagates new jack.Client to collaborators
    + triggers 3 refresh phases (ports, matrix, connection views) with
    per-exception swallowing.
  * ``_connect_jack_signals_to_connection_views`` — wires 4 JackService
    signals × 2 views to request_refresh lambdas.
  * ``update_connections`` / ``update_midi_connections`` — delegates to
    connection_visualizer.update_connection_graphics.
  * ``_handle_unified_port_added`` — sink reconnection on port_added.
  * ``disconnect_all_unified`` / ``reconnect_all_unified`` — thin delegates
    to cables.connection_operations.

Bodies are byte-identical moves from ``cables/connection_manager.py`` (only
``self.X`` → ``ctx.X`` parameterisation). No behaviour change. The frozen
public-API methods on ``JackConnectionManager`` remain as thin delegators
that call into this controller.
"""

import logging
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QTreeWidget

from cables import connection_operations as conn_ops
from cables import selection_utils as sel

logger = logging.getLogger(__name__)


class PortRefreshController:
    """Owns port-tree refresh behaviour (Seam 2 of ``JackConnectionManager``).

    Holds no Qt widgets directly — receives a ``ctx`` namespace exposing
    the attrs the moved methods read (``port_type``, ``port_manager``,
    ``input_tree``, ``output_tree``, ``midi_input_tree``,
    ``midi_output_tree``, ``connection_view``, ``midi_connection_view``,
    ``midi_matrix_widget``, ``audio_matrix_widget``,
    ``ui_manager``, ``ui_state_manager``, ``highlight_manager``,
    ``connection_visualizer``, ``connection_scene``,
    ``midi_connection_scene``, ``node_visibility_manager``,
    ``latency_tester``, ``_jack_service``, ``jack_handler``,
    ``unified_sink_manager``, ``client``, ``_get_graph_scene``,
    ``_get_graph_view``, ``_get_graph_main_window``, ``graph_main_window``,
    plus stub delegates for ``update_connections``, ``update_midi_connections``,
    ``_refresh_single_port_type``, ``_get_selected_item_info``,
    ``_restore_selection``).
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    # ── _handle_unified_port_added ─────────────────────────────────────

    def handle_unified_port_added(
        self,
        port_name: str,
        client_name: str,
        flags: int,
        type_str: str,
        is_input: bool,
    ) -> None:
        ctx = self.ctx
        scene = ctx._get_graph_scene()
        if not scene:
            return

        scene = ctx.graph_main_window.scene
        unified_nodes = scene.get_unified_nodes()

        for node in unified_nodes:
            if node.client_name == client_name:
                logger.debug(
                    f"New port {port_name} for unified client {client_name}. Reconnecting to sink."
                )
                # Use unified sink manager to reconnect ports
                all_ports = ctx._jack_service.get_ports()
                ctx.unified_sink_manager.connect_ports_to_unified_sink(
                    node, ctx.jack_handler, all_ports
                )
                break

    def disconnect_all_unified(self) -> None:
        conn_ops.disconnect_all_unified(
            self.ctx._get_graph_scene(), self.ctx.jack_handler
        )

    def reconnect_all_unified(self) -> None:
        ctx = self.ctx
        scene = ctx._get_graph_scene()
        all_ports = ctx._jack_service.get_ports()
        conn_ops.reconnect_all_unified(
            scene, ctx.jack_handler, ctx.unified_sink_manager, all_ports
        )

    # ── refresh_visualizations ─────────────────────────────────────────

    def refresh_visualizations(self) -> None:
        ctx = self.ctx
        if ctx.port_type == "audio":
            ctx.update_connections()
        else:
            ctx.update_midi_connections()

    # ── _connect_jack_signals_to_connection_views ──────────────────────

    def connect_jack_signals_to_connection_views(self) -> None:
        """Connect JackService signals to connection view refresh.

        This enables event-driven refresh when connections change,
        ensuring the visualization updates without constant polling.
        """
        ctx = self.ctx
        jack_service = ctx._jack_service

        # Audio connection view: refresh on any connection change
        if ctx.connection_view is not None:
            jack_service.connection_made.connect(
                lambda out, inp: ctx.connection_view.request_refresh()
            )
            jack_service.connection_broken.connect(
                lambda out, inp: ctx.connection_view.request_refresh()
            )
            jack_service.port_added.connect(
                lambda *args: ctx.connection_view.request_refresh()
            )
            jack_service.port_removed.connect(
                lambda *args: ctx.connection_view.request_refresh()
            )

        # MIDI connection view: refresh on any connection change
        if ctx.midi_connection_view is not None:
            jack_service.connection_made.connect(
                lambda out, inp: ctx.midi_connection_view.request_refresh()
            )
            jack_service.connection_broken.connect(
                lambda out, inp: ctx.midi_connection_view.request_refresh()
            )
            jack_service.port_added.connect(
                lambda *args: ctx.midi_connection_view.request_refresh()
            )
            jack_service.port_removed.connect(
                lambda *args: ctx.midi_connection_view.request_refresh()
            )

    # ── _on_jack_reconnected ───────────────────────────────────────────

    def on_jack_reconnected(self) -> None:
        """Handle JACK client reconnection after PipeWire restart.

        Updates all direct client references to the new jack.Client instance
        and triggers a full refresh of all tabs.
        """
        ctx = self.ctx
        logger.info("JackConnectionManager: JACK reconnected, updating client references...")

        # Get the new client from JackService
        new_client = ctx._jack_service.client
        if new_client is None:
            logger.error("JackConnectionManager: Reconnected signal received but no client available.")
            return

        # Update direct client references
        ctx.client = new_client
        ctx.jack_handler._client = new_client
        ctx.port_manager.jack_client = new_client

        # Refresh all port trees (Audio + MIDI)
        try:
            ctx.refresh_ports(refresh_all=True)
        except Exception as e:
            logger.error(f"Error refreshing ports after reconnect: {e}")

        # Refresh matrix widgets if they exist
        try:
            if hasattr(ctx, 'midi_matrix_widget') and ctx.midi_matrix_widget is not None:
                ctx.midi_matrix_widget.refresh()
        except Exception as e:
            logger.error(f"Error refreshing MIDI matrix after reconnect: {e}")

        # Refresh connection views
        try:
            if ctx.connection_view is not None:
                ctx.connection_view.request_refresh()
            if ctx.midi_connection_view is not None:
                ctx.midi_connection_view.request_refresh()
        except Exception as e:
            logger.error(f"Error refreshing connection views after reconnect: {e}")

        logger.info("JackConnectionManager: JACK reconnection recovery complete.")

    # ── _refresh_single_port_type ─────────────────────────────────────

    def refresh_single_port_type(self, port_type_to_refresh: str) -> None:
        ctx = self.ctx
        if port_type_to_refresh == "audio":
            input_tree = ctx.input_tree
            output_tree = ctx.output_tree
            update_visuals = ctx.update_connections
            update_buttons = ctx.update_connection_buttons
            is_midi = False
        elif port_type_to_refresh == "midi":
            input_tree = ctx.midi_input_tree
            output_tree = ctx.midi_output_tree
            update_visuals = ctx.update_midi_connections
            update_buttons = ctx.update_midi_connection_buttons
            is_midi = True
        else:
            logger.warning(
                f"Warning: Invalid port_type '{port_type_to_refresh}' passed to _refresh_single_port_type"
            )
            return

        input_filter_edit = getattr(ctx.ui_manager, "input_filter_edit", None)
        current_input_filter = input_filter_edit.text() if input_filter_edit else ""
        output_filter_edit = getattr(ctx.ui_manager, "output_filter_edit", None)
        current_output_filter = output_filter_edit.text() if output_filter_edit else ""

        selected_input_info = ctx._get_selected_item_info(input_tree)
        selected_output_info = ctx._get_selected_item_info(output_tree)

        input_tree.clear()
        output_tree.clear()

        input_ports, output_ports = ctx.port_manager._get_ports(is_midi_tab=is_midi)

        input_tree.populate_tree(input_ports)
        output_tree.populate_tree(output_ports)

        ctx.port_manager.filter_ports(input_tree, current_input_filter)
        ctx.port_manager.filter_ports(output_tree, current_output_filter)

        ctx._restore_selection(input_tree, selected_input_info)
        ctx._restore_selection(output_tree, selected_output_info)

        update_visuals()
        if is_midi:
            ctx.highlight_manager.clear_midi_highlights()
        else:
            ctx.highlight_manager.clear_highlights()
        update_buttons()

        restored_input_item = input_tree.currentItem()
        restored_output_item = output_tree.currentItem()

        if restored_input_item:
            ctx.highlight_manager.apply_highlights_for_selection(
                restored_input_item, input_tree, is_midi
            )

        if restored_output_item:
            if restored_output_item != restored_input_item:
                ctx.highlight_manager.apply_highlights_for_selection(
                    restored_output_item, output_tree, is_midi
                )

        if ctx.port_type == port_type_to_refresh:
            ctx.ui_state_manager.apply_collapse_state_to_current_trees()

    # ── refresh_ports ──────────────────────────────────────────────────

    def refresh_ports(
        self, refresh_all: bool = False, from_shortcut: bool = False
    ) -> None:
        ctx = self.ctx
        if refresh_all:
            ctx._refresh_single_port_type("audio")
            ctx._refresh_single_port_type("midi")
        else:
            ctx._refresh_single_port_type(ctx.port_type)

        # Apply node visibility settings after refreshing ports
        if ctx.node_visibility_manager is not None:
            ctx.node_visibility_manager.apply_visibility_settings()

    # ── _on_port_registered / _on_port_unregistered ────────────────────

    def on_port_registered(self, port_name: str, is_input: bool) -> None:
        ctx = self.ctx
        if not ctx.ui_state_manager.are_callbacks_enabled():
            return

        if ctx.latency_tester is not None and (
            port_name == "jack_delay:in" or port_name == "jack_delay:out"
        ):
            logger.debug(
                f"Detected registration of {port_name}, attempting latency auto-connection via LatencyTester..."
            )
            QTimer.singleShot(50, ctx.latency_tester._attempt_latency_auto_connection)

        ctx.refresh_ports(refresh_all=True)

    def on_port_unregistered(self, port_name: str, is_input: bool) -> None:
        ctx = self.ctx
        if not ctx.ui_state_manager.are_callbacks_enabled():
            return
        ctx.refresh_ports(refresh_all=True)

    # ── update_connections / update_midi_connections ───────────────────

    def update_connections(self) -> None:
        ctx = self.ctx
        ctx.connection_visualizer.update_connection_graphics(
            ctx.connection_scene,
            ctx.connection_view,
            ctx.output_tree,
            ctx.input_tree,
            is_midi=False,
        )

    def update_midi_connections(self) -> None:
        ctx = self.ctx
        ctx.connection_visualizer.update_connection_graphics(
            ctx.midi_connection_scene,
            ctx.midi_connection_view,
            ctx.midi_output_tree,
            ctx.midi_input_tree,
            is_midi=True,
        )
