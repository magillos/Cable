# --- PyQt Graphical Items - NodeItem ---
import re # Import regex for natural sorting
import traceback # For error reporting in _split_node

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QGraphicsPathItem, QMenu,
    QStyleOptionGraphicsItem, QWidget, QStyle, QGraphicsSceneHoverEvent
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QAction, QPolygonF,
    QFontMetrics, QPalette
)
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QLineF, QEvent, QSize
)

from . import constants # Import the new constants module
from .port_item import PortItem # Import PortItem
from .bulk_area_item import BulkAreaItem # Import BulkAreaItem
from .config_utils import ConfigManager # Import ConfigManager
# Note: ConnectionItem is needed for creating new connections during split/unsplit
# from .connection_item import ConnectionItem # Avoid circular import here, use string literal


# --- Natural Sort Helper (Moved from gui_items.py) ---

def natural_sort_key(port_item: PortItem):
    """
    Creates a sort key that groups ports like 'name' before 'name-1', 'name-2'.
    Takes a PortItem as input.
    Returns a tuple: (has_number, base_name, number_value)
    """
    text = port_item.short_name.lower()
    # Regex to find base name and optional trailing -<number> or _<number>
    match = re.match(r'^(.*?)(?:[-_](\d+))?$', text)
    if match:
        base_name = match.group(1)
        number_str = match.group(2)
        if number_str:
            # Has number: (1, base, number)
            return (1, base_name, int(number_str))
        else:
            # No number: (0, base, -1)
            return (0, base_name, -1)
    else:
        # Should not happen with typical JACK names, but fallback to simple text sort
        return (0, text, -1)


# --- Modified Node Item ---

class NodeItem(QGraphicsItem):
    """Represents a JACK client with its ports."""
    # Modify the __init__ signature and logic
    def __init__(self, client_name, jack_handler, config_manager: ConfigManager, ports_to_add: dict | None = None):
        super().__init__()
        self.client_name = client_name # This might be the modified name like "Client (Inputs)"
        self.jack_handler = jack_handler
        self.config_manager = config_manager
        self.input_ports = {} # port_name: PortItem
        self.output_ports = {} # port_name: PortItem
        self._calculated_title_height = constants.NODE_TITLE_HEIGHT
        self._bounding_rect = QRectF(0, 0, constants.NODE_WIDTH, self._calculated_title_height)
        self.input_area_item: BulkAreaItem | None = None
        self.output_area_item: BulkAreaItem | None = None
        self.is_split_part = False # Flag to identify nodes *created* by splitting
        self.is_split_origin = False # Flag for the original node that *was* split
        self.split_input_node: 'NodeItem' | None = None # Reference to the input part (on origin)
        self.split_output_node: 'NodeItem' | None = None # Reference to the output part (on origin)
        self.split_origin_node: 'NodeItem' | None = None # Reference back to origin (on parts)
        self.original_client_name = None # Store the original JACK client name (for split parts)
        self.is_folded = False # New attribute for folding state (primarily for unsplit nodes)
        self._fold_state_initialized_from_config = False # True after fold state is first set from config
        self._header_rect = QRectF() # New attribute to store header rect for double-click
        self._internal_state_change_in_progress = False # Flag to control saving during split/unsplit

        # New attributes for fold state in split nodes (or nodes that *can* be split)
        # These are primarily used by the *split parts* themselves.
        # The origin node will read these from its parts before unsplitting.
        self.input_part_folded = False
        self.output_part_folded = False

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges)

        # Use the provided client_name (which might be modified) for the title
        self.title_item = QGraphicsTextItem(client_name, self)
        # self.title_item.setDefaultTextColor(constants.NODE_TITLE_COLOR) # Allow theme to control text color
        font = QFont()
        font.setBold(True)
        self.title_item.setFont(font)

        # Populate ports based on provided dict or fetch if None
        if ports_to_add is None:
            # This case might not be used often after this change,
            # but keep it for standard node creation.
            # Note: update_ports uses self.client_name, which might be modified.
            # This needs careful handling if we want standard creation to still work
            # based on the *actual* JACK name. Maybe pass original_client_name here?
            # For now, assume standard creation happens via scene.add_node which uses the real name.
            self.update_ports()
        else:
            # Store the original name if this is potentially a split part
            # The caller of __init__ should handle setting this correctly.
            # self.original_client_name = ??? # Needs to be set by caller if ports_to_add is used

            # print(f"Initializing node '{client_name}' with provided ports: {list(ports_to_add.keys())}") # Silenced
            # Ensure layout is calculated at least once if ports are added manually
            ports_added = False
            for port_name, port_obj in ports_to_add.items():
                if self.add_port(port_name, port_obj):
                    ports_added = True
            # Call layout_ports manually if ports were provided and added
            # if ports_added: # add_port calls layout_ports, so this might be redundant
            #     self.layout_ports()
            # Ensure layout runs even if no ports were provided (e.g., empty input/output node)
            if not ports_added:
                 self.layout_ports() # Calculate initial size even with no ports


    def boundingRect(self):
        return self._bounding_rect

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        # border_color = constants.SELECTION_BORDER_COLOR if is_selected else constants.NODE_BORDER_COLOR
        border_color = constants.SELECTION_BORDER_COLOR if is_selected else option.palette.color(QPalette.ColorRole.WindowText) # Use text color for default border
        border_width = 1.5 if is_selected else 1

        # Determine colors based on light/dark mode
        original_node_body_bg = option.palette.color(QPalette.ColorRole.Base)
        is_light_mode = original_node_body_bg.lightnessF() > 0.7  # Threshold for considering it light mode

        if is_light_mode:
            # Specific colors for light mode to ensure contrast
            node_body_bg_color = QColor(240, 240, 240)  # Very light gray (#F0F0F0)
            title_bg_color = QColor(220, 220, 220)    # Light gray (#DCDCDC)
            final_separator_color = QColor(192, 192, 192) # Medium gray (#C0C0C0)
        else:
            # Default behavior for dark mode or other themes
            node_body_bg_color = original_node_body_bg
            title_bg_color = option.palette.color(QPalette.ColorRole.Button)
            final_separator_color = option.palette.color(QPalette.ColorRole.Mid)

        # --- Draw Base Rounded Rectangle (Border) ---
        # Always draw the border based on the bounding rect
        painter.setBrush(Qt.BrushStyle.NoBrush) # Don't fill initially
        painter.setPen(QPen(border_color, border_width))
        painter.drawRoundedRect(self.boundingRect(), 5, 5)

        # --- Draw Title Background ---
        painter.setBrush(title_bg_color)
        painter.setPen(Qt.PenStyle.NoPen) # No border for the overlay
        # Define the title area rect
        title_rect = QRectF(0, 0, self.boundingRect().width(), self._calculated_title_height)
        # Create a path that only covers the title area within the rounded rect
        clip_path = QPainterPath()
        # Use a slightly smaller rect for clipping to avoid painting over the border itself
        clip_rect = self.boundingRect().adjusted(border_width / 2, border_width / 2, -border_width / 2, -border_width / 2)
        clip_path.addRoundedRect(clip_rect, 5, 5) # Use the same rounding
        title_path = QPainterPath()
        title_path.addRect(title_rect)
        # Intersect the title rect with the rounded node shape
        title_area_path = clip_path.intersected(title_path)
        painter.drawPath(title_area_path)

        # --- Draw Node Body and Separator (Only if NOT a split origin AND NOT folded) ---
        # Also consider part-specific folding if this node *is* a split part
        is_this_node_effectively_folded = self.is_folded
        if self.is_split_part:
            if self.input_ports and not self.output_ports: # This is an input part
                is_this_node_effectively_folded = self.input_part_folded
            elif self.output_ports and not self.input_ports: # This is an output part
                is_this_node_effectively_folded = self.output_part_folded
            # If it's a split part with both (shouldn't happen with current split logic), it defaults to self.is_folded

        if not self.is_split_origin and not is_this_node_effectively_folded:
            # Fill the body area below the title
            painter.setBrush(node_body_bg_color)
            painter.setPen(Qt.PenStyle.NoPen) # No border for this fill
            body_rect = QRectF(0, self._calculated_title_height, self.boundingRect().width(), self.boundingRect().height() - self._calculated_title_height)
            body_path = QPainterPath()
            body_path.addRect(body_rect)
            # Intersect with the rounded shape to clip correctly
            body_area_path = clip_path.intersected(body_path)
            painter.drawPath(body_area_path)

            # Draw Title Separator Line (Optional, can be themed too)
            # final_separator_color is already defined above based on light/dark mode
            painter.setPen(QPen(final_separator_color, 0.5))
            y_separator = int(self._calculated_title_height)
            # Draw line slightly inset to avoid overlapping the main border
            painter.drawLine(int(border_width), y_separator, int(self.boundingRect().width() - border_width), y_separator)

        # Bulk Connection Areas and Ports are separate child items and will paint themselves if visible.
        # Title text is also a child item (self.title_item) and paints itself.


    def add_port(self, port_name, port_obj):
        if self.is_split_origin: # If this is the hidden original node
            is_input_flag = port_obj.is_input
            target_node_part = self.split_input_node if is_input_flag else self.split_output_node
            if target_node_part:
                # print(f"NodeItem '{self.client_name}' (split origin) delegating add_port '{port_name}' to '{target_node_part.client_name}'")
                return target_node_part.add_port(port_name, port_obj)
            else:
                print(f"Warning: NodeItem '{self.client_name}' (split origin) cannot delegate add_port '{port_name}', target split part not found.")
                return False

        # Original logic for non-split nodes or for split parts themselves
        is_input_flag = port_obj.is_input
        port_map = self.input_ports if is_input_flag else self.output_ports

        if port_name not in port_map:
            # Create BulkAreaItem if this is the first port of its type
            if is_input_flag and not self.input_area_item:
                self.input_area_item = BulkAreaItem(self, is_input=True)
            elif not is_input_flag and not self.output_area_item:
                self.output_area_item = BulkAreaItem(self, is_input=False)

            port_item = PortItem(self, port_name, port_obj, is_input_flag)
            port_map[port_name] = port_item
            self.layout_ports() # Recalculate layout
            return True
        return False

    def remove_port(self, port_name):
        if self.is_split_origin: # If this is the hidden original node
            # Determine if it was an input or output port by checking the split parts
            removed_from_target = False
            if self.split_input_node and port_name in self.split_input_node.input_ports:
                # print(f"NodeItem '{self.client_name}' (split origin) delegating remove_port '{port_name}' to input part '{self.split_input_node.client_name}'")
                removed_from_target = self.split_input_node.remove_port(port_name)
            elif self.split_output_node and port_name in self.split_output_node.output_ports:
                # print(f"NodeItem '{self.client_name}' (split origin) delegating remove_port '{port_name}' to output part '{self.split_output_node.client_name}'")
                removed_from_target = self.split_output_node.remove_port(port_name)
            else:
                # This can happen if the port was already removed from the split part by a previous event
                # or if the split parts are not yet fully populated during a rapid sequence of events.
                # print(f"Warning: NodeItem '{self.client_name}' (split origin) could not find port '{port_name}' on its active split parts to delegate removal.")
                # It's also possible the port belonged to the origin but was removed before split parts were checked.
                # For safety, we can try to remove from self if it's somehow still there (though unlikely for a split origin).
                pass # No action if not found on split parts; the port might not exist there.
            return removed_from_target

        # Original logic for non-split nodes or for split parts themselves
        port_item = None
        if port_name in self.input_ports:
            port_item = self.input_ports.pop(port_name)
        elif port_name in self.output_ports:
            port_item = self.output_ports.pop(port_name)

        if port_item:
            # Clean up connections associated with this port visually
            for conn in list(port_item.connections): # Iterate copy
                conn.destroy() # Remove connection from scene and port lists
            # Remove port item itself from the scene
            if self.scene():
                 self.scene().removeItem(port_item)

            # Check if this was the last port of its type and remove BulkAreaItem
            if port_item.is_input and not self.input_ports and self.input_area_item:
                if self.scene():
                    self.scene().removeItem(self.input_area_item)
                self.input_area_item = None
            elif not port_item.is_input and not self.output_ports and self.output_area_item:
                 if self.scene():
                    self.scene().removeItem(self.output_area_item)
                 self.output_area_item = None

            self.layout_ports() # Recalculate layout
            return True
        return False

    def layout_ports(self):
        """Positions port items vertically and updates node height and width, including dynamic title height.
           If the node is a split origin, only calculates title size."""
        # --- Prepare for Geometry Change ---
        self.prepareGeometryChange()

        # --- Calculate Title Size (Always needed) ---
        # Determine a reasonable width for the title even if split
        # Use current width if available, otherwise estimate based on ports or default
        current_width = self._bounding_rect.width() if self._bounding_rect.width() > 0 else constants.NODE_WIDTH
        max_in_width = max((port.calculated_width for port in self.input_ports.values()), default=constants.PORT_WIDTH_MIN)
        max_out_width = max((port.calculated_width for port in self.output_ports.values()), default=constants.PORT_WIDTH_MIN)

        # Calculate node width appropriate to the node's state
        if self.is_split_origin:
            # For split origins, use estimated full width
            estimated_full_width = max(constants.NODE_WIDTH, max_in_width + max_out_width + 2 * constants.NODE_PADDING)
            node_width = estimated_full_width
        elif self.is_split_part:
            # For split parts (input-only or output-only), just need width for their ports
            if self.input_ports and not self.output_ports:  # Input part
                node_width = max(constants.NODE_WIDTH, max_in_width + 2 * constants.NODE_PADDING)
            elif self.output_ports and not self.input_ports:  # Output part
                node_width = max(constants.NODE_WIDTH, max_out_width + 2 * constants.NODE_PADDING)
            else:
                # Should not happen, but handle just in case
                node_width = max(constants.NODE_WIDTH, max_in_width + max_out_width + 2 * constants.NODE_PADDING)
        else:
            # Normal node with both inputs and outputs - allocate space for both
            node_width = max(constants.NODE_WIDTH, max_in_width + max_out_width + 2 * constants.NODE_PADDING)

        self._bounding_rect.setWidth(node_width) # Set width first

        title_width = node_width - 2 * constants.NODE_PADDING
        self.title_item.setTextWidth(title_width)
        self.title_item.setPos(constants.NODE_PADDING, constants.NODE_PADDING)
        doc_height = self.title_item.document().size().height()
        self._calculated_title_height = max(constants.NODE_TITLE_HEIGHT, doc_height + constants.NODE_PADDING * 2)
        self._header_rect = QRectF(0, 0, self._bounding_rect.width(), self._calculated_title_height) # Update header rect

        # If this is the visually split origin node, only set height to title height
        if self.is_split_origin:
            self._bounding_rect.setHeight(self._calculated_title_height)
            # Ensure ports and bulk areas are hidden
            for port in list(self.input_ports.values()) + list(self.output_ports.values()):
                if port.isVisible(): port.hide()
            if self.input_area_item and self.input_area_item.isVisible(): self.input_area_item.hide()
            if self.output_area_item and self.output_area_item.isVisible(): self.output_area_item.hide()
            self.update()
            return # Stop layout here for split origin

        # --- Handle Folded State ---
        # This needs to check the correct fold attribute based on whether it's a split part
        is_this_node_effectively_folded = self.is_folded
        if self.is_split_part:
            if self.input_ports and not self.output_ports: # Input part
                is_this_node_effectively_folded = self.input_part_folded
            elif self.output_ports and not self.input_ports: # Output part
                is_this_node_effectively_folded = self.output_part_folded

        if is_this_node_effectively_folded:
            self._bounding_rect.setHeight(self._calculated_title_height)
            # Ensure ports and bulk areas are hidden
            for port in list(self.input_ports.values()) + list(self.output_ports.values()):
                if port.isVisible(): port.hide()
            if self.input_area_item and self.input_area_item.isVisible(): self.input_area_item.hide()
            if self.output_area_item and self.output_area_item.isVisible(): self.output_area_item.hide()
            # Connections will need to be updated to point to the header
            for port_list in [self.input_ports, self.output_ports]:
                for port_item in port_list.values():
                    for conn in port_item.connections:
                        conn.update_path()
            self.update()
            return # Stop layout here for folded node

        # --- Continue Layout for Normal, Unfolded or Split Part Nodes ---
        # Ensure ports and bulk areas are visible if not split origin and not folded
        for port in list(self.input_ports.values()) + list(self.output_ports.values()):
            if not port.isVisible(): port.show()
        if self.input_area_item and not self.input_area_item.isVisible(): self.input_area_item.show()
        if self.output_area_item and not self.output_area_item.isVisible(): self.output_area_item.show()

        # --- Calculate Bulk Area Positions (if they exist) ---
        bulk_y = self._calculated_title_height + constants.NODE_VMARGIN
        pad = constants.NODE_BULK_AREA_HPADDING
        if self.input_area_item:
            bulk_in_width = max_in_width - 2*pad
            self.input_area_item._bounding_rect.setWidth(bulk_in_width)
            self.input_area_item.setPos(pad, bulk_y)
        if self.output_area_item:
            bulk_out_width = max_out_width - 2*pad
            self.output_area_item._bounding_rect.setWidth(bulk_out_width)

            # Position based on node type
            if self.is_split_part and not self.input_ports:
                # For output-only part, position at left with padding
                out_x = pad
            else:
                # For normal nodes or input parts with some outputs, position at right
                out_x = node_width - max_out_width + pad

            self.output_area_item.setPos(out_x, bulk_y)

        # --- Calculate Port Positions ---
        y_start_offset = self._calculated_title_height + constants.NODE_VMARGIN
        if self.input_area_item or self.output_area_item:
             y_start_offset += constants.NODE_BULK_AREA_HEIGHT + constants.NODE_VMARGIN

        # Position input ports (left side) - Use natural sorting
        y_in = y_start_offset
        for port_item in sorted(self.input_ports.values(), key=natural_sort_key):
            # Make sure each port uses its own calculated width
            port_item.calculated_width = port_item._calculate_required_width()
            # Position directly rather than through calculate_layout
            port_item.setPos(0, y_in)
            # Explicitly set the bounding rectangle to ensure correct hit testing
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, constants.PORT_HEIGHT)
            y_in += constants.PORT_HEIGHT + constants.NODE_VMARGIN

        # Position output ports (right side) - Use natural sorting
        y_out = y_start_offset
        for port_item in sorted(self.output_ports.values(), key=natural_sort_key):
            # Make sure each port uses its own calculated width
            port_item.calculated_width = port_item._calculate_required_width()

            # ALWAYS position output ports at right edge - port width
            x_pos = node_width - port_item.calculated_width
            port_item.setPos(x_pos, y_out)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, constants.PORT_HEIGHT)

            y_out += constants.PORT_HEIGHT + constants.NODE_VMARGIN

        # --- Adjust Node Height ---
        height_ports = max(y_in, y_out) - constants.NODE_VMARGIN if (self.input_ports or self.output_ports) else y_start_offset
        height_bulk_bottom = bulk_y + constants.NODE_BULK_AREA_HEIGHT if (self.input_area_item or self.output_area_item) else self._calculated_title_height
        height = max(height_ports, height_bulk_bottom) + constants.NODE_PADDING

        self._bounding_rect.setHeight(height)
        self.update()

    def get_bulk_connection_point(self, is_input: bool):
        """Return the scene coordinates of the center of the corresponding BulkAreaItem."""
        area_item = self.input_area_item if is_input else self.output_area_item
        if area_item:
            return area_item.get_connection_point()
        # Fallback or error? Return node center maybe?
        print(f"Warning: Tried to get bulk connection point for {'input' if is_input else 'output'} but BulkAreaItem doesn't exist.")
        return self.mapToScene(self.boundingRect().center())

    # hoverMoveEvent, hoverLeaveEvent, contextMenuEvent for bulk areas are now handled by BulkAreaItem
    # mousePressEvent for bulk areas is now handled by BulkAreaItem

    def _disconnect_all_connections(self):
        """Disconnect all input and output ports of this node using the centralized JackConnectionHandler."""
        print(f"NodeItem: Requesting disconnection of all ports for {self.client_name}")
        
        # Use the original client name if this is a split part, otherwise use its own client_name.
        # The JackConnectionHandler.disconnect_all_ports_of_client expects the actual JACK client name.
        client_to_disconnect = self.original_client_name if self.is_split_part and self.original_client_name else self.client_name
        
        current_scene = self.scene()
        if current_scene and hasattr(current_scene, 'jack_connection_handler'):
            try:
                # Call the centralized handler
                current_scene.jack_connection_handler.disconnect_all_ports_of_client(client_to_disconnect)
                print(f"Finished request to disconnect all ports for {client_to_disconnect} via JackConnectionHandler.")
                # UI updates, including graph refresh, should be handled by JackConnectionHandler._port_operation
            except Exception as e:
                print(f"Error calling JackConnectionHandler.disconnect_all_ports_of_client for {client_to_disconnect}: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"Error: Scene or JackConnectionHandler not available for disconnecting {client_to_disconnect}")

    # _disconnect_all_inputs and _disconnect_all_outputs are no longer needed
    # as _disconnect_all_connections now delegates to the centralized handler.

    def contextMenuEvent(self, event):
        """Show context menu for the node, specifically for the title area."""
        # Check if the click is within the title area
        if event.pos().y() <= self._calculated_title_height:
            menu = QMenu()

            # Determine properties for "Disconnect all" action (used in multiple cases)
            can_disconnect_inputs = any(p.connections for p in self.input_ports.values())
            can_disconnect_outputs = any(p.connections for p in self.output_ports.values())
            disconnect_is_enabled = can_disconnect_inputs or can_disconnect_outputs

            if self.is_split_part: # This NodeItem is a split part
                # Determine if it's an input or output part
                is_input_part = bool(self.input_ports and not self.output_ports)
                is_output_part = bool(self.output_ports and not self.input_ports)

                # 1. Disconnect Action
                disconnect_action_text = "Disconnect all"
                if is_input_part:
                    disconnect_action_text = "Disconnect all INs"
                elif is_output_part:
                    disconnect_action_text = "Disconnect all OUTs"
                disconnect_action = menu.addAction(disconnect_action_text) # Disconnects all ports of this part
                disconnect_action.setEnabled(disconnect_is_enabled)
                if is_input_part:
                    disconnect_action.triggered.connect(self._disconnect_this_part_input_ports)
                elif is_output_part:
                    disconnect_action.triggered.connect(self._disconnect_this_part_output_ports)
                else: # Should not happen for a split part, but fallback
                    disconnect_action.triggered.connect(self._disconnect_all_connections)


                # 2. Unsplit Action
                if self.split_origin_node:
                    unsplit_action = menu.addAction("Unsplit Node")
                    unsplit_action.triggered.connect(lambda: self.split_origin_node._unsplit_node(save_state=True))
                else:
                    unsplit_action = menu.addAction("Unsplit Node (Error: No Origin)")
                    unsplit_action.setEnabled(False)

                # 3. Fold/Unfold Part Action
                if is_input_part:
                    fold_action_text = "Unfold Input Part" if self.input_part_folded else "Fold Input Part"
                    fold_part_action = menu.addAction(fold_action_text)
                    fold_part_action.triggered.connect(lambda: self.toggle_input_fold())
                elif is_output_part:
                    fold_action_text = "Unfold Output Part" if self.output_part_folded else "Fold Output Part"
                    fold_part_action = menu.addAction(fold_action_text)
                    fold_part_action.triggered.connect(lambda: self.toggle_output_fold())

            elif self.is_split_origin: # This NodeItem is the (hidden) origin of a split node
                # 1. Disconnect Action
                # "Disconnect all" for a split origin should disconnect all ports of the original client
                disconnect_action = menu.addAction("Disconnect all")
                disconnect_action.setEnabled(disconnect_is_enabled) # Based on its own (delegated) ports
                disconnect_action.triggered.connect(self._disconnect_all_connections)

                # 2. Unsplit Action
                unsplit_action = menu.addAction("Unsplit Node")
                unsplit_action.triggered.connect(lambda: self._unsplit_node(save_state=True))

            else: # Original, non-split-part node
                disconnect_action = menu.addAction("Disconnect all")
                disconnect_action.setEnabled(disconnect_is_enabled)
                disconnect_action.triggered.connect(self._disconnect_all_connections)

                # 2. Split Action
                split_action = menu.addAction("Split Node")
                split_action.triggered.connect(lambda: self._split_node(save_state=True))
                # Split action must be enabled even if self.is_folded == True
                split_action.setEnabled(bool(self.input_ports) and bool(self.output_ports))
                
                # 3. Fold/Unfold Action
                fold_action_text = "Unfold Node" if self.is_folded else "Fold Node"
                fold_action = menu.addAction(fold_action_text)
                fold_action.triggered.connect(self._toggle_fold_state)

            menu.exec(event.screenPos())
            event.accept() # Consume the event so it doesn't propagate further
        else:
            # If clicked outside the title area, let the event propagate (e.g., to the scene)
            super().contextMenuEvent(event)

    # mousePressEvent no longer needs bulk area check, BulkAreaItem handles its own press.
    # Just call super for node movement and selection.
    def mousePressEvent(self, event):
        """Handle node selection and movement, and bring to front."""
        super().mousePressEvent(event)
        if self.scene():
            # Bring to front logic
            current_max_z = 0
            for item in self.scene().items():
                # Ensure we are comparing with other NodeItem instances and not self
                if item != self and isinstance(item, NodeItem):
                    current_max_z = max(current_max_z, item.zValue())
            self.setZValue(current_max_z + 1)
        # If we need specific node-level click actions later, add them here.

    def mouseDoubleClickEvent(self, event: QGraphicsSceneHoverEvent): # QGraphicsSceneMouseEvent actually
        """Handle double-click on the node's header to fold/unfold."""
        # Check if the double-click is within the header area
        # self._header_rect is in item's local coordinates. event.pos() is also local.
        if self._header_rect.contains(event.pos()):
            if self.is_split_part:
                is_input_part = bool(self.input_ports and not self.output_ports)
                is_output_part = bool(self.output_ports and not self.input_ports)
                if is_input_part:
                    self.toggle_input_fold()
                    event.accept()
                    return
                elif is_output_part:
                    self.toggle_output_fold()
                    event.accept()
                    return
            elif not self.is_split_origin: # Normal, unsplit node
                self._toggle_fold_state()
                event.accept()
                return
        super().mouseDoubleClickEvent(event) # Pass to parent if not handled

    def apply_configuration(self, config: dict):
        """Applies visual state (split, position, fold states) from a configuration dictionary."""
        
        # Determine target split state from config
        is_split_in_config = config.get("is_split", False)

        # Apply split/unsplit if current state differs from config
        if is_split_in_config and not self.is_split_origin:
            self._split_node(save_state=False) # This sets self.is_split_origin = True
        elif not is_split_in_config and self.is_split_origin:
            self._unsplit_node(save_state=False) # This sets self.is_split_origin = False

        # Now, self.is_split_origin reflects the state dictated by the config (or initial state if no change needed)

        # Apply positions
        if self.is_split_origin: # Node is now split
            if self.split_input_node:
                split_input_pos_qpoint = config.get("split_input_pos")
                if isinstance(split_input_pos_qpoint, QPointF):
                    self.split_input_node.setPos(split_input_pos_qpoint)
            if self.split_output_node:
                split_output_pos_qpoint = config.get("split_output_pos")
                if isinstance(split_output_pos_qpoint, QPointF):
                    self.split_output_node.setPos(split_output_pos_qpoint)
        else: # Node is now unsplit
            node_pos_qpoint = config.get("pos")
            if isinstance(node_pos_qpoint, QPointF):
                self.setPos(node_pos_qpoint)

        # Apply fold states
        if self.is_split_origin: # Node is split, apply to parts
            if self.split_input_node:
                # Default to current part's state if key missing (current state might be from inheritance in _split_node)
                loaded_input_folded = config.get(ConfigManager.INPUT_PART_FOLDED_KEY, self.split_input_node.input_part_folded)
                if self.split_input_node.input_part_folded != loaded_input_folded:
                    self.split_input_node.input_part_folded = loaded_input_folded
                    self.split_input_node.layout_ports()
            if self.split_output_node:
                loaded_output_folded = config.get(ConfigManager.OUTPUT_PART_FOLDED_KEY, self.split_output_node.output_part_folded)
                if self.split_output_node.output_part_folded != loaded_output_folded:
                    self.split_output_node.output_part_folded = loaded_output_folded
                    self.split_output_node.layout_ports()
        else: # Node is unsplit, apply to main node
            if not self.is_split_part: # Ensure this is not a part itself (should be covered by is_split_origin check)
                # If IS_FOLDED_KEY is present in config, use its value.
                # self.is_folded would have been set to False by _unsplit_node if it just ran.
                if ConfigManager.IS_FOLDED_KEY in config:
                    is_folded_from_config = config.get(ConfigManager.IS_FOLDED_KEY)
                    if self.is_folded != is_folded_from_config:
                        self.is_folded = is_folded_from_config
                        self.layout_ports()
                # If key not in config, self.is_folded (e.g. False from _unsplit_node) is kept.
        
        self._fold_state_initialized_from_config = True # Mark that config has been applied once
        
        # Final layout update for the main node might be needed if its direct state changed
        # or if it was just unsplit.
        if not self.is_split_origin:
             self.layout_ports()
        self.update()


    def itemChange(self, change, value):
        # Ensure scene and config_manager exist before proceeding
        # self.config_manager should be set by the time itemChange is called after node creation.
        if not self.scene() or not hasattr(self, 'config_manager') or not self.config_manager:
            return super().itemChange(change, value)

        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # value is True if selected, False if deselected
            if value: # Item selected
                if self.scene():
                    current_max_z = 0
                    for item in self.scene().items():
                        # Ensure we are comparing with other NodeItem instances and not self
                        if item != self and isinstance(item, NodeItem):
                            current_max_z = max(current_max_z, item.zValue())
                    self.setZValue(current_max_z + 1)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # This 'value' is the new position QPointF
            # print(f"Node '{self.client_name}' ItemPositionHasChanged to {value}")

            # Note: z-value handling for movement is primarily done in mousePressEvent
            # or ItemSelectedHasChanged. If an item is moved programmatically without
            # selection change or mouse press, z-value might need explicit handling here.

            if self.is_split_part:
                if self.split_origin_node and self.split_origin_node.scene() and \
                   not self.split_origin_node._internal_state_change_in_progress:
                    # The origin node's client_name is the key for the config.
                    # save_node_states for the origin will pick up this part's new pos
                    # because it accesses self.split_origin_node.split_input_node.scenePos() etc.
                    nodes_to_save = {self.split_origin_node.client_name: self.split_origin_node}
                    self.config_manager.save_node_states(nodes_to_save)
                    # print(f"Saved due to split part '{self.client_name}' move. Origin: '{self.split_origin_node.client_name}' (state change in progress: {self.split_origin_node._internal_state_change_in_progress})")
            elif not self.is_split_origin and not self.is_split_part: # It's an original, non-split, visible node
                  # In this case, self.client_name is the correct key for the config.
                  if not self._internal_state_change_in_progress:
                    nodes_to_save = {self.client_name: self}
                    self.config_manager.save_node_states(nodes_to_save)
                    # print(f"Saved due to original node '{self.client_name}' move. (state change in progress: {self._internal_state_change_in_progress})")
            # If it's a split_origin (hidden title bar), its move doesn't save its own 'pos' directly.
            # Its parts' moves save their positions under the origin's config entry.
 
        return super().itemChange(change, value)

    def _toggle_fold_state(self):
        """Toggles the folded state of the node."""
        if self.is_split_origin or self.is_split_part: # Cannot fold/unfold split nodes directly
            return

        self.is_folded = not self.is_folded
        self.layout_ports() # This will hide/show ports and adjust size, and update connections if folding
        self.update()       # Repaint
        
        # Explicitly update all connections for this node after fold/unfold.
        # This is especially important for UNFOLDING to ensure wires snap back to ports.
        # For FOLDING, layout_ports already calls update_path on connections.
        # This loop ensures it for both cases for robustness.
        if not self.is_folded: # If just unfolded, ensure connections update
            for port_list in [self.input_ports, self.output_ports]:
                for port_item in port_list.values():
                    for conn in port_item.connections:
                        conn.update_path()
        
        # Save the new fold state to config
        if self.scene() and hasattr(self.scene(), 'request_specific_node_save'):
            self.scene().request_specific_node_save(self)
            # print(f"Saved fold state for node '{self.client_name}' due to toggle.")

    def _split_node(self, save_state: bool = True):
        """Visually splits the node into two parts: one for inputs, one for outputs.
        Sets default positions for split parts; apply_configuration may override these.
        Args:
            save_state (bool): If True, saves the node states after splitting.
        """
        # print(f"Visually splitting node: {self.client_name}") # Silenced
        self._internal_state_change_in_progress = True
        scene = self.scene()
        # NodeItem has its own self.jack_handler instance (GraphJackHandler)
        # It should use that directly.
        if not scene:
            print("Error: NodeItem cannot access scene for splitting.")
            return
        
        # Use the NodeItem's own jack_handler (which is GraphJackHandler)
        # and check its underlying jack.Client's existence.
        # Actual operational status will be determined by JACK calls within this method,
        # which are expected to handle JackError if the client is unresponsive.
        if not self.jack_handler or not self.jack_handler.jack_client:
            print(f"Error: JACK handler or its client object not available for splitting node {self.client_name}.")
            return

        handler = self.jack_handler # This is the GraphJackHandler instance

        if self.is_split_origin or self.is_split_part:
            print("Node is already split or is a split part.")
            return

        original_pos = self.scenePos()
        original_client_name = self.client_name # Actual JACK client name

        # 1. Get original port data (name -> jack.Port object)
        input_ports_data = {}
        output_ports_data = {}
        all_original_port_items = list(self.input_ports.values()) + list(self.output_ports.values())
        for port_item in all_original_port_items:
            port_name = port_item.port_name
            port_obj = handler.get_port_by_name(port_name) # Fetch fresh object
            if port_obj:
                if port_obj.is_input:
                    input_ports_data[port_name] = port_obj
                else:
                    output_ports_data[port_name] = port_obj
            else:
                print(f"Warning: Could not get port object for {port_name} during split.")

        if not input_ports_data or not output_ports_data:
            print("Node cannot be split: requires both input and output ports.")
            return # Cannot split if no inputs or no outputs

        # 2. Create new NodeItems for visual parts
        input_node_display_name = f"{original_client_name}{constants.SPLIT_INPUT_SUFFIX}"
        output_node_display_name = f"{original_client_name}{constants.SPLIT_OUTPUT_SUFFIX}"

        # Pass self.config_manager to the constructor for split parts
        if not self.config_manager:
            print("Error: NodeItem._split_node - self.config_manager is None. Cannot create split parts.")
            # Potentially raise an error or handle gracefully
            return

        input_node = NodeItem(input_node_display_name, handler, self.config_manager, ports_to_add=input_ports_data)
        output_node = NodeItem(output_node_display_name, handler, self.config_manager, ports_to_add=output_ports_data)

        input_node.is_split_part = True
        output_node.is_split_part = True
        input_node.original_client_name = original_client_name
        output_node.original_client_name = original_client_name
        input_node.split_origin_node = self
        output_node.split_origin_node = self

        scene.addItem(input_node)
        scene.addItem(output_node)

        # 4. Set DEFAULT positions for new nodes.
        # apply_configuration will override these if specific positions are in config.
        input_node.layout_ports() # Ensure size is calculated first
        output_node.layout_ports()

        # Default position for input part (e.g., below original or at original_pos)
        input_node.setPos(original_pos + QPointF(0, self.boundingRect().height() + constants.NODE_VMARGIN * 2)) # Default offset
        # print(f"  Set default position for input part: {input_node.scenePos()}") # Silenced

        # Default position for output part (e.g., to the right of input part)
        output_node.setPos(input_node.scenePos() + QPointF(input_node.boundingRect().width() + constants.NODE_HSPACING, 0)) # Default offset
        # print(f"  Set default position for output part: {output_node.scenePos()}") # Silenced
        
        # 5. Mark original node as split, store references, and HIDE it
        self.is_split_origin = True
        self.split_input_node = input_node
        self.split_output_node = output_node

        # If the original node was folded, the new parts should inherit this folded state
        if self.is_folded:
            input_node.input_part_folded = True
            output_node.output_part_folded = True
            # The main node is now a split origin, its own 'is_folded' should be False
            # as its appearance is just a header, and parts control their folding.
            self.is_folded = False
        
        input_node.layout_ports() # Update layout for potential fold
        output_node.layout_ports() # Update layout for potential fold

        self.hide() # Hide the original node completely

        # 6. Transfer visual connections (No need to hide original ports explicitly now)
        # print("Transferring visual connections...") # Silenced
        unique_connections_to_transfer = set()
        # Collect unique connections from original ports
        for port_item in all_original_port_items:
            for conn in port_item.connections:
                unique_connections_to_transfer.add(conn)

        # print(f"Found {len(unique_connections_to_transfer)} unique connections to transfer.") # Silenced

        # Import ConnectionItem here to avoid circular dependency at the top
        from .connection_item import ConnectionItem

        for conn_item in unique_connections_to_transfer:
            # Ensure the connection still exists and has valid ports before processing
            if not conn_item.source_port or not conn_item.dest_port:
                print(f"Skipping already destroyed or invalid connection: {conn_item}")
                continue

            old_source_port_name = conn_item.source_port.port_name
            old_dest_port_name = conn_item.dest_port.port_name
            conn_key = (old_source_port_name, old_dest_port_name)

            new_source_item = None
            new_dest_item = None

            # Find the new source port item
            if conn_item.source_port.parent_node == self: # Source is on the node being split
                new_source_item = output_node.output_ports.get(old_source_port_name)
            else: # Source is external
                new_source_item = conn_item.source_port # Keep original external port

            # Find the new destination port item
            if conn_item.dest_port.parent_node == self: # Destination is on the node being split
                new_dest_item = input_node.input_ports.get(old_dest_port_name)
            else: # Destination is external
                new_dest_item = conn_item.dest_port # Keep original external port

            # Remove old connection from scene dict FIRST
            scene.connections.pop(conn_key, None)
            # Now destroy the visual item (which also removes from port lists)
            conn_item.destroy()

            # Create new visual connection if both ends found
            if new_source_item and new_dest_item:
                try:
                    new_conn = ConnectionItem(new_source_item, new_dest_item)
                    scene.addItem(new_conn)
                    scene.connections[conn_key] = new_conn # Add to scene dict with original key
                except Exception as e:
                    print(f"Error creating new ConnectionItem for {old_source_port_name} -> {old_dest_port_name}: {e}")
                    traceback.print_exc()
            else:
                print(f"Warning: Could not find port items to recreate connection: {old_source_port_name} -> {old_dest_port_name}")

        # 8. Update original node's appearance (layout/paint will handle this)
        self.layout_ports() # Recalculate original node size (likely just title bar)
        self.update() # Trigger repaint for original node

        # 9. Update the scene's config dictionary to reflect the new split state
        # This ensures that if _split_node is called directly (e.g., context menu),
        # the config is updated. apply_configuration also does this.
        if scene and hasattr(scene, 'node_configs'):
            if original_client_name not in scene.node_configs:
                scene.node_configs[original_client_name] = {}
            scene.node_configs[original_client_name]['is_split'] = True
            # Positions of split parts will be saved by JackGraphScene._update_config_for_moved_node
            # when they are moved, or by apply_configuration if loaded.
            # print(f"Updated scene config for '{original_client_name}': is_split = True (from _split_node)") # Silenced

        # Ensure layout and repaint before saving
        self.layout_ports() # Original node is now just a header
        self.update()
        if self.split_input_node: self.split_input_node.layout_ports(); self.split_input_node.update()
        if self.split_output_node: self.split_output_node.layout_ports(); self.split_output_node.update()

        self._internal_state_change_in_progress = False # Reset flag before final save
        # Save the new split state to config if requested
        if save_state and self.scene() and hasattr(self.scene(), 'request_specific_node_save'):
            self.scene().request_specific_node_save(self) # 'self' is the original node
            # print(f"Saved split state for node '{original_client_name}' due to _split_node.")

        # print(f"Node {original_client_name} visually split complete.") # Silenced


    def _unsplit_node(self, save_state: bool = True):
        """Reverses the visual split, restoring the original node appearance.
        The original node's position should be set by apply_configuration after this call.
        Args:
            save_state (bool): If True, saves the node states after unsplitting.
        """
        # print(f"Unsplitting node: {self.client_name}") # Silenced
        self._internal_state_change_in_progress = True
        scene = self.scene()
        if not scene:
            print("Error: Cannot access scene for unsplitting.")
            return
        if not self.is_split_origin or not self.split_input_node or not self.split_output_node:
            print("Error: Node is not in a valid split state to unsplit.")
            return

        input_part = self.split_input_node
        output_part = self.split_output_node

        # Determine the fold state of the unsplit node
        # Rule: unsplit node is_folded=False if EITHER part was folded.
        # This implies if one was folded and other not, result is unfolded.
        # If both were unfolded, result is unfolded.
        # The prompt seems to imply: result is_folded = False (unfolded) if any part was folded.
        # "Only if *both* self.input_part_folded and self.output_part_folded were False ... should the resulting self.is_folded also be False."
        # This is a bit confusing. Let's re-read:
        # "The resulting unsplit node's self.is_folded must be set to False (i.e., the node becomes unfolded)
        #  if *either* self.input_part_folded was True OR self.output_part_folded was True."
        # "Only if *both* self.input_part_folded and self.output_part_folded were False ... should the resulting self.is_folded also be False."
        # New logic: The unsplit node is folded if and only if BOTH parts were folded.
        if input_part and output_part:
            self.is_folded = input_part.input_part_folded and output_part.output_part_folded
        else:
            # Fallback if parts are somehow missing, default to unfolded
            self.is_folded = False

        # Reset part-specific fold states on the parts before they are destroyed (though they are not on self)
        # These attributes are on input_part and output_part, not self.
        # No need to reset them on self as they don't exist there.
        # The information is used above for self.is_folded.

        # 1. Transfer visual connections back to the original node
        # print("Transferring connections back to original node...")
        unique_connections_to_transfer = set() # Use a set
        # Collect unique connections from split parts' ports
        for port_item in list(input_part.input_ports.values()):
            for conn in port_item.connections: # Iterate through connections on input ports
                 unique_connections_to_transfer.add(conn)
        for port_item in list(output_part.output_ports.values()):
             for conn in port_item.connections: # Iterate through connections on output ports
                 unique_connections_to_transfer.add(conn)

       # print(f"Found {len(unique_connections_to_transfer)} unique connections to transfer back.") # Silenced

        # Import ConnectionItem here to avoid circular dependency at the top
        from .connection_item import ConnectionItem

        for conn_item in unique_connections_to_transfer: # Iterate the set
            # Add check for already destroyed connection
            if not conn_item.source_port or not conn_item.dest_port:
                print(f"Skipping already destroyed or invalid connection during unsplit: {conn_item}")
                continue

            old_source_port_name = conn_item.source_port.port_name
            old_dest_port_name = conn_item.dest_port.port_name
            conn_key = (old_source_port_name, old_dest_port_name)

            new_source_item = None
            new_dest_item = None

            # Find the original source port item
            if conn_item.source_port.parent_node == output_part: # Source was on the output part
                new_source_item = self.output_ports.get(old_source_port_name)
            else: # Source is external
                new_source_item = conn_item.source_port # Keep original external port

            # Find the original destination port item
            if conn_item.dest_port.parent_node == input_part: # Destination was on the input part
                new_dest_item = self.input_ports.get(old_dest_port_name)
            else: # Destination is external
                new_dest_item = conn_item.dest_port # Keep original external port

            # Remove old connection from scene dict FIRST
            scene.connections.pop(conn_key, None)
            # Now destroy the visual item (which also removes from port lists)
            conn_item.destroy()

            # Create new visual connection on original node if both ends found
            if new_source_item and new_dest_item:
                try:
                    new_conn = ConnectionItem(new_source_item, new_dest_item)
                    scene.addItem(new_conn)
                    scene.connections[conn_key] = new_conn # Add to scene dict
                except Exception as e:
                    print(f"Error creating new ConnectionItem for {old_source_port_name} -> {old_dest_port_name}: {e}")
                    traceback.print_exc()
            else:
                print(f"Warning: Could not find original port items to recreate connection: {old_source_port_name} -> {old_dest_port_name}")

        # 2. Remove visual split parts from the scene
        scene.removeItem(input_part)
        scene.removeItem(output_part)

        # 3. Reset original node state
        self.is_split_origin = False
        self.split_input_node = None
        self.split_output_node = None

        # 4. Make original ports/areas visible again
        for port_item in self.input_ports.values():
            port_item.show()
        for port_item in self.output_ports.values():
            port_item.show()
        if self.input_area_item: self.input_area_item.show()
        if self.output_area_item: self.output_area_item.show()

        # 5. Update layout and appearance and make original node visible
        self.show() # Make the original node visible again
        self.layout_ports() # Recalculate full layout
        self.update()

        # 6. Update the scene's config dictionary to reflect the new split state.
        # apply_configuration will handle setting the 'pos' for the unsplit node.
        if scene and hasattr(scene, 'node_configs'):
            # Ensure the config for the original client name is updated.
            # self.client_name is the original client name for the node calling _unsplit_node.
            if self.client_name not in scene.node_configs:
                scene.node_configs[self.client_name] = {}
            scene.node_configs[self.client_name]['is_split'] = False
            # The 'pos' of the unsplit node will be applied by apply_configuration
            # using config.get('pos') if available.
            # print(f"Updated scene config for '{self.client_name}': is_split = False (from _unsplit_node)") # Silenced

        # Ensure layout and repaint before saving
        self.layout_ports() # Original node is now full again
        self.update()

        self._internal_state_change_in_progress = False # Reset flag before final save
        # Save the new unsplit state to config if requested
        if save_state and self.scene() and hasattr(self.scene(), 'request_specific_node_save'):
            self.scene().request_specific_node_save(self) # 'self' is the original node
            # print(f"Saved unsplit state for node '{self.client_name}' due to _unsplit_node.")

        # print(f"Node {self.client_name} unsplit complete.") # Silenced


    def update_ports(self):
        """Fetch current ports for this client from JACK and update visuals."""
        # Check if the handler exists and has a valid jack_client
        if not self.jack_handler or not self.jack_handler.jack_client:
            # print(f"NodeItem {self.client_name}: update_ports skipped, no valid jack_handler.jack_client.") # Optional debug
            return

        all_ports_in_jack = self.jack_handler.get_ports() # Get all ports
        # Filter ports belonging to this client
        current_ports_in_jack = [p for p in all_ports_in_jack if p.name.startswith(self.client_name + ':')]
        current_port_names = {p.name for p in current_ports_in_jack}
        existing_port_names = set(self.input_ports.keys()) | set(self.output_ports.keys())

        # Remove ports that no longer exist
        ports_to_remove = existing_port_names - current_port_names
        for port_name in ports_to_remove:
            self.remove_port(port_name)

        # Add new ports
        ports_to_add = current_port_names - existing_port_names
        port_objects = {p.name: p for p in current_ports_in_jack} # Map for quick lookup
        for port_name in ports_to_add:
            port_obj = port_objects.get(port_name)
            if port_obj:
                self.add_port(port_name, port_obj)
            else:
                print(f"Warning: Could not find port object for {port_name} during update.")

        # No need to call layout_ports here, add/remove_port does it

    def toggle_input_fold(self, fold_state=None):
        """Toggles or sets the folded state of the input part of a split node."""
        if not self.is_split_part or not (self.input_ports and not self.output_ports):
            # This method is intended for nodes that are specifically input parts
            # print(f"Node {self.client_name} is not an input part, cannot toggle input fold.")
            return

        if fold_state is None:
            self.input_part_folded = not self.input_part_folded
        else:
            self.input_part_folded = bool(fold_state)
        
        self.layout_ports() # Will hide/show ports and adjust size
        self.update()       # Repaint

        # Explicitly update connections if the part was just unfolded
        if not self.input_part_folded:
            for port_item in self.input_ports.values():
                for conn in port_item.connections:
                    conn.update_path()
        
        # Save state - trigger save for the original node
        if self.scene() and hasattr(self.scene(), 'request_specific_node_save') and self.split_origin_node:
            self.scene().request_specific_node_save(self.split_origin_node)
            # print(f"Saved input_part_folded for {self.client_name} (origin: {self.split_origin_node.client_name if self.split_origin_node else 'N/A'})")

    def toggle_output_fold(self, fold_state=None):
        """Toggles or sets the folded state of the output part of a split node."""
        if not self.is_split_part or not (self.output_ports and not self.input_ports):
            # This method is intended for nodes that are specifically output parts
            # print(f"Node {self.client_name} is not an output part, cannot toggle output fold.")
            return

        if fold_state is None:
            self.output_part_folded = not self.output_part_folded
        else:
            self.output_part_folded = bool(fold_state)

        self.layout_ports() # Will hide/show ports and adjust size
        self.update()       # Repaint

        # Explicitly update connections if the part was just unfolded
        if not self.output_part_folded:
            for port_item in self.output_ports.values():
                for conn in port_item.connections:
                    conn.update_path()

        # Save state - trigger save for the original node
        if self.scene() and hasattr(self.scene(), 'request_specific_node_save') and self.split_origin_node:
            self.scene().request_specific_node_save(self.split_origin_node)
            # print(f"Saved output_part_folded for {self.client_name} (origin: {self.split_origin_node.client_name if self.split_origin_node else 'N/A'})")
 
    def set_bulk_drag_highlight(self, highlight_input: bool, highlight_output: bool):
        """Externally set the highlight state for BulkAreaItems during drag."""
        if self.input_area_item:
            self.input_area_item.set_drag_highlight(highlight_input)
        if self.output_area_item:
            self.output_area_item.set_drag_highlight(highlight_output)

    def _disconnect_this_part_input_ports(self):
        """Disconnect all input ports of this specific node item (assumed to be an input split part)."""
        # print(f"NodeItem: Requesting disconnection of input ports for part {self.client_name}")
        current_scene = self.scene()
        if not current_scene or not hasattr(current_scene, 'jack_connection_handler'):
            print(f"Error: Scene or JackConnectionHandler not available for disconnecting inputs of {self.client_name}")
            return

        jack_handler = current_scene.jack_connection_handler
        ports_to_disconnect = list(self.input_ports.values()) # Operate on a copy

        for port_item in ports_to_disconnect:
            if not port_item: continue
            # Disconnect all connections this port is involved in
            for conn_item in list(port_item.connections): # Iterate over a copy
                if conn_item and conn_item.source_port and conn_item.dest_port:
                    try:
                        # print(f"  Breaking connection: {conn_item.source_port.port_name} -> {conn_item.dest_port.port_name}")
                        jack_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                    except Exception as e:
                        print(f"Error breaking connection for port {port_item.port_name} of {self.client_name}: {e}")
        # print(f"Finished request to disconnect input ports for part {self.client_name}")
        # UI update should be triggered by jack_handler signals

    def _disconnect_this_part_output_ports(self):
        """Disconnect all output ports of this specific node item (assumed to be an output split part)."""
        # print(f"NodeItem: Requesting disconnection of output ports for part {self.client_name}")
        current_scene = self.scene()
        if not current_scene or not hasattr(current_scene, 'jack_connection_handler'):
            print(f"Error: Scene or JackConnectionHandler not available for disconnecting outputs of {self.client_name}")
            return

        jack_handler = current_scene.jack_connection_handler
        ports_to_disconnect = list(self.output_ports.values()) # Operate on a copy

        for port_item in ports_to_disconnect:
            if not port_item: continue
            # Disconnect all connections this port is involved in
            for conn_item in list(port_item.connections): # Iterate over a copy
                if conn_item and conn_item.source_port and conn_item.dest_port:
                    try:
                        # print(f"  Breaking connection: {conn_item.source_port.port_name} -> {conn_item.dest_port.port_name}")
                        jack_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                    except Exception as e:
                        print(f"Error breaking connection for port {port_item.port_name} of {self.client_name}: {e}")
        # print(f"Finished request to disconnect output ports for part {self.client_name}")
        # UI update should be triggered by jack_handler signals