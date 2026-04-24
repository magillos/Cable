# --- PyQt Graphical Items - BulkAreaItem ---
"""
QGraphicsItem representing a per-pair bulk connection area on a node
for drag-based mass connect/disconnect of a stereo port pair.

Each BulkAreaItem controls exactly 2 paired PortItems (a stereo pair).
Ports that do not form a recognizable stereo pair get no bulk area.
"""

import logging

from PyQt6.QtWidgets import (
QGraphicsItem, QStyleOptionGraphicsItem, QWidget, QStyle, QGraphicsSceneHoverEvent, QMenu,
QGraphicsSceneMouseEvent, QGraphicsSceneContextMenuEvent
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QAction
)
from PyQt6.QtCore import (
Qt, QRectF, QPointF
)

from . import constants # Import the constants module
import typing
from typing import Any, List

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from .node_item import NodeItem
    from .port_item import PortItem
    from .connection_item import ConnectionItem


class BulkAreaItem(QGraphicsItem):
    """A selectable item representing a per-pair bulk connection area of a NodeItem.

    Unlike the previous design where one bulk area controlled ALL input or
    ALL output ports, each BulkAreaItem now controls exactly 2 paired
    PortItems (a stereo pair detected by ``detect_stereo_pairs()``).

    Attributes:
        parent_node: The NodeItem this bulk area belongs to.
        is_input: True for an input-side bulk, False for output-side.
        paired_ports: List of exactly 2 PortItems this bulk controls.
    """
    def __init__(self, parent_node: 'NodeItem', is_input: bool, paired_ports: List['PortItem']) -> None:
        super().__init__(parent_node)
        self.parent_node = parent_node
        self.is_input = is_input
        self.paired_ports = paired_ports  # Exactly 2 ports
        self._bounding_rect = QRectF(
            0, 0,
            constants.PORT_WIDTH_MIN - (2 * constants.NODE_BULK_AREA_HPADDING),
            constants.NODE_BULK_PAIR_AREA_HEIGHT,
        )
        self._is_hovered = False
        self._is_drag_highlighted = False # For drag hover
        self._connection_highlighted = False # Flag for connection highlighting
        self._mouse_press_pos = None # Store initial press position for drag threshold
        self._is_handling_selection_change = False # Flag to prevent re-entry during selection cascade

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def boundingRect(self) -> QRectF:
        return self._bounding_rect

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Determine background color
        bg_color = constants.NODE_BULK_AREA_COLOR
        if is_selected or self._is_hovered or self._is_drag_highlighted or self._connection_highlighted:
            bg_color = constants.HOVER_HIGHLIGHT_COLOR # Use hover color for consistency

        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen) # No border for the area itself unless selected
        painter.drawRect(self.boundingRect())

        # Text Label
        painter.setPen(constants.PORT_TEXT_COLOR)
        label = "IN" if self.is_input else "OUT"
        painter.drawText(self.boundingRect(), Qt.AlignmentFlag.AlignCenter, label)

        # Selection Border
        if is_selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(constants.SELECTION_BORDER_COLOR, 1.5))
            painter.drawRect(self.boundingRect())

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: 'QGraphicsSceneMouseEvent') -> None:
        """Handle selection and start potential bulk drag."""
        # Let selection run first
        super().mousePressEvent(event)

        # Store press position if it's a left click for potential drag start by scene
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_press_pos = event.pos()
        else:
            self._mouse_press_pos = None
        # Do not accept the event here, let it propagate fully

    def mouseDoubleClickEvent(self, event: 'QGraphicsSceneMouseEvent') -> None:
        """Handle double-click to select the bulk area and connected ports of its paired ports."""
        if event.button() == Qt.MouseButton.LeftButton:
            items_to_select = [self] # Include the bulk area itself

            for port in self.paired_ports:
                for conn in port.connections:
                    other_port = conn.source_port if conn.dest_port == port else conn.dest_port
                    if other_port not in items_to_select: # Avoid duplicates
                        items_to_select.append(other_port)

            if self.scene() and hasattr(self.scene(), 'interaction_handler'):
                self.scene().clearSelection()
                self.scene().interaction_handler._select_items(items_to_select)
                self.scene().interaction_handler._is_double_click = True

            # Manually trigger highlighting of connected bulk areas
            self._highlight_connected_bulk_areas()

            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: 'QGraphicsSceneContextMenuEvent') -> None:
        """Show context menu for disconnecting the paired ports.

        Menu structure:
          - "Disconnect all INs" / "Disconnect all OUTs"  (disconnects everything)
          - separator
          - "Disconnect from <client>" per connected client  (disconnects only that client)
        """
        menu = QMenu()
        action_text = "Disconnect all INs" if self.is_input else "Disconnect all OUTs"
        disconnect_action = menu.addAction(action_text)

        def handle_bulk_disconnect() -> None:
            current_scene = self.scene()
            if not current_scene or not hasattr(current_scene, 'jack_connection_handler'):
                logger.error(f"Scene or JackConnectionHandler not available for bulk disconnect from {self.parent_node.client_name}")
                return

            connection_handler = current_scene.jack_connection_handler

            logger.info(f"BulkAreaItem: Disconnecting {'inputs' if self.is_input else 'outputs'} for {self.parent_node.client_name}")
            for port_item in self.paired_ports:
                try:
                    logger.debug(f" Requesting disconnect for port: {port_item.port_name}")
                    connection_handler.disconnect_node(port_item.port_name)
                except Exception as e:
                    logger.error(f" Error disconnecting port {port_item.port_name}: {e}")
            logger.info(f"Finished request to disconnect {'inputs' if self.is_input else 'outputs'} for {self.parent_node.client_name}")

        disconnect_action.triggered.connect(handle_bulk_disconnect)

        # Disable if no connections exist on the paired ports
        can_disconnect = any(p.connections for p in self.paired_ports)
        disconnect_action.setEnabled(can_disconnect)

        # --- Per-client disconnect actions ---
        # Collect all connections from both paired ports, grouped by the other client name.
        # client_name -> list of (source_port_name, dest_port_name, is_midi) tuples
        client_connections: dict[str, list[tuple[str, str, bool]]] = {}

        for port_item in self.paired_ports:
            for conn in port_item.connections:
                # Determine the "other" port in this connection
                if conn.source_port == port_item:
                    other_port = conn.dest_port
                else:
                    other_port = conn.source_port

                if not other_port:
                    continue

                other_client = other_port.parent_node.client_name if other_port.parent_node else other_port.port_name.split(':')[0]

                # Build the (source, dest) tuple for the JACK call
                source_name = conn.source_port.port_name
                dest_name = conn.dest_port.port_name
                is_midi = port_item.is_midi

                if other_client not in client_connections:
                    client_connections[other_client] = []
                client_connections[other_client].append((source_name, dest_name, is_midi))

        if client_connections:
            menu.addSeparator()
            # Sort client names for consistent menu ordering
            for client_name in sorted(client_connections.keys()):
                conns = client_connections[client_name]
                action = QAction(f"Disconnect from {client_name}", menu)

                def make_disconnect_handler(connections: list[tuple[str, str, bool]]) -> None:
                    def handler() -> None:
                        current_scene = self.scene()
                        if not current_scene or not hasattr(current_scene, 'jack_connection_handler'):
                            logger.error(f"Scene or JackConnectionHandler not available for per-client bulk disconnect")
                            return
                        connection_handler = current_scene.jack_connection_handler
                        for src, dst, midi in connections:
                            try:
                                if midi:
                                    connection_handler.break_midi_connection(src, dst)
                                else:
                                    connection_handler.break_connection(src, dst)
                            except Exception as e:
                                logger.error(f" Error disconnecting {src} -> {dst}: {e}")

                    action.triggered.connect(handler)

                make_disconnect_handler(conns)
                menu.addAction(action)

        menu.exec(event.screenPos())
        event.accept()

    def get_connection_point(self) -> QPointF:
        """Return the scene coordinates of the center of the bulk connection area."""
        return self.mapToScene(self.boundingRect().center())

    def _is_connected_to_other_bulk(self, other_bulk_area: 'BulkAreaItem') -> bool:
        """Checks if this bulk area has at least one connection to the other_bulk_area.

        Only checks connections between this bulk's ``paired_ports`` and the
        other bulk's ``paired_ports``, not all ports on the node.
        """
        if not self.parent_node or not other_bulk_area or not other_bulk_area.parent_node:
            return False
        if self.parent_node == other_bulk_area.parent_node: # Not for connections on the same node
            return False
        if self.is_input == other_bulk_area.is_input: # Must be IN to OUT or OUT to IN
            return False

        # Determine source and sink ports from the two bulk areas
        if not self.is_input: # 'self' is an OUTPUT area
            source_ports = self.paired_ports
            sink_ports = other_bulk_area.paired_ports
        else: # 'self' is an INPUT area
            source_ports = other_bulk_area.paired_ports
            sink_ports = self.paired_ports

        for source_port_item in source_ports:
            for connection in source_port_item.connections:
                if connection.source_port == source_port_item and \
                   connection.dest_port and \
                   connection.dest_port in sink_ports:
                    return True
        return False

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """Handle selection synchronization with associated paired PortItems and other BulkAreaItems."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            from .node_item import NodeItem # Local import for isinstance and logic

            if self.scene() and hasattr(self.scene(), 'interaction_handler') and self.parent_node:
                handler = self.scene().interaction_handler

                # If GraphInteractionHandler is doing a batch selection, only do basic child port sync.
                if handler._processing_selection:
                    current_selection_state = bool(value)
                    for port_item in self.paired_ports:
                        if port_item.isSelected() != current_selection_state:
                            port_item.setSelected(current_selection_state)
                    return super().itemChange(change, value)

                # Prevent re-entry for this specific bulk area's selection change processing
                if self._is_handling_selection_change:
                    return super().itemChange(change, value)

                self._is_handling_selection_change = True
                try:
                    # Part 1: Synchronize with own paired ports
                    new_selection_state = bool(value)
                    for port_item in self.paired_ports:
                        if port_item.isSelected() != new_selection_state:
                            port_item.setSelected(new_selection_state)

                    # Part 2: Inter-Node Bulk Area Selection Synchronization
                    # Determine if this level can propagate bulk-to-bulk selection
                    can_propagate_bulk_to_bulk = False
                    if not handler._is_in_auto_selection_cascade:
                        can_propagate_bulk_to_bulk = True
                        handler._is_in_auto_selection_cascade = True

                    try:
                        if can_propagate_bulk_to_bulk:
                            # 2. Propagate selection to connected BulkAreaItems on other nodes
                            all_items_in_scene = list(self.scene().items())

                            if value: # Current bulk area (self) is being SELECTED
                                for item_in_scene_check in all_items_in_scene:
                                    if not isinstance(item_in_scene_check, typing.cast(type, NodeItem)) or item_in_scene_check == self.parent_node:
                                        continue

                                    other_node = item_in_scene_check
                                    # Check all bulk areas on the other node's opposite side
                                    target_bulks = other_node.input_bulk_areas if not self.is_input else other_node.output_bulk_areas

                                    for target_bulk in target_bulks:
                                        if target_bulk and not target_bulk.isSelected():
                                            if self._is_connected_to_other_bulk(target_bulk):
                                                target_bulk.set_connection_highlighted(True)
                            else: # Current bulk area (self) is being DESELECTED
                                for item_in_scene_check in all_items_in_scene:
                                    if not isinstance(item_in_scene_check, typing.cast(type, NodeItem)) or item_in_scene_check == self.parent_node:
                                        continue

                                    other_node_to_check = item_in_scene_check
                                    bulks_on_other = other_node_to_check.input_bulk_areas if not self.is_input else other_node_to_check.output_bulk_areas

                                    for bulk_on_other in bulks_on_other:
                                        if bulk_on_other:
                                            if self._is_connected_to_other_bulk(bulk_on_other):
                                                bulk_on_other.set_connection_highlighted(False)
                    finally:
                        if can_propagate_bulk_to_bulk:
                            handler._is_in_auto_selection_cascade = False
                finally:
                    self._is_handling_selection_change = False
        return super().itemChange(change, value)

    def set_drag_highlight(self, highlighted: bool) -> None:
        """Externally set the highlight state for drag hover."""
        if self._is_drag_highlighted != highlighted:
            self._is_drag_highlighted = highlighted
            self.update()

    def _highlight_connected_bulk_areas(self) -> None:
        """Highlight bulk areas connected to this one via its paired ports."""
        from .node_item import NodeItem # Local import for isinstance

        if not self.scene():
            return

        all_items_in_scene = list(self.scene().items())
        for item_in_scene in all_items_in_scene:
            if not isinstance(item_in_scene, typing.cast(type, NodeItem)) or item_in_scene == self.parent_node:
                continue

            other_node = item_in_scene
            target_bulks = other_node.input_bulk_areas if not self.is_input else other_node.output_bulk_areas

            for target_bulk in target_bulks:
                if target_bulk and not target_bulk.isSelected():
                    if self._is_connected_to_other_bulk(target_bulk):
                        target_bulk.set_connection_highlighted(True)

    def set_connection_highlighted(self, highlighted: bool) -> None:
        """Set the connection highlighting state."""
        if self._connection_highlighted != highlighted:
            self._connection_highlighted = highlighted
            self.update()
