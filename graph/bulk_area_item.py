# --- PyQt Graphical Items - BulkAreaItem ---

from PyQt6.QtWidgets import (
    QGraphicsItem, QStyleOptionGraphicsItem, QWidget, QStyle, QGraphicsSceneHoverEvent, QMenu
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor
)
from PyQt6.QtCore import (
    Qt, QRectF, QPointF
)

from . import constants # Import the new constants module
import typing

if typing.TYPE_CHECKING:
    from .node_item import NodeItem
    from .port_item import PortItem
    from .connection_item import ConnectionItem


class BulkAreaItem(QGraphicsItem):
    """A selectable item representing the 'IN' or 'OUT' bulk connection area of a NodeItem."""
    def __init__(self, parent_node: 'NodeItem', is_input: bool):
        super().__init__(parent_node)
        self.parent_node = parent_node
        self.is_input = is_input
        self._bounding_rect = QRectF(0, 0, constants.PORT_WIDTH_MIN - (2 * constants.NODE_BULK_AREA_HPADDING), constants.NODE_BULK_AREA_HEIGHT)
        self._is_hovered = False
        self._is_drag_highlighted = False # For drag hover
        self._mouse_press_pos = None # Store initial press position for drag threshold
        self._is_handling_selection_change = False # Flag to prevent re-entry during selection cascade

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        # Don't make the area itself movable, the parent node handles movement.
        # self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges) # Not needed if parent moves


    def boundingRect(self):
        return self._bounding_rect

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Determine background color
        bg_color = constants.NODE_BULK_AREA_COLOR
        if is_selected or self._is_hovered or self._is_drag_highlighted:
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

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """Handle selection and start potential bulk drag."""
        # Let selection run first
        super().mousePressEvent(event)

        # Store press position if it's a left click for potential drag start by scene
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_press_pos = event.pos()
            print(f"BulkAreaItem mousePress: Stored press pos {self._mouse_press_pos} for scene. Event accepted by super: {event.isAccepted()}")
        else:
            self._mouse_press_pos = None
        # Do not accept the event here, let it propagate fully

    # Remove mouseMoveEvent and mouseReleaseEvent overrides - scene handles drag initiation
    # def mouseMoveEvent(self, event): ...
    # def mouseReleaseEvent(self, event): ...

    def contextMenuEvent(self, event):
        """Show context menu for disconnecting all."""
        menu = QMenu()
        action_text = "Disconnect all INs" if self.is_input else "Disconnect all OUTs"
        disconnect_action = menu.addAction(action_text)

        # Define a new method to handle the disconnection logic
        def handle_bulk_disconnect():
            current_scene = self.scene()
            if not current_scene or not hasattr(current_scene, 'jack_connection_handler'):
                print(f"Error: Scene or JackConnectionHandler not available for bulk disconnect from {self.parent_node.client_name}")
                return

            connection_handler = current_scene.jack_connection_handler
            ports_to_process = self.parent_node.input_ports if self.is_input else self.parent_node.output_ports
            
            print(f"BulkAreaItem: Disconnecting {'inputs' if self.is_input else 'outputs'} for {self.parent_node.client_name}")
            for port_item in ports_to_process.values():
                try:
                    print(f"  Requesting disconnect for port: {port_item.port_name}")
                    connection_handler.disconnect_node(port_item.port_name)
                except Exception as e:
                    print(f"  Error disconnecting port {port_item.port_name}: {e}")
            print(f"Finished request to disconnect {'inputs' if self.is_input else 'outputs'} for {self.parent_node.client_name}")

        disconnect_action.triggered.connect(handle_bulk_disconnect)

        # Disable if no connections exist on relevant ports
        ports_to_check = self.parent_node.input_ports if self.is_input else self.parent_node.output_ports
        can_disconnect = any(p.connections for p in ports_to_check.values())
        disconnect_action.setEnabled(can_disconnect)

        menu.exec(event.screenPos())
        event.accept()

    def get_connection_point(self):
        """Return the scene coordinates of the center of the bulk connection area."""
        return self.mapToScene(self.boundingRect().center())

    def _is_connected_to_other_bulk(self, other_bulk_area: 'BulkAreaItem') -> bool:
        """Checks if this bulk area has at least one connection to the other_bulk_area."""
        # from .node_item import NodeItem # Not needed due to TYPE_CHECKING
        # from .port_item import PortItem # Not needed due to TYPE_CHECKING

        if not self.parent_node or not other_bulk_area or not other_bulk_area.parent_node:
            return False
        # Ensure parent_node is correctly typed or checked if direct attribute access is used.
        # For this helper, we assume parent_node is a NodeItem instance.
        if self.parent_node == other_bulk_area.parent_node: # Not for connections on the same node via this logic
            return False
        if self.is_input == other_bulk_area.is_input: # Must be IN to OUT or OUT to IN
            return False

        effective_source_node: 'NodeItem'
        # effective_sink_node: 'NodeItem' # Not strictly needed for the check logic below
        source_ports_collection: dict[str, 'PortItem']

        if not self.is_input: # 'self' is an OUTPUT area
            effective_source_node = self.parent_node
            source_ports_collection = self.parent_node.output_ports
            # effective_sink_node = other_bulk_area.parent_node # 'other_bulk_area' must be an INPUT area
        else: # 'self' is an INPUT area
            effective_source_node = other_bulk_area.parent_node # 'other_bulk_area' must be an OUTPUT area
            source_ports_collection = other_bulk_area.parent_node.output_ports
            # effective_sink_node = self.parent_node

        if not source_ports_collection:
            return False # Source node has no relevant ports to form a connection

        # The effective_sink_node is the one whose ports we are checking against.
        # If self is OUT, sink is other_bulk_area.parent_node.
        # If self is IN, sink is self.parent_node.
        node_whose_ports_are_targets = other_bulk_area.parent_node if not self.is_input else self.parent_node

        for source_port_item in source_ports_collection.values():
            for connection in source_port_item.connections: # connection is ConnectionItem
                # A connection goes from connection.source_port to connection.dest_port
                # We need to check if this connection's destination port is on the node_whose_ports_are_targets
                # and is of the correct type (input if node_whose_ports_are_targets is receiving).
                if connection.source_port == source_port_item and \
                   connection.dest_port and \
                   connection.dest_port.parent_node == node_whose_ports_are_targets and \
                   connection.dest_port.is_input: # Destination on sink node must be an input port
                    return True # Found a connection from a source port to a sink port on the target node
        return False

    def itemChange(self, change, value):
        """Handle selection synchronization with associated PortItems and other BulkAreaItems."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            from .node_item import NodeItem # Local import for isinstance and logic

            if self.scene() and hasattr(self.scene(), 'interaction_handler') and self.parent_node:
                handler = self.scene().interaction_handler

                # If GraphInteractionHandler is doing a batch selection, only do basic child port sync.
                if handler._processing_selection:
                    ports_to_sync_directly = self.parent_node.input_ports if self.is_input else self.parent_node.output_ports
                    current_selection_state = bool(value)
                    for port_item in ports_to_sync_directly.values():
                        if port_item.isSelected() != current_selection_state:
                            # Directly set, PortItem.itemChange will also respect handler._processing_selection
                            port_item.setSelected(current_selection_state)
                    return super().itemChange(change, value)

                # Prevent re-entry for this specific bulk area's selection change processing
                if self._is_handling_selection_change:
                    return super().itemChange(change, value)

                self._is_handling_selection_change = True
                try:
                    # Part 1: Synchronize with own child ports
                    # This will trigger PortItem.itemChange for each child, which handles Port-to-Port cascades
                    # and then updates this BulkAreaItem if all its siblings change state.
                    ports_to_update_map = self.parent_node.input_ports if self.is_input else self.parent_node.output_ports
                    new_selection_state = bool(value)
                    for port_item in ports_to_update_map.values():
                        if port_item.isSelected() != new_selection_state:
                            port_item.setSelected(new_selection_state)

                    # Part 2: Inter-Node Bulk Area Selection Synchronization
                    # This part runs after child ports have been set. If selecting this bulk area
                    # caused all its ports to select, and those ports caused other ports on another node
                    # to select, and that caused the other node's bulk area to select, this logic
                    # might re-select an already selected item, but the .setSelected(True) on an
                    # already selected item is a no-op in terms of visual change and itemChange trigger.
                    all_items_in_scene = list(self.scene().items())

                    if value: # Current bulk area (self) is being SELECTED
                        for item_in_scene_check in all_items_in_scene:
                            if not isinstance(item_in_scene_check, NodeItem) or item_in_scene_check == self.parent_node:
                                continue
                            
                            other_node = item_in_scene_check
                            target_bulk_on_other_node = other_node.input_area_item if not self.is_input else other_node.output_area_item

                            if target_bulk_on_other_node and not target_bulk_on_other_node.isSelected():
                                if self._is_connected_to_other_bulk(target_bulk_on_other_node):
                                    target_bulk_on_other_node.setSelected(True) # Triggers itemChange on other bulk
                    else: # Current bulk area (self) is being DESELECTED
                        for item_in_scene_check in all_items_in_scene:
                            if not isinstance(item_in_scene_check, NodeItem) or item_in_scene_check == self.parent_node:
                                continue

                            other_node_to_check = item_in_scene_check
                            bulk_on_other_to_check = other_node_to_check.input_area_item if not self.is_input else other_node_to_check.output_area_item
                            
                            if bulk_on_other_to_check and bulk_on_other_to_check.isSelected():
                                # Check if bulk_on_other_to_check was connected to 'self' (which is now being deselected)
                                if self._is_connected_to_other_bulk(bulk_on_other_to_check):
                                    # It was connected to self. Now check if it has other reasons to stay selected.
                                    should_other_remain_selected = False
                                    for third_item_check_loop in all_items_in_scene:
                                        if not isinstance(third_item_check_loop, NodeItem) or \
                                           third_item_check_loop == bulk_on_other_to_check.parent_node or \
                                           third_item_check_loop == self.parent_node: # Exclude self, and the node of the item being checked
                                            continue
                                        
                                        third_node_as_peer_source = third_item_check_loop
                                        # Peer bulk area on third_node that could connect to bulk_on_other_to_check
                                        peer_bulk_on_third_node = third_node_as_peer_source.input_area_item if not bulk_on_other_to_check.is_input else third_node_as_peer_source.output_area_item
                                        
                                        if peer_bulk_on_third_node and peer_bulk_on_third_node.isSelected():
                                            # Check connection from bulk_on_other_to_check to this *selected* peer
                                            if bulk_on_other_to_check._is_connected_to_other_bulk(peer_bulk_on_third_node):
                                                should_other_remain_selected = True
                                                break
                                    
                                    if not should_other_remain_selected:
                                        bulk_on_other_to_check.setSelected(False) # Triggers itemChange on other bulk
                finally:
                    self._is_handling_selection_change = False
        return super().itemChange(change, value)

    def set_drag_highlight(self, highlighted: bool):
        """Externally set the highlight state for drag hover."""
        if self._is_drag_highlighted != highlighted:
            self._is_drag_highlighted = highlighted
            self.update()