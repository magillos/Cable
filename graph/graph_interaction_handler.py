import typing
import traceback
from PyQt6.QtWidgets import QGraphicsSceneMouseEvent, QGraphicsItem, QGraphicsPathItem, QApplication
from PyQt6.QtGui import QPen, QPainterPath, QColor
from PyQt6.QtCore import Qt, QPointF, QTimer # Added QTimer

# Import constants and other necessary types
from . import constants
from .port_item import PortItem
from .bulk_area_item import BulkAreaItem
from .node_item import NodeItem

if typing.TYPE_CHECKING:
    from .gui_scene import JackGraphScene
    from .node_item import NodeItem
    from .connection_item import ConnectionItem # Corrected import
    from .jack_handler import JackHandler
    from .config_utils import ConfigManager
    from cables.jack_connection_handler import JackConnectionHandler # Added for type hint


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

    def __init__(self, scene: 'JackGraphScene', jack_handler: 'JackHandler', config_manager: 'ConfigManager', jack_connection_handler: 'JackConnectionHandler'):
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

    def _select_items(self, items_to_select: list[QGraphicsItem]):
        """Adds the given items to the scene's current selection."""
        if not items_to_select or not self.scene:
            return

        # If already processing, let the current operation complete to avoid nested issues.
        if self._processing_selection:
            print("DEBUG: _select_items called while already _processing_selection. Aborting current call.")
            return

        self._processing_selection = True # Set flag for the entire multi-stage operation
        # print(f"DEBUG: _select_items started. _processing_selection = True. Items: {[type(i).__name__ for i in items_to_select if i]}")

        processed_any_item = False
        if items_to_select:
            first_item_to_select = items_to_select[0]
            if first_item_to_select:
                first_item_to_select.setSelected(True)
                if self.scene.views(): self.scene.views()[0].ensureVisible(first_item_to_select)
                
                item_id = ""
                if hasattr(first_item_to_select, 'port_name'): item_id = getattr(first_item_to_select, 'port_name')
                elif hasattr(first_item_to_select, 'client_name'): item_id = getattr(first_item_to_select, 'client_name')
                elif isinstance(first_item_to_select, BulkAreaItem) and first_item_to_select.parent_node: item_id = f"BulkArea of {first_item_to_select.parent_node.client_name}"
                # print(f"    Immediately selected: {type(first_item_to_select).__name__} {item_id}")
                processed_any_item = True

            remaining_items = [item for item in items_to_select[1:] if item] # Filter out None items

            if remaining_items:
                # Pass a copy of the list to the lambda
                QTimer.singleShot(0, lambda items_copy=list(remaining_items): self._select_remaining_items_deferred(items_copy))
                # DO NOT reset _processing_selection here; it will be reset by the deferred call
            elif processed_any_item: # Only first item was processed, no deferred items
                # print("DEBUG: _select_items finished (only first item, no deferred). _processing_selection = False.")
                self._processing_selection = False
            else: # No items were processed at all (e.g. items_to_select was empty or all None)
                # print("DEBUG: _select_items finished (no items processed). _processing_selection = False.")
                self._processing_selection = False
        else: # items_to_select was empty
            # print("DEBUG: _select_items called with empty list. _processing_selection = False.")
            self._processing_selection = False


    def _select_remaining_items_deferred(self, items: list[QGraphicsItem]):
        """Selects items deferred by QTimer.singleShot. Resets _processing_selection flag."""
        # print(f"DEBUG: _select_remaining_items_deferred started for {len(items)} items. _processing_selection should be True.")
        try:
            for item_to_select in items:
                if item_to_select: # Should have been filtered already, but double check
                    item_to_select.setSelected(True)
                    if self.scene.views(): self.scene.views()[0].ensureVisible(item_to_select)

                    item_id = ""
                    if hasattr(item_to_select, 'port_name'): item_id = getattr(item_to_select, 'port_name')
                    elif hasattr(item_to_select, 'client_name'): item_id = getattr(item_to_select, 'client_name')
                    elif isinstance(item_to_select, BulkAreaItem) and item_to_select.parent_node: item_id = f"BulkArea of {item_to_select.parent_node.client_name}"
                    # print(f"      Deferred selected: {type(item_to_select).__name__} {item_id}")
        finally:
            # This is the end of the entire multi-selection operation (including deferred parts).
            # print("DEBUG: _select_remaining_items_deferred finished. _processing_selection = False.")
            self._processing_selection = False

    # --- Drag Initiation ---

    def start_connection_drag(self, source_port: 'PortItem', is_disconnect_drag: bool = False):
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


    def start_bulk_connection_drag(self, source_item: 'BulkAreaItem', is_input_area: bool, is_disconnect_drag: bool):
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

    def update_drag_line(self, cursor_pos: QPointF):
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


    # --- Helper methods to determine drag action and color ---

    def _determine_port_to_port_action(self, source_port: 'PortItem', target_port: 'PortItem') -> tuple[typing.Optional[str], QColor]:
        """Determines action (connect/disconnect) and color for port-to-port drag."""
        if not source_port or not target_port:
            return None, constants.DEFAULT_DRAG_LINE_COLOR
        
        # Check for self-connection
        if source_port.parent_node == target_port.parent_node:
            parent_node = source_port.parent_node
            # Allow self-connection only if the node is not split
            if parent_node.is_split_origin or parent_node.is_split_part:
                return None, constants.DEFAULT_DRAG_LINE_COLOR # Cannot connect to same node if split
            # If unsplit, proceed to check connection validity (e.g. IN to OUT)
        
        out_p, in_p = (source_port, target_port) if not source_port.is_input and target_port.is_input else \
                      (target_port, source_port) if source_port.is_input and not target_port.is_input else \
                      (None, None)

        if not out_p or not in_p:
            return None, constants.DEFAULT_DRAG_LINE_COLOR # Invalid type combination

        is_already_connected = any(
            (conn.source_port == out_p and conn.dest_port == in_p)
            for conn in out_p.connections # Check connections of the output port
        )

        if is_already_connected:
            return "disconnect", constants.PORT_DISCONNECT_DRAG_COLOR
        else:
            return "connect", constants.PORT_DRAG_COLOR

    def _determine_port_to_bulk_action(self, source_port: 'PortItem', target_bulk: 'BulkAreaItem') -> tuple[typing.Optional[str], QColor]:
        """Determines action and color for port-to-bulk drag."""
        if not source_port or not target_bulk:
            return None, constants.DEFAULT_DRAG_LINE_COLOR
        
        parent_node = source_port.parent_node
        if parent_node == target_bulk.parent_node: # Self-connection attempt
            if parent_node.is_split_origin or parent_node.is_split_part:
                return None, constants.DEFAULT_DRAG_LINE_COLOR # Disallow if split
            # If unsplit, proceed with type check

        if source_port.is_input == target_bulk.is_input: # Must be different types (e.g., port OUT to bulk IN)
            return None, constants.DEFAULT_DRAG_LINE_COLOR

        compatible_target_ports: list[PortItem] = []
        if not source_port.is_input and target_bulk.is_input: # Source OUT, Target Bulk IN
            compatible_target_ports.extend(p for p in target_bulk.parent_node.input_ports.values() if p.is_input) # Ensure they are indeed input ports
        elif source_port.is_input and not target_bulk.is_input: # Source IN, Target Bulk OUT
            compatible_target_ports.extend(p for p in target_bulk.parent_node.output_ports.values() if not p.is_input) # Ensure they are indeed output ports

        if not compatible_target_ports:
            return None, constants.DEFAULT_DRAG_LINE_COLOR # No compatible ports in target bulk

        num_already_connected_to_source = 0
        for port_in_bulk in compatible_target_ports:
            out_p_item, in_p_item = (source_port, port_in_bulk) if not source_port.is_input else (port_in_bulk, source_port)
            if any((conn.source_port == out_p_item and conn.dest_port == in_p_item) for conn in out_p_item.connections):
                num_already_connected_to_source += 1
        
        if len(compatible_target_ports) > 0 and num_already_connected_to_source == len(compatible_target_ports):
            # If source is connected to ALL compatible ports in target bulk, action is disconnect
            return "disconnect", constants.PORT_DISCONNECT_DRAG_COLOR
        else:
            # Otherwise, action is connect (even if some are connected, intent is to connect others or the first one)
            return "connect", constants.PORT_DRAG_COLOR

    def _determine_bulk_to_port_action(self, source_bulk: 'BulkAreaItem', target_port: 'PortItem') -> tuple[typing.Optional[str], QColor]:
        """Determines action and color for bulk-to-port drag."""
        if not source_bulk or not target_port:
            return None, constants.DEFAULT_DRAG_LINE_COLOR

        parent_node = source_bulk.parent_node
        if parent_node == target_port.parent_node: # Self-connection attempt
            if parent_node.is_split_origin or parent_node.is_split_part:
                return None, constants.DEFAULT_DRAG_LINE_COLOR # Disallow if split
            # If unsplit, proceed with type check

        if source_bulk.is_input == target_port.is_input: # Must be different types (e.g., bulk OUT to port IN)
            return None, constants.DEFAULT_DRAG_LINE_COLOR

        source_ports_to_consider = source_bulk.parent_node.input_ports.values() if source_bulk.is_input else source_bulk.parent_node.output_ports.values()
        compatible_source_ports: list[PortItem] = [sp for sp in source_ports_to_consider if sp.is_input != target_port.is_input]

        if not compatible_source_ports:
            return None, constants.DEFAULT_DRAG_LINE_COLOR

        num_already_connected_to_target = 0
        for s_port in compatible_source_ports:
            out_p, in_p = (s_port, target_port) if not s_port.is_input else (target_port, s_port)
            if any(conn.source_port == out_p and conn.dest_port == in_p for conn in out_p.connections):
                num_already_connected_to_target += 1

        if len(compatible_source_ports) > 0 and num_already_connected_to_target == len(compatible_source_ports):
            # If ALL compatible source ports are connected to target_port, action is disconnect
            return "disconnect", constants.PORT_DISCONNECT_DRAG_COLOR
        else:
            # Otherwise, action is connect
            return "connect", constants.PORT_DRAG_COLOR

    def _determine_bulk_to_bulk_action(self, source_bulk: 'BulkAreaItem', target_bulk: 'BulkAreaItem') -> tuple[typing.Optional[str], QColor]:
        """Determines action and color for bulk-to-bulk drag, considering specific direction."""
        if not source_bulk or not target_bulk:
            return None, constants.DEFAULT_DRAG_LINE_COLOR

        parent_node = source_bulk.parent_node
        if parent_node == target_bulk.parent_node: # Self-connection attempt
            if parent_node.is_split_origin or parent_node.is_split_part:
                # Cannot connect a node to itself via bulk areas if split
                return None, constants.DEFAULT_DRAG_LINE_COLOR
            # If unsplit, proceed to check if IN to OUT or OUT to IN for self-connection
            if source_bulk.is_input == target_bulk.is_input: # e.g. IN bulk to IN bulk on same node
                return None, constants.DEFAULT_DRAG_LINE_COLOR
        elif source_bulk.is_input == target_bulk.is_input: # For different nodes, still disallow IN-IN or OUT-OUT
            # Cannot connect IN to IN or OUT to OUT
            return None, constants.DEFAULT_DRAG_LINE_COLOR

        # Determine effective output and input nodes/ports for the current drag direction
        source_node = source_bulk.parent_node
        target_node = target_bulk.parent_node

        # Forward type declarations for clarity within this scope
        out_node_for_drag: 'NodeItem'
        in_node_for_drag: 'NodeItem'
        out_ports_for_drag: list['PortItem']
        in_ports_for_drag: list['PortItem']

        if not source_bulk.is_input:  # Source is an OUTPUT bulk area
            # Target must be an INPUT bulk area (checked by source_bulk.is_input == target_bulk.is_input)
            out_node_for_drag = source_node
            out_ports_for_drag = list(source_node.output_ports.values())
            in_node_for_drag = target_node
            in_ports_for_drag = list(target_node.input_ports.values())
        else:  # Source is an INPUT bulk area
            # Target must be an OUTPUT bulk area
            in_node_for_drag = source_node
            in_ports_for_drag = list(source_node.input_ports.values())
            out_node_for_drag = target_node
            out_ports_for_drag = list(target_node.output_ports.values())
        
        if not out_ports_for_drag or not in_ports_for_drag:
            # If either side has no relevant ports for a bulk connection (e.g., a node with only inputs being dragged from its output area)
            # Default to allowing a connection attempt, JACK might handle it or it might be an edge case.
            # For color indication, if one side is empty, it's unlikely to be a "disconnect all" scenario for existing connections.
            return "connect_all", constants.PORT_DRAG_COLOR

        num_potential_connections = min(len(out_ports_for_drag), len(in_ports_for_drag))
        
        # If there are no ports on one side that could form a pair, treat as a new connection attempt.
        if num_potential_connections == 0:
             return "connect_all", constants.PORT_DRAG_COLOR

        num_existing_connections_in_direction = 0
        # Check connections specifically from the determined out_ports_for_drag to in_ports_for_drag
        for out_port_item in out_ports_for_drag:
            # Only consider the first 'num_potential_connections' ports if port counts differ,
            # mimicking how JACK often connects sequentially.
            # This check is primarily for connections *between* the two bulk areas in the current drag direction.
            idx_out = out_ports_for_drag.index(out_port_item)
            if idx_out >= num_potential_connections:
                continue # Only check up to the number of potential pairings

            for conn_item in out_port_item.connections:
                # Check if this connection's destination is one of the in_ports_for_drag
                # AND belongs to the in_node_for_drag
                # AND is within the potential pairing range
                if conn_item.dest_port in in_ports_for_drag:
                    idx_in = in_ports_for_drag.index(conn_item.dest_port)
                    if idx_in < num_potential_connections and conn_item.dest_port.parent_node == in_node_for_drag:
                         # A more precise check: ensure the connected pair corresponds to a potential sequential pairing
                        if out_ports_for_drag[idx_out] == conn_item.source_port and \
                           in_ports_for_drag[idx_in] == conn_item.dest_port and \
                           idx_out == idx_in: # Basic sequential pairing check
                            num_existing_connections_in_direction += 1
        
        # If all potential connections *in this specific direction and pairing* already exist,
        # then the action is to disconnect them.
        if num_existing_connections_in_direction >= num_potential_connections:
            return "disconnect_all", constants.PORT_DISCONNECT_DRAG_COLOR
        else:
            # Otherwise, the action is to connect (which might connect missing ones or all if none exist).
            return "connect_all", constants.PORT_DRAG_COLOR

    # --- Drag Finalization ---

    def end_connection_drag(self, source_port: 'PortItem', target_item: QGraphicsItem | None, is_disconnect_drag: bool): # is_disconnect_drag is now for initial UI cue, not final action
        """Finalize drag: connect or disconnect based on existing connections."""
        print(f"Handler end_connection_drag: source={source_port.port_name if source_port else 'None'}, target_type={type(target_item).__name__}")

        if not source_port:
            print("  Invalid source port, exiting.")
            return

        # --- Handle Target is PortItem ---
        if isinstance(target_item, PortItem) and target_item != source_port:
            target_as_port = target_item
            parent_node = source_port.parent_node
            
            if parent_node == target_as_port.parent_node:
                # This is a self-connection attempt
                if parent_node.is_split_origin or parent_node.is_split_part:
                    print("  Cannot connect port to another port on the same node (node is split).")
                    return
                # If unsplit, proceed with connection logic for self-connection
                print(f"  Attempting self-connection on unsplit node: {parent_node.client_name}")

            out_p_item, in_p_item = (source_port, target_as_port) if not source_port.is_input and target_as_port.is_input else \
                                    (target_as_port, source_port) if source_port.is_input and not target_as_port.is_input else \
                                    (None, None)

            if not out_p_item or not in_p_item:
                print(f"  Invalid port type combination for connection: {source_port.port_name}({source_port.is_input}) to {target_as_port.port_name}({target_as_port.is_input}).")
                return

            is_already_connected = any(
                (conn.source_port == out_p_item and conn.dest_port == in_p_item) or \
                (conn.source_port == in_p_item and conn.dest_port == out_p_item) # Should not happen with correct out/in assignment
                for conn in out_p_item.connections # Check connections of the output port
            )

            if is_already_connected:
                print(f"  Ports {out_p_item.port_name} and {in_p_item.port_name} are already connected. Attempting disconnect.")
                try:
                    if out_p_item.is_midi:
                        self.jack_connection_handler.break_midi_connection(out_p_item.port_name, in_p_item.port_name)
                    else:
                        self.jack_connection_handler.break_connection(out_p_item.port_name, in_p_item.port_name)
                    print(f"    JACK disconnect successful: {out_p_item.port_name} from {in_p_item.port_name}")
                except Exception as e:
                    print(f"    Error during JACK disconnect: {e}")
            else:
                print(f"  Attempting JACK connect: {out_p_item.port_name} -> {in_p_item.port_name}")
                try:
                    if out_p_item.is_midi:
                        self.jack_connection_handler.make_midi_connection(out_p_item.port_name, in_p_item.port_name)
                    else:
                        self.jack_connection_handler.make_connection(out_p_item.port_name, in_p_item.port_name)
                    print(f"    JACK connect successful: {out_p_item.port_name} -> {in_p_item.port_name}")
                    self._select_items([source_port, target_as_port]) # Select source and target port
                except Exception as e:
                    print(f"    Error during JACK connect: {e}")

        # --- Handle Target is BulkAreaItem ---
        elif isinstance(target_item, BulkAreaItem): # Target is BulkArea
            target_as_bulk = target_item
            parent_node = source_port.parent_node

            if parent_node == target_as_bulk.parent_node: # Self-connection: Port to Bulk on same node
                if parent_node.is_split_origin or parent_node.is_split_part:
                    print(f"  Cannot connect port {source_port.port_name} to BulkArea on the same node (node is split).")
                    return
                print(f"  Attempting self-connection: Port {source_port.port_name} to BulkArea on unsplit node {parent_node.client_name}")
            
            # Determine compatible ports in the target bulk area
            compatible_target_ports: list[PortItem] = []
            if not source_port.is_input and target_as_bulk.is_input: # Source OUT, Target Bulk IN
                compatible_target_ports.extend(target_as_bulk.parent_node.input_ports.values())
            elif source_port.is_input and not target_as_bulk.is_input: # Source IN, Target Bulk OUT
                compatible_target_ports.extend(target_as_bulk.parent_node.output_ports.values())
            else:
                print(f"  Invalid port-to-bulk type combination: {source_port.port_name}({source_port.is_input}) to BulkArea({target_as_bulk.is_input}).")
                return

            if not compatible_target_ports:
                print(f"  No compatible ports found in target BulkArea for {source_port.port_name}.")
                return

            num_already_connected = 0
            connections_to_make = []
            connections_to_break = []

            for port_in_bulk in compatible_target_ports:
                out_p_item, in_p_item = (source_port, port_in_bulk) if not source_port.is_input else (port_in_bulk, source_port)
                
                is_this_pair_connected = any(
                    (conn.source_port == out_p_item and conn.dest_port == in_p_item)
                    for conn in out_p_item.connections
                )

                if is_this_pair_connected:
                    num_already_connected += 1
                    connections_to_break.append((out_p_item, in_p_item))
                else:
                    connections_to_make.append((out_p_item, in_p_item))
            
            if num_already_connected == len(compatible_target_ports) and len(compatible_target_ports) > 0 : # Exact repeat of full connection
                print(f"  Source port {source_port.port_name} is already fully connected to compatible ports in BulkArea. Attempting disconnect all.")
                for out_p, in_p in connections_to_break: # Should be all compatible_target_ports
                    try:
                        if out_p.is_midi:
                            self.jack_connection_handler.break_midi_connection(out_p.port_name, in_p.port_name)
                        else:
                            self.jack_connection_handler.break_connection(out_p.port_name, in_p.port_name)
                        print(f"    JACK disconnect successful: {out_p.port_name} from {in_p.port_name}")
                    except Exception as e:
                        print(f"    Error during JACK disconnect (port-to-bulk): {e}")
            else: # Not an exact full repeat, so connect all compatible (JACK connect usually handles existing ones gracefully)
                print(f"  Attempting to connect {source_port.port_name} to all compatible ports in BulkArea.")
                connection_succeeded_for_bulk = False # Flag
                for port_in_bulk in compatible_target_ports:
                    out_p_item, in_p_item = (source_port, port_in_bulk) if not source_port.is_input else (port_in_bulk, source_port)
                    # Check again if already connected before trying to connect, to avoid redundant calls if some were already connected
                    is_this_pair_connected = any(
                        (conn.source_port == out_p_item and conn.dest_port == in_p_item)
                        for conn in out_p_item.connections
                    )
                    if not is_this_pair_connected:
                        print(f"    Attempting JACK connect: {out_p_item.port_name} -> {in_p_item.port_name}")
                        try:
                            if out_p_item.is_midi:
                                self.jack_connection_handler.make_midi_connection(out_p_item.port_name, in_p_item.port_name)
                            else:
                                self.jack_connection_handler.make_connection(out_p_item.port_name, in_p_item.port_name)
                            print(f"      JACK connect successful: {out_p_item.port_name} -> {in_p_item.port_name}")
                            connection_succeeded_for_bulk = True # Mark success
                        except Exception as e:
                            print(f"      Error during JACK connect (port-to-bulk): {e}")
                    else:
                        print(f"    Skipping already connected: {out_p_item.port_name} -> {in_p_item.port_name}")
                
                if connection_succeeded_for_bulk and target_as_bulk.parent_node:
                    # Try selecting Node first, then Port
                    items_to_select_after_port_to_bulk = []
                    # Select the target BulkAreaItem and the source PortItem
                    items_to_select_after_port_to_bulk.append(target_as_bulk)
                    items_to_select_after_port_to_bulk.append(source_port)
                    
                    # --- DEBUG PRINT ---
                    print(f"DEBUG Port-to-Bulk (Node first): Attempting to select {len(items_to_select_after_port_to_bulk)} items:")
                    for item_debug in items_to_select_after_port_to_bulk:
                        debug_id = "UnknownID"
                        if hasattr(item_debug, 'port_name'): debug_id = item_debug.port_name
                        elif hasattr(item_debug, 'client_name'): debug_id = item_debug.client_name
                        elif isinstance(item_debug, BulkAreaItem) and item_debug.parent_node: debug_id = f"BulkArea of {item_debug.parent_node.client_name}"
                        print(f"  - Type: {type(item_debug).__name__}, ID: {debug_id}, Instance: {item_debug}")
                    # --- END DEBUG PRINT ---
                    print(f"LOGGING: Port-to-Bulk - Items to select: {[type(i).__name__ + (' (' + (i.port_name if hasattr(i, 'port_name') else i.client_name if hasattr(i, 'client_name') else f'Bulk of {i.parent_node.client_name}' if isinstance(i, BulkAreaItem) and i.parent_node else 'Unknown') + ')' if i else 'None') for i in items_to_select_after_port_to_bulk]}")
                    if items_to_select_after_port_to_bulk: # Ensure list is not empty
                        self._select_items(items_to_select_after_port_to_bulk)

        else:
            print(f"  Target item is not a valid PortItem or BulkAreaItem, or is on the same node: {type(target_item)}")


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

    def end_bulk_connection_drag(self, source_item: 'BulkAreaItem', target_item_at_release: QGraphicsItem | None, is_input_area: bool, _is_disconnect_drag_hint: bool): # _is_disconnect_drag_hint is ignored for final action
        """Finalize bulk drag: connect or disconnect based on existing connections."""
        source_node = source_item.parent_node
        print(f"Handler end_bulk_connection_drag: source_node={source_node.client_name}({'IN' if source_item.is_input else 'OUT'}), target_item_type={type(target_item_at_release).__name__}")

        resolved_target_bulk_area: typing.Optional[BulkAreaItem] = None
        resolved_target_port: typing.Optional[PortItem] = None
        target_node_for_connection: typing.Optional[NodeItem] = None

        if isinstance(target_item_at_release, PortItem):
            resolved_target_port = target_item_at_release
            target_node_for_connection = resolved_target_port.parent_node
            print(f"  Target resolved to Port: {resolved_target_port.port_name} on Node {target_node_for_connection.client_name if target_node_for_connection else 'None'}")
        elif isinstance(target_item_at_release, BulkAreaItem):
            resolved_target_bulk_area = target_item_at_release
            target_node_for_connection = resolved_target_bulk_area.parent_node
            print(f"  Target resolved to BulkArea on Node {target_node_for_connection.client_name if target_node_for_connection else 'None'}")
        elif isinstance(target_item_at_release, NodeItem):
            target_node_for_connection = target_item_at_release
            if source_item.is_input and target_node_for_connection.output_area_item:
                 resolved_target_bulk_area = target_node_for_connection.output_area_item
            elif not source_item.is_input and target_node_for_connection.input_area_item:
                 resolved_target_bulk_area = target_node_for_connection.input_area_item
            print(f"  Target resolved to NodeItem: {target_node_for_connection.client_name}. Effective BulkArea: {'Yes' if resolved_target_bulk_area else 'No'}")
        
        if not target_node_for_connection:
            print("  Handler bulk drag: Target node could not be resolved. Aborting.")
            return

        if target_node_for_connection == source_node: # Self-connection attempt
            if source_node.is_split_origin or source_node.is_split_part:
                print("  Handler bulk drag: Target is the same node, but node is split. Self-connection disallowed. Aborting.")
                return
            print(f"  Handler bulk drag: Attempting self-connection on unsplit node {source_node.client_name}.")
            # Proceed with logic for self-connection
        
        # --- Scenario 1: Dragging BulkArea to a single PortItem ---
        if resolved_target_port:
            print(f"  Processing Bulk-to-Port: Source Bulk ({'IN' if source_item.is_input else 'OUT'}) of {source_node.client_name} to Port {resolved_target_port.port_name}")
            source_ports_to_consider = source_node.input_ports.values() if source_item.is_input else source_node.output_ports.values()
            
            compatible_source_ports: list[PortItem] = []
            for s_port in source_ports_to_consider:
                if s_port.is_input != resolved_target_port.is_input: # Must be different types (IN to OUT or OUT to IN)
                    compatible_source_ports.append(s_port)

            if not compatible_source_ports:
                print(f"    No compatible ports in source BulkArea for target Port {resolved_target_port.port_name}.")
                return

            num_already_connected = 0
            connections_to_break: list[tuple[PortItem, PortItem]] = []
            connections_to_make: list[tuple[PortItem, PortItem]] = []

            for s_port in compatible_source_ports:
                out_p, in_p = (s_port, resolved_target_port) if not s_port.is_input else (resolved_target_port, s_port)
                is_this_pair_connected = any(conn.source_port == out_p and conn.dest_port == in_p for conn in out_p.connections)
                
                if is_this_pair_connected:
                    num_already_connected += 1
                    connections_to_break.append((out_p, in_p))
                else:
                    connections_to_make.append((out_p, in_p))
            
            if num_already_connected == len(compatible_source_ports) and len(compatible_source_ports) > 0: # Exact repeat: all compatible source ports are connected to target port
                print(f"    All compatible ports in source BulkArea already connected to {resolved_target_port.port_name}. Disconnecting all.")
                for out_p, in_p in connections_to_break:
                    try:
                        if out_p.is_midi: # Assuming PortItem has is_midi
                            self.jack_connection_handler.break_midi_connection(out_p.port_name, in_p.port_name)
                        else:
                            self.jack_connection_handler.break_connection(out_p.port_name, in_p.port_name)
                        print(f"      JACK disconnect successful: {out_p.port_name} from {in_p.port_name}")
                    except Exception as e:
                        print(f"      Error during JACK disconnect (bulk-to-port): {e}")
            else: # Not an exact repeat, or no connections exist. Connect missing ones.
                print(f"    Attempting to connect compatible ports from source BulkArea to {resolved_target_port.port_name}.")
                connection_succeeded_bulk_to_port = False
                for out_p, in_p in connections_to_make:
                    print(f"      Attempting JACK connect: {out_p.port_name} -> {in_p.port_name}")
                    try:
                        if out_p.is_midi: # Assuming PortItem has is_midi
                            self.jack_connection_handler.make_midi_connection(out_p.port_name, in_p.port_name)
                        else:
                            self.jack_connection_handler.make_connection(out_p.port_name, in_p.port_name)
                        print(f"        JACK connect successful: {out_p.port_name} -> {in_p.port_name}")
                        connection_succeeded_bulk_to_port = True
                    except Exception as e:
                        print(f"        Error during JACK connect (bulk-to-port): {e}")
                if not connections_to_make and num_already_connected > 0 and num_already_connected < len(compatible_source_ports):
                     print(f"    Some connections already existed but not all. No new connections made. {num_already_connected}/{len(compatible_source_ports)} were connected.")
                
                if connection_succeeded_bulk_to_port:
                    items_to_select_after_bulk_to_port = []
                    if source_item.parent_node:
                        items_to_select_after_bulk_to_port.append(source_item.parent_node)
                    items_to_select_after_bulk_to_port.append(resolved_target_port)
                    self._select_items(items_to_select_after_bulk_to_port) # Select source node and target port

        # --- Scenario 2: Dragging BulkArea to another BulkAreaItem (or NodeItem resolving to BulkArea) ---
        elif resolved_target_bulk_area:
            print(f"  Processing Bulk-to-Bulk: Source Bulk ({'IN' if source_item.is_input else 'OUT'}) of {source_node.client_name} to Target Bulk ({'IN' if resolved_target_bulk_area.is_input else 'OUT'}) of {target_node_for_connection.client_name}")

            if source_item.is_input == resolved_target_bulk_area.is_input:
                print("    Cannot connect IN to IN or OUT to OUT for Bulk-to-Bulk. Aborting.")
                return

            actual_source_client_name = source_node.original_client_name if source_node.is_split_part and source_node.original_client_name else source_node.client_name
            actual_target_client_name = target_node_for_connection.original_client_name if target_node_for_connection.is_split_part and target_node_for_connection.original_client_name else target_node_for_connection.client_name

            # Determine the actual output client and input client for the connection attempt
            # and their respective port collections.
            out_node_for_bulk_op: NodeItem
            in_node_for_bulk_op: NodeItem
            out_ports_collection_for_bulk_op: dict[str, PortItem]
            in_ports_collection_for_bulk_op: dict[str, PortItem]
            
            effective_output_client_name: str
            effective_input_client_name: str

            if not source_item.is_input: # Source is an OUTPUT bulk area
                out_node_for_bulk_op = source_node
                out_ports_collection_for_bulk_op = source_node.output_ports
                effective_output_client_name = actual_source_client_name

                # Target must be an INPUT bulk area (already checked by line 449)
                in_node_for_bulk_op = target_node_for_connection
                in_ports_collection_for_bulk_op = target_node_for_connection.input_ports
                effective_input_client_name = actual_target_client_name
            else: # Source is an INPUT bulk area
                in_node_for_bulk_op = source_node
                in_ports_collection_for_bulk_op = source_node.input_ports
                effective_input_client_name = actual_source_client_name

                # Target must be an OUTPUT bulk area (already checked by line 449)
                out_node_for_bulk_op = target_node_for_connection
                out_ports_collection_for_bulk_op = target_node_for_connection.output_ports
                effective_output_client_name = actual_target_client_name

            out_ports_list = list(out_ports_collection_for_bulk_op.values())
            in_ports_list = list(in_ports_collection_for_bulk_op.values())

            num_existing_connections = 0
            for out_port_item in out_ports_list:
                for conn_item in out_port_item.connections:
                    if conn_item.dest_port in in_ports_list and conn_item.dest_port.parent_node == in_node_for_bulk_op:
                        num_existing_connections += 1
            
            num_potential_connections = min(len(out_ports_list), len(in_ports_list))
            if not out_ports_list or not in_ports_list: # handles empty port lists
                num_potential_connections = 0

            print(f"    Bulk-to-Bulk analysis: Effective Output Node: {out_node_for_bulk_op.client_name} ({len(out_ports_list)} ports), Effective Input Node: {in_node_for_bulk_op.client_name} ({len(in_ports_list)} ports)")
            print(f"    Number of existing connections between these bulk areas: {num_existing_connections}")
            print(f"    Number of potential connections (e.g., stereo pair): {num_potential_connections}")

            if num_potential_connections == 0:
                print("    No potential connections to make (e.g., one side has no relevant ports). Aborting.")
                return

            # If all potential connections are already made, the action is to disconnect those specific connections.
            if num_existing_connections >= num_potential_connections: # Using >= for robustness
                print(f"    All {num_potential_connections} potential connections between these bulk areas appear to exist ({num_existing_connections} found). Disconnecting these specific pairs.")
                disconnect_count = 0
                for out_port_item in out_ports_list: # These are PortItem objects from the output bulk area
                    # Iterate over a copy of connections list in case it's modified by callbacks
                    for conn_item in list(out_port_item.connections):
                        # Check if the destination of this connection is one of the ports in the input bulk area
                        if conn_item.dest_port in in_ports_list and conn_item.dest_port.parent_node == in_node_for_bulk_op:
                            print(f"      Attempting to disconnect specific pair: {conn_item.source_port.port_name} -> {conn_item.dest_port.port_name}")
                            try:
                                # Determine if MIDI from the port item
                                is_midi_conn = conn_item.source_port.is_midi
                                if is_midi_conn:
                                    self.jack_connection_handler.break_midi_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                                else:
                                    self.jack_connection_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                                disconnect_count +=1
                                print(f"        JACK disconnect successful: {conn_item.source_port.port_name} from {conn_item.dest_port.port_name}")
                            except Exception as e:
                                print(f"        Error during specific JACK disconnect: {e}")
                print(f"    Disconnected {disconnect_count} specific pairs.")
            else:
                # Fewer than all potential connections exist (or none exist). Attempt to make all potential connections.
                print(f"    Not all potential connections exist ({num_existing_connections}/{num_potential_connections}). Attempting to connect all between {effective_output_client_name} and {effective_input_client_name}.")
                try:
                    # Use JackConnectionHandler's make_multiple_connections
                    # It determines is_midi based on the active tab, which might need review for graph context.
                    # For now, we pass the raw port names.
                    output_port_names = [p.port_name for p in out_ports_list]
                    input_port_names = [p.port_name for p in in_ports_list]
                    
                    if output_port_names and input_port_names:
                        self.jack_connection_handler.make_multiple_connections(output_port_names, input_port_names)
                        print("      Bulk JACK make_multiple_connections call successful.")
                        
                        items_to_select_for_b2b = []
                        # Select the target BulkAreaItem then the source BulkAreaItem
                        if resolved_target_bulk_area:
                            items_to_select_for_b2b.append(resolved_target_bulk_area)
                        if source_item: # source_item is the BulkAreaItem that was dragged
                            # Avoid adding if it's somehow the same as target and already added.
                            if source_item not in items_to_select_for_b2b:
                                items_to_select_for_b2b.append(source_item)
                        
                        # --- DEBUG PRINT ---
                        print(f"DEBUG Bulk-to-Bulk (Target Node first): Attempting to select {len(items_to_select_for_b2b)} items:")
                        for item_debug in items_to_select_for_b2b:
                            debug_id = "UnknownID"
                            if hasattr(item_debug, 'client_name'): debug_id = item_debug.client_name
                            elif isinstance(item_debug, BulkAreaItem) and item_debug.parent_node: debug_id = f"BulkArea of {item_debug.parent_node.client_name}"
                            print(f"  - Type: {type(item_debug).__name__}, ID: {debug_id}, Instance: {item_debug}")
                        # --- END DEBUG PRINT ---
                        print(f"LOGGING: Bulk-to-Bulk - Items to select: {[type(i).__name__ + (' (' + (i.client_name if hasattr(i, 'client_name') else f'Bulk of {i.parent_node.client_name}' if isinstance(i, BulkAreaItem) and i.parent_node else 'Unknown') + ')' if i else 'None') for i in items_to_select_for_b2b]}")
                        if items_to_select_for_b2b: # Ensure list is not empty
                            self._select_items(items_to_select_for_b2b)
                    else: # This else corresponds to 'if output_port_names and input_port_names:'
                        print("      Skipping make_multiple_connections due to empty output or input port lists for bulk operation.")
                except Exception as e: # This except corresponds to the 'try:' at line 743
                    print(f"      Error during bulk JACK make_multiple_connections call: {e}")
                    traceback.print_exc()
        # This else corresponds to 'elif resolved_target_bulk_area:' at line 658
        else:
            print("  Handler bulk drag: Target is not a resolvable Port or BulkArea. Aborting.")


    # --- Stereo Node Drop Logic ---
    def handle_node_drop_connection(self, source_node: 'NodeItem', target_node: 'NodeItem'):
        """Attempts to create a stereo connection when a node is dropped onto another."""
        print(f"Handler handling node drop: {source_node.client_name} onto {target_node.client_name}")

        source_outputs = source_node.output_ports
        target_inputs = target_node.input_ports

        if not source_outputs or not target_inputs:
            print("  Handler: Source has no outputs or target has no inputs.")
            return

        def find_port_with_suffix(port_dict, suffix_list):
            for port_name, port_item in port_dict.items():
                short_name = port_item.short_name
                for suffix in suffix_list:
                    if short_name.endswith(suffix): return port_item
            return None

        left_out_port = find_port_with_suffix(source_outputs, constants.STEREO_LEFT_SUFFIXES)
        left_in_port = find_port_with_suffix(target_inputs, constants.STEREO_LEFT_SUFFIXES)
        right_out_port = find_port_with_suffix(source_outputs, constants.STEREO_RIGHT_SUFFIXES)
        right_in_port = find_port_with_suffix(target_inputs, constants.STEREO_RIGHT_SUFFIXES)

        connection_made_on_drop = False
        if left_out_port and left_in_port:
            print(f"  Handler attempting LEFT connect: {left_out_port.port_name} -> {left_in_port.port_name}")
            try:
                if left_out_port.is_midi: # Assuming PortItem has is_midi
                    self.jack_connection_handler.make_midi_connection(left_out_port.port_name, left_in_port.port_name)
                else:
                    self.jack_connection_handler.make_connection(left_out_port.port_name, left_in_port.port_name)
                connection_made_on_drop = True
            except Exception as e: print(f"  Handler LEFT connection failed: {e}")
        else: print(f"  Handler could not find matching LEFT ports (Out: {left_out_port}, In: {left_in_port})")

        if right_out_port and right_in_port:
            print(f"  Handler attempting RIGHT connect: {right_out_port.port_name} -> {right_in_port.port_name}")
            try:
                if right_out_port.is_midi: # Assuming PortItem has is_midi
                    self.jack_connection_handler.make_midi_connection(right_out_port.port_name, right_in_port.port_name)
                else:
                    self.jack_connection_handler.make_connection(right_out_port.port_name, right_in_port.port_name)
                connection_made_on_drop = True
            except Exception as e: print(f"  Handler RIGHT connection failed: {e}")
        else: print(f"  Handler could not find matching RIGHT ports (Out: {right_out_port}, In: {right_in_port})")

        if connection_made_on_drop:
            self._select_items([source_node, target_node]) # Select source and target node of the drop


    # --- Mouse Events ---

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
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
                print(f"Handler mousePress: Stored potential drag item: {type(pressed_item).__name__}")
            elif isinstance(pressed_item, NodeItem):
                 # Track node for potential move (handled by scene's super call) or node-on-node drop
                 self._moved_node = pressed_item
                 print(f"Handler mousePress: Tracking potential move/drop for node: {pressed_item.client_name}")
        # Note: Scene's mousePressEvent will call super() AFTER this method


    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> bool:
        """Handle custom drag initiation, drag line updates. Returns True if event consumed."""
        # Need PortItem, BulkAreaItem for type checks and drag start

        self._last_mouse_pos = event.scenePos() # Store last position

        # --- Initiate Custom Drag if Conditions Met ---
        if self._potential_drag_item and event.buttons() & Qt.MouseButton.LeftButton:
            distance = (event.scenePos() - self._potential_drag_start_pos).manhattanLength()
            drag_threshold = QApplication.startDragDistance()

            if distance >= drag_threshold:
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    # Threshold met, no Shift -> Initiate custom drag
                    item_to_drag = self._potential_drag_item
                    self._potential_drag_item = None # Consume the potential drag
                    self._potential_drag_start_pos = None

                    if isinstance(item_to_drag, PortItem):
                        is_disconnect = bool(item_to_drag.connections)
                        print(f"Handler mouseMoveEvent: Initiating Port drag from {item_to_drag.port_name}")
                        self.start_connection_drag(item_to_drag, is_disconnect)
                        return True # Consume event
                    elif isinstance(item_to_drag, BulkAreaItem):
                        is_disconnect = any(p.connections for p in (item_to_drag.parent_node.input_ports if item_to_drag.is_input else item_to_drag.parent_node.output_ports).values())
                        print(f"Handler mouseMoveEvent: Initiating Bulk drag from {item_to_drag.parent_node.client_name} ({'IN' if item_to_drag.is_input else 'OUT'})")
                        self.start_bulk_connection_drag(item_to_drag, item_to_drag.is_input, is_disconnect)
                        return True # Consume event
                else:
                    # Drag threshold met, but Shift is pressed. Clear potential drag.
                    print("Handler mouseMoveEvent: Drag threshold met, but Shift pressed. Clearing potential drag.")
                    self._potential_drag_item = None
                    self._potential_drag_start_pos = None
                    # Fall through, do not consume, let scene handle rubber band

        # --- Handle Active Drag Line Update and Highlighting ---
        if self._drag_connection_line: # Check if a custom drag is active
            self.update_drag_line(event.scenePos())

            # Need PortItem, BulkAreaItem for type checks

            # Find item under cursor for highlighting
            view = self.scene.views()[0] if self.scene.views() else None
            target_item = None
            if view:
                items_under_cursor = self.scene.items(event.scenePos())
                for item in items_under_cursor:
                    if item == self._drag_connection_line: continue
                    if isinstance(item, PortItem):
                        target_item = item; break
                    if isinstance(item, BulkAreaItem) and not target_item:
                        target_item = item

            # --- Unified Highlighting Logic ---
            current_target_as_port = target_item if isinstance(target_item, PortItem) else None
            current_target_as_bulk = target_item if isinstance(target_item, BulkAreaItem) else None

            newly_highlighted_port: typing.Optional[PortItem] = None
            newly_highlighted_bulk: typing.Optional[BulkAreaItem] = None

            # Determine what to highlight based on whether a valid action can be performed
            if self._drag_source_port:  # Dragging from a PortItem
                if current_target_as_port: # Potential Port-to-Port
                    action, _ = self._determine_port_to_port_action(self._drag_source_port, current_target_as_port)
                    if action: # If any valid action (connect or disconnect)
                        newly_highlighted_port = current_target_as_port
                elif current_target_as_bulk: # Potential Port-to-Bulk
                    action, _ = self._determine_port_to_bulk_action(self._drag_source_port, current_target_as_bulk)
                    if action:
                        newly_highlighted_bulk = current_target_as_bulk
            elif self._drag_source_bulk_item:  # Dragging from a BulkAreaItem
                if current_target_as_port: # Potential Bulk-to-Port
                    action, _ = self._determine_bulk_to_port_action(self._drag_source_bulk_item, current_target_as_port)
                    if action:
                        newly_highlighted_port = current_target_as_port
                elif current_target_as_bulk: # Potential Bulk-to-Bulk
                    action, _ = self._determine_bulk_to_bulk_action(self._drag_source_bulk_item, current_target_as_bulk)
                    if action:
                        newly_highlighted_bulk = current_target_as_bulk
            
            # Update Port Highlighting
            if self._drag_hovered_port != newly_highlighted_port:
                if self._drag_hovered_port:
                    self._drag_hovered_port.set_drag_highlight(False)
                self._drag_hovered_port = newly_highlighted_port
                if self._drag_hovered_port:
                    self._drag_hovered_port.set_drag_highlight(True)

            # Update Bulk Area Highlighting
            if self._drag_hovered_bulk_area != newly_highlighted_bulk:
                if self._drag_hovered_bulk_area:
                    self._drag_hovered_bulk_area.set_drag_highlight(False)
                self._drag_hovered_bulk_area = newly_highlighted_bulk
                if self._drag_hovered_bulk_area:
                    self._drag_hovered_bulk_area.set_drag_highlight(True)

            # Ensure mutual exclusivity: if a port is highlighted, no bulk area should be, and vice-versa.
            if newly_highlighted_port and self._drag_hovered_bulk_area:
                 if self._drag_hovered_bulk_area != newly_highlighted_bulk: # only if it wasn't just set
                    self._drag_hovered_bulk_area.set_drag_highlight(False)
                    self._drag_hovered_bulk_area = None
            elif newly_highlighted_bulk and self._drag_hovered_port:
                 if self._drag_hovered_port != newly_highlighted_port: # only if it wasn't just set
                    self._drag_hovered_port.set_drag_highlight(False)
                    self._drag_hovered_port = None

            # --- Update Drag Line Color Based on Hover Target using Helper Methods ---
            if self._drag_connection_line:
                new_pen = self._drag_connection_line.pen()
                _action, target_color = None, constants.DEFAULT_DRAG_LINE_COLOR # Default

                current_hovered_port = self._drag_hovered_port
                current_hovered_bulk = self._drag_hovered_bulk_area

                if self._drag_source_port: # Dragging from a PortItem
                    if current_hovered_port:
                        _action, target_color = self._determine_port_to_port_action(self._drag_source_port, current_hovered_port)
                    elif current_hovered_bulk:
                        _action, target_color = self._determine_port_to_bulk_action(self._drag_source_port, current_hovered_bulk)
                
                elif self._drag_source_bulk_item: # Dragging from a BulkAreaItem
                    if current_hovered_port:
                        _action, target_color = self._determine_bulk_to_port_action(self._drag_source_bulk_item, current_hovered_port)
                    elif current_hovered_bulk:
                        _action, target_color = self._determine_bulk_to_bulk_action(self._drag_source_bulk_item, current_hovered_bulk)
                
                if new_pen.color() != target_color:
                    new_pen.setColor(target_color)
                    self._drag_connection_line.setPen(new_pen)

            return True # Consume event while custom drag is active

        # --- No Custom Drag Active ---
        return False # Event not consumed by handler


    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> tuple[typing.Optional['NodeItem'], bool]:
        """Handle end of drag or node drop. Returns (moved_node, consumed)."""
        # Need PortItem, BulkAreaItem, NodeItem for type checks

        # print(f"Handler mouseReleaseEvent: Button={event.button()}") # Silenced

        # Store potentially moved node before resetting state
        moved_node_before_reset = self._moved_node
        consumed = False # Flag if handler consumed the event

        # --- Clear Potential Drag Item ---
        self._potential_drag_item = None
        self._potential_drag_start_pos = None

        # --- Handle End of Custom Drag ---
        if event.button() == Qt.MouseButton.LeftButton:
            # Regardless of drag type, clear any active drag highlights first
            # This addresses the stuck highlight issue.
            drag_was_active = bool(self._drag_source_port or self._drag_source_bulk_item)

            if self._drag_hovered_port:
                self._drag_hovered_port.set_drag_highlight(False)
                self._drag_hovered_port = None
            if self._drag_hovered_bulk_area:
                self._drag_hovered_bulk_area.set_drag_highlight(False)
                self._drag_hovered_bulk_area = None

            # Now, handle the drag finalization
            if self._drag_source_bulk_item:
                source_item = self._drag_source_bulk_item
                is_input = source_item.is_input
                is_disconnect = self._is_bulk_disconnect_drag
                
                # Reset state for bulk drag
                self._drag_source_bulk_item = None
                self._is_bulk_drag = False
                self._is_bulk_disconnect_drag = False
                consumed = True

                if self._drag_connection_line:
                    self.scene.removeItem(self._drag_connection_line)
                    self._drag_connection_line = None

                view = self.scene.views()[0] if self.scene.views() else None
                target_item = self.scene.itemAt(self._last_mouse_pos, view.transform()) if view and self._last_mouse_pos else None
                print(f"Handler Bulk Drag End - Target: {type(target_item).__name__}")
                self.end_bulk_connection_drag(source_item, target_item, is_input, is_disconnect)
                print("Handler bulk drag mouse release consumed.")

            elif self._drag_source_port:
                source_port_item = self._drag_source_port
                is_disconnect = self._is_disconnect_drag

                # Reset state for port drag
                self._drag_source_port = None
                self._is_disconnect_drag = False
                consumed = True

                if self._drag_connection_line:
                    self.scene.removeItem(self._drag_connection_line)
                    self._drag_connection_line = None

                view = self.scene.views()[0] if self.scene.views() else None
                target_item = self.scene.itemAt(self._last_mouse_pos, view.transform()) if view and self._last_mouse_pos else None
                print(f"Handler Port Drag End - Target: {type(target_item).__name__}")
                self.end_connection_drag(source_port_item, target_item, is_disconnect)
                print("Handler port drag mouse release consumed.")

        # --- Handle Node Drop ---
        # Check for node-on-node drop only if a node was being tracked *and* drag didn't end
        if not consumed and moved_node_before_reset and event.button() == Qt.MouseButton.LeftButton:
            view = self.scene.views()[0] if self.scene.views() else None
            target_item = self.scene.itemAt(self._last_mouse_pos, view.transform()) if view and self._last_mouse_pos else None
            if isinstance(target_item, NodeItem) and target_item != moved_node_before_reset:
                print(f"Handler node drop detected: {moved_node_before_reset.client_name} onto {target_item.client_name}")
                self.handle_node_drop_connection(moved_node_before_reset, target_item)
                # Don't mark as consumed, let scene's super handle final position update

        # Reset moved node tracker *after* checking for drop
        self._moved_node = None

        # Return the node that was potentially moved and whether the event was consumed by drag end
        return moved_node_before_reset, consumed

    # Selection linking logic is now decentralized to PortItem and BulkAreaItem itemChange methods.
    # The _processing_selection flag in this handler is used by those items
    # via self.scene().interaction_handler._processing_selection to prevent recursion.