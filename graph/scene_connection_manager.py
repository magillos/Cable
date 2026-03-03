"""
Manages ConnectionItem lifecycle within JackGraphScene — creation, removal, visibility, and JACK sync.
"""
import jack
import logging
from typing import TYPE_CHECKING, List, Dict, Optional

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtCore import pyqtSlot

from cable_core import config_keys as keys
from cables.utils.connection_colors import get_client_color, client_name_from_port

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .gui_scene import JackGraphScene
    from .node_item import NodeItem
    from .connection_item import ConnectionItem


class SceneConnectionManager:
    """Manages visual connections in the graph scene.
    
    Handles adding, removing, synchronizing, and updating visibility
    of ConnectionItem instances. Delegates port lookups to the scene.
    """

    def __init__(self, scene: 'JackGraphScene') -> None:
        self.scene = scene

    def _get_client_color(self, port_name: str) -> QColor | None:
        """Return a per-client color if colored connections are enabled, else None."""
        config = self.scene.main_config_manager
        if not config or not config.get_bool(keys.GRAPH_COLORED_CONNECTIONS, False):
            return None
        dark_mode = self.scene.palette().color(QPalette.ColorRole.Window).lightness() < 128
        return get_client_color(client_name_from_port(port_name), dark_mode)

    def add_connection(self, out_port_name: str, in_port_name: str) -> None:
        """Add a visual connection between two ports."""
        conn_key = (out_port_name, in_port_name)
        if conn_key in self.scene.connections:
            return  # Already exists visually

        source_port_item = self.scene.find_port_item(out_port_name)
        dest_port_item = self.scene.find_port_item(in_port_name)

        if source_port_item and dest_port_item:
            from .connection_item import ConnectionItem
            client_color = self._get_client_color(out_port_name)
            conn = ConnectionItem(source_port_item, dest_port_item, client_color=client_color)
            self.scene.addItem(conn)
            self.scene.connections[conn_key] = conn
            self.scene.scene_connections_changed.emit()
        else:
            logger.warning(f"Warning: Could not find port items for connection: {out_port_name} -> {in_port_name}")

    def remove_connection(self, out_port_name: str, in_port_name: str) -> None:
        """Remove a visual connection between two ports."""
        conn_key = (out_port_name, in_port_name)
        conn = self.scene.connections.pop(conn_key, None)
        if conn:
            logger.debug(f"Removing visual connection: {out_port_name} -> {in_port_name}")
            conn.destroy()
            self.scene.scene_connections_changed.emit()

    def synchronize_connections_with_jack(self, all_ports: List[jack.Port]) -> None:
        """Adds new visual connections from JACK and removes those not in JACK."""
        logger.debug("Synchronizing connections with JACK...")
        # Clear existing visual connections first
        for conn in list(self.scene.connections.values()):
            conn.destroy()
        self.scene.connections.clear()

        # Rebuild connections by querying JACK
        all_connections_set = set()
        output_ports = [p for p in all_ports if p.is_output]

        if output_ports:
            for out_port in output_ports:
                try:
                    jack_connections = self.scene.graph_jack_handler.get_all_connections(out_port.name)
                    for actual_out, actual_in in jack_connections:
                        all_connections_set.add((actual_out, actual_in))
                except Exception as e:
                    logger.error(f"Error fetching connections for {out_port.name}: {e}")

        # Synchronize visual connections
        for conn_key in all_connections_set:
            self.add_connection(*conn_key)

    def update_connections_visibility(self, node: 'NodeItem') -> None:
        """Updates visibility of connections for a node based on its visibility."""
        if not node.isVisible():
            # Hide all connections for this node's ports
            for port in list(node.input_ports.values()) + list(node.output_ports.values()):
                for conn in port.connections:
                    conn.setVisible(False)
        else:
            # Show connections only if both nodes are visible
            for port in list(node.input_ports.values()) + list(node.output_ports.values()):
                for conn in port.connections:
                    other_port = conn.source_port if port.is_input else conn.dest_port
                    if other_port and other_port.parentItem().isVisible():
                        conn.setVisible(True)

    def update_node_connections_visibility(self, node: 'NodeItem', visible: bool) -> None:
        """Update the visibility of all connections for a node.
        
        Args:
            node: The node whose connections should be updated
            visible: Whether the connections should be visible
        """
        if not node:
            return

        for port_list in [node.input_ports, node.output_ports]:
            for port_item in port_list.values():
                for conn in list(port_item.connections):
                    if conn:
                        conn.setVisible(visible)

    def refresh_all_connection_visibility(self) -> None:
        """Ensure all connections have proper visibility based on their connected ports.
        A connection should only be visible if BOTH its source and destination ports
        are visible.
        """
        for conn_key, conn in list(self.scene.connections.items()):
            if not conn or not conn.source_port or not conn.dest_port:
                continue

            source_node = conn.source_port.parentItem()
            dest_node = conn.dest_port.parentItem()

            should_be_visible = (source_node and dest_node and
                                source_node.isVisible() and
                                dest_node.isVisible())

            conn.setVisible(should_be_visible)

    def update_all_connection_paths(self) -> None:
        """Iterates through all ConnectionItem instances and calls their update_path()
        method to refresh their visual representation.
        """
        for connection_item in self.scene.connections.values():
            connection_item.update_path()
        self.scene.update()

    def clear_all_connections(self) -> None:
        """Destroy and clear all visual connections."""
        for conn in list(self.scene.connections.values()):
            conn.destroy()
        self.scene.connections.clear()

    def handle_connection_made(self, out_port_name: str, in_port_name: str) -> None:
        """Handles the connection_made signal from JackService."""
        logger.debug(f"GraphScene: Connection made - From: {out_port_name}, To: {in_port_name}")
        self.add_connection(out_port_name, in_port_name)

    def handle_connection_broken(self, out_port_name: str, in_port_name: str) -> None:
        """Handles the connection_broken signal from JackService."""
        logger.debug(f"GraphScene: Connection broken - From: {out_port_name}, To: {in_port_name}")
        self.remove_connection(out_port_name, in_port_name)
