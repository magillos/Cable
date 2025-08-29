# --- PyQt Graphical Items - PortItem ---
# Removed re and traceback as they are not used directly by PortItem.
# re is used by natural_sort_key in node_item.py
# traceback is used by NodeItem in node_item.py

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QGraphicsPathItem, QMenu,
    QStyleOptionGraphicsItem, QWidget, QStyle, QGraphicsSceneHoverEvent # Import QStyle and QGraphicsSceneHoverEvent
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QAction, QPolygonF,
    QFontMetrics, QPalette # Import QFontMetrics
)
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QLineF, QEvent, QSize # Import QSize
)

from . import constants # Import the new constants module
# Note: JackHandler is needed for context menu actions within PortItem
# We'll need to pass it in or access it via the scene later.

# Forward declaration for type hinting
# from node_item import NodeItem # Avoid circular import here, use string literal
# from connection_item import ConnectionItem # Avoid circular import here, use string literal


class PortItem(QGraphicsItem):
    """Represents a single input or output port on a NodeItem."""
    def __init__(self, parent_node: 'NodeItem', port_name, port_obj, is_input):
        super().__init__(parent_node)
        self.parent_node = parent_node
        self.port_name = port_name
        self.port_obj = port_obj  # Store the JACK port object
        self.short_name = port_obj.shortname # Correct attribute name
        self.is_input = is_input
        self.connections = [] # List of ConnectionItems attached

        # Calculate the width needed for this specific port based on text length
        self.calculated_width = self._calculate_required_width()

        # Initialize with default rect - will be updated in calculate_layout
        self._bounding_rect = QRectF(0, 0, self.calculated_width, constants.PORT_HEIGHT)
        self._is_drag_highlighted = False # Flag for external highlight during drag
        self._mouse_press_pos = None # Store initial press position for drag threshold
        self._is_handling_selection_change = False # Flag to prevent re-entry during selection cascade
        self.is_midi = hasattr(port_obj, 'is_midi') and port_obj.is_midi # Store is_midi

        # Determine type for color coding
        if self.is_midi:
            self.port_color = constants.PORT_MIDI_COLOR
        elif hasattr(port_obj, 'is_audio') and port_obj.is_audio: # Check for audio if not MIDI
            self.port_color = constants.PORT_AUDIO_COLOR
        else:
            # Fallback for ports that are neither explicitly audio nor MIDI
            self.port_color = constants.PORT_OTHER_COLOR
        # self.port_color = None # Will use palette colors

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable) # Enable selection

    def _calculate_required_width(self):
        """Calculate the minimum width needed to display this port's text properly"""
        font = QFont()
        font.setPointSize(8)  # Match font in paint method
        fm = QFontMetrics(font)

        # Get text width
        text_width = fm.horizontalAdvance(self.short_name)

        # Calculate space needed for indicator and padding
        indicator_size = constants.PORT_HEIGHT * 0.6
        indicator_margin = (constants.PORT_HEIGHT - indicator_size) / 2
        indicator_space = indicator_size + 2 * indicator_margin

        # Total width needed = indicator + padding + text + padding
        required_width = indicator_space + 2 * constants.PORT_LABEL_OFFSET + text_width + 15  # Extra padding

        # Ensure minimum width
        return max(constants.PORT_WIDTH_MIN, required_width)

    def calculate_layout(self, y_pos):
        """Calculates the position and bounding rect based on parent."""
        x_pos = 0 if self.is_input else self.parent_node.boundingRect().width() - self.calculated_width

        # Update internal bounding rect
        self._bounding_rect = QRectF(0, 0, self.calculated_width, constants.PORT_HEIGHT)

        # Update position
        self.setPos(x_pos, y_pos)

        return self._bounding_rect.height() + constants.NODE_VMARGIN

    def boundingRect(self):
        return self._bounding_rect

    def shape(self):
        """Defines the detailed shape used for collision detection and mouse events."""
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Port background / type indicator
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Determine background color
        if is_selected or is_hovered or self._is_drag_highlighted:
            bg_color = option.palette.color(QPalette.ColorRole.Highlight) # Use theme's highlight
        else:
            bg_color = self.port_color # Use type-specific color for default state


        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)

        indicator_size = constants.PORT_HEIGHT * 0.6
        indicator_margin = (constants.PORT_HEIGHT - indicator_size) / 2
        if self.is_input:
            indicator_rect = QRectF(indicator_margin, indicator_margin, indicator_size, indicator_size)
            painter.drawEllipse(indicator_rect)
        else:
            # For output ports, indicator is on the right side of the port's area
            indicator_rect = QRectF(self.boundingRect().width() - indicator_size - indicator_margin,
                                   indicator_margin, indicator_size, indicator_size)
            painter.drawRect(indicator_rect)

        # Port Label
        # painter.setPen(constants.PORT_TEXT_COLOR) # Use theme text color
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        if self.is_input:
            # For input ports: start after the indicator + padding
            text_x = indicator_size + indicator_margin * 2 + constants.PORT_LABEL_OFFSET
            text_width = self.boundingRect().width() - text_x - constants.PORT_LABEL_OFFSET
            text_rect = QRectF(text_x, 0, text_width, constants.PORT_HEIGHT)
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        else:
            # For output ports: end before the indicator - padding
            text_width = self.boundingRect().width() - (indicator_size + indicator_margin * 2) - constants.PORT_LABEL_OFFSET*2
            text_rect = QRectF(constants.PORT_LABEL_OFFSET, 0, text_width, constants.PORT_HEIGHT)
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        # Draw the full text - no elision
        painter.drawText(text_rect, align, self.short_name)

        # Draw selection outline if selected
        if is_selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(constants.SELECTION_BORDER_COLOR, 1.5))
            painter.drawRect(self.boundingRect())

    def get_connection_point(self):
        """Return the scene coordinates for the connection.
        If the parent node is folded, this will be a point on the node's header.
        Otherwise, it's the center of the port's connection indicator.
        """
        parent = self.parent_node
        is_effectively_folded = False
        if parent:
            if parent.is_split_part:
                # This port is on a split part. Check the part's specific fold state.
                if self.is_input: # PortItem's own is_input
                    is_effectively_folded = parent.input_part_folded
                else:
                    is_effectively_folded = parent.output_part_folded
            else:
                # This port is on a normal (unsplit) node. Use its is_folded.
                is_effectively_folded = parent.is_folded

        if parent and is_effectively_folded:
            # Node or part is folded, connections should go to the middle of its header's edge
            parent_header_rect = parent._header_rect # This is in parent_node's coordinates
            # Map this rect to scene coordinates
            scene_header_top_left = self.parent_node.mapToScene(parent_header_rect.topLeft())
            scene_header_bottom_right = self.parent_node.mapToScene(parent_header_rect.bottomRight())
            scene_header_rect = QRectF(scene_header_top_left, scene_header_bottom_right)

            if self.is_input:
                # Connect to the middle of the left edge of the header
                return QPointF(scene_header_rect.left(), scene_header_rect.center().y())
            else:
                # Connect to the middle of the right edge of the header
                return QPointF(scene_header_rect.right(), scene_header_rect.center().y())
        else:
            # Node is not folded, use the port's actual indicator
            center_y = self.boundingRect().height() / 2
            if self.is_input:
                center_x = constants.PORT_HEIGHT / 2 # Center of the circle indicator
            else:
                center_x = self.boundingRect().width() - (constants.PORT_HEIGHT / 2) # Center of the square indicator on right
            return self.mapToScene(QPointF(center_x, center_y))

    def itemChange(self, change, value):
        """Update connection lines when the port (node) moves and handle selection synchronization."""
        if change == QGraphicsItem.GraphicsItemChange.ItemScenePositionHasChanged:
            for conn in self.connections:
                conn.update_path()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # value is True if selected, False if deselected

            # Update connected lines' appearance
            for conn_item in self.connections:
                conn_item.update() # Trigger repaint of the connection

            if self.scene() and hasattr(self.scene(), 'interaction_handler') and self.parent_node:
                handler = self.scene().interaction_handler

                # If GraphInteractionHandler is doing a batch selection, only do basic selection.
                if handler._processing_selection:
                    return super().itemChange(change, value)

                # Prevent re-entry for this specific port's selection change processing
                if self._is_handling_selection_change:
                    return super().itemChange(change, value)

                self._is_handling_selection_change = True
                try:
                    # Determine if this level can propagate port-to-port selection
                    can_propagate_port_to_port = False
                    if not handler._is_in_auto_selection_cascade:
                        can_propagate_port_to_port = True
                        handler._is_in_auto_selection_cascade = True
                    
                    try:
                        if can_propagate_port_to_port:
                            # 1. Port-to-Port selection cascade
                            if value: # Current port (self) is being SELECTED
                                ports_to_potentially_select = []
                                for conn in self.connections:
                                    other_port = conn.source_port if conn.dest_port == self else conn.dest_port
                                    if other_port and not other_port.isSelected():
                                        ports_to_potentially_select.append(other_port)
                                for p_to_select in ports_to_potentially_select:
                                    p_to_select.setSelected(True) # This will trigger itemChange on other_port

                            else: # Current port (self) is being DESELECTED
                                ports_to_potentially_deselect = []
                                for conn in self.connections:
                                    other_port = conn.source_port if conn.dest_port == self else conn.dest_port
                                    if other_port and other_port.isSelected():
                                        should_other_remain_selected = False
                                        for other_conn in other_port.connections:
                                            port_at_far_end_of_other_conn = None
                                            if other_conn.source_port == other_port:
                                                port_at_far_end_of_other_conn = other_conn.dest_port
                                            else:
                                                port_at_far_end_of_other_conn = other_conn.source_port
                                            
                                            if port_at_far_end_of_other_conn and \
                                               port_at_far_end_of_other_conn != self and \
                                               port_at_far_end_of_other_conn.isSelected():
                                                should_other_remain_selected = True
                                                break
                                        if not should_other_remain_selected:
                                            ports_to_potentially_deselect.append(other_port)
                                for p_to_deselect in ports_to_potentially_deselect:
                                    p_to_deselect.setSelected(False) # This will trigger itemChange on other_port
                        # If not can_propagate_port_to_port, the above block is skipped, preventing cascade.
                    finally:
                        # Reset the flag only if this level was the one that set it.
                        if can_propagate_port_to_port: # This implies it was False before, and this level set it to True.
                            handler._is_in_auto_selection_cascade = False
                    # End of controlled port-to-port cascade. The original empty line (256) is now covered.

                    # 2. Update parent BulkAreaItem's selection state
                    bulk_area_to_update = None
                    sibling_ports_map = {}
                    if self.is_input:
                        bulk_area_to_update = self.parent_node.input_area_item
                        sibling_ports_map = self.parent_node.input_ports
                    else:
                        bulk_area_to_update = self.parent_node.output_area_item
                        sibling_ports_map = self.parent_node.output_ports

                    if bulk_area_to_update:
                        all_siblings_selected = True
                        if not sibling_ports_map:
                            all_siblings_selected = False
                        else:
                            for port in sibling_ports_map.values():
                                if not port.isSelected():
                                    all_siblings_selected = False
                                    break
                        
                        if bulk_area_to_update.isSelected() != all_siblings_selected:
                            # This will trigger BulkAreaItem.itemChange, which will then handle
                            # its own cascades (to its ports and other bulk areas)
                            bulk_area_to_update.setSelected(all_siblings_selected)
                finally:
                    self._is_handling_selection_change = False
            
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        """Handle selection and start potential drag connection."""
        # Let selection run first
        super().mousePressEvent(event)

        # Store press position if it's a left click for potential drag start by scene
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_press_pos = event.pos()
            print(f"PortItem mousePress: Stored press pos {self._mouse_press_pos} for scene. Event accepted by super: {event.isAccepted()}")
        else:
            self._mouse_press_pos = None
        # Do not accept the event here, let it propagate fully


    # Remove mouseMoveEvent and mouseReleaseEvent overrides - scene handles drag initiation
    # def mouseMoveEvent(self, event): ...
    # def mouseReleaseEvent(self, event): ...

    def contextMenuEvent(self, event):
        """Show context menu to disconnect."""
        menu = QMenu()
        # Accessing the scene and then the handler is necessary here.
        # This implies either the scene needs to be passed around,
        # or the handler needs to be accessible globally or via the application instance.
        # For now, assume scene() provides access.
        # Access self.parent_node.scene().jack_connection_handler
        current_scene = self.parent_node.scene()
        if not self.parent_node or not current_scene or \
           not hasattr(current_scene, 'jack_connection_handler') or \
           not current_scene.jack_connection_handler or \
           not hasattr(current_scene, 'graph_jack_handler') or \
           not current_scene.graph_jack_handler: # Also keep graph_jack_handler for get_all_connections
            action = menu.addAction("Error: Cannot access JACK handlers")
            action.setEnabled(False)
            menu.exec(event.screenPos())
            return

        query_handler = current_scene.graph_jack_handler # For querying connections
        connection_handler = current_scene.jack_connection_handler # For performing disconnections

        connections = query_handler.get_all_connections(self.port_name)

        if not connections:
            action = menu.addAction("No connections")
            action.setEnabled(False)
        else:
            for out_port_name, in_port_name in connections:
                other_port_name = out_port_name if self.is_input else in_port_name
                other_short_name = other_port_name.split(':')[-1]
                client_name = other_port_name.split(':')[0]

                action_text = f"Disconnect from {other_short_name} ({client_name})"
                action = QAction(action_text, menu)
                
                # Determine if the connection being broken is MIDI or Audio
                # We assume the current port (self) determines the type of its connections.
                is_conn_midi = self.is_midi

                # Use lambda to capture current loop variables
                action.triggered.connect(
                    lambda checked=False, op=out_port_name, ip=in_port_name, midi=is_conn_midi:
                        connection_handler.break_midi_connection(op, ip) if midi else connection_handler.break_connection(op, ip)
                )
                menu.addAction(action)

        menu.exec(event.screenPos())


    def set_drag_highlight(self, highlighted: bool):
        """Externally set the highlight state, e.g., during connection drag."""
        if self._is_drag_highlighted != highlighted:
            self._is_drag_highlighted = highlighted
            self.update() # Trigger repaint
