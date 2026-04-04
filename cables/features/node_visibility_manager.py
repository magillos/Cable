"""
NodeVisibilityManager - Manages node visibility preferences

This class manages node visibility settings for different views (Audio, MIDI, Graph).
It uses the NodeVisibilityManagerInterface to access the capabilities it needs from
the main application, enabling better testability and reduced coupling.
"""

import os
import json
from typing import Any, Dict, Optional, Set, TYPE_CHECKING, List
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QPushButton,
    QScrollArea,
    QWidget,
    QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from cables.jack_service import get_jack_service
from cable_core import config_keys as keys
from .node_visibility_dialog import NodeVisibilityDialog

import logging

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cables.interfaces import NodeVisibilityManagerInterface
    from cable_core.config import ConfigManager


class NodeVisibilityManager:
    """
    Manages node visibility preferences for the Cables application.

    This class handles saving and loading node visibility settings,
    and provides a dialog for configuring which nodes should be visible.

    The class uses the NodeVisibilityManagerInterface protocol to access capabilities
    from the main application. The connection_manager parameter must implement:
    - ConfigProvider: for config_manager access
    - GraphAccessor: for _get_graph_scene
    - PortTreeProvider: for port trees and selection methods
    - UIRefreshProvider: for refresh_visualizations
    - JACKClientProvider: for client access
    """

    def __init__(
        self,
        connection_manager: "NodeVisibilityManagerInterface",
        config_manager: "ConfigManager",
    ) -> None:
        """
        Initialize the NodeVisibilityManager.

        Args:
            connection_manager: Reference to an object implementing NodeVisibilityManagerInterface.
                               Typically the JackConnectionManager instance.
            config_manager: The ConfigManager instance for settings persistence.
        """
        self.connection_manager = connection_manager
        self.config_manager = config_manager
        self.config_path = os.path.expanduser("~/.config/cable/node_visibility.json")
        self.load_visibility_settings()

    def load_visibility_settings(self) -> None:
        """Load node visibility settings from the config file."""
        # Initialize with empty dictionaries - each tab has its own visibility settings
        # Audio tab
        self.audio_input_visibility: Dict[str, bool] = {}
        self.audio_output_visibility: Dict[str, bool] = {}
        # MIDI tab
        self.midi_input_visibility: Dict[str, bool] = {}
        self.midi_output_visibility: Dict[str, bool] = {}
        # MIDI Matrix tab
        self.midi_matrix_input_visibility: Dict[str, bool] = {}
        self.midi_matrix_output_visibility: Dict[str, bool] = {}
        # Audio Matrix tab
        self.audio_matrix_input_visibility: Dict[str, bool] = {}
        self.audio_matrix_output_visibility: Dict[str, bool] = {}
        # Graph tab (separate from Audio/MIDI tabs)
        self.graph_audio_input_visibility: Dict[str, bool] = {}
        self.graph_audio_output_visibility: Dict[str, bool] = {}
        self.graph_midi_input_visibility: Dict[str, bool] = {}
        self.graph_midi_output_visibility: Dict[str, bool] = {}

        # For backward compatibility
        self.audio_node_visibility: Dict[str, bool] = {}
        self.midi_node_visibility: Dict[str, bool] = {}

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)

                    # Load legacy format if present (for backward compatibility)
                    if "audio" in data:
                        self.audio_node_visibility = data.get("audio", {})
                    if "midi" in data:
                        self.midi_node_visibility = data.get("midi", {})

                    # Load new format
                    self.audio_input_visibility = data.get("audio_input", {})
                    self.audio_output_visibility = data.get("audio_output", {})
                    self.midi_input_visibility = data.get("midi_input", {})
                    self.midi_output_visibility = data.get("midi_output", {})
                    self.midi_matrix_input_visibility = data.get(
                        "midi_matrix_input", {}
                    )
                    self.midi_matrix_output_visibility = data.get(
                        "midi_matrix_output", {}
                    )
                    self.audio_matrix_input_visibility = data.get(
                        "audio_matrix_input", {}
                    )
                    self.audio_matrix_output_visibility = data.get(
                        "audio_matrix_output", {}
                    )
                    # Load graph tab visibility (separate from Audio/MIDI tabs)
                    self.graph_audio_input_visibility = data.get(
                        "graph_audio_input", {}
                    )
                    self.graph_audio_output_visibility = data.get(
                        "graph_audio_output", {}
                    )
                    self.graph_midi_input_visibility = data.get("graph_midi_input", {})
                    self.graph_midi_output_visibility = data.get(
                        "graph_midi_output", {}
                    )

                    # If using legacy format, convert to new format
                    if (
                        self.audio_node_visibility or self.midi_node_visibility
                    ) and not (
                        self.audio_input_visibility
                        or self.audio_output_visibility
                        or self.midi_input_visibility
                        or self.midi_output_visibility
                    ):
                        self._convert_legacy_settings()
            except Exception as e:
                logger.error(f"Error loading node visibility settings: {e}")

    def _convert_legacy_settings(self) -> None:
        """Convert legacy node visibility settings to input/output format."""
        # Convert audio settings
        for node, visible in self.audio_node_visibility.items():
            self.audio_input_visibility[node] = visible
            self.audio_output_visibility[node] = visible

        # Convert MIDI settings
        for node, visible in self.midi_node_visibility.items():
            self.midi_input_visibility[node] = visible
            self.midi_output_visibility[node] = visible

    def save_visibility_settings(self) -> None:
        """Save node visibility settings to the config file."""
        config_dir = os.path.dirname(self.config_path)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)

        data = {
            # Audio tab
            "audio_input": self.audio_input_visibility,
            "audio_output": self.audio_output_visibility,
            # MIDI tab
            "midi_input": self.midi_input_visibility,
            "midi_output": self.midi_output_visibility,
            # MIDI Matrix tab
            "midi_matrix_input": self.midi_matrix_input_visibility,
            "midi_matrix_output": self.midi_matrix_output_visibility,
            # Audio Matrix tab
            "audio_matrix_input": self.audio_matrix_input_visibility,
            "audio_matrix_output": self.audio_matrix_output_visibility,
            # Graph tab (separate from Audio/MIDI tabs)
            "graph_audio_input": self.graph_audio_input_visibility,
            "graph_audio_output": self.graph_audio_output_visibility,
            "graph_midi_input": self.graph_midi_input_visibility,
            "graph_midi_output": self.graph_midi_output_visibility,
        }

        try:
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving node visibility settings: {e}")

    def _extract_client_name(self, node_name: str) -> str:
        """
        Extract the base client name from a node name.
        Handles port names (with ':'), split audio/midi nodes (with ' (Audio)' or ' (MIDI)'),
        and split input/output nodes (with ' (Inputs)' or ' (Outputs)').

        Args:
            node_name: The name of the node (e.g., "Client:port", "Client (Audio)", "Client (MIDI)",
                      "Client (Inputs)", "Client (Outputs)")

        Returns:
            str: The base client name
        """
        # First, get the client name part (before the colon for port names)
        parts = node_name.split(":")
        client_name = parts[0] if parts else node_name

        # Then, strip various suffixes if present
        # Order matters: check longer suffixes first
        if client_name.endswith(" (Audio)"):
            client_name = client_name[:-8]  # Remove ' (Audio)'
        elif client_name.endswith(" (MIDI)"):
            client_name = client_name[:-7]  # Remove ' (MIDI)'
        elif client_name.endswith(" (Inputs)"):
            client_name = client_name[:-9]  # Remove ' (Inputs)'
        elif client_name.endswith(" (Outputs)"):
            client_name = client_name[:-10]  # Remove ' (Outputs)'

        return client_name

    def is_node_visible(
        self, node_name: str, is_midi: bool = False, tab_type: str = "audio"
    ) -> bool:
        """
        Check if a node should be visible.

        This uses OR logic - if EITHER input or output is visible, the node itself
        is considered visible. Individual split parts are then hidden based on
        their specific settings in `_apply_split_part_visibility`.

        For nodes where only one direction has an explicit setting, we query JACK
        to determine if the node has both directions or just one.

        Args:
            node_name: The name of the node to check
            is_midi: Whether this is a MIDI node
            tab_type: The tab type ('audio', 'midi', 'graph')

        Returns:
            bool: True if the node should be visible (any part of it), False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # Select the appropriate visibility dictionaries based on tab type
        if tab_type == "graph":
            if is_midi:
                input_visibility_dict = self.graph_midi_input_visibility
                output_visibility_dict = self.graph_midi_output_visibility
            else:
                input_visibility_dict = self.graph_audio_input_visibility
                output_visibility_dict = self.graph_audio_output_visibility
        else:
            # For audio/midi tabs
            if is_midi:
                input_visibility_dict = self.midi_input_visibility
                output_visibility_dict = self.midi_output_visibility
            else:
                input_visibility_dict = self.audio_input_visibility
                output_visibility_dict = self.audio_output_visibility

        # Check if the client has explicit visibility settings
        has_input_setting = client_name in input_visibility_dict
        has_output_setting = client_name in output_visibility_dict

        # Get visibility values (default to True if not set)
        input_visible = input_visibility_dict.get(client_name, True)
        output_visible = output_visibility_dict.get(client_name, True)

        # If both settings exist, use OR logic
        if has_input_setting and has_output_setting:
            return input_visible or output_visible

        # If only one setting exists, we need to determine if the node actually has both directions
        # Query JACK to check what ports the client has
        if has_input_setting or has_output_setting:
            try:
                jack_service = get_jack_service()

                # Check for input ports
                input_ports = jack_service.get_ports(
                    name_pattern=f"{client_name}:",
                    is_input=True,
                    is_midi=is_midi,
                    is_audio=not is_midi,
                )
                has_inputs = bool(input_ports)

                # Check for output ports
                output_ports = jack_service.get_ports(
                    name_pattern=f"{client_name}:",
                    is_output=True,
                    is_midi=is_midi,
                    is_audio=not is_midi,
                )
                has_outputs = bool(output_ports)

                # If the node only has one direction, use that direction's visibility
                if has_inputs and not has_outputs:
                    # Input-only node
                    return input_visible
                elif has_outputs and not has_inputs:
                    # Output-only node
                    return output_visible
                else:
                    # Bidirectional node - use OR logic with defaults
                    return input_visible or output_visible

            except Exception as e:
                logger.error(f"Error querying ports for {client_name}: {e}")
                # Fall back to OR logic with defaults
                return input_visible or output_visible

        # No settings at all - visible by default
        return True

    def is_input_visible(
        self, node_name: str, is_midi: bool = False, tab_type: str = "audio"
    ) -> bool:
        """
        Check if a node's input should be visible.

        Args:
            node_name: The name of the node to check
            is_midi: Whether this is a MIDI node
            tab_type: The tab type ('audio', 'midi', 'graph')

        Returns:
            bool: True if the node's input should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # Select the appropriate visibility dictionary based on tab type
        if tab_type == "graph":
            visibility_dict = (
                self.graph_midi_input_visibility
                if is_midi
                else self.graph_audio_input_visibility
            )
        else:
            visibility_dict = (
                self.midi_input_visibility if is_midi else self.audio_input_visibility
            )

        # If the node is not in the dictionary, it's visible by default
        return visibility_dict.get(client_name, True)

    def is_output_visible(
        self, node_name: str, is_midi: bool = False, tab_type: str = "audio"
    ) -> bool:
        """
        Check if a node's output should be visible.

        Args:
            node_name: The name of the node to check
            is_midi: Whether this is a MIDI node
            tab_type: The tab type ('audio', 'midi', 'graph')

        Returns:
            bool: True if the node's output should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # Select the appropriate visibility dictionary based on tab type
        if tab_type == "graph":
            visibility_dict = (
                self.graph_midi_output_visibility
                if is_midi
                else self.graph_audio_output_visibility
            )
        else:
            visibility_dict = (
                self.midi_output_visibility if is_midi else self.audio_output_visibility
            )

        # If the node is not in the dictionary, it's visible by default
        return visibility_dict.get(client_name, True)

    def is_midi_matrix_input_visible(self, node_name: str) -> bool:
        """
        Check if a node's input should be visible in the MIDI Matrix.

        Args:
            node_name: The name of the node to check

        Returns:
            bool: True if the node's input should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # If the node is not in the dictionary, it's visible by default
        return self.midi_matrix_input_visibility.get(client_name, True)

    def is_midi_matrix_output_visible(self, node_name: str) -> bool:
        """
        Check if a node's output should be visible in the MIDI Matrix.

        Args:
            node_name: The name of the node to check

        Returns:
            bool: True if the node's output should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # If the node is not in the dictionary, it's visible by default
        return self.midi_matrix_output_visibility.get(client_name, True)

    def is_audio_matrix_input_visible(self, node_name: str) -> bool:
        """
        Check if a node's input should be visible in the Audio Matrix.

        Args:
            node_name: The name of the node to check

        Returns:
            bool: True if the node's input should be visible, False otherwise
        """
        client_name = self._extract_client_name(node_name)
        return self.audio_matrix_input_visibility.get(client_name, True)

    def is_audio_matrix_output_visible(self, node_name: str) -> bool:
        """
        Check if a node's output should be visible in the Audio Matrix.

        Args:
            node_name: The name of the node to check

        Returns:
            bool: True if the node's output should be visible, False otherwise
        """
        client_name = self._extract_client_name(node_name)
        return self.audio_matrix_output_visibility.get(client_name, True)

    def show_configuration_dialog(
        self, parent: Optional[QWidget] = None, tab_type: str = "graph"
    ) -> None:
        """
        Show the node visibility configuration dialog.

        Args:
            parent: The parent widget
            tab_type: The type of tab ('audio', 'midi', 'midi_matrix', 'audio_matrix', or 'graph')
        """
        if tab_type == "midi_matrix":
            dialog = NodeVisibilityDialog(
                self.connection_manager,
                {},  # No audio for MIDI matrix
                {},  # No audio for MIDI matrix
                self.midi_matrix_input_visibility,
                self.midi_matrix_output_visibility,
                parent,
                tab_type,
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Settings are already modified directly since dialog works with references
                self.save_visibility_settings()
                # Apply new visibility settings
                self.apply_visibility_settings()

        elif tab_type == "audio_matrix":
            dialog = NodeVisibilityDialog(
                self.connection_manager,
                self.audio_matrix_input_visibility,
                self.audio_matrix_output_visibility,
                {},  # No MIDI for Audio matrix
                {},  # No MIDI for Audio matrix
                parent,
                tab_type,
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.save_visibility_settings()
                self.apply_visibility_settings()

        elif tab_type == "audio":
            # Audio tab has its own visibility settings
            dialog = NodeVisibilityDialog(
                self.connection_manager,
                self.audio_input_visibility,
                self.audio_output_visibility,
                {},  # No MIDI for Audio tab
                {},  # No MIDI for Audio tab
                parent,
                tab_type,
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.audio_input_visibility = dialog.audio_input_visibility
                self.audio_output_visibility = dialog.audio_output_visibility
                self.save_visibility_settings()
                self.apply_visibility_settings()

        elif tab_type == "midi":
            # MIDI tab has its own visibility settings
            dialog = NodeVisibilityDialog(
                self.connection_manager,
                {},  # No audio for MIDI tab
                {},  # No audio for MIDI tab
                self.midi_input_visibility,
                self.midi_output_visibility,
                parent,
                tab_type,
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.midi_input_visibility = dialog.midi_input_visibility
                self.midi_output_visibility = dialog.midi_output_visibility
                self.save_visibility_settings()
                self.apply_visibility_settings()

        else:  # graph tab
            # Graph tab has its own separate visibility settings
            dialog = NodeVisibilityDialog(
                self.connection_manager,
                self.graph_audio_input_visibility,
                self.graph_audio_output_visibility,
                self.graph_midi_input_visibility,
                self.graph_midi_output_visibility,
                parent,
                tab_type,
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Update settings from dialog
                self.graph_audio_input_visibility = dialog.audio_input_visibility
                self.graph_audio_output_visibility = dialog.audio_output_visibility
                self.graph_midi_input_visibility = dialog.midi_input_visibility
                self.graph_midi_output_visibility = dialog.midi_output_visibility
                self.save_visibility_settings()
                # Apply new visibility settings
                self.apply_visibility_settings()

    def unhide_all_nodes(self, tab_type: str = "all") -> None:
        """
        Reset visibility settings to show all nodes.

        Args:
            tab_type: Which tab's visibility to reset. Options:
                     - "all": Reset all tabs (default for backward compatibility)
                     - "graph": Reset only graph tab
                     - "audio": Reset only audio tab
                     - "midi": Reset only midi tab
                     - "audio_matrix": Reset only audio matrix tab
                     - "midi_matrix": Reset only midi matrix tab
        """
        if tab_type == "all":
            # Clear all visibility dictionaries to reset to default (visible)
            self.audio_input_visibility.clear()
            self.audio_output_visibility.clear()
            self.midi_input_visibility.clear()
            self.midi_output_visibility.clear()
            self.midi_matrix_input_visibility.clear()
            self.midi_matrix_output_visibility.clear()
            self.audio_matrix_input_visibility.clear()
            self.audio_matrix_output_visibility.clear()
            self.graph_audio_input_visibility.clear()
            self.graph_audio_output_visibility.clear()
            self.graph_midi_input_visibility.clear()
            self.graph_midi_output_visibility.clear()
            logger.info("All nodes have been unhidden in all tabs")
        elif tab_type == "graph":
            # Clear only graph visibility dictionaries
            self.graph_audio_input_visibility.clear()
            self.graph_audio_output_visibility.clear()
            self.graph_midi_input_visibility.clear()
            self.graph_midi_output_visibility.clear()
            logger.info("All nodes have been unhidden in graph tab")
        elif tab_type == "audio":
            self.audio_input_visibility.clear()
            self.audio_output_visibility.clear()
            logger.info("All nodes have been unhidden in audio tab")
        elif tab_type == "midi":
            self.midi_input_visibility.clear()
            self.midi_output_visibility.clear()
            logger.info("All nodes have been unhidden in midi tab")
        elif tab_type == "audio_matrix":
            self.audio_matrix_input_visibility.clear()
            self.audio_matrix_output_visibility.clear()
            logger.info("All nodes have been unhidden in audio matrix tab")
        elif tab_type == "midi_matrix":
            self.midi_matrix_input_visibility.clear()
            self.midi_matrix_output_visibility.clear()
            logger.info("All nodes have been unhidden in midi matrix tab")

        # Save the cleared settings
        self.save_visibility_settings()

        # Apply the changes
        self.apply_visibility_settings()

    def hide_client(
        self, client_name: str, is_midi: bool = False, tab_type: str = "audio"
    ) -> None:
        """
        Hide a client completely by setting both input and output visibility to False.

        Args:
            client_name: Name of the client to hide
            is_midi: Whether this is a MIDI client
            tab_type: The tab type ('audio', 'midi', 'graph', etc.)
        """
        client_name = self._extract_client_name(client_name)

        if tab_type == "graph":
            if is_midi:
                self.graph_midi_input_visibility[client_name] = False
                self.graph_midi_output_visibility[client_name] = False
            else:
                self.graph_audio_input_visibility[client_name] = False
                self.graph_audio_output_visibility[client_name] = False
        elif tab_type == "midi":
            self.midi_input_visibility[client_name] = False
            self.midi_output_visibility[client_name] = False
        elif tab_type == "audio":
            self.audio_input_visibility[client_name] = False
            self.audio_output_visibility[client_name] = False
        elif tab_type == "midi_matrix":
            self.midi_matrix_input_visibility[client_name] = False
            self.midi_matrix_output_visibility[client_name] = False
        elif tab_type == "audio_matrix":
            self.audio_matrix_input_visibility[client_name] = False
            self.audio_matrix_output_visibility[client_name] = False

        self.save_visibility_settings()
        self.apply_visibility_settings()

    def apply_visibility_settings(self) -> None:
        """Apply current visibility settings to the port trees."""
        # Update audio tab
        self._update_tree_visibility(
            self.connection_manager.input_tree,
            self.connection_manager.output_tree,
            is_midi=False,
        )

        # Update MIDI tab
        self._update_tree_visibility(
            self.connection_manager.midi_input_tree,
            self.connection_manager.midi_output_tree,
            is_midi=True,
        )

        # Update MIDI matrix
        if self.connection_manager.midi_matrix_widget is not None:
            self.connection_manager.midi_matrix_widget.refresh_matrix()

        # Update Audio matrix
        if self.connection_manager.audio_matrix_widget is not None:
            self.connection_manager.audio_matrix_widget.refresh_matrix()

        # Update graph view
        scene = self.connection_manager._get_graph_scene()
        if scene:
            # Make sure the scene has a reference to this node visibility manager
            if (
                not hasattr(scene, "node_visibility_manager")
                or scene.node_visibility_manager is None
            ):
                scene.set_node_visibility_manager(self)

            # Log changes from dialog to help with debugging
            logger.debug("Applying visibility settings to graph. Current settings:")
            nodes_to_split = []  # Track nodes that need to be split

            # Use graph-specific visibility settings
            for client_name in set(
                list(self.graph_audio_input_visibility.keys())
                + list(self.graph_audio_output_visibility.keys())
                + list(self.graph_midi_input_visibility.keys())
                + list(self.graph_midi_output_visibility.keys())
            ):
                audio_in_visible = self.graph_audio_input_visibility.get(
                    client_name, True
                )
                audio_out_visible = self.graph_audio_output_visibility.get(
                    client_name, True
                )
                midi_in_visible = self.graph_midi_input_visibility.get(
                    client_name, True
                )
                midi_out_visible = self.graph_midi_output_visibility.get(
                    client_name, True
                )

                # Check for partial visibility (one part hidden, one visible)
                if (audio_in_visible != audio_out_visible) or (
                    midi_in_visible != midi_out_visible
                ):
                    logger.debug(
                        f"Node {client_name} has partial visibility - should be split"
                    )
                    logger.debug(
                        f"  Audio in: {audio_in_visible}, Audio out: {audio_out_visible}"
                    )
                    logger.debug(
                        f"  MIDI in: {midi_in_visible}, MIDI out: {midi_out_visible}"
                    )
                    nodes_to_split.append(client_name)

            # Auto-split nodes that need partial visibility but aren't split yet
            self._auto_split_nodes_for_visibility(scene, nodes_to_split)

            # Perform a full refresh to apply visibility settings
            scene.full_graph_refresh()

    def _auto_split_nodes_for_visibility(
        self, scene, nodes_to_split: List[str]
    ) -> None:
        """
        Automatically split nodes that have partial visibility but are not yet split.

        Args:
            scene: The graph scene
            nodes_to_split: List of client names that need to be split
        """
        if not nodes_to_split:
            return

        for client_name in nodes_to_split:
            # Check if the node exists in the scene
            if client_name not in scene.nodes:
                continue

            node = scene.nodes[client_name]

            # Skip if already split
            if node.is_split_origin:
                continue

            # Skip if it's a split part (not an origin)
            if node.is_split_part:
                continue

            # Check if node has both input and output ports (required for splitting)
            has_inputs = bool(node.input_ports)
            has_outputs = bool(node.output_ports)

            if not has_inputs or not has_outputs:
                logger.debug(
                    f"Node {client_name} cannot be split: missing {'inputs' if not has_inputs else 'outputs'}"
                )
                continue

            # Check if the node has a split_handler
            if not hasattr(node, "split_handler"):
                logger.warning(
                    f"Node {client_name} has no split_handler, cannot auto-split"
                )
                continue

            # Perform the split
            try:
                logger.info(f"Auto-splitting node {client_name} for partial visibility")
                node.split_handler.split_node(save_state=True)
            except Exception as e:
                logger.error(f"Error auto-splitting node {client_name}: {e}")

    def _update_tree_visibility(
        self, input_tree: Any, output_tree: Any, is_midi: bool = False
    ) -> None:
        """
        Update the visibility of nodes in the specified trees.

        Args:
            input_tree: The input port tree widget
            output_tree: The output port tree widget
            is_midi: Whether these are MIDI trees
        """
        # For the port trees, we don't need to do anything special here
        # as the port trees are rebuilt by _refresh_single_port_type which
        # uses PortManager._get_ports, which we've updated to handle
        # partial visibility (showing only input or only output)

        # Get the current tab's port type for the refresh
        port_type = keys.TAB_MIDI if is_midi else keys.TAB_AUDIO

        # Store current selections to restore after refresh
        input_selection = None
        output_selection = None

        if input_tree and hasattr(self.connection_manager, "_get_selected_item_info"):
            input_selection = self.connection_manager._get_selected_item_info(
                input_tree
            )

        if output_tree and hasattr(self.connection_manager, "_get_selected_item_info"):
            output_selection = self.connection_manager._get_selected_item_info(
                output_tree
            )

        # Refresh the port trees - this will use our updated _get_ports method
        # to show only the appropriate ports
        self.connection_manager._refresh_single_port_type(port_type)

        # Restore selections if possible
        if (
            input_tree
            and input_selection
            and hasattr(self.connection_manager, "_restore_selection")
        ):
            self.connection_manager._restore_selection(input_tree, input_selection)

        if (
            output_tree
            and output_selection
            and hasattr(self.connection_manager, "_restore_selection")
        ):
            self.connection_manager._restore_selection(output_tree, output_selection)

        # Refresh connections visualization
        self.connection_manager.refresh_visualizations()
