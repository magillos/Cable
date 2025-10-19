# --- PyQt Graphical Items - NodeItem ---
import re # Import regex for natural sorting
import traceback # For error reporting in _split_node

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QGraphicsPathItem, QMenu,
    QStyleOptionGraphicsItem, QWidget, QStyle, QGraphicsSceneHoverEvent,
    QMessageBox, QCheckBox, QVBoxLayout, QDialog, QDialogButtonBox, QLabel, QRadioButton
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QAction, QPolygonF,
    QFontMetrics, QPalette
)
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QLineF, QEvent, QSize, QTimer
)

from . import constants # Import the new constants module
from .port_item import PortItem # Import PortItem
from .bulk_area_item import BulkAreaItem # Import BulkAreaItem
from .config_utils import ConfigManager # Import ConfigManager
from typing import TYPE_CHECKING, Optional, Dict, List, Tuple, Any, Union, Callable

if TYPE_CHECKING:
    from .layout import GraphLayouter  # For type hints only
# Note: ConnectionItem is needed for creating new connections during split/unsplit
# from .connection_item import ConnectionItem # Avoid circular import here, use string literal

from .node_fold_handler import NodeFoldHandler
from .node_split_handler import NodeSplitHandler
# --- Natural Sort Helper (Moved from gui_items.py) ---

def natural_sort_key(port_item: PortItem):
    """
    Creates an enhanced sort key that groups ports by base name.
    Uses the same enhanced sorting logic as cables/port_manager.py.
    
    For example, ports like:
    - input_FL
    - input_FL-448
    - input_FL-458
    - input_FR
    - input_FR-449
    - input_FR-459
    
    Will be sorted as:
    - input_FL
    - input_FR
    - input_FL-448
    - input_FR-449
    - input_FL-458
    - input_FR-459
    """
    text = port_item.short_name.lower()
    
    def tryint(text):
        try:
            return int(text)
        except ValueError:
            return text.lower()

    # Extract base name and suffix from port name
    # Look for patterns like "input_FL-448" or "output_1-mono"
    base_name = text
    suffix = ''
    
    # Try to find a suffix pattern (dash followed by numbers/text)
    suffix_match = re.search(r'[-_](\d+.*?)$', text)
    if suffix_match:
        suffix = suffix_match.group(1)
        base_name = text[:suffix_match.start()]
    
    # Create sort key components
    base_name_key = [tryint(part) for part in re.split(r'(\d+)', base_name)]
    
    # For the desired sorting behavior:
    # 1. First show all base ports (no suffix) sorted by base name
    # 2. Then show suffixed ports, grouped by suffix value, with base names sorted within each suffix group
    if suffix:
        suffix_key = [tryint(part) for part in re.split(r'(\d+)', suffix)]
        # For suffixed ports: sort by (suffix, base_name)
        return ([1], suffix_key, base_name_key)  # [1] puts suffixed ports after base ports
    else:
        # For base ports: sort by (base_name)
        return ([0], base_name_key, [])  # [0] puts base ports first


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
        self.is_unified = False
        self.unified_virtual_sink_name = None
        self.unified_module_id = None
        self.unify_action = None
        self.wait_for_sink_timer = None
        self.wait_for_sink_retries = 0
        self.unified_ports_type = None  # 'input', 'output', or None

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
 
            # Ports will be added via add_port, which calls layout_ports if in a scene.
            # If no ports are added, layout will be handled by the scene after adding the node.
            for port_name, port_obj in ports_to_add.items():
                self.add_port(port_name, port_obj)

        # Store the configuration object
        self.config = {}

        # Initialize unified state from config manager if needed
        # This pre-sets is_unified before apply_configuration is called
        if config_manager and hasattr(config_manager, 'node_positions_file'):
            try:
                import json
                if config_manager.node_positions_file.exists():
                    with open(config_manager.node_positions_file, 'r') as f:
                        saved_data = json.load(f)
                    client_config = saved_data.get(client_name, {})
                    if client_config.get(config_manager.IS_UNIFIED_KEY, False):
                        self.is_unified = True
                        unified_sink_name = client_config.get(config_manager.UNIFIED_SINK_NAME_KEY)
                        if unified_sink_name:
                            self.unified_virtual_sink_name = unified_sink_name
                        unified_module_id = client_config.get(config_manager.UNIFIED_MODULE_ID_KEY)
                        if unified_module_id:
                            self.unified_module_id = unified_module_id
                        # Load the ports type (input/output) for unified nodes
                        unified_ports_type = client_config.get(config_manager.UNIFIED_PORTS_TYPE_KEY)
                        if unified_ports_type in ['input', 'output']:
                            self.unified_ports_type = unified_ports_type
            except Exception as e:
                # Silently fail, unified state will be set by apply_configuration later
                pass

        # Check if this is a virtual sink (do this after initialization)
        self._check_if_virtual_sink(client_name)
        print(f"DEBUG: Node {client_name} initialized - is_virtual_sink: {getattr(self, 'is_virtual_sink', False)}, is_unified_sink: {getattr(self, 'is_unified_sink', False)}")

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

        if getattr(self, 'is_unified_sink', False):
            # Virtual sinks created by Unify toggle - use darker blue
            if is_light_mode:
                title_bg_color = QColor(200, 220, 255) # A dark blue for unified sinks
            else:
                title_bg_color = QColor(50, 70, 100) # A darker blue for unified sinks
        elif self.is_unified:
            # Regular unified nodes - use dirty pink
            if is_light_mode:
                title_bg_color = QColor(240, 190, 210) # Dirty pink, not too bright
            else:
                title_bg_color = QColor(90, 50, 70) # Darker dirty pink for dark mode
        else:
            if is_light_mode:
                title_bg_color = QColor(220, 220, 220)
            else:
                title_bg_color = option.palette.color(QPalette.ColorRole.Button)

        if is_light_mode:
            node_body_bg_color = QColor(240, 240, 240)
            final_separator_color = QColor(192, 192, 192)
        else:
            node_body_bg_color = original_node_body_bg
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

            # Automatically connect new input/output ports to unified sink if node is unified
            if self.is_unified and self.unified_virtual_sink_name and self.scene() and hasattr(self.scene(), 'jack_connection_handler'):
                self._connect_new_port_to_unified_sink(port_item)

            # Only try to lay out ports if we're already in a scene
            if self.scene():
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

            # Only try to lay out ports if we're in a scene
            if self.scene():
                self.layout_ports() # Recalculate layout
            return True
        return False
        
    def _calculate_and_set_title_geometry(self, node_width: float) -> float:
        """
        Calculate and set the title geometry using the scene's GraphLayouter.
        
        Args:
            node_width: The width of the node
            
        Returns:
            float: The calculated title height
            
        Raises:
            RuntimeError: If no layouter is available
        """
        if not self.scene() or not hasattr(self.scene(), 'layouter') or not self.scene().layouter:
            raise RuntimeError("Cannot calculate title geometry: No GraphLayouter available")
            
        return self.scene().layouter._calculate_and_set_title_geometry(self, node_width)

    def _hide_all_ports_and_bulk_areas(self):
        """
        Hide all port items and bulk area items using the scene's GraphLayouter.
        
        Raises:
            RuntimeError: If no layouter is available
        """
        if not self.scene() or not hasattr(self.scene(), 'layouter') or not self.scene().layouter:
            raise RuntimeError("Cannot hide ports and bulk areas: No GraphLayouter available")
            
        self.scene().layouter._hide_all_ports_and_bulk_areas(self)

    def _show_all_ports_and_bulk_areas(self):
        """
        Show all port items and bulk area items using the scene's GraphLayouter.
        
        Raises:
            RuntimeError: If no layouter is available
        """
        if not self.scene() or not hasattr(self.scene(), 'layouter') or not self.scene().layouter:
            raise RuntimeError("Cannot show ports and bulk areas: No GraphLayouter available")
            
        self.scene().layouter._show_all_ports_and_bulk_areas(self)

    def _layout_bulk_areas(self, current_node_width: float, max_in_width: float, 
                         max_out_width: float, y_start_bulk: float):
        """
        Position the bulk area items using the scene's GraphLayouter.
        
        Args:
            current_node_width: Current width of the node
            max_in_width: Maximum width of input ports
            max_out_width: Maximum width of output ports
            y_start_bulk: Y-coordinate to start placing bulk areas
            
        Raises:
            RuntimeError: If no layouter is available
        """
        if not self.scene() or not hasattr(self.scene(), 'layouter') or not self.scene().layouter:
            raise RuntimeError("Cannot layout bulk areas: No GraphLayouter available")
            
        self.scene().layouter._layout_bulk_areas(
            self, current_node_width, max_in_width, max_out_width, y_start_bulk
        )

    def _layout_individual_ports(self, current_node_width: float, 
                              y_start_ports: float) -> tuple[float, float]:
        """
        Position individual port items using the scene's GraphLayouter.
        
        Args:
            current_node_width: Current width of the node
            y_start_ports: Y-coordinate to start placing ports
            
        Returns:
            Tuple[float, float]: Final y-offsets for input and output ports
            
        Raises:
            RuntimeError: If no layouter is available
        """
        if not self.scene() or not hasattr(self.scene(), 'layouter') or not self.scene().layouter:
            raise RuntimeError("Cannot layout individual ports: No GraphLayouter available")
            
        return self.scene().layouter._layout_individual_ports(
            self, current_node_width, y_start_ports
        )
        
    def layout_ports(self):
        """Positions port items vertically and updates node height and width.
        
        Requires the scene to have a GraphLayouter instance set as 'layouter'.
        """
        if not self.scene():
            raise RuntimeError("Cannot layout ports: Node is not in a scene")
        if not hasattr(self.scene(), 'layouter') or not self.scene().layouter:
            raise RuntimeError("Cannot layout ports: Scene has no GraphLayouter")
            
        self.scene().layouter.layout_node_ports(self)

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
            message = f"{custom_message}\n\nYou can restore it later from the Clients Visibility dialog."
        else:
            message = f"Hide {client_name} {message_type} node?\n\nYou can restore it later from the Clients Visibility dialog."
        
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
        
        # Add separator after Disconnect
        menu.addSeparator()

        if self.split_origin_node:
            unsplit_action = menu.addAction("Unsplit")
            unsplit_action.setShortcut(Qt.Key.Key_U)
            unsplit_action.triggered.connect(lambda: self.split_origin_node.split_handler.unsplit_node(save_state=True))
        else:
            menu.addAction("Unsplit (Error: No Origin)").setEnabled(False)

        if is_input_part:
            fold_text = "Unfold Input Part" if self.input_part_folded else "Fold Input Part"
            menu.addAction(fold_text).triggered.connect(lambda: self.fold_handler.toggle_input_part_fold())
        elif is_output_part:
            fold_text = "Unfold Output Part" if self.output_part_folded else "Fold Output Part"
            menu.addAction(fold_text).triggered.connect(lambda: self.fold_handler.toggle_output_part_fold())
            
        # Add the Hide option
        hide_action = menu.addAction("Hide")
        hide_action.setShortcut(Qt.Key.Key_H)
        hide_action.triggered.connect(self._hide_node)

    def _build_context_menu_for_split_origin(self, menu: QMenu, disconnect_is_enabled: bool):
        disconnect_action = menu.addAction("Disconnect all")
        disconnect_action.setEnabled(disconnect_is_enabled)
        disconnect_action.triggered.connect(self._disconnect_all_connections)
        
        # Add separator after Disconnect
        menu.addSeparator()
        
        unsplit_action = menu.addAction("Unsplit Node")
        unsplit_action.setShortcut(Qt.Key.Key_U)
        unsplit_action.triggered.connect(lambda: self.split_handler.unsplit_node(save_state=True))
        
        # Add the Hide option
        hide_action = menu.addAction("Hide")
        hide_action.setShortcut(Qt.Key.Key_H)
        hide_action.triggered.connect(self._hide_node)

    def ensure_unified_sink_exists(self):
        """Check if the unified sink exists and recreate it if not or if broken."""
        if not self.is_unified or not self.unified_virtual_sink_name:
            return

        # Check if sink exists by looking for its ports
        jack_handler = self.jack_handler if self.jack_handler else getattr(self.scene(), 'jack_connection_handler', None)
        if not jack_handler:
            return

        all_ports = jack_handler.get_ports()
        sink_client_name = f"{self.unified_virtual_sink_name} Audio/Sink sink"
        sink_ports = [p for p in all_ports if p.name.startswith(sink_client_name)]

        if not sink_ports:
            # Sink doesn't exist, recreate it
            print(f"Unified sink {self.unified_virtual_sink_name} not found, recreating...")
            self._create_unified_sink()
            self._wait_for_sink_and_connect()
        else:
            print(f"Unified sink {self.unified_virtual_sink_name} found, testing connections...")
            # Test if the sink is functional by trying to make a test connection
            if self._test_sink_functionality():
                print(f"Unified sink {self.unified_virtual_sink_name} is functional, ensuring connections...")
                self._connect_to_unified_sink()
            else:
                print(f"Unified sink {self.unified_virtual_sink_name} is broken, recreating...")
                # First unload the broken sink if we can find the module ID
                if hasattr(self, 'unified_module_id') and self.unified_module_id:
                    try:
                        import subprocess
                        subprocess.run(["pactl", "unload-module", str(self.unified_module_id)],
                                     check=True, capture_output=True, text=True)
                    except Exception as e:
                        print(f"Warning: Could not unload broken unified sink: {e}")

                # Clear the old module ID so we get a fresh one
                self.unified_module_id = None

                # Recreate the sink
                self._create_unified_sink()
                self._wait_for_sink_and_connect()

    def _test_sink_functionality(self):
        """Test if the unified sink is functional by checking if connection logic works."""
        if not self.unified_virtual_sink_name or not self.scene() or not hasattr(self.scene(), 'jack_connection_handler'):
            return False

        try:
            # Try to find the sink ports
            jack_handler = self.jack_handler
            all_ports = jack_handler.get_ports()
            sink_client_name = f"{self.unified_virtual_sink_name} Audio/Sink sink"

            if self.unified_ports_type == 'output':
                # For output unification, we need sink inputs
                sink_inputs = [p for p in all_ports if
                              p.is_input and
                              p.name.startswith(sink_client_name + ':') and
                              (p.name.endswith(':playback_FL') or p.name.endswith(':playback_FR'))]
                return len(sink_inputs) >= 2  # Should have at least left and right channels

            elif self.unified_ports_type == 'input':
                # For input unification, we need sink outputs
                sink_outputs = [p for p in all_ports if
                               p.is_output and
                               p.name.startswith(sink_client_name + ':') and
                               (p.name.endswith(':monitor_FL') or p.name.endswith(':monitor_FR'))]
                return len(sink_outputs) >= 2  # Should have at least left and right channels

            return False

        except Exception as e:
            print(f"Error testing sink functionality for {self.unified_virtual_sink_name}: {e}")
            return False

    def unify_from_preset(self, unify_data):
        """Applies the unified state to the node from a preset."""
        self.is_unified = True
        self.unified_virtual_sink_name = unify_data.get('virtual_sink_name')
        if self.unified_virtual_sink_name:
            # Skip sink creation and connection during preset restoration
            # The unified state is preserved but we don't create unwanted sinks on startup
            self.update()

    def _create_unified_sink(self):
        """Execute the pactl command to create the unified virtual sink."""
        import subprocess
        import json

        if not self.unified_virtual_sink_name:
            return

        command = ["pactl", "load-module", "module-null-sink", f"sink_name={self.unified_virtual_sink_name}", "channel_map=stereo"]

        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            self.unified_module_id = result.stdout.strip()

            # Save the module ID to config
            self._save_unified_module_id()

            print(f"Created unified virtual sink: {self.unified_virtual_sink_name}")
            print(f"Module ID: {self.unified_module_id}")
        except subprocess.CalledProcessError as e:
            print(f"Error creating unified virtual sink: {e}")

    def _save_unified_module_id(self):
        """Save the unified module ID to config file for later unloading."""
        import json
        try:
            from cable_core.config import ConfigManager
            config_manager = ConfigManager()

            # Get existing module IDs, or initialize empty dict
            module_ids_json = config_manager.get_str_setting('unified_virtual_sinks', '{}')
            try:
                module_ids = json.loads(module_ids_json) if module_ids_json else {}
            except json.JSONDecodeError:
                module_ids = {}

            # Add/update the module ID
            module_ids[self.unified_virtual_sink_name] = self.unified_module_id

            # Save back to config
            config_manager.set_str_setting('unified_virtual_sinks', json.dumps(module_ids))

        except Exception as e:
            print(f"Error saving unified module ID for {self.unified_virtual_sink_name}: {e}")

    def _unload_unified_sink(self):
        """Unload the unified virtual sink."""
        import subprocess
        import json

        if not self.unified_module_id:
            return

        command = ["pactl", "unload-module", self.unified_module_id]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            print(f"Unloaded unified virtual sink: {self.unified_virtual_sink_name}")

            # Remove the module ID from config
            self._remove_unified_module_id()

        except subprocess.CalledProcessError as e:
            print(f"Error unloading unified virtual sink: {e}")

    def _remove_unified_module_id(self):
        """Remove the unified module ID from config file."""
        try:
            import json
            from cable_core.config import ConfigManager
            config_manager = ConfigManager()

            module_ids_json = config_manager.get_str_setting('unified_virtual_sinks', '{}')
            try:
                module_ids = json.loads(module_ids_json) if module_ids_json else {}
            except json.JSONDecodeError:
                module_ids = {}

            if self.unified_virtual_sink_name in module_ids:
                del module_ids[self.unified_virtual_sink_name]

            config_manager.set_str_setting('unified_virtual_sinks', json.dumps(module_ids))

        except Exception as e:
            print(f"Error removing unified module ID for {self.unified_virtual_sink_name}: {e}")

    def _connect_to_unified_sink(self):
        """Connect this node's ports to the unified sink based on the unified_ports_type setting."""
        if not self.is_unified or not self.unified_virtual_sink_name or not self.scene() or not hasattr(self.scene(), 'jack_connection_handler'):
            return

        jack_handler = self.jack_handler
        all_ports = jack_handler.get_ports()
        sink_name_base = self.unified_virtual_sink_name
        connection_handler = self.scene().jack_connection_handler

        # Use the unified_ports_type to determine which ports to connect
        if self.unified_ports_type == 'output':
            # Connect output ports to sink inputs
            node_outputs = sorted([p for p in self.output_ports.values()], key=natural_sort_key)

            # Find sink input ports that belong to our specific unified sink
            sink_client_name = f"{self.unified_virtual_sink_name} Audio/Sink sink"
            sink_inputs = [p for p in all_ports if
                          p.is_input and
                          p.name.startswith(sink_client_name + ':') and
                          (p.name.endswith(':playback_FL') or p.name.endswith(':playback_FR'))]

            print(f"Connecting {'output' if self.unified_ports_type == 'output' else 'input'} node to sink '{self.unified_virtual_sink_name}':")
            print(f"  Node outputs: {[p.port_name for p in node_outputs]}")
            print(f"  Sink inputs found: {[p.name for p in sink_inputs]}")

            if not node_outputs or not sink_inputs:
                print("Unified sink connection failed: No node outputs or sink inputs found.")
                return

            # Match and connect outputs to inputs
            for i, port_item in enumerate(node_outputs):
                port_name = port_item.short_name.lower()
                target_sink_input = None

                if 'left' in port_name or 'fl' in port_name:
                    target_sink_input = sink_inputs[0].name if len(sink_inputs) > 0 else None
                elif 'right' in port_name or 'fr' in port_name:
                    target_sink_input = sink_inputs[1].name if len(sink_inputs) > 1 else sink_inputs[0].name if len(sink_inputs) > 0 else None
                else:
                    target_sink_input = sink_inputs[i % len(sink_inputs)].name if sink_inputs else None

                if target_sink_input:
                    try:
                        connection_handler.make_connection(port_item.port_name, target_sink_input)
                        print(f"  Connected {port_item.port_name} -> {target_sink_input}")
                    except Exception as e:
                        print(f"Error connecting {port_item.port_name} to {target_sink_input}: {e}")

        elif self.unified_ports_type == 'input':
            # Connect sink outputs to input ports
            node_inputs = sorted([p for p in self.input_ports.values()], key=natural_sort_key)

            # Find sink output ports that belong to our specific unified sink
            sink_client_name = f"{self.unified_virtual_sink_name} Audio/Sink sink"
            sink_outputs = [p for p in all_ports if
                           p.is_output and
                           p.name.startswith(sink_client_name + ':') and
                           (p.name.endswith(':monitor_FL') or p.name.endswith(':monitor_FR'))]

            print(f"Connecting {'input' if self.unified_ports_type == 'input' else 'output'} node to sink '{self.unified_virtual_sink_name}':")
            print(f"  Node inputs: {[p.port_name for p in node_inputs]}")
            print(f"  Sink outputs found: {[p.name for p in sink_outputs]}")

            if not node_inputs or not sink_outputs:
                print("Unified sink connection failed: No node inputs or sink outputs found.")
                return

            # Match and connect sink outputs to node inputs
            for i, port_item in enumerate(node_inputs):
                port_name = port_item.short_name.lower()
                source_sink_output = None

                if 'left' in port_name or 'fl' in port_name:
                    source_sink_output = sink_outputs[0].name if len(sink_outputs) > 0 else None
                elif 'right' in port_name or 'fr' in port_name:
                    source_sink_output = sink_outputs[1].name if len(sink_outputs) > 1 else sink_outputs[0].name if len(sink_outputs) > 0 else None
                else:
                    source_sink_output = sink_outputs[i % len(sink_outputs)].name if sink_outputs else None

                if source_sink_output:
                    try:
                        connection_handler.make_connection(source_sink_output, port_item.port_name)
                        print(f"  Connected {source_sink_output} -> {port_item.port_name}")
                    except Exception as e:
                        print(f"Error connecting {source_sink_output} to {port_item.port_name}: {e}")


    def _connect_new_port_to_unified_sink(self, port_item: PortItem):
        """Connect a newly added port to the unified sink using channel matching."""
        if not self.unified_virtual_sink_name or not self.scene() or not hasattr(self.scene(), 'jack_connection_handler'):
            return

        jack_handler = self.jack_handler
        all_ports = jack_handler.get_ports()

        sink_name_base = self.unified_virtual_sink_name
        sink_name_full = f"{sink_name_base} Audio/Sink sink"
        sink_inputs = sorted([p for p in all_ports if (p.name.startswith(sink_name_base + ':') or p.name.startswith(sink_name_full + ':')) and p.is_input], key=lambda p: p.name)

        if not sink_inputs:
            print(f"Unified sink not found for {port_item.port_name}")
            return

        # Identify left and right sink inputs
        left_sink_input = None
        right_sink_input = None
        if len(sink_inputs) >= 2:
            left_sink_input = sink_inputs[0].name
            right_sink_input = sink_inputs[1].name
        elif len(sink_inputs) == 1:
            left_sink_input = sink_inputs[0].name
            right_sink_input = sink_inputs[0].name # Fallback to mono

        if not left_sink_input or not right_sink_input:
            return

        # Match port to sink input based on channel name
        port_name_lower = port_item.short_name.lower()
        target_sink_input = None

        if 'left' in port_name_lower or 'fl' in port_name_lower or 'l' == port_name_lower:
            target_sink_input = left_sink_input
        elif 'right' in port_name_lower or 'fr' in port_name_lower or 'r' == port_name_lower:
            target_sink_input = right_sink_input
        else:
            # Try to match by position - assume first unconnected output goes to left, second to right
            # This logic works well for applications that add ports dynamically
            node_outputs = sorted([p for p in self.output_ports.values()], key=natural_sort_key)
            port_index = node_outputs.index(port_item) if port_item in node_outputs else 0
            target_sink_input = left_sink_input if port_index % 2 == 0 else right_sink_input

        if target_sink_input:
            try:
                connection_handler = self.scene().jack_connection_handler
                connection_handler.make_connection(port_item.port_name, target_sink_input)
                print(f"Auto-connected new port {port_item.port_name} to unified sink")
            except Exception as e:
                print(f"Error auto-connecting {port_item.port_name} to {target_sink_input}: {e}")

    def _wait_for_sink_and_connect(self):
        """Waits for the unified sink to appear and then connects to it."""
        MAX_RETRIES = 50 # 50 * 100ms = 5 seconds
        if self.wait_for_sink_retries >= MAX_RETRIES:
            print("Unified sink did not appear in time.")
            self.wait_for_sink_retries = 0
            return

        if not self.unified_virtual_sink_name:
            print("No unified sink name available for connection attempt.")
            self.wait_for_sink_retries = 0
            return

        jack_handler = self.jack_handler
        all_ports = jack_handler.get_ports()
        sink_name_base = self.unified_virtual_sink_name

        # Look specifically for ports that belong to the sink we created for this node
        # The full JACK client name will be: "sink_name_base Audio/Sink sink"
        sink_client_name = f"{sink_name_base} Audio/Sink sink"
        sink_inputs = sorted([p for p in all_ports if (
            p.name.startswith(sink_client_name + ':')  # ports from our specific sink
        ) and p.is_input], key=lambda p: p.name)

        print(f"Waiting for sink - name_base: '{sink_name_base}', found {len(sink_inputs)} sink inputs")
        if sink_inputs:
            for port in sink_inputs[:5]:  # Show first 5
                print(f"  Found sink input: {port.name}")

        if sink_inputs:
            self.wait_for_sink_retries = 0
            self._connect_to_unified_sink()
        else:
            self.wait_for_sink_retries += 1
            self.wait_for_sink_timer = QTimer()
            self.wait_for_sink_timer.setSingleShot(True)
            self.wait_for_sink_timer.timeout.connect(self._wait_for_sink_and_connect)
            self.wait_for_sink_timer.start(100)

    def _toggle_unify(self, checked):
        # Temporarily disconnect the signal to prevent infinite loops
        if hasattr(self, 'unify_action') and self.unify_action:
            self.unify_action.blockSignals(True)

        try:
            if checked:
                # For nodes with both inputs and outputs, show dialog to choose ports type
                has_inputs = bool(self.input_ports)
                has_outputs = bool(self.output_ports)

                # For mixed nodes (both inputs and outputs), show a dialog to choose ports type
                if has_outputs and has_inputs:
                    # Show dialog to choose whether to unify inputs or outputs
                    chosen_ports_type = self._show_unify_ports_choice_dialog()
                    if not chosen_ports_type:
                        # User canceled - reset the action's checked state
                        if hasattr(self, 'unify_action') and self.unify_action:
                            self.unify_action.setChecked(self.is_unified)
                        return  # User canceled
                    self.unified_ports_type = chosen_ports_type
                elif has_outputs:
                    self.unified_ports_type = 'output'
                elif has_inputs:
                    self.unified_ports_type = 'input'
                else:
                    print("Node has no ports, cannot unify")
                    # Reset the action's checked state since we can't unify
                    if hasattr(self, 'unify_action') and self.unify_action:
                        self.unify_action.setChecked(self.is_unified)
                    return

                self.is_unified = True
                self.unified_virtual_sink_name = f"unified-{self.client_name.replace(' ', '_')}"
                self._create_unified_sink()
                self._wait_for_sink_and_connect()
            else:
                # User wants to disable unify
                self.is_unified = False
                # Capture sink name before clearing it
                sink_name_to_remove = self.unified_virtual_sink_name
                module_id_to_remove = self.unified_module_id

                self._unload_unified_sink()
                self.unified_virtual_sink_name = None
                self.unified_module_id = None
                self.unified_ports_type = None

            # Update visual highlighting for all nodes in the scene
            self.update()

            # Refresh highlighting of any existing virtual sink nodes
            if self.scene():
                for item in self.scene().items():
                    if isinstance(item, NodeItem) and hasattr(item, 'is_virtual_sink') and item.is_virtual_sink:
                        # Re-check if this virtual sink should be unified
                        old_unified_status = getattr(item, 'is_unified_sink', False)
                        item._check_if_virtual_sink(item.client_name)
                        new_unified_status = getattr(item, 'is_unified_sink', False)

                        # If the unified status changed, force a visual update
                        if old_unified_status != new_unified_status:
                            print(f"Unified sink status changed for {item.client_name}: {old_unified_status} -> {new_unified_status}")
                        item.update()

            # Update the unified state in saved config
            if hasattr(self, 'config_manager') and self.config_manager:
                # Load current config
                try:
                    import json
                    if self.config_manager.node_positions_file.exists():
                        with open(self.config_manager.node_positions_file, 'r') as f:
                            saved_data = json.load(f)

                        client_config = saved_data.get(self.client_name, {})

                        # Update unified state in config
                        if self.is_unified:
                            client_config[self.config_manager.IS_UNIFIED_KEY] = True
                            client_config[self.config_manager.UNIFIED_SINK_NAME_KEY] = self.unified_virtual_sink_name
                            client_config[self.config_manager.UNIFIED_MODULE_ID_KEY] = self.unified_module_id
                            if self.unified_ports_type:
                                client_config[self.config_manager.UNIFIED_PORTS_TYPE_KEY] = self.unified_ports_type
                        else:
                            # Remove unified state from config
                            client_config.pop(self.config_manager.IS_UNIFIED_KEY, None)
                            client_config.pop(self.config_manager.UNIFIED_SINK_NAME_KEY, None)
                            client_config.pop(self.config_manager.UNIFIED_MODULE_ID_KEY, None)

                        # Save updated config
                        saved_data[self.client_name] = client_config
                        with open(self.config_manager.node_positions_file, 'w') as f:
                            json.dump(saved_data, f, indent=4)

                    # Also clear from unified virtual sinks config
                    if not self.is_unified and sink_name_to_remove and module_id_to_remove:
                        try:
                            from cable_core.config import ConfigManager
                            config_manager = ConfigManager()
                            module_ids_json = config_manager.get_str_setting('unified_virtual_sinks', '{}')
                            if module_ids_json:
                                module_ids = json.loads(module_ids_json)
                                if sink_name_to_remove in module_ids:
                                    del module_ids[sink_name_to_remove]
                                    config_manager.set_str_setting('unified_virtual_sinks', json.dumps(module_ids))
                        except Exception as e:
                            print(f"Error cleaning up unified virtual sinks config: {e}")
                except Exception as e:
                    print(f"Error updating unified state in config: {e}")
        finally:
            # Re-enable the signal
            if hasattr(self, 'unify_action') and self.unify_action:
                self.unify_action.blockSignals(False)

    def _show_unify_ports_choice_dialog(self):
        """
        Show a dialog to choose whether to unify input ports or output ports.

        Returns:
            str or None: 'input', 'output', or None if canceled
        """
        # Get the main window as parent for proper centering
        parent = None
        if self.scene() and self.scene().views():
            parent = self.scene().views()[0]

        dialog = QDialog(parent)
        dialog.setWindowTitle("Choose Ports to Unify")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        # Add instruction text
        instruction = QLabel("Unify:")
        instruction.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(instruction)

        # Create radio buttons
        output_radio = QRadioButton("Output ports")
        output_radio.setChecked(True)  # Default selection
        layout.addWidget(output_radio)

        input_radio = QRadioButton("Input ports")
        layout.addWidget(input_radio)

        # Add buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # Center the dialog in the main window
        if parent:
            dialog.adjustSize()  # Ensure the dialog size is calculated
            parent_center = parent.rect().center()
            dialog_center = dialog.rect().center()
            dialog.move(parent.mapToGlobal(parent_center - dialog_center))

        # Execute dialog
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            if input_radio.isChecked():
                return 'input'
            elif output_radio.isChecked():
                return 'output'
            else:
                return None
        else:
            return None

    def _build_context_menu_for_normal_node(self, menu: QMenu, disconnect_is_enabled: bool):
        disconnect_action = menu.addAction("Disconnect all")
        disconnect_action.setEnabled(disconnect_is_enabled)
        disconnect_action.triggered.connect(self._disconnect_all_connections)

        # Add separator after Disconnect
        menu.addSeparator()

        # Add "Unload sink" option for virtual sinks
        if hasattr(self, 'is_virtual_sink') and self.is_virtual_sink:
            unload_action = menu.addAction("Unload sink/source")
            unload_action.triggered.connect(self._unload_sink)

        split_action = menu.addAction("Split")
        split_action.setShortcut(Qt.Key.Key_S)
        split_action.setEnabled(bool(self.input_ports) and bool(self.output_ports))
        split_action.triggered.connect(lambda: self.split_handler.split_node(save_state=True))

        fold_text = "Unfold" if self.is_folded else "Fold"
        menu.addAction(fold_text).triggered.connect(self.fold_handler.toggle_main_fold_state)

        # Add the Hide option
        hide_action = menu.addAction("Hide")
        hide_action.setShortcut(Qt.Key.Key_H)
        hide_action.triggered.connect(self._hide_node)

        # Check if this is a MIDI node - Unify toggle should not be available for MIDI nodes
        # Also hide unify option for all sinks (virtual sinks created by the app or externally)
        is_midi_node = False
        for port_list in [self.input_ports, self.output_ports]:
            for port_item in port_list.values():
                if hasattr(port_item.port_obj, 'is_midi') and port_item.port_obj.is_midi:
                    is_midi_node = True
                    break
            if is_midi_node:
                break

        # Check if this is a virtual sink (any virtual sink)
        is_virtual_sink = getattr(self, 'is_virtual_sink', False)

        # Add second separator and "Unify" checkbox only for audio nodes that aren't virtual sinks
        if not is_midi_node and not is_virtual_sink:
            # Add separator before Unify section
            menu.addSeparator()

            self.unify_action = QAction("Unify ports", menu)
            self.unify_action.setCheckable(True)
            # Force the checkbox to reflect the current unified state
            self.unify_action.setChecked(self.is_unified)
            self.unify_action.toggled.connect(self._toggle_unify)
            menu.addAction(self.unify_action)

            # Add help text below the Unify action
            help_text = QAction("Route all client ports\nthrough a dedicated\nstereo virtual sink", menu)
            help_text.setEnabled(False)  # Make it non-clickable
            menu.addAction(help_text)

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
        self._internal_state_change_in_progress = True
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

        # Apply unified state
        if config.get('is_unified'):
            self.unify_from_preset(config)
            self.ensure_unified_sink_exists()
        
        self._internal_state_change_in_progress = False

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

    def _check_if_virtual_sink(self, client_name: str):
        """Check if this node represents a virtual sink by looking at stored module IDs or detecting pattern."""
        try:
            from cable_core.config import ConfigManager
            config_manager = ConfigManager()
            module_ids_json = config_manager.get_str_setting('virtual_sink_module_ids', '{}')

            if module_ids_json:
                import json
                module_ids = json.loads(module_ids_json)
                # Check exact match first (full client name in config)
                if client_name in module_ids:
                    self.is_virtual_sink = True
                    self.module_id = module_ids[client_name]
                else:
                    # Check if client name starts with any sink name (app-created sinks)
                    self.is_virtual_sink = False
                    for sink_name in module_ids.keys():
                        if client_name.startswith(sink_name + ' '):
                            self.is_virtual_sink = True
                            self.module_id = module_ids[sink_name]
                            break

                    # Fallback: Check for any virtual sink pattern (external sinks)
                    if not self.is_virtual_sink and client_name.endswith(' Audio/Sink sink'):
                        self.is_virtual_sink = True
                        self.module_id = None  # Will find dynamically
                        self.external_sink = True
            else:
                # No config entries, but still check for virtual sink pattern
                if client_name.endswith(' Audio/Sink sink'):
                    self.is_virtual_sink = True
                    self.module_id = None
                    self.external_sink = True

            # Check if this virtual sink was created by Unify toggle
            if self.is_virtual_sink:
                unified_sinks_json = config_manager.get_str_setting('unified_virtual_sinks', '{}')
                if unified_sinks_json:
                    unified_sinks = json.loads(unified_sinks_json)
                    # Check if this sink is a unified sink
                    for unified_sink_name in unified_sinks.keys():
                        if (client_name == unified_sink_name or  # Direct match
                            client_name == f"{unified_sink_name} Audio/Sink sink"):  # Full JACK name match
                            self.is_unified_sink = True
                            print(f"Detected unified sink: {client_name} matches {unified_sink_name}")
                            break
                                    # Check pattern by normalizing both names to use underscores for comparison
                        sink_base_from_client = client_name.replace(' Audio/Sink sink', '').replace(' ', '_').replace('-', '_')
                        unified_sink_name_normalized = unified_sink_name.replace(' ', '_').replace('-', '_')
                        if unified_sink_name_normalized.startswith(sink_base_from_client + '_'):
                            self.is_unified_sink = True
                            print(f"Detected unified sink (pattern match): {client_name} matches {unified_sink_name}")
                            break

        except Exception as e:
            print(f"Error checking if node is virtual sink for {client_name}: {e}")
            self.is_virtual_sink = False
            self.module_id = None

    def _find_module_id_for_external_sink(self, sink_name: str):
        """Find module ID for an external virtual sink using pactl list sinks."""
        try:
            import subprocess
            result = subprocess.run(["pactl", "list", "sinks"],
                                  capture_output=True, text=True, check=True)

            lines = result.stdout.split('\n')
            in_target_sink = False

            for line in lines:
                line = line.strip()

                # Start of target sink - be more precise with matching
                if not in_target_sink and line == f'Name: {sink_name}':
                    in_target_sink = True

                # Found Owner Module within target sink
                elif in_target_sink and 'Owner Module:' in line:
                    module_id = line.split(':', 1)[1].strip()
                    # Validate it's a real module ID (not error value)
                    if module_id.isdigit():
                        module_id_int = int(module_id)
                        if module_id_int != 4294967295:
                            return module_id
                        else:
                            print(f"Warning: Invalid module ID {module_id} for sink '{sink_name}' (error value)")
                            return None
                    else:
                        print(f"Warning: Non-numeric module ID '{module_id}' for sink '{sink_name}'")
                        return None

                # Exit sink block when we hit the next sink
                elif in_target_sink and line.startswith('Name: ') and line != f'Name: {sink_name}':
                    break

            print(f"Warning: Could not find valid Owner Module for sink '{sink_name}'")
            return None

        except subprocess.CalledProcessError as e:
            print(f"Error running pactl list sinks: {e}")
            return None
        except Exception as e:
            print(f"Error finding module ID for external sink '{sink_name}': {e}")
            return None

    def _unload_sink(self):
        """Unload this virtual sink using the stored module ID or finding it dynamically."""
        if not self.is_virtual_sink:
            print(f"Cannot unload sink: {self.client_name} is not identified as a virtual sink")
            return

        # Extract sink name from client name (remove " Audio/Sink sink" suffix)
        sink_name = self.client_name.replace(' Audio/Sink sink', '')

        # Get module ID - either stored or find dynamically
        module_id = getattr(self, 'module_id', None)
        if not module_id:
            module_id = self._find_module_id_for_external_sink(sink_name)

        if not module_id:
            print(f"Cannot unload sink: No module ID found for {self.client_name}")
            return

        import subprocess
        command = ["pactl", "unload-module", str(module_id)]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            sink_type = "external" if getattr(self, 'external_sink', False) else "tracked"
            print(f"Successfully unloaded {sink_type} virtual sink: {self.client_name} (module ID: {module_id})")

            # For tracked sinks: Remove from stored module IDs
            if getattr(self, 'external_sink', False) is False:
                try:
                    from cable_core.config import ConfigManager
                    config_manager = ConfigManager()
                    module_ids_json = config_manager.get_str_setting('virtual_sink_module_ids', '{}')

                    if module_ids_json:
                        import json
                        module_ids = json.loads(module_ids_json)

                        # Find the key that matches this client (either exact or partial match)
                        key_to_remove = None
                        for stored_sink_name in module_ids.keys():
                            if self.client_name == stored_sink_name or self.client_name.startswith(stored_sink_name + ' '):
                                key_to_remove = stored_sink_name
                                break

                        if key_to_remove:
                            del module_ids[key_to_remove]
                            config_manager.set_str_setting('virtual_sink_module_ids', json.dumps(module_ids))
                            print(f"Removed module ID {module_id} from config for sink '{key_to_remove}' (client: {self.client_name})")
                        else:
                            print(f"Warning: Could not find config entry to remove for {self.client_name}")

                except Exception as e:
                    print(f"Error removing module ID from config for {self.client_name}: {e}")

        except subprocess.CalledProcessError as e:
            print(f"Error unloading virtual sink {self.client_name}: {e}")
