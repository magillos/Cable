"""
Handler for hiding/showing NodeItems via the NodeVisibilityManager.
Extracted from NodeItem to separate visibility/business logic from the visual item.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cable_core import config_keys as keys

if TYPE_CHECKING:
    from .node_item import NodeItem

logger = logging.getLogger(__name__)


class NodeVisibilityHandler:
    """Handles hide-node operations for a NodeItem.

    Delegates to the scene's ``NodeVisibilityManager`` for persistence
    and applies connection visibility updates via ``SceneConnectionManager``.
    """

    def __init__(self, node_item: NodeItem) -> None:
        """
        Args:
            node_item: The NodeItem instance this handler is associated with.
        """
        self.node_item = node_item

    def hide_node(self) -> None:
        """Hides this node or part based on the NodeVisibilityManager settings."""
        ni = self.node_item
        current_scene = ni.scene()
        node_vis_mgr = (
            getattr(current_scene, "node_visibility_manager", None)
            if current_scene
            else None
        )
        if not node_vis_mgr:
            logger.warning("Cannot hide node: NodeVisibilityManager not available")
            return

        # Determine the client name to hide
        client_name = None

        # For split parts, use the original client name from origin node
        if ni.is_split_part and ni.split_origin_node:
            # Get the original name from the origin node
            client_name = ni.split_origin_node.client_name
        # For split origin, use its own client name
        elif ni.is_split_origin:
            client_name = ni.client_name
        # For normal nodes, use the client name
        else:
            client_name = ni.client_name

        # Use original_client_name if set (for any node type)
        if ni.original_client_name:
            client_name = ni.original_client_name

        # Determine if this is a MIDI node using the is_midi property
        # For split parts, check the origin node which covers all parts
        if ni.is_split_part and ni.split_origin_node:
            is_midi = ni.split_origin_node.is_midi
        else:
            is_midi = ni.is_midi

        if not client_name:
            logger.warning("Cannot hide node: Unable to determine client name")
            return

        # Get a parent widget for the dialog (the view)
        parent_widget = None
        if current_scene.views():
            parent_widget = current_scene.views()[0]

        # Check if we should show the confirmation dialog
        show_dialog = True
        app_config = None

        # Try to get the global config from the connection_manager
        connection_manager = getattr(current_scene, "connection_manager", None)
        if connection_manager:
            config_manager = getattr(connection_manager, "config_manager", None)
            if config_manager:
                # Use the application-level config_manager which has get_bool method
                app_config = current_scene.connection_manager.config_manager
                show_dialog = app_config.get_bool(
                    keys.SHOW_HIDE_NODE_CONFIRMATION, default=True
                )

        # Determine what to hide based on node type
        hide_inputs = False
        hide_outputs = False

        if ni.is_split_part:
            # For split parts, only hide the specific part (input or output)
            if bool(ni.input_ports) and not bool(ni.output_ports):
                # This is the input part
                hide_inputs = True
                message_type = "input" + (" MIDI" if is_midi else " audio")
            elif bool(ni.output_ports) and not bool(ni.input_ports):
                # This is the output part
                hide_outputs = True
                message_type = "output" + (" MIDI" if is_midi else " audio")
            else:
                # This should not happen, but handle it anyway
                hide_inputs = True
                hide_outputs = True
                message_type = "MIDI" if is_midi else "audio"
        else:
            # For regular nodes or split origins, hide both input and output
            hide_inputs = True
            hide_outputs = True
            message_type = "MIDI" if is_midi else "audio"

        if show_dialog and parent_widget:
            # Build custom message based on what's being hidden
            if hide_inputs and hide_outputs:
                message = f"Hide {client_name} {message_type} node?"
            elif hide_inputs:
                message = f"Hide {client_name} input ports?"
            elif hide_outputs:
                message = f"Hide {client_name} output ports?"
            else:
                message = f"Hide {client_name}?"  # Fallback

            from cable_core.dialogs import show_hide_node_confirmation_dialog

            result = show_hide_node_confirmation_dialog(
                parent=parent_widget,
                node_name=client_name,
                message_type=message_type,
                config_manager=app_config,
                custom_message=message,
            )
            if not result:
                return

        # When hiding both inputs and outputs (default Hide action), use hide_client to fully hide
        if hide_inputs and hide_outputs:
            current_scene.node_visibility_manager.hide_client(
                client_name, is_midi, "graph"
            )
        else:
            # Only update specific directions if hiding individual parts
            if is_midi:
                if hide_inputs:
                    current_scene.node_visibility_manager.graph_midi_input_visibility[
                        client_name
                    ] = False
                if hide_outputs:
                    current_scene.node_visibility_manager.graph_midi_output_visibility[
                        client_name
                    ] = False
            else:
                if hide_inputs:
                    current_scene.node_visibility_manager.graph_audio_input_visibility[
                        client_name
                    ] = False
                if hide_outputs:
                    current_scene.node_visibility_manager.graph_audio_output_visibility[
                        client_name
                    ] = False

            # Save and apply the updated settings for partial hide
            current_scene.node_visibility_manager.save_visibility_settings()

        # When hiding a node part, also hide its connections if this is a split part
        if ni.is_split_part:
            # For split parts, hide connections before applying visibility settings
            # which will eventually hide the node
            connection_mgr = getattr(current_scene, "connection_mgr", None)
            if connection_mgr:
                connection_mgr.update_node_connections_visibility(ni, False)

        # Apply the changes which will hide the node(s)
        current_scene.node_visibility_manager.apply_visibility_settings()

        # Do a full refresh of all connection visibility to ensure consistency
        connection_mgr = getattr(current_scene, "connection_mgr", None)
        if connection_mgr:
            connection_mgr.refresh_all_connection_visibility()