# --- PyQt Graphical Items - NodeItem ---
"""
QGraphicsItem representing a JACK client node with ports, folding, splitting, and context menus.
"""
import logging
import traceback # For error reporting in _split_node
import os

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QGraphicsPathItem, QMenu,
    QStyleOptionGraphicsItem, QWidget, QStyle, QGraphicsSceneHoverEvent,
    QMessageBox, QCheckBox, QVBoxLayout, QDialog, QDialogButtonBox, QLabel,
    QGraphicsSceneMouseEvent, QGraphicsSceneContextMenuEvent
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QAction, QPolygonF,
    QFontMetrics, QPalette
)
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QLineF, QEvent, QSize, QTimer
)

from . import constants # Import the new constants module
from cable_core import config_keys as keys
from .port_item import PortItem # Import PortItem
from .bulk_area_item import BulkAreaItem # Import BulkAreaItem
from .config_utils import GraphConfigManager
from typing import TYPE_CHECKING, Optional, Dict, List, Tuple, Any, Union, Callable

if TYPE_CHECKING:
    from .layout import GraphLayouter  # For type hints only
# Note: ConnectionItem is needed for creating new connections during split/unsplit
# from .connection_item import ConnectionItem # Avoid circular import here, use string literal

from .node_fold_handler import NodeFoldHandler
from .node_split_handler import NodeSplitHandler
from .node_unify_handler import NodeUnifyHandler

# Import shared sorting utility
from cables.utils.sort_utils import natural_sort_key_for_port_item as natural_sort_key




# --- Modified Node Item ---

class NodeItem(QGraphicsItem):
    """Represents a JACK client with its ports."""
    # Modify the __init__ signature and logic
    def __init__(self, client_name: str, jack_handler: Any, config_manager: GraphConfigManager, ports_to_add: dict | None = None, original_client_name: str | None = None) -> None:
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
        self.original_client_name = original_client_name if original_client_name else client_name
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
        self.unify_handler = NodeUnifyHandler(self)

        # Split unification state
        self.is_input_unified = False
        self.is_output_unified = False
        self.unified_input_sink_name = None
        self.unified_output_sink_name = None
        self.unified_input_module_id = None
        self.unified_output_module_id = None
        
        self.unify_input_action = None
        self.unify_output_action = None
        self.wait_for_sink_timer = None
        self.wait_for_sink_retries = 0

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
        if config_manager and getattr(config_manager, 'node_positions_file', None):
            try:
                import json
                if config_manager.node_positions_file.exists():
                    with open(config_manager.node_positions_file, 'r') as f:
                        saved_data = json.load(f)
                    client_config = saved_data.get(client_name, {})

                    # Load split unified state
                    if client_config.get(config_manager.IS_INPUT_UNIFIED_KEY, False):
                        self.is_input_unified = True
                        self.unified_input_sink_name = client_config.get(config_manager.UNIFIED_INPUT_SINK_NAME_KEY)
                        self.unified_input_module_id = client_config.get(config_manager.UNIFIED_INPUT_MODULE_ID_KEY)

                    if client_config.get(config_manager.IS_OUTPUT_UNIFIED_KEY, False):
                        self.is_output_unified = True
                        self.unified_output_sink_name = client_config.get(config_manager.UNIFIED_OUTPUT_SINK_NAME_KEY)
                        self.unified_output_module_id = client_config.get(config_manager.UNIFIED_OUTPUT_MODULE_ID_KEY)

            except Exception as e:
                # Silently fail, unified state will be set by apply_configuration later
                logger.error(f"Error loading unified state in __init__: {e}")

        # Check if this is a virtual sink (do this after initialization)
        self.check_if_virtual_sink(client_name)

        # Virtual sink nodes must never carry unification state.
        # If they do, they can connect their own monitor/playback ports together.
        if getattr(self, 'is_virtual_sink', False):
            self.is_input_unified = False
            self.is_output_unified = False
            self.unified_input_sink_name = None
            self.unified_output_sink_name = None
            self.unified_input_module_id = None
            self.unified_output_module_id = None

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

    @property
    def is_midi(self) -> bool:
        """Check if this node has any MIDI ports.

        Returns:
            bool: True if any port (input or output) is a MIDI port, False otherwise.
        """
        # Check all ports in this node
        for port_list in [self.input_ports, self.output_ports]:
            for port_item in port_list.values():
                if getattr(port_item.port_obj, 'is_midi', False):
                    return True

        # Check split parts if this is a split origin node
        if self.is_split_origin:
            for part in [self.split_input_node, self.split_output_node]:
                if part:
                    for port_list in [part.input_ports, part.output_ports]:
                        for port_item in port_list.values():
                            if getattr(port_item.port_obj, 'is_midi', False):
                                return True

        return False

    def _get_paint_colors(self, option: QStyleOptionGraphicsItem, is_selected: bool) -> tuple[QColor, QColor, QColor, QColor]:
        """Determines the colors for painting the node based on theme and selection."""
        border_color = constants.SELECTION_BORDER_COLOR if is_selected else option.palette.color(QPalette.ColorRole.WindowText)

        original_node_body_bg = option.palette.color(QPalette.ColorRole.Base)
        is_light_mode = original_node_body_bg.lightnessF() > 0.7

        # Determine effective unified status
        is_unified_sink = getattr(self, 'is_unified_sink', False)
        is_unified = self.is_input_unified or self.is_output_unified

        # If this is a split part, inherit status from origin
        if self.is_split_part and self.split_origin_node:
            if getattr(self.split_origin_node, 'is_unified_sink', False):
                is_unified_sink = True
            if self.split_origin_node.is_input_unified or self.split_origin_node.is_output_unified:
                is_unified = True

        if is_unified_sink:
            # Virtual sinks created by Unify toggle
            # Check if it's an input or output unified sink based on name
            if "unified-input" in self.client_name or "unified_input" in self.client_name:
                # Input Unified Sink -> Purple #5a3246
                if is_light_mode:
                    title_bg_color = QColor(240, 190, 210)
                else:
                    title_bg_color = QColor(90, 50, 70)
            else:
                # Output Unified Sink -> Green #344b29
                if is_light_mode:
                    title_bg_color = QColor(180, 210, 160)
                else:
                    title_bg_color = QColor(41, 57, 38)
        elif is_unified or self.is_input_unified or self.is_output_unified:
            # Regular unified nodes -> Blue #324664
            if is_light_mode:
                title_bg_color = QColor(200, 220, 255) # Light blue for light mode
            else:
                title_bg_color = QColor(50, 70, 100) # #324664
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

        # Reddish border for virtual sinks marked "Recreate at auto-start"
        if (not is_unified_sink and not is_selected
                and getattr(self, 'is_virtual_sink', False)
                and self._is_recreate_at_autostart()):
            border_color = QColor(180, 70, 70) if is_light_mode else QColor(200, 80, 80)

        return node_body_bg_color, title_bg_color, final_separator_color, border_color
 
    def _bring_to_front(self) -> None:
        """Brings the node item to the front of other NodeItems in the scene."""
        if self.scene():
            current_max_z = 0
            for item in self.scene().items():
                if item != self and isinstance(item, NodeItem):
                    current_max_z = max(current_max_z, item.zValue())
            self.setZValue(current_max_z + 1)
 
    # --- QGraphicsItem Overrides ---
    def boundingRect(self) -> QRectF:
        return self._bounding_rect

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
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

    def add_port(self, port_name: str, port_obj: Any) -> bool:
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

            # Automatically connect new ports to unified sink if node is unified
            self.unify_handler.handle_new_port(port_item, is_input_flag)

            # Only try to lay out ports if we're already in a scene
            if self.scene():
                self.layout_ports() # Recalculate layout
            return True
        return False

    def remove_port(self, port_name: str) -> bool:
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
            if port_item.is_input and not self.input_ports:
                if self.input_area_item:
                    if self.scene():
                        self.scene().removeItem(self.input_area_item)
                    self.input_area_item = None
                
                # If input unification is active but no input ports remain, temporarily unload the sink
                if self.is_input_unified:
                    logger.info(f"No input ports remaining for {self.client_name}, temporarily unloading unified input sink.")
                    self.unify_handler._unload_unified_sink(is_input=True)
                    # Note: We do NOT set is_input_unified to False, so it persists and will auto-recreate

            elif not port_item.is_input and not self.output_ports:
                if self.output_area_item:
                     if self.scene():
                        self.scene().removeItem(self.output_area_item)
                     self.output_area_item = None

                # If output unification is active but no output ports remain, temporarily unload the sink
                if self.is_output_unified:
                    logger.info(f"No output ports remaining for {self.client_name}, temporarily unloading unified output sink.")
                    self.unify_handler._unload_unified_sink(is_input=False)
                    # Note: We do NOT set is_output_unified to False, so it persists and will auto-recreate

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
        scene = self.scene()
        if not scene or not getattr(scene, 'layouter', None):
            raise RuntimeError("Cannot calculate title geometry: No GraphLayouter available")
            
        return self.scene().layouter._calculate_and_set_title_geometry(self, node_width)

    def _hide_all_ports_and_bulk_areas(self) -> None:
        """
        Hide all port items and bulk area items using the scene's GraphLayouter.
        
        Raises:
            RuntimeError: If no layouter is available
        """
        scene = self.scene()
        if not scene or not getattr(scene, 'layouter', None):
            raise RuntimeError("Cannot hide ports and bulk areas: No GraphLayouter available")
            
        self.scene().layouter._hide_all_ports_and_bulk_areas(self)

    def _show_all_ports_and_bulk_areas(self) -> None:
        """
        Show all port items and bulk area items using the scene's GraphLayouter.
        
        Raises:
            RuntimeError: If no layouter is available
        """
        scene = self.scene()
        if not scene or not getattr(scene, 'layouter', None):
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
        scene = self.scene()
        if not scene or not getattr(scene, 'layouter', None):
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
        scene = self.scene()
        if not scene or not getattr(scene, 'layouter', None):
            raise RuntimeError("Cannot layout individual ports: No GraphLayouter available")
            
        return self.scene().layouter._layout_individual_ports(
            self, current_node_width, y_start_ports
        )
        
    def layout_ports(self) -> None:
        """Positions port items vertically and updates node height and width.
        
        Requires the scene to have a GraphLayouter instance set as 'layouter'.
        """
        if not self.scene():
            raise RuntimeError("Cannot layout ports: Node is not in a scene")
        if not getattr(self.scene(), 'layouter', None):
            raise RuntimeError("Cannot layout ports: Scene has no GraphLayouter")
            
        self.scene().layouter.layout_node_ports(self)

    def get_bulk_connection_point(self, is_input: bool) -> QPointF:
        area_item = self.input_area_item if is_input else self.output_area_item
        if area_item:
            return area_item.get_connection_point()
        # Fallback if bulk area item does not exist
        return self.mapToScene(self.boundingRect().center())

    # hoverMoveEvent, hoverLeaveEvent, contextMenuEvent for bulk areas are handled by BulkAreaItem
    # mousePressEvent for bulk areas is handled by BulkAreaItem

    def _disconnect_all_connections(self) -> None:
        """Disconnects all ports of the client this NodeItem (or its origin) represents."""
        client_to_disconnect = self.original_client_name
        current_scene = self.scene()
        jack_handler = getattr(current_scene, 'jack_connection_handler', None) if current_scene else None
        if jack_handler:
            try:
                jack_handler.disconnect_all_ports_of_client(client_to_disconnect)
            except Exception as e:
                # Basic error logging, consider a more robust logging mechanism
                logger.error(f"Error in _disconnect_all_connections for {client_to_disconnect}: {e}")

    # _disconnect_all_inputs and _disconnect_all_outputs are no longer needed.

    # --- Context Menu Helper Methods ---
    def _hide_node(self) -> None:
        """Hides this node or part based on the NodeVisibilityManager settings."""
        current_scene = self.scene()
        node_vis_mgr = getattr(current_scene, 'node_visibility_manager', None) if current_scene else None
        if not node_vis_mgr:
            logger.warning("Cannot hide node: NodeVisibilityManager not available")
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
        
        # Determine if this is a MIDI node using the is_midi property
        # For split parts, check the origin node which covers all parts
        if self.is_split_part and self.split_origin_node:
            is_midi = self.split_origin_node.is_midi
        else:
            is_midi = self.is_midi

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
        connection_manager = getattr(current_scene, 'connection_manager', None)
        if connection_manager:
            config_manager = getattr(connection_manager, 'config_manager', None)
            if config_manager:
                # Use the application-level config_manager which has get_bool method
                app_config = current_scene.connection_manager.config_manager
                show_dialog = app_config.get_bool(keys.SHOW_HIDE_NODE_CONFIRMATION, default=True)
        
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
                custom_message=message
            )
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
            connection_mgr = getattr(current_scene, 'connection_mgr', None)
            if connection_mgr:
                connection_mgr.update_node_connections_visibility(self, False)
                
        # Apply the changes which will hide the node(s)
        current_scene.node_visibility_manager.apply_visibility_settings()
        
        # Do a full refresh of all connection visibility to ensure consistency
        connection_mgr = getattr(current_scene, 'connection_mgr', None)
        if connection_mgr:
            connection_mgr.refresh_all_connection_visibility()
    


    def _build_context_menu_for_split_part(self, menu: QMenu, disconnect_is_enabled: bool) -> None:
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

        # Add the Hide option (skip for unified sinks)
        is_unified = getattr(self, 'is_unified_sink', False)
        if not is_unified:
            hide_action = menu.addAction("Hide")
            hide_action.setShortcut(Qt.Key.Key_H)
            hide_action.triggered.connect(self._hide_node)

    def _build_context_menu_for_split_origin(self, menu: QMenu, disconnect_is_enabled: bool) -> None:
        disconnect_action = menu.addAction("Disconnect all")
        disconnect_action.setEnabled(disconnect_is_enabled)
        disconnect_action.triggered.connect(self._disconnect_all_connections)
        
        # Add separator after Disconnect
        menu.addSeparator()
        
        unsplit_action = menu.addAction("Unsplit Node")
        unsplit_action.setShortcut(Qt.Key.Key_U)
        unsplit_action.triggered.connect(lambda: self.split_handler.unsplit_node(save_state=True))

        # Add the Hide option (skip for unified sinks)
        is_unified = getattr(self, 'is_unified_sink', False)
        if not is_unified:
            hide_action = menu.addAction("Hide")
            hide_action.setShortcut(Qt.Key.Key_H)
            hide_action.triggered.connect(self._hide_node)

    def ensure_unified_sink_exists(self) -> None:
        self.unify_handler.ensure_sink_exists()

    def unify_from_preset(self, unify_data: Dict[str, Any]) -> None:
        self.unify_handler.apply_preset(unify_data)

    def _build_context_menu_for_normal_node(self, menu: QMenu, disconnect_is_enabled: bool) -> None:
        # Skip "Disconnect all" for unified sinks
        is_unified_sink = getattr(self, 'is_unified_sink', False)
        if not is_unified_sink:
            disconnect_action = menu.addAction("Disconnect all")
            disconnect_action.setEnabled(disconnect_is_enabled)
            disconnect_action.triggered.connect(self._disconnect_all_connections)

        # Add virtual sink options (but NOT unified sinks)
        if getattr(self, 'is_virtual_sink', False) and not getattr(self, 'is_unified_sink', False):
            menu.addSeparator()

            # Unload sink/source
            unload_action = menu.addAction("Unload sink/source")
            unload_action.triggered.connect(self.unify_handler.unload_sink)

            # Set as default node
            default_action = QAction("Set as default node", menu)
            default_action.setCheckable(True)
            default_action.setChecked(self._is_default_sink())
            default_action.triggered.connect(lambda checked: self._toggle_default_sink(checked))
            menu.addAction(default_action)

            # Recreate at auto-start
            recreate_action = QAction("Recreate at auto-start", menu)
            recreate_action.setCheckable(True)
            recreate_action.setChecked(self._is_recreate_at_autostart())
            recreate_action.triggered.connect(lambda checked: self._toggle_recreate_at_autostart(checked))
            menu.addAction(recreate_action)

            # Add separator after virtual sink options
            menu.addSeparator()

        split_action = menu.addAction("Split")
        split_action.setShortcut(Qt.Key.Key_S)
        split_action.setEnabled(bool(self.input_ports) and bool(self.output_ports))
        split_action.triggered.connect(lambda: self.split_handler.split_node(save_state=True))

        fold_text = "Unfold" if self.is_folded else "Fold"
        menu.addAction(fold_text).triggered.connect(self.fold_handler.toggle_main_fold_state)

        # Add the Hide option (skip for unified sinks)
        is_unified = getattr(self, 'is_unified_sink', False)
        if not is_unified:
            hide_action = menu.addAction("Hide")
            hide_action.setShortcut(Qt.Key.Key_H)
            hide_action.triggered.connect(self._hide_node)

        # Add unify menu items
        self.unify_handler.build_context_menu(menu)

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent) -> None:
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

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
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

    def apply_configuration(self, config: dict) -> None:
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
        if config.get('is_input_unified') or self.is_input_unified or config.get('is_output_unified') or self.is_output_unified or config.get('is_unified'):
            self.unify_handler.apply_preset(config)
            self.unify_handler.ensure_sink_exists()
        
        self._internal_state_change_in_progress = False

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if not self.scene() or not getattr(self, 'config_manager', None):
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

    def update_ports(self) -> None:
        """Fetches current ports for this client from JACK and updates visuals."""
        if not self.jack_handler or not self.jack_handler.jack_client:
            return # Silently return if no valid jack_handler

        all_ports_in_jack = self.jack_handler.get_ports()
        # Determine the correct JACK client name to match against
        jack_client_name_to_match = self.original_client_name
        
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

    def set_bulk_drag_highlight(self, highlight_input: bool, highlight_output: bool) -> None:
        """Externally sets the highlight state for BulkAreaItems during drag operations."""
        if self.input_area_item:
            self.input_area_item.set_drag_highlight(highlight_input)
        if self.output_area_item:
            self.output_area_item.set_drag_highlight(highlight_output)

    def _disconnect_this_part_input_ports(self) -> None:
        """Disconnects all input ports of this specific node item (assumed to be an input split part)."""
        current_scene = self.scene()
        jack_handler = getattr(current_scene, 'jack_connection_handler', None) if current_scene else None
        if not jack_handler:
            return
        jack_handler = current_scene.jack_connection_handler
        for port_item in list(self.input_ports.values()): # Iterate copy
            if not port_item: continue
            for conn_item in list(port_item.connections): # Iterate copy
                if conn_item and conn_item.source_port and conn_item.dest_port:
                    try:
                        jack_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                    except Exception as e:
                        logger.error(f"Error breaking input connection for {port_item.port_name} of {self.client_name}: {e}")

    def _disconnect_this_part_output_ports(self) -> None:
        """Disconnects all output ports of this specific node item (assumed to be an output split part)."""
        current_scene = self.scene()
        jack_handler = getattr(current_scene, 'jack_connection_handler', None) if current_scene else None
        if not jack_handler:
            return
        jack_handler = current_scene.jack_connection_handler
        for port_item in list(self.output_ports.values()): # Iterate copy
            if not port_item: continue
            for conn_item in list(port_item.connections): # Iterate copy
                if conn_item and conn_item.source_port and conn_item.dest_port:
                    try:
                        jack_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name)
                    except Exception as e:
                        logger.error(f"Error breaking output connection for {port_item.port_name} of {self.client_name}: {e}")

    def check_if_virtual_sink(self, client_name: str) -> None:
        self.unify_handler.classify_node(client_name)

    def _get_sink_base_name(self) -> str:
        """Get the base sink name (without JACK suffix) for config lookups."""
        from cables.unified_sink_manager import _strip_sink_suffix
        return _strip_sink_suffix(self.client_name)

    def _get_config_manager(self):
        """Get ConfigManager from the scene's connection_manager."""
        scene = self.scene()
        if not scene:
            return None
        cm = getattr(scene, 'connection_manager', None)
        return getattr(cm, 'config_manager', None) if cm else None

    def _is_recreate_at_autostart(self) -> bool:
        """Check if this virtual sink is marked for recreation at auto-start."""
        import json
        config = self._get_config_manager()
        if not config:
            return False
        try:
            data = json.loads(config.get_str(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, '{}') or '{}')
            return self.client_name in data
        except (json.JSONDecodeError, Exception):
            return False

    def _toggle_recreate_at_autostart(self, checked: bool) -> None:
        """Toggle the 'recreate at auto-start' setting for this virtual sink."""
        import json
        config = self._get_config_manager()
        if not config:
            return
        try:
            data = json.loads(config.get_str(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, '{}') or '{}')
            if checked:
                sink_name = self._get_sink_base_name()
                channel_map = self._detect_channel_map(sink_name)
                data[self.client_name] = {'sink_name': sink_name, 'channel_map': channel_map}
            else:
                data.pop(self.client_name, None)
            config.set_str(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, json.dumps(data))
            self.update()
        except Exception as e:
            logger.error(f"Error toggling recreate-at-autostart for {self.client_name}: {e}")

    def _detect_channel_map(self, sink_name: str) -> str:
        """Detect the channel map of a running sink via pactl."""
        import subprocess
        try:
            result = subprocess.run(
                ['pactl', 'list', 'sinks'],
                capture_output=True, text=True, check=True
            )
            in_target_sink = False
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith('Name:') and stripped.split(':', 1)[1].strip() == sink_name:
                    in_target_sink = True
                elif stripped.startswith('Name:'):
                    in_target_sink = False
                elif in_target_sink and stripped.startswith('Channel Map:'):
                    return stripped.split(':', 1)[1].strip().replace(' ', '')
        except Exception as e:
            logger.warning(f"Could not detect channel map for {sink_name}: {e}")
        return 'front-left,front-right'

    def _get_pw_node_id(self) -> Optional[int]:
        """Resolve the PipeWire node ID for this virtual sink via pw-dump."""
        import subprocess as _sp
        import re

        # Extract PipeWire node ID from JACK client name suffix
        m = re.search(r'-(\d+)$', self.client_name)
        target_node_id = int(m.group(1)) if m else None

        sink_base_name = self._get_sink_base_name()

        # Check for Flatpak environment
        flatpak_env = os.path.exists('/.flatpak-info')
        cmd = ['pw-dump']
        if flatpak_env:
            cmd = ['flatpak-spawn', '--host'] + cmd

        try:
            result = _sp.run(
                cmd, capture_output=True, text=True, check=True
            )
            import json as _json
            data = _json.loads(result.stdout)
            
            matching_nodes = []
            
            for node in data:
                if node.get('type') != 'PipeWire:Interface:Node':
                    continue
                
                node_id = int(node['id'])
                props = node.get('info', {}).get('props', {})
                
                # If we have a target node ID from suffix, use it to exactly match the node
                if target_node_id is not None and node_id == target_node_id:
                    return node_id
                    
                # Original fallback exact match
                if props.get('node.description') == self.client_name:
                    return node_id
                    
                # Match by base sink name
                if props.get('node.name') == sink_base_name:
                    serial = int(props.get('object.serial', 0))
                    matching_nodes.append((serial, node_id))
            
            if target_node_id is None and matching_nodes:
                # No suffix -> we want the primary node. PipeWire assigns the lowest serial
                # to the first-created node. Pick the node with the lowest serial.
                matching_nodes.sort(key=lambda x: x[0])
                return matching_nodes[0][1]
                
        except Exception as e:
            logger.error(f"Error resolving PipeWire node ID for '{self.client_name}': {e}")
        return None

    def _is_default_sink(self) -> bool:
        """Check if this virtual sink is currently the default audio sink."""
        import subprocess as _sp
        node_id = self._get_pw_node_id()
        if node_id is None:
            return False

        # Check for Flatpak environment
        flatpak_env = os.path.exists('/.flatpak-info')
        cmd = ['wpctl', 'inspect', '@DEFAULT_AUDIO_SINK@']
        if flatpak_env:
            cmd = ['flatpak-spawn', '--host'] + cmd

        try:
            result = _sp.run(
                cmd,
                capture_output=True, text=True, check=True
            )
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith('id '):
                    current_id = stripped.split(',')[0].split()[-1].strip()
                    return str(node_id) == current_id
        except Exception as e:
            logger.error(f"Error checking default sink status: {e}")
        return False

    def _toggle_default_sink(self, checked: bool) -> None:
        """Set or clear this virtual sink as the default audio sink."""
        import subprocess as _sp
        node_id = self._get_pw_node_id()
        if node_id is None:
            logger.error(f"Cannot toggle default: failed to resolve PipeWire ID for '{self.client_name}'")
            return

        # Check for Flatpak environment
        flatpak_env = os.path.exists('/.flatpak-info')

        try:
            if checked:
                cmd = ['wpctl', 'set-default', str(node_id)]
                if flatpak_env:
                    cmd = ['flatpak-spawn', '--host'] + cmd
                _sp.run(cmd,
                        check=True, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                logger.info(f"Set default sink to '{self.client_name}' (ID {node_id})")
            else:
                cmd = ['wpctl', 'clear-default', '0']
                if flatpak_env:
                    cmd = ['flatpak-spawn', '--host'] + cmd
                _sp.run(cmd,
                        check=True, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                logger.info(f"Cleared default audio sink (was '{self.client_name}')")
        except Exception as e:
            logger.error(f"Error toggling default sink for '{self.client_name}': {e}")
