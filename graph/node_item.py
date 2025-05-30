# --- PyQt Graphical Items - NodeItem ---
import re # Import regex for natural sorting
import traceback # For error reporting in _split_node

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QGraphicsPathItem, QMenu,
    QStyleOptionGraphicsItem, QWidget, QStyle, QGraphicsSceneHoverEvent,
    QMessageBox, QCheckBox, QVBoxLayout, QDialog, QDialogButtonBox, QLabel
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

from .node_fold_handler import NodeFoldHandler
from .node_split_handler import NodeSplitHandler
# --- Natural Sort Helper (Moved from gui_items.py) ---

def natural_sort_key(port_item: PortItem):
    """
    Creates a natural sort key that properly handles numeric values in port names.
    Uses the same sorting logic as cables/port_manager.py.
    """
    text = port_item.short_name.lower()
    
    def tryint(text):
        try:
            return int(text)
        except ValueError:
            return text.lower()

    return [tryint(part) for part in re.split(r'(\d+)', text)]


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

        # Instantiate handlers
        self.fold_handler = NodeFoldHandler(self)
        self.split_handler = NodeSplitHandler(self)

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
 
            # Ensure layout is calculated at least once if ports are added manually
            ports_added = False
            for port_name, port_obj in ports_to_add.items():
                if self.add_port(port_name, port_obj):
                    ports_added = True
            # add_port calls layout_ports.
            # Ensure layout runs if no ports were provided (e.g., empty input/output node after init)
            if not ports_added:
                 self.layout_ports() # Calculate initial size

        # Store the configuration object
        self.config = {}

    # --- Helper Methods ---
    def _is_effectively_folded(self) -> bool:
        """Determines if the node should be treated as folded, considering its split state."""
        if self.is_split_part:
            if self.input_ports and not self.output_ports:  # This is an input part
                return self.input_part_folded
            elif self.output_ports and not self.input_ports:  # This is an output part
                return self.output_part_folded
            # Fallback for unexpected split part with both input/output, or neither.
        return self.is_folded
 
    def _get_paint_colors(self, option: QStyleOptionGraphicsItem, is_selected: bool) -> tuple[QColor, QColor, QColor, QColor]:
        """Determines the colors for painting the node based on theme and selection."""
        border_color = constants.SELECTION_BORDER_COLOR if is_selected else option.palette.color(QPalette.ColorRole.WindowText)
 
        original_node_body_bg = option.palette.color(QPalette.ColorRole.Base)
        is_light_mode = original_node_body_bg.lightnessF() > 0.7
 
        if is_light_mode:
            node_body_bg_color = QColor(240, 240, 240)
            title_bg_color = QColor(220, 220, 220)
            final_separator_color = QColor(192, 192, 192)
        else:
            node_body_bg_color = original_node_body_bg
            title_bg_color = option.palette.color(QPalette.ColorRole.Button)
            final_separator_color = option.palette.color(QPalette.ColorRole.Mid)
        
        return node_body_bg_color, title_bg_color, final_separator_color, border_color
 
    def _bring_to_front(self):
        """Brings the node item to the front of other NodeItems in the scene."""
        if self.scene():
            current_max_z = 0
            for item in self.scene().items():
                if item != self and isinstance(item, NodeItem):
                    current_max_z = max(current_max_z, item.zValue())
            self.setZValue(current_max_z + 1)
 
    # --- QGraphicsItem Overrides ---
    def boundingRect(self):
        return self._bounding_rect

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        node_body_bg_color, title_bg_color, final_separator_color, border_color = self._get_paint_colors(option, is_selected)
        border_width = 1.5 if is_selected else 1

        # --- Draw Base Rounded Rectangle (Border) ---
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border_color, border_width))
        painter.drawRoundedRect(self.boundingRect(), 5, 5)

        # --- Draw Title Background ---
        painter.setBrush(title_bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        title_rect = QRectF(0, 0, self.boundingRect().width(), self._calculated_title_height)
        
        # Create a path for the rounded rectangle of the entire node to use for clipping
        clip_path = QPainterPath()
        # Adjust clip_rect slightly to avoid painting over the border itself when filling
        clip_rect_for_fill = self.boundingRect().adjusted(border_width / 2, border_width / 2, -border_width / 2, -border_width / 2)
        clip_path.addRoundedRect(clip_rect_for_fill, 5, 5) # Use same rounding as border
        
        # Create a path for the title area and intersect it with the rounded node shape
        title_fill_candidate_path = QPainterPath()
        title_fill_candidate_path.addRect(title_rect)
        actual_title_fill_path = clip_path.intersected(title_fill_candidate_path)
        painter.drawPath(actual_title_fill_path)

        # --- Draw Node Body and Separator (Only if NOT a split origin AND NOT effectively folded) ---
        if not self.is_split_origin and not self._is_effectively_folded():
            # Fill the body area below the title
            painter.setBrush(node_body_bg_color)
            painter.setPen(Qt.PenStyle.NoPen) # No border for this fill
            body_rect = QRectF(0, self._calculated_title_height, self.boundingRect().width(), self.boundingRect().height() - self._calculated_title_height)
            
            body_fill_candidate_path = QPainterPath()
            body_fill_candidate_path.addRect(body_rect)
            actual_body_fill_path = clip_path.intersected(body_fill_candidate_path) # Intersect with the rounded shape
            painter.drawPath(actual_body_fill_path)

            # Draw Title Separator Line
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
                return target_node_part.add_port(port_name, port_obj)
            # If target_node_part is None (e.g., during complex setup/teardown), silently fail to add.
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
                removed_from_target = self.split_input_node.remove_port(port_name)
            elif self.split_output_node and port_name in self.split_output_node.output_ports:
                removed_from_target = self.split_output_node.remove_port(port_name)
            # If port not found on parts (e.g. already removed), removed_from_target remains False.
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

    # --- Layout Helper Methods ---
    def _calculate_and_set_title_geometry(self, node_width: float) -> float:
        """Calculates and sets the title item's geometry and returns the calculated title height."""
        title_width = node_width - 2 * constants.NODE_PADDING
        self.title_item.setTextWidth(title_width)
        self.title_item.setPos(constants.NODE_PADDING, constants.NODE_PADDING)
        doc_height = self.title_item.document().size().height()
        calculated_title_height = max(constants.NODE_TITLE_HEIGHT, doc_height + constants.NODE_PADDING * 2)
        self._calculated_title_height = calculated_title_height
        self._header_rect = QRectF(0, 0, self._bounding_rect.width(), calculated_title_height)
        return calculated_title_height

    def _hide_all_ports_and_bulk_areas(self):
        """Hides all port items and bulk area items."""
        for port in list(self.input_ports.values()) + list(self.output_ports.values()):
            if port.isVisible(): port.hide()
        if self.input_area_item and self.input_area_item.isVisible(): self.input_area_item.hide()
        if self.output_area_item and self.output_area_item.isVisible(): self.output_area_item.hide()

    def _show_all_ports_and_bulk_areas(self):
        """Shows all port items and bulk area items."""
        for port in list(self.input_ports.values()) + list(self.output_ports.values()):
            if not port.isVisible(): port.show()
        if self.input_area_item and not self.input_area_item.isVisible(): self.input_area_item.show()
        if self.output_area_item and not self.output_area_item.isVisible(): self.output_area_item.show()

    def _layout_bulk_areas(self, current_node_width: float, max_in_width: float, max_out_width: float, y_start_bulk: float):
        """Positions the bulk area items."""
        pad = constants.NODE_BULK_AREA_HPADDING
        if self.input_area_item:
            bulk_in_width = max_in_width - 2 * pad
            self.input_area_item._bounding_rect.setWidth(bulk_in_width)
            self.input_area_item.setPos(pad, y_start_bulk)
        
        if self.output_area_item:
            bulk_out_width = max_out_width - 2 * pad
            self.output_area_item._bounding_rect.setWidth(bulk_out_width)
            out_x = pad if (self.is_split_part and self.input_ports) else (current_node_width - max_out_width + pad)
            self.output_area_item.setPos(out_x, y_start_bulk)

    def _layout_individual_ports(self, current_node_width: float, y_start_ports: float) -> tuple[float, float]:
        """Positions individual port items and returns the final y-offsets for inputs and outputs."""
        # Separate and sort audio ports first, then MIDI ports
        input_audio_ports = [p for p in self.input_ports.values() if not p.port_obj.is_midi]
        input_midi_ports = [p for p in self.input_ports.values() if p.port_obj.is_midi]
        output_audio_ports = [p for p in self.output_ports.values() if not p.port_obj.is_midi]
        output_midi_ports = [p for p in self.output_ports.values() if p.port_obj.is_midi]

        y_in = y_start_ports
        # Layout audio input ports first
        for port_item in sorted(input_audio_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            port_item.setPos(0, y_in)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, constants.PORT_HEIGHT)
            y_in += constants.PORT_HEIGHT + constants.NODE_VMARGIN
        # Then MIDI input ports
        for port_item in sorted(input_midi_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            port_item.setPos(0, y_in)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, constants.PORT_HEIGHT)
            y_in += constants.PORT_HEIGHT + constants.NODE_VMARGIN

        y_out = y_start_ports
        # Layout audio output ports first
        for port_item in sorted(output_audio_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            x_pos = current_node_width - port_item.calculated_width
            port_item.setPos(x_pos, y_out)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, constants.PORT_HEIGHT)
            y_out += constants.PORT_HEIGHT + constants.NODE_VMARGIN
        # Then MIDI output ports
        for port_item in sorted(output_midi_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            x_pos = current_node_width - port_item.calculated_width
            port_item.setPos(x_pos, y_out)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, constants.PORT_HEIGHT)
            y_out += constants.PORT_HEIGHT + constants.NODE_VMARGIN
        return y_in, y_out

    def layout_ports(self):
        """Positions port items vertically and updates node height and width."""
        self.prepareGeometryChange()

        max_in_width = max((port.calculated_width for port in self.input_ports.values()), default=constants.PORT_WIDTH_MIN)
        max_out_width = max((port.calculated_width for port in self.output_ports.values()), default=constants.PORT_WIDTH_MIN)

        if self.is_split_origin:
            node_width = max(constants.NODE_WIDTH, max_in_width + max_out_width + 2 * constants.NODE_PADDING)
        elif self.is_split_part:
            if self.input_ports and not self.output_ports: # Input part
                node_width = max(constants.NODE_WIDTH, max_in_width + 2 * constants.NODE_PADDING)
            elif self.output_ports and not self.input_ports: # Output part
                node_width = max(constants.NODE_WIDTH, max_out_width + 2 * constants.NODE_PADDING)
            else: # Fallback for unexpected split part state
                node_width = max(constants.NODE_WIDTH, max_in_width + max_out_width + 2 * constants.NODE_PADDING)
        else: # Normal node
            node_width = max(constants.NODE_WIDTH, max_in_width + max_out_width + 2 * constants.NODE_PADDING)
        
        self._bounding_rect.setWidth(node_width)
        title_height = self._calculate_and_set_title_geometry(node_width) # self._calculated_title_height is updated here

        if self.is_split_origin:
            self._bounding_rect.setHeight(title_height)
            self._hide_all_ports_and_bulk_areas()
            self.update()
            return

        if self._is_effectively_folded():
            self._bounding_rect.setHeight(title_height)
            self._hide_all_ports_and_bulk_areas()
            for port_list in [self.input_ports, self.output_ports]:
                for port_item in port_list.values():
                    for conn in port_item.connections: conn.update_path()
            self.update()
            return

        self._show_all_ports_and_bulk_areas()

        y_current = title_height + constants.NODE_VMARGIN
        self._layout_bulk_areas(node_width, max_in_width, max_out_width, y_current)

        if self.input_area_item or self.output_area_item:
            y_current += constants.NODE_BULK_AREA_HEIGHT + constants.NODE_VMARGIN
        
        y_in_final, y_out_final = self._layout_individual_ports(node_width, y_current)

        # Calculate the height based on the maximum extent of ports or bulk areas
        max_y_ports = 0
        if self.input_ports or self.output_ports:
            max_y_ports = max(y_in_final, y_out_final) - constants.NODE_VMARGIN # Remove last margin
        else: # No ports, height is determined by bulk areas or just title
            max_y_ports = y_current # This is the y_start_offset for ports

        max_y_bulk = 0
        if self.input_area_item or self.output_area_item:
            max_y_bulk = title_height + constants.NODE_VMARGIN + constants.NODE_BULK_AREA_HEIGHT
        else: # No bulk areas
            max_y_bulk = title_height
            
        content_bottom_y = max(max_y_ports, max_y_bulk)
        
        # If there's no content below the title (e.g. only title, or title + empty bulk area space)
        # ensure a minimum content height for padding.
        # If content_bottom_y is just title_height, it means no ports and no bulk areas.
        # If content_bottom_y is title_height + NODE_VMARGIN + NODE_BULK_AREA_HEIGHT, but no ports,
        # then that's the content height.
        if not (self.input_ports or self.output_ports or self.input_area_item or self.output_area_item):
             # Only title is visible, or node is empty after title
             final_node_height = title_height + constants.NODE_PADDING # Minimal padding below title
        else:
             final_node_height = content_bottom_y + constants.NODE_PADDING

        self._bounding_rect.setHeight(final_node_height)
        self.update()

    def get_bulk_connection_point(self, is_input: bool):
        area_item = self.input_area_item if is_input else self.output_area_item
        if area_item:
            return area_item.get_connection_point()
        # Fallback if bulk area item does not exist
        return self.mapToScene(self.boundingRect().center())

    # hoverMoveEvent, hoverLeaveEvent, contextMenuEvent for bulk areas are handled by BulkAreaItem
    # mousePressEvent for bulk areas is handled by BulkAreaItem

    def _disconnect_all_connections(self):
        """Disconnects all ports of the client this NodeItem (or its origin) represents."""
        client_to_disconnect = self.original_client_name if self.is_split_part and self.original_client_name else self.client_name
        current_scene = self.scene()
        if current_scene and hasattr(current_scene, 'jack_connection_handler'):
            try:
                current_scene.jack_connection_handler.disconnect_all_ports_of_client(client_to_disconnect)
            except Exception as e:
                # Basic error logging, consider a more robust logging mechanism
                print(f"Error in NodeItem._disconnect_all_connections for {client_to_disconnect}: {e}")

    # _disconnect_all_inputs and _disconnect_all_outputs are no longer needed.

    # --- Context Menu Helper Methods ---
    def _hide_node(self):
        """Hides this node or part based on the NodeVisibilityManager settings."""
        current_scene = self.scene()
        if not current_scene or not hasattr(current_scene, 'node_visibility_manager') or not current_scene.node_visibility_manager:
            print("Cannot hide node: NodeVisibilityManager not available")
            return

        # Determine the client name to hide
        client_name = None
        
        # For split parts, use the original client name from origin node
        if self.is_split_part and self.split_origin_node:
            # Get the original name from the origin node
            client_name = self.split_origin_node.client_name
        # For split origin, use its own client name
        elif self.is_split_origin:
            client_name = self.client_name
        # For normal nodes, use the client name
        else:
            client_name = self.client_name
        
        # Use original_client_name if set (for any node type)
        if self.original_client_name:
            client_name = self.original_client_name
        
        # Determine if this is a MIDI node by checking any port
        is_midi = False
        
        # First check this node's ports
        for port_list in [self.input_ports, self.output_ports]:
            for port_item in port_list.values():
                if hasattr(port_item.port_obj, 'is_midi') and port_item.port_obj.is_midi:
                    is_midi = True
                    break
            if is_midi:
                break
        
        # For split parts/origin, check the related nodes as well
        if not is_midi:
            # If this is a split origin, check its parts
            if self.is_split_origin:
                # Check input part
                if self.split_input_node:
                    for port_item in self.split_input_node.input_ports.values():
                        if hasattr(port_item.port_obj, 'is_midi') and port_item.port_obj.is_midi:
                            is_midi = True
                            break
                # Check output part
                if not is_midi and self.split_output_node:
                    for port_item in self.split_output_node.output_ports.values():
                        if hasattr(port_item.port_obj, 'is_midi') and port_item.port_obj.is_midi:
                            is_midi = True
                            break
            # If this is a split part, check the origin node
            elif self.is_split_part and self.split_origin_node:
                # Check other part via origin
                other_part = None
                if bool(self.input_ports) and not bool(self.output_ports):  # This is input part
                    other_part = self.split_origin_node.split_output_node
                else:  # This is output part
                    other_part = self.split_origin_node.split_input_node
                
                if other_part:
                    for port_list in [other_part.input_ports, other_part.output_ports]:
                        for port_item in port_list.values():
                            if hasattr(port_item.port_obj, 'is_midi') and port_item.port_obj.is_midi:
                                is_midi = True
                                break
                        if is_midi:
                            break

        if not client_name:
            print(f"Cannot hide node: Unable to determine client name")
            return
        
        # Get a parent widget for the dialog (the view)
        parent_widget = None
        if current_scene.views():
            parent_widget = current_scene.views()[0]
        
        # Check if we should show the confirmation dialog
        show_dialog = True
        
        # Try to get the global config from the connection_manager
        if hasattr(current_scene, 'connection_manager') and current_scene.connection_manager:
            if hasattr(current_scene.connection_manager, 'config_manager') and current_scene.connection_manager.config_manager:
                # Use the application-level config_manager which has get_bool method
                app_config = current_scene.connection_manager.config_manager
                show_dialog = app_config.get_bool('show_hide_node_confirmation', default=True)
        
        # Determine what to hide based on node type
        hide_inputs = False
        hide_outputs = False
        
        if self.is_split_part:
            # For split parts, only hide the specific part (input or output)
            if bool(self.input_ports) and not bool(self.output_ports):
                # This is the input part
                hide_inputs = True
                message_type = "input" + (" MIDI" if is_midi else " audio")
            elif bool(self.output_ports) and not bool(self.input_ports):
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
            # Create a custom dialog with checkbox
            if hide_inputs and hide_outputs:
                message = f"Hide {client_name} {message_type} node?"
            elif hide_inputs:
                message = f"Hide {client_name} input ports?"
            elif hide_outputs:
                message = f"Hide {client_name} output ports?"
            else:
                message = f"Hide {client_name}?"  # Fallback
                
            result = self._show_hide_confirmation_dialog(parent_widget, client_name, message_type, message)
            if not result:
                return
        
        # Update visibility setting and apply
        if is_midi:
            if hide_inputs:
                current_scene.node_visibility_manager.midi_input_visibility[client_name] = False
            if hide_outputs:
                current_scene.node_visibility_manager.midi_output_visibility[client_name] = False
        else:
            if hide_inputs:
                current_scene.node_visibility_manager.audio_input_visibility[client_name] = False
            if hide_outputs:
                current_scene.node_visibility_manager.audio_output_visibility[client_name] = False
                
        # Save and apply the updated settings
        current_scene.node_visibility_manager.save_visibility_settings()
        
        # When hiding a node part, also hide its connections if this is a split part
        if self.is_split_part:
            # For split parts, hide connections before applying visibility settings
            # which will eventually hide the node
            if hasattr(current_scene, '_update_node_connections_visibility'):
                current_scene._update_node_connections_visibility(self, False)
                
        # Apply the changes which will hide the node(s)
        current_scene.node_visibility_manager.apply_visibility_settings()
        
        # Do a full refresh of all connection visibility to ensure consistency
        if hasattr(current_scene, '_refresh_all_connection_visibility'):
            current_scene._refresh_all_connection_visibility()
    
    def _show_hide_confirmation_dialog(self, parent, client_name, message_type, custom_message=None):
        """
        Show a confirmation dialog with 'don't show again' checkbox.
        
        Args:
            parent: Parent widget for the dialog
            client_name: Name of the client to hide
            message_type: Type of the node (audio/MIDI)
            custom_message: Optional custom message to show
            
        Returns:
            bool: True if user confirmed, False otherwise
        """
        # Create a custom dialog
        dialog = QDialog(parent)
        dialog.setWindowTitle("Hide Node")
        dialog.setModal(True)
        
        # Create layout
        layout = QVBoxLayout(dialog)
        
        # Add message
        if custom_message:
            message = f"{custom_message}\n\nYou can restore it later from the Node Visibility dialog."
        else:
            message = f"Hide {client_name} {message_type} node?\n\nYou can restore it later from the Node Visibility dialog."
        
        label = QLabel(message)
        layout.addWidget(label)
        
        # Add checkbox
        checkbox = QCheckBox("Don't show this message again")
        layout.addWidget(checkbox)
        
        # Add buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        # Execute dialog
        result = dialog.exec() == QDialog.DialogCode.Accepted
        
        # Save checkbox state if accepted
        if result and checkbox.isChecked():
            # Try to get the global config from the scene's connection_manager
            current_scene = self.scene()
            if current_scene and hasattr(current_scene, 'connection_manager') and current_scene.connection_manager:
                if hasattr(current_scene.connection_manager, 'config_manager') and current_scene.connection_manager.config_manager:
                    app_config = current_scene.connection_manager.config_manager
                    if hasattr(app_config, 'set_bool'):
                        app_config.set_bool('show_hide_node_confirmation', False)
                    else:
                        print("Warning: config_manager doesn't have set_bool method")
        
        return result

    def _build_context_menu_for_split_part(self, menu: QMenu, disconnect_is_enabled: bool):
        is_input_part = bool(self.input_ports and not self.output_ports)
        is_output_part = bool(self.output_ports and not self.input_ports)

        disconnect_text = "Disconnect all INs" if is_input_part else ("Disconnect all OUTs" if is_output_part else "Disconnect all")
        action = menu.addAction(disconnect_text)
        action.setEnabled(disconnect_is_enabled)
        if is_input_part: action.triggered.connect(self._disconnect_this_part_input_ports)
        elif is_output_part: action.triggered.connect(self._disconnect_this_part_output_ports)
        else: action.triggered.connect(self._disconnect_all_connections)

        if self.split_origin_node:
            menu.addAction("Unsplit").triggered.connect(lambda: self.split_origin_node.split_handler.unsplit_node(save_state=True))
        else:
            menu.addAction("Unsplit (Error: No Origin)").setEnabled(False)

        if is_input_part:
            fold_text = "Unfold Input Part" if self.input_part_folded else "Fold Input Part"
            menu.addAction(fold_text).triggered.connect(lambda: self.fold_handler.toggle_input_part_fold())
        elif is_output_part:
            fold_text = "Unfold Output Part" if self.output_part_folded else "Fold Output Part"
            menu.addAction(fold_text).triggered.connect(lambda: self.fold_handler.toggle_output_part_fold())
            
        # Add the Hide option
        menu.addSeparator()
        menu.addAction("Hide").triggered.connect(self._hide_node)

    def _build_context_menu_for_split_origin(self, menu: QMenu, disconnect_is_enabled: bool):
        disconnect_action = menu.addAction("Disconnect all")
        disconnect_action.setEnabled(disconnect_is_enabled)
        disconnect_action.triggered.connect(self._disconnect_all_connections)
        menu.addAction("Unsplit Node").triggered.connect(lambda: self.split_handler.unsplit_node(save_state=True))
        
        # Add the Hide option
        menu.addSeparator()
        menu.addAction("Hide").triggered.connect(self._hide_node)

    def _build_context_menu_for_normal_node(self, menu: QMenu, disconnect_is_enabled: bool):
        disconnect_action = menu.addAction("Disconnect all")
        disconnect_action.setEnabled(disconnect_is_enabled)
        disconnect_action.triggered.connect(self._disconnect_all_connections)
        
        split_action = menu.addAction("Split")
        split_action.setEnabled(bool(self.input_ports) and bool(self.output_ports))
        split_action.triggered.connect(lambda: self.split_handler.split_node(save_state=True))
        
        fold_text = "Unfold" if self.is_folded else "Fold"
        menu.addAction(fold_text).triggered.connect(self.fold_handler.toggle_main_fold_state)
        
        # Add the Hide option
        menu.addSeparator()
        menu.addAction("Hide").triggered.connect(self._hide_node)

    def contextMenuEvent(self, event):
        if not (event.pos().y() <= self._calculated_title_height):
            super().contextMenuEvent(event)
            return

        menu = QMenu()
        # Check if any port has connections to enable "Disconnect" options
        has_input_connections = any(p.connections for p in self.input_ports.values())
        has_output_connections = any(p.connections for p in self.output_ports.values())
        
        # For split origin, check its parts' connections if it has no direct ports (which it shouldn't)
        disconnect_is_enabled = False
        if self.is_split_origin:
            input_part_connections = False
            output_part_connections = False
            if self.split_input_node:
                input_part_connections = any(p.connections for p in self.split_input_node.input_ports.values())
            if self.split_output_node:
                output_part_connections = any(p.connections for p in self.split_output_node.output_ports.values())
            disconnect_is_enabled = input_part_connections or output_part_connections
        else: # For normal nodes and split parts, check their own ports
            disconnect_is_enabled = has_input_connections or has_output_connections


        if self.is_split_part:
            self._build_context_menu_for_split_part(menu, disconnect_is_enabled)
        elif self.is_split_origin:
            self._build_context_menu_for_split_origin(menu, disconnect_is_enabled)
        else:
            self._build_context_menu_for_normal_node(menu, disconnect_is_enabled)

        menu.exec(event.screenPos())
        event.accept()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._bring_to_front()

    def mouseDoubleClickEvent(self, event: QGraphicsSceneHoverEvent): # Type hint is QGraphicsSceneMouseEvent
        if self._header_rect.contains(event.pos()):
            if self.is_split_part:
                is_input_part = bool(self.input_ports and not self.output_ports)
                is_output_part = bool(self.output_ports and not self.input_ports)
                if is_input_part:
                    self.fold_handler.toggle_input_part_fold()
                    event.accept()
                elif is_output_part:
                    self.fold_handler.toggle_output_part_fold()
                    event.accept()
                # If a split part has both or neither (should not happen), double click does nothing on header.
            elif not self.is_split_origin: # Normal, unsplit node
                self.fold_handler.toggle_main_fold_state()
                event.accept()
            # If it's a split origin, double click does nothing on header.
            if event.isAccepted():
                return
        super().mouseDoubleClickEvent(event)

    def apply_configuration(self, config: dict):
        """Applies visual state (split, position, fold states) from a configuration dictionary."""
        # Store the config on the node for reference
        self.config = config.copy()  # Make a copy to avoid reference issues
        
        self.split_handler.apply_split_config(config) # Establishes split state first

        # Apply positions based on the now-current split state
        if self.is_split_origin:
            if self.split_input_node and "split_input_pos" in config and isinstance(config["split_input_pos"], QPointF):
                self.split_input_node.setPos(config["split_input_pos"])
            if self.split_output_node and "split_output_pos" in config and isinstance(config["split_output_pos"], QPointF):
                self.split_output_node.setPos(config["split_output_pos"])
        elif "pos" in config and isinstance(config["pos"], QPointF): # Node is unsplit (or was never split)
            self.setPos(config["pos"])

        # Apply fold configuration using the fold handler, aware of current split state
        self.fold_handler.apply_fold_config(config, self.is_split_origin, self.is_split_part)
        self._fold_state_initialized_from_config = True
        
        # Final layout update for the main node or parts if their direct state changed
        if not self.is_split_origin: # If it's a normal node or a split part
             self.layout_ports() # Recalculate its own layout
        # If it IS a split origin, its layout is minimal (title bar only) and handled by split_handler.
        # Its parts (if they exist) will have their layout_ports called by their own apply_fold_config if needed.
        self.update() # Ensure repaint

    def itemChange(self, change, value):
        if not self.scene() or not hasattr(self, 'config_manager') or not self.config_manager:
            return super().itemChange(change, value)

        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if value: # Item selected
                self._bring_to_front()
  
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Avoid saving state during programmatic changes like split/unsplit operations
            if self._internal_state_change_in_progress:
                 return super().itemChange(change, value)

            node_to_save_config_for = None
            # If this is a split part, save under its origin's name
            if self.is_split_part and self.split_origin_node:
                node_to_save_config_for = self.split_origin_node
            # If this is an original, non-split, visible node
            elif not self.is_split_origin and not self.is_split_part:
                node_to_save_config_for = self
            
            if node_to_save_config_for:
                # The save_node_states method will correctly get positions of parts if node_to_save_config_for is an origin
                self.config_manager.save_node_states({node_to_save_config_for.client_name: node_to_save_config_for})
            # If it's a split_origin itself being moved (should not happen as it's hidden/static), no direct save.
  
        return super().itemChange(change, value)

    # Old methods _toggle_fold_state, _split_node, _unsplit_node are now in handlers.

    def update_ports(self):
        """Fetches current ports for this client from JACK and updates visuals."""
        if not self.jack_handler or not self.jack_handler.jack_client:
            return # Silently return if no valid jack_handler

        all_ports_in_jack = self.jack_handler.get_ports()
        # Determine the correct JACK client name to match against
        jack_client_name_to_match = self.original_client_name if self.is_split_part and self.original_client_name else self.client_name
        
        current_ports_in_jack = [p for p in all_ports_in_jack if p.name.startswith(jack_client_name_to_match + ':')]
        current_port_names_in_jack = {p.name for p in current_ports_in_jack}
        
        # Existing port names are based on the PortItems currently held by this NodeItem instance
        existing_port_item_names = set(self.input_ports.keys()) | set(self.output_ports.keys())

        # Remove ports that no longer exist in JACK
        ports_to_remove_from_ui = existing_port_item_names - current_port_names_in_jack
        for port_name in ports_to_remove_from_ui:
            self.remove_port(port_name) # remove_port handles delegation for split origins

        # Add new ports that exist in JACK but not in UI
        ports_to_add_to_ui = current_port_names_in_jack - existing_port_item_names
        port_objects_map = {p.name: p for p in current_ports_in_jack} # For quick lookup
        for port_name in ports_to_add_to_ui:
            port_obj = port_objects_map.get(port_name)
            if port_obj:
                self.add_port(port_name, port_obj) # add_port handles delegation for split origins
            # else: Consider logging if a port name is found but its object isn't (should not happen)

        # add_port/remove_port call layout_ports, so no explicit call here unless other metadata changed.

    # Old methods toggle_input_fold and toggle_output_fold are now in NodeFoldHandler.

    def set_bulk_drag_highlight(self, highlight_input: bool, highlight_output: bool):
        """Externally sets the highlight state for BulkAreaItems during drag operations."""
        if self.input_area_item:
            self.input_area_item.set_drag_highlight(highlight_input)
        if self.output_area_item:
            self.output_area_item.set_drag_highlight(highlight_output)

    def _disconnect_this_part_input_ports(self):
        """Disconnects all input ports of this specific node item (assumed to be an input split part)."""
        current_scene = self.scene()
        if not current_scene or not hasattr(current_scene, 'jack_connection_handler'):
            return
        jack_handler = current_scene.jack_connection_handler
        for port_item in list(self.input_ports.values()): # Iterate copy
            if not port_item: continue
            for conn_item in list(port_item.connections): # Iterate copy
                if conn_item and conn_item.source_port and conn_item.dest_port:
                    try:
                        jack_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                    except Exception as e:
                        print(f"Error breaking input connection for {port_item.port_name} of {self.client_name}: {e}")

    def _disconnect_this_part_output_ports(self):
        """Disconnects all output ports of this specific node item (assumed to be an output split part)."""
        current_scene = self.scene()
        if not current_scene or not hasattr(current_scene, 'jack_connection_handler'):
            return
        jack_handler = current_scene.jack_connection_handler
        for port_item in list(self.output_ports.values()): # Iterate copy
            if not port_item: continue
            for conn_item in list(port_item.connections): # Iterate copy
                if conn_item and conn_item.source_port and conn_item.dest_port:
                    try:
                        jack_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                    except Exception as e:
                        print(f"Error breaking output connection for {port_item.port_name} of {self.client_name}: {e}")