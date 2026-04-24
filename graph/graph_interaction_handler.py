"""
Mouse and drag interaction handler for the graph scene (port dragging, bulk connections, rubber-band selection).
"""
import logging
import typing
import traceback
from PyQt6.QtWidgets import QGraphicsSceneMouseEvent, QGraphicsItem, QGraphicsPathItem, QApplication
from PyQt6.QtGui import QPen, QPainterPath, QColor
from PyQt6.QtCore import Qt, QPointF, QTimer # Added QTimer

logger = logging.getLogger(__name__)

# Import constants and other necessary types
from . import constants
from .port_item import PortItem
from .bulk_area_item import BulkAreaItem
from .node_item import NodeItem
from . import graph_drag_helpers

if typing.TYPE_CHECKING:
    from .gui_scene import JackGraphScene
    from .node_item import NodeItem
    from .connection_item import ConnectionItem # Corrected import
    from .jack_handler import JackHandler
    from .config_utils import GraphConfigManager
    from cables.jack_connection_handler import JackConnectionHandler # Added for type hint
from typing import TYPE_CHECKING, List, Optional, Tuple, Any, Dict, Set, Union


class GraphInteractionHandler:
    """Handles mouse interactions, dragging, connections, and selection for the JackGraphScene."""

    # State variables moved from JackGraphScene
    _drag_connection_line: typing.Optional[QGraphicsPathItem] = None
    _drag_source_port: typing.Optional['PortItem'] = None
    _is_disconnect_drag: bool = False
    _drag_source_bulk_item: typing.Optional['BulkAreaItem'] = None
    _is_bulk_drag: bool = False
    _is_bulk_disconnect_drag: bool = False
    _moved_node: typing.Optional['NodeItem'] = None # Store the actual NodeItem or None
    _drag_hovered_port: typing.Optional['PortItem'] = None
    _drag_hovered_bulk_area: typing.Optional['BulkAreaItem'] = None
    _potential_drag_item: typing.Optional[QGraphicsItem] = None
    _potential_drag_start_pos: typing.Optional[QPointF] = None
    _processing_selection: bool = False
    _last_mouse_pos: typing.Optional[QPointF] = None # Needed for release event item check

    def __init__(self, scene: 'JackGraphScene', jack_handler: 'JackHandler', config_manager: 'GraphConfigManager', jack_connection_handler: 'JackConnectionHandler') -> None:
        self.scene = scene
        self.jack_handler = jack_handler # This is GraphJackHandler, for querying
        self.config_manager = config_manager # Keep if needed for future interaction logic
        self.jack_connection_handler = jack_connection_handler # The new centralized handler

        # Reset state variables on initialization (optional, but good practice)
        self._drag_connection_line = None
        self._drag_source_port = None
        self._is_disconnect_drag = False
        self._drag_source_bulk_item = None
        self._is_bulk_drag = False
        self._is_bulk_disconnect_drag = False
        self._moved_node = None
        self._drag_hovered_port = None
        self._drag_hovered_bulk_area = None
        self._potential_drag_item = None
        self._potential_drag_start_pos = None
        self._processing_selection = False
        self._last_mouse_pos = None
        self._is_in_auto_selection_cascade = False
        self._is_double_click = False

    def clear_all_connection_highlights(self) -> None:
        """Clear connection highlighting from all PortItems and BulkAreaItems in the scene."""
        if not self.scene:
            return

        for item in self.scene.items():
            if hasattr(item, 'set_connection_highlighted'):
                item.set_connection_highlighted(False)

    def _select_items(self, items_to_select: List[QGraphicsItem]) -> None:
        """Adds the given items to the scene's current selection."""
        if not items_to_select or not self.scene:
            return

        # Clear any existing connection highlights before making new selections
        self.clear_all_connection_highlights()

        # If already processing, let the current operation complete to avoid nested issues.
        if self._processing_selection:
            # This can happen if selection changes trigger other selection changes rapidly.
            # Aborting the new call to prevent potential recursion or unexpected states.
            return
 
        self._processing_selection = True # Set flag for the entire multi-stage operation
 
        processed_any_item = False
        if items_to_select:
            first_item_to_select = items_to_select[0]
            if first_item_to_select:
                first_item_to_select.setSelected(True)
                if self.scene.views(): self.scene.views()[0].ensureVisible(first_item_to_select)
                processed_any_item = True
 
            remaining_items = [item for item in items_to_select[1:] if item] # Filter out None items
 
            if remaining_items:
                # Pass a copy of the list to the lambda
                QTimer.singleShot(0, lambda items_copy=list(remaining_items): self._select_remaining_items_deferred(items_copy))
                # _processing_selection is reset by the deferred call
            elif processed_any_item: # Only first item was processed, no deferred items
                self._processing_selection = False
            else: # No items were processed at all
                self._processing_selection = False
        else: # items_to_select was empty
            self._processing_selection = False
 
 
    def _select_remaining_items_deferred(self, items: List[QGraphicsItem]) -> None:
        """Selects items deferred by QTimer.singleShot. Resets _processing_selection flag."""
        try:
            for item_to_select in items:
                if item_to_select: # Should have been filtered already, but double check
                    item_to_select.setSelected(True)
                    if self.scene.views(): self.scene.views()[0].ensureVisible(item_to_select)
        finally:
            # This is the end of the entire multi-selection operation (including deferred parts).
            self._processing_selection = False

    # --- Drag Initiation ---

    def start_connection_drag(self, source_port: 'PortItem', is_disconnect_drag: bool = False) -> None:
        """Initiate drawing the temporary connection line."""
        if self._drag_connection_line: # Should not happen, but cleanup just in case
            self.scene.removeItem(self._drag_connection_line)

        self._drag_source_port = source_port
        self._is_disconnect_drag = is_disconnect_drag # Store the drag type
        self._drag_connection_line = QGraphicsPathItem()
        self._drag_connection_line.setZValue(1) # Draw drag line ON TOP of ports/nodes

        # Initial drag line color is default (e.g., white)
        pen = QPen(constants.DEFAULT_DRAG_LINE_COLOR, 2, Qt.PenStyle.DashLine)

        self._drag_connection_line.setPen(pen)
        self.scene.addItem(self._drag_connection_line)
        self._drag_connection_line.setEnabled(False) # Make it non-interactive
        self.update_drag_line(source_port.mapToScene(source_port.boundingRect().center())) # Start line near source port


    def start_bulk_connection_drag(self, source_item: 'BulkAreaItem', is_input_area: bool, is_disconnect_drag: bool) -> None:
        """Initiate drawing the temporary connection line for a bulk drag."""
        # is_input_area is redundant now as source_item.is_input tells us
        if self._drag_connection_line: # Cleanup just in case
            self.scene.removeItem(self._drag_connection_line)

        self._drag_source_bulk_item = source_item # Store the BulkAreaItem
        self._is_bulk_drag = True
        self._is_bulk_disconnect_drag = is_disconnect_drag
        self._drag_connection_line = QGraphicsPathItem()
        self._drag_connection_line.setZValue(1) # Draw drag line ON TOP of ports/nodes

        # Initial drag line color is default (e.g., white)
        pen = QPen(constants.DEFAULT_DRAG_LINE_COLOR, 2, Qt.PenStyle.DashLine)

        self._drag_connection_line.setPen(pen)
        self.scene.addItem(self._drag_connection_line)
        self._drag_connection_line.setEnabled(False) # Make it non-interactive
        # Start line near the bulk area center using the item's method
        start_point = source_item.get_connection_point()
        self.update_drag_line(start_point)


    # --- Drag Update ---

    def update_drag_line(self, cursor_pos: QPointF) -> None:
        """Update the end point of the temporary drag line (handles both port and bulk drags)."""
        if not self._drag_connection_line:
            return

        # Need PortItem and BulkAreaItem for type checks below

        # Determine start point based on drag type
        if self._is_bulk_drag and self._drag_source_bulk_item:
            p1 = self._drag_source_bulk_item.get_connection_point() # Use BulkAreaItem's method
        elif not self._is_bulk_drag and self._drag_source_port:
            p1 = self._drag_source_port.get_connection_point()
        else:
            return # No valid drag source

        p2 = cursor_pos

        path = QPainterPath()
        path.moveTo(p1)
        # Simple bezier for drag line
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        c1x = p1.x() + dx * 0.5
        c1y = p1.y()
        c2x = p1.x() + dx * 0.5
        c2y = p2.y()
        path.cubicTo(c1x, c1y, c2x, c2y, p2.x(), p2.y())

        self._drag_connection_line.setPath(path)


    # --- Drag Finalization ---
 
    def _handle_port_to_port_interaction(self, source_port: 'PortItem', target_port: 'PortItem') -> None:
        """Handles connection/disconnection logic between two PortItems."""
        source_parent_node = source_port.parent_node
        if source_parent_node == target_port.parent_node and \
           (source_parent_node.is_split_origin or source_parent_node.is_split_part):
            return # Silently disallow self-connection on split nodes

        out_p_item, in_p_item = (source_port, target_port) if not source_port.is_input and target_port.is_input else \
                                (target_port, source_port) if source_port.is_input and not target_port.is_input else \
                                (None, None)

        if not out_p_item or not in_p_item:
            return # Invalid port type combination

        is_already_connected = any(
            conn.source_port == out_p_item and conn.dest_port == in_p_item
            for conn in out_p_item.connections
        )

        try:
            if is_already_connected:
                if out_p_item.is_midi:
                    self.jack_connection_handler.break_midi_connection(out_p_item.port_name, in_p_item.port_name)
                else:
                    self.jack_connection_handler.break_connection(out_p_item.port_name, in_p_item.port_name)
            else:
                if out_p_item.is_midi:
                    self.jack_connection_handler.make_midi_connection(out_p_item.port_name, in_p_item.port_name)
                else:
                    self.jack_connection_handler.make_connection(out_p_item.port_name, in_p_item.port_name)
                self._select_items([source_port, target_port])
        except Exception as e:
            logger.error(f"Error in _handle_port_to_port_interaction: {e}")

    def _handle_port_to_bulk_interaction(self, source_port: 'PortItem', target_bulk_area: 'BulkAreaItem') -> None:
        """Handles connection/disconnection logic between a PortItem and a BulkAreaItem.

        Connects the single source port to all ports in the bulk area's ``paired_ports``.
        """
        source_parent_node = source_port.parent_node
        if source_parent_node == target_bulk_area.parent_node and \
            (source_parent_node.is_split_origin or source_parent_node.is_split_part):
            return # Silently disallow self-connection to bulk on split nodes

        # Use only the bulk area's paired ports as targets
        if source_port.is_input == target_bulk_area.is_input:
            return # Invalid port-to-bulk type combination (same direction)

        target_ports = target_bulk_area.paired_ports
        if not target_ports:
            return

        # Build pairs: source_port → every port in target_bulk_area.paired_ports
        pairs: list[tuple[PortItem, PortItem]] = []
        for t_port in target_ports:
            pairs.append((source_port, t_port))

        if not pairs:
            return

        num_already_connected = 0
        connections_to_make: list[tuple[PortItem, PortItem]] = []
        connections_to_break: list[tuple[PortItem, PortItem]] = []

        for s_port, t_port in pairs:
            out_p, in_p = (s_port, t_port) if not s_port.is_input else (t_port, s_port)
            if any(conn.source_port == out_p and conn.dest_port == in_p for conn in out_p.connections):
                num_already_connected += 1
                connections_to_break.append((out_p, in_p))
            else:
                connections_to_make.append((out_p, in_p))

        action_performed = False
        if num_already_connected == len(pairs) and connections_to_break: # All pairs are connected
            for out_p, in_p in connections_to_break:
                try:
                    if out_p.is_midi: self.jack_connection_handler.break_midi_connection(out_p.port_name, in_p.port_name)
                    else: self.jack_connection_handler.break_connection(out_p.port_name, in_p.port_name)
                    action_performed = True
                except Exception as e: logger.error(f"Error breaking port-to-bulk connection: {e}")
        elif connections_to_make: # Connect missing ones
            for out_p, in_p in connections_to_make:
                try:
                    if out_p.is_midi: self.jack_connection_handler.make_midi_connection(out_p.port_name, in_p.port_name)
                    else: self.jack_connection_handler.make_connection(out_p.port_name, in_p.port_name)
                    action_performed = True
                except Exception as e: logger.error(f"Error making port-to-bulk connection: {e}")

        if action_performed:
            self._select_items([source_port, target_bulk_area])

    def end_connection_drag(self, source_port: 'PortItem', target_item: Optional[QGraphicsItem], _is_disconnect_drag_hint: bool) -> None:
        """Finalize drag from a PortItem: connect or disconnect based on existing connections."""
        if not source_port:
            return
 
        if isinstance(target_item, PortItem) and target_item != source_port:
            self._handle_port_to_port_interaction(source_port, target_item)
        elif isinstance(target_item, BulkAreaItem):
            self._handle_port_to_bulk_interaction(source_port, target_item)
        # else: Target is not a valid PortItem or BulkAreaItem, or is the source_port itself.


    def _check_any_connection_between_nodes(self, node1: 'NodeItem', node2: 'NodeItem') -> bool:
        """Checks if any port on node1 is connected to any port on node2."""
        if not node1 or not node2:
            return False
        
        # Check connections from node1's ports
        for port1_collection in [node1.input_ports.values(), node1.output_ports.values()]:
            for port1 in port1_collection:
                for conn_item in port1.connections:
                    other_port = conn_item.dest_port if conn_item.source_port == port1 else conn_item.source_port
                    if other_port.parent_node == node2:
                        return True
        return False

    def _handle_bulk_to_port_interaction(self, source_bulk_area: 'BulkAreaItem', target_port: 'PortItem') -> None:
        """Handles connection/disconnection logic between a BulkAreaItem and a PortItem.

        Connects all ports in the bulk area's ``paired_ports`` to the single target port.
        """
        source_node = source_bulk_area.parent_node
        if not source_node: return

        # Disallow self-connection on split nodes
        if source_node == target_port.parent_node and \
            (source_node.is_split_origin or source_node.is_split_part):
            return

        # Use only the bulk area's paired ports as sources
        source_ports = source_bulk_area.paired_ports
        if not source_ports: return

        # Build pairs: every port in source_bulk_area.paired_ports → target_port
        pairs: list[tuple[PortItem, PortItem]] = []
        for s_port in source_ports:
            pairs.append((s_port, target_port))

        if not pairs: return

        num_already_connected = 0
        connections_to_make: list[tuple[PortItem, PortItem]] = []
        connections_to_break: list[tuple[PortItem, PortItem]] = []

        for s_port, t_port in pairs:
            out_p, in_p = (s_port, t_port) if not s_port.is_input else (t_port, s_port)
            if any(conn.source_port == out_p and conn.dest_port == in_p for conn in out_p.connections):
                num_already_connected += 1
                connections_to_break.append((out_p, in_p))
            else:
                connections_to_make.append((out_p, in_p))

        action_performed = False
        if num_already_connected == len(pairs) and connections_to_break: # All pairs are connected
            for out_p, in_p in connections_to_break:
                try:
                    if out_p.is_midi: self.jack_connection_handler.break_midi_connection(out_p.port_name, in_p.port_name)
                    else: self.jack_connection_handler.break_connection(out_p.port_name, in_p.port_name)
                    action_performed = True
                except Exception as e: logger.error(f"Error breaking bulk-to-port connection: {e}")
        elif connections_to_make: # Connect missing ones
            for out_p, in_p in connections_to_make:
                try:
                    if out_p.is_midi: self.jack_connection_handler.make_midi_connection(out_p.port_name, in_p.port_name)
                    else: self.jack_connection_handler.make_connection(out_p.port_name, in_p.port_name)
                    action_performed = True
                except Exception as e: logger.error(f"Error making bulk-to-port connection: {e}")

        if action_performed:
            self._select_items([source_bulk_area, target_port])

    def _handle_bulk_to_bulk_interaction(self, source_bulk_area: 'BulkAreaItem', target_bulk_area: 'BulkAreaItem') -> None:
        """Handles connection/disconnection logic between two BulkAreaItems.

        Per-pair mapping: uses each bulk area's ``paired_ports`` instead of
        all node ports.  Sequential mapping by index.
        """
        source_node = source_bulk_area.parent_node
        target_node = target_bulk_area.parent_node
        if not source_node or not target_node: return

        if source_node == target_node and \
            (source_node.is_split_origin or source_node.is_split_part):
            return # Disallow self-connection on split nodes

        if source_bulk_area.is_input == target_bulk_area.is_input:
            return # Cannot connect IN-to-IN or OUT-to-OUT

        # Use paired ports from each bulk area
        if not source_bulk_area.is_input:
            out_ports_list = source_bulk_area.paired_ports
            in_ports_list = target_bulk_area.paired_ports
        else:
            out_ports_list = target_bulk_area.paired_ports
            in_ports_list = source_bulk_area.paired_ports

        if not out_ports_list or not in_ports_list: return

        num_existing_connections = 0
        for out_p_item in out_ports_list:
            for conn in out_p_item.connections:
                if conn.dest_port in in_ports_list:
                    num_existing_connections += 1

        num_potential_connections = min(len(out_ports_list), len(in_ports_list))
        if num_potential_connections == 0: return

        action_performed = False
        if num_existing_connections >= num_potential_connections: # Disconnect existing pairs
            for out_p_item in out_ports_list:
                for conn_item in list(out_p_item.connections): # Iterate copy
                    if conn_item.dest_port in in_ports_list:
                        try:
                            if conn_item.source_port.is_midi: self.jack_connection_handler.break_midi_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                            else: self.jack_connection_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                            action_performed = True
                        except Exception as e: logger.error(f"Error breaking bulk-to-bulk pair: {e}")
        else: # Make connections
            try:
                output_port_names = [p.port_name for p in out_ports_list]
                input_port_names = [p.port_name for p in in_ports_list]
                self.jack_connection_handler.make_multiple_connections(output_port_names, input_port_names)
                action_performed = True
            except Exception as e:
                logger.error(f"Error in bulk make_multiple_connections: {e}")

        if action_performed:
            self._select_items([source_bulk_area, target_bulk_area])

    def end_bulk_connection_drag(self, source_bulk_item: 'BulkAreaItem', target_item_at_release: Optional[QGraphicsItem], _is_source_input_area: bool, _is_disconnect_drag_hint: bool) -> None:
        """Finalize bulk drag: connect or disconnect based on existing connections."""
        source_node = source_bulk_item.parent_node
        if not source_node: return

        resolved_target_bulk_area: typing.Optional[BulkAreaItem] = None
        resolved_target_port: typing.Optional[PortItem] = None
        target_node_for_connection: typing.Optional[NodeItem] = None

        if isinstance(target_item_at_release, PortItem):
            resolved_target_port = target_item_at_release
            target_node_for_connection = resolved_target_port.parent_node
        elif isinstance(target_item_at_release, BulkAreaItem):
            resolved_target_bulk_area = target_item_at_release
            target_node_for_connection = resolved_target_bulk_area.parent_node
        elif isinstance(target_item_at_release, NodeItem):
            target_node_for_connection = target_item_at_release
            # Resolve to the first bulk area on the opposite side of the target node
            if source_bulk_item.is_input and target_node_for_connection.output_bulk_areas:
                resolved_target_bulk_area = target_node_for_connection.output_bulk_areas[0]
            elif not source_bulk_item.is_input and target_node_for_connection.input_bulk_areas:
                resolved_target_bulk_area = target_node_for_connection.input_bulk_areas[0]
        
        if not target_node_for_connection:
            return

        if resolved_target_port:
            self._handle_bulk_to_port_interaction(source_bulk_item, resolved_target_port)
        elif resolved_target_bulk_area:
            self._handle_bulk_to_bulk_interaction(source_bulk_item, resolved_target_bulk_area)
        # else: Target is not a resolvable Port or BulkArea.

    # --- Stereo Node Drop Logic ---
    def handle_node_drop_connection(self, source_node: 'NodeItem', target_node: 'NodeItem') -> None:
        """Attempts to create a stereo connection when a node is dropped onto another."""
        if not source_node.output_ports or not target_node.input_ports:
            return

        def find_port_with_suffix(port_dict: Dict[str, 'PortItem'], suffix_list: List[str]) -> Optional['PortItem']:
            for port_item in port_dict.values():
                for suffix in suffix_list:
                    if port_item.short_name.endswith(suffix): return port_item
            return None

        left_out = find_port_with_suffix(source_node.output_ports, constants.STEREO_LEFT_SUFFIXES)
        left_in = find_port_with_suffix(target_node.input_ports, constants.STEREO_LEFT_SUFFIXES)
        right_out = find_port_with_suffix(source_node.output_ports, constants.STEREO_RIGHT_SUFFIXES)
        right_in = find_port_with_suffix(target_node.input_ports, constants.STEREO_RIGHT_SUFFIXES)

        connection_made_this_drop = False
        try:
            if left_out and left_in:
                if left_out.is_midi: self.jack_connection_handler.make_midi_connection(left_out.port_name, left_in.port_name)
                else: self.jack_connection_handler.make_connection(left_out.port_name, left_in.port_name)
                connection_made_this_drop = True
            if right_out and right_in:
                if right_out.is_midi: self.jack_connection_handler.make_midi_connection(right_out.port_name, right_in.port_name)
                else: self.jack_connection_handler.make_connection(right_out.port_name, right_in.port_name)
                connection_made_this_drop = True
        except Exception as e:
            logger.error(f"Error during node drop stereo connection: {e}")

        if connection_made_this_drop:
            self._select_items([source_node, target_node])


    # --- Mouse Events ---

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Handle press events: store potential drag item."""
        # Need PortItem, BulkAreaItem, NodeItem for type checks

        self._potential_drag_item = None # Reset potential drag item
        self._potential_drag_start_pos = None
        self._moved_node = None # Reset moved node tracker

        # Check item under cursor using scene's method
        pressed_item = self.scene.itemAt(event.scenePos(), self.scene.views()[0].transform() if self.scene.views() else None)

        if event.button() == Qt.MouseButton.LeftButton:
            if isinstance(pressed_item, (PortItem, BulkAreaItem)):
                # Store item and position for potential drag initiation in mouseMoveEvent
                self._potential_drag_item = pressed_item
                self._potential_drag_start_pos = event.scenePos()
            elif isinstance(pressed_item, NodeItem):
                 # Track node for potential move (handled by scene's super call) or node-on-node drop
                 self._moved_node = pressed_item
        # Scene's mousePressEvent will call super() AFTER this method, handling standard item movement.
 
    def _try_initiate_custom_drag(self, event: QGraphicsSceneMouseEvent) -> bool:
        """
        Checks if a custom drag (from PortItem or BulkAreaItem) should be initiated.
        Returns True if drag was initiated and event should be consumed, False otherwise.
        """
        if not (self._potential_drag_item and self._potential_drag_start_pos and
                event.buttons() & Qt.MouseButton.LeftButton):
            return False

        distance = (event.scenePos() - self._potential_drag_start_pos).manhattanLength()
        drag_threshold = QApplication.startDragDistance()

        if distance < drag_threshold:
            return False # Not far enough to start drag

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Drag threshold met, but Shift is pressed. Clear potential drag for standard selection.
            self._potential_drag_item = None
            self._potential_drag_start_pos = None
            return False # Let scene handle rubber band selection

        # Threshold met, no Shift -> Initiate custom drag
        item_to_drag = self._potential_drag_item
        self._potential_drag_item = None # Consume the potential drag state
        self._potential_drag_start_pos = None

        if isinstance(item_to_drag, PortItem):
            is_disconnect_hint = bool(item_to_drag.connections)
            self.start_connection_drag(item_to_drag, is_disconnect_hint)
            return True
        elif isinstance(item_to_drag, BulkAreaItem) and item_to_drag.parent_node:
            ports_in_bulk_type = item_to_drag.parent_node.input_ports if item_to_drag.is_input else item_to_drag.parent_node.output_ports
            is_disconnect_hint = any(p.connections for p in ports_in_bulk_type.values())
            self.start_bulk_connection_drag(item_to_drag, item_to_drag.is_input, is_disconnect_hint)
            return True
        
        return False # Should not be reached if item_to_drag was valid PortItem or BulkAreaItem

    def _update_active_drag_visuals(self, event: QGraphicsSceneMouseEvent) -> None:
        """Updates drag line, highlights, and line color during an active custom drag."""
        if not self._drag_connection_line: return

        self.update_drag_line(event.scenePos())

        view = self.scene.views()[0] if self.scene.views() else None
        target_item_under_cursor = None
        if view:
            items_under_cursor = self.scene.items(event.scenePos())
            for item in items_under_cursor:
                if item == self._drag_connection_line: continue
                if isinstance(item, PortItem):
                    target_item_under_cursor = item; break
                if isinstance(item, BulkAreaItem) and not target_item_under_cursor:
                    target_item_under_cursor = item
        
        current_target_as_port = target_item_under_cursor if isinstance(target_item_under_cursor, PortItem) else None
        current_target_as_bulk = target_item_under_cursor if isinstance(target_item_under_cursor, BulkAreaItem) else None

        newly_highlighted_port: typing.Optional[PortItem] = None
        newly_highlighted_bulk: typing.Optional[BulkAreaItem] = None
        action_color = constants.DEFAULT_DRAG_LINE_COLOR

        if self._drag_source_port:
            if current_target_as_port:
                action, color = graph_drag_helpers.determine_port_to_port_action(self._drag_source_port, current_target_as_port, constants)
                if action: newly_highlighted_port = current_target_as_port; action_color = color
            elif current_target_as_bulk:
                action, color = graph_drag_helpers.determine_port_to_bulk_action(self._drag_source_port, current_target_as_bulk, constants)
                if action: newly_highlighted_bulk = current_target_as_bulk; action_color = color
        elif self._drag_source_bulk_item:
            if current_target_as_port:
                action, color = graph_drag_helpers.determine_bulk_to_port_action(self._drag_source_bulk_item, current_target_as_port, constants)
                if action: newly_highlighted_port = current_target_as_port; action_color = color
            elif current_target_as_bulk:
                action, color = graph_drag_helpers.determine_bulk_to_bulk_action(self._drag_source_bulk_item, current_target_as_bulk, constants)
                if action: newly_highlighted_bulk = current_target_as_bulk; action_color = color

        # Update Port Highlighting
        if self._drag_hovered_port != newly_highlighted_port:
            if self._drag_hovered_port: self._drag_hovered_port.set_drag_highlight(False)
            self._drag_hovered_port = newly_highlighted_port
            if self._drag_hovered_port: self._drag_hovered_port.set_drag_highlight(True)

        # Update Bulk Area Highlighting
        if self._drag_hovered_bulk_area != newly_highlighted_bulk:
            if self._drag_hovered_bulk_area: self._drag_hovered_bulk_area.set_drag_highlight(False)
            self._drag_hovered_bulk_area = newly_highlighted_bulk
            if self._drag_hovered_bulk_area: self._drag_hovered_bulk_area.set_drag_highlight(True)
        
        # Ensure mutual exclusivity of highlights
        if newly_highlighted_port and self._drag_hovered_bulk_area:
            self._drag_hovered_bulk_area.set_drag_highlight(False)
            self._drag_hovered_bulk_area = None
        elif newly_highlighted_bulk and self._drag_hovered_port:
            self._drag_hovered_port.set_drag_highlight(False)
            self._drag_hovered_port = None

        # Update Drag Line Color
        current_pen = self._drag_connection_line.pen()
        if current_pen.color() != action_color:
            current_pen.setColor(action_color)
            self._drag_connection_line.setPen(current_pen)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> bool:
        """Handle custom drag initiation, drag line updates. Returns True if event consumed."""
        self._last_mouse_pos = event.scenePos()

        # Check if we're moving a split node and restrict to horizontal movement
        moved_node = self._moved_node
        if moved_node and moved_node.is_split_part:
            # Lock Y position to original value, only allow X movement
            new_pos = QPointF(event.scenePos().x(), moved_node.scenePos().y())
            moved_node.setPos(new_pos)
            event.setAccepted(True)
            return True

        if self._try_initiate_custom_drag(event):
            return True # Custom drag started, event consumed

        if self._drag_connection_line: # A custom drag is active
            self._update_active_drag_visuals(event)
            return True # Consume event while custom drag is active
            
        return False # Event not consumed (e.g. standard move or rubber band selection)


    def _clear_drag_highlights(self) -> None:
        """Clears any active drag highlights on ports or bulk areas."""
        if self._drag_hovered_port:
            self._drag_hovered_port.set_drag_highlight(False)
            self._drag_hovered_port = None
        if self._drag_hovered_bulk_area:
            self._drag_hovered_bulk_area.set_drag_highlight(False)
            self._drag_hovered_bulk_area = None

    def _finalize_port_connection_drag(self, event: QGraphicsSceneMouseEvent) -> bool:
        """Handles the end of a drag initiated from a PortItem. Returns True if drag was processed."""
        if not self._drag_source_port:
            return False

        source_port_item = self._drag_source_port
        is_disconnect_hint = self._is_disconnect_drag

        # Reset state for port drag
        self._drag_source_port = None
        self._is_disconnect_drag = False

        if self._drag_connection_line:
            self.scene.removeItem(self._drag_connection_line)
            self._drag_connection_line = None

        view = self.scene.views()[0] if self.scene.views() else None
        target_item_at_release = self.scene.itemAt(event.scenePos(), view.transform()) if view else None # Use event.scenePos() for release
        self.end_connection_drag(source_port_item, target_item_at_release, is_disconnect_hint)
        return True

    def _finalize_bulk_connection_drag(self, event: QGraphicsSceneMouseEvent) -> bool:
        """Handles the end of a drag initiated from a BulkAreaItem. Returns True if drag was processed."""
        if not self._drag_source_bulk_item:
            return False

        source_bulk_item = self._drag_source_bulk_item
        is_source_input = source_bulk_item.is_input
        is_disconnect_hint = self._is_bulk_disconnect_drag
        
        # Reset state for bulk drag
        self._drag_source_bulk_item = None
        self._is_bulk_drag = False
        self._is_bulk_disconnect_drag = False

        if self._drag_connection_line:
            self.scene.removeItem(self._drag_connection_line)
            self._drag_connection_line = None

        view = self.scene.views()[0] if self.scene.views() else None
        target_item_at_release = self.scene.itemAt(event.scenePos(), view.transform()) if view else None # Use event.scenePos() for release
        self.end_bulk_connection_drag(source_bulk_item, target_item_at_release, is_source_input, is_disconnect_hint)
        return True

    def _finalize_node_drop_if_applicable(self, event: QGraphicsSceneMouseEvent, moved_node: Optional['NodeItem']) -> None:
        """Handles node-on-node drop if applicable."""
        if not moved_node: # No node was being tracked for a move/drop
            return

        view = self.scene.views()[0] if self.scene.views() else None
        # Use event.scenePos() for the drop location, not _last_mouse_pos which might be stale if no move occurred after press.
        target_item_at_drop = self.scene.itemAt(event.scenePos(), view.transform()) if view else None
        
        if isinstance(target_item_at_drop, NodeItem) and target_item_at_drop != moved_node:
            self.handle_node_drop_connection(moved_node, target_item_at_drop)
            # The scene's superclass method will handle the item's final position update.

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> Tuple[Optional['NodeItem'], bool]:
        """Handle end of drag or node drop. Returns (moved_node, consumed_by_custom_drag_end)."""
        moved_node_before_reset = self._moved_node # Store before any state is reset by finalize helpers
        consumed_by_custom_drag_end = False

        self._potential_drag_item = None # Always clear potential drag on release
        self._potential_drag_start_pos = None

        if event.button() == Qt.MouseButton.LeftButton:
            self._clear_drag_highlights() # Clear highlights regardless of what happens next

            if self._drag_source_bulk_item: # Prioritize bulk drag finalization
                consumed_by_custom_drag_end = self._finalize_bulk_connection_drag(event)
            elif self._drag_source_port: # Then port drag finalization
                consumed_by_custom_drag_end = self._finalize_port_connection_drag(event)
            
            # If a custom drag was not active or not finalized by the above, check for node drop
            if not consumed_by_custom_drag_end:
                self._finalize_node_drop_if_applicable(event, moved_node_before_reset)

        self._moved_node = None # Reset tracker after all potential actions
        self._last_mouse_pos = None # Reset last mouse position from mouseMove

        return moved_node_before_reset, consumed_by_custom_drag_end

    # Selection linking logic is now decentralized to PortItem and BulkAreaItem itemChange methods.
    # The _processing_selection flag in this handler is used by those items
    # via self.scene().interaction_handler._processing_selection to prevent recursion.
