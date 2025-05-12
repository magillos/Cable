# --- PyQt Graphical Items - ConnectionItem ---

from PyQt6.QtWidgets import (
    QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget, QStyle
)
from PyQt6.QtGui import (
    QPainter, QPen, QPainterPath, QPalette
)
from PyQt6.QtCore import (
    Qt, QPointF
)

from . import constants # Import the new constants module

# Forward declaration for type hinting
# from port_item import PortItem # Avoid circular import here, use string literal


class ConnectionItem(QGraphicsPathItem):
    """A bezier curve connecting two PortItems."""
    def __init__(self, source_port: 'PortItem', dest_port: 'PortItem'):
        super().__init__()
        self.source_port = source_port
        self.dest_port = dest_port

        # Add this connection to the ports' lists
        self.source_port.connections.append(self)
        self.dest_port.connections.append(self)

        # Store base pen properties, paint method will adjust width/color
        # self._base_pen = QPen(constants.CONNECTION_COLOR, constants.CONNECTION_WIDTH)
        # self._highlight_pen = QPen(constants.CONNECTION_HIGHLIGHT_COLOR, constants.CONNECTION_HIGHLIGHT_WIDTH)
        # Pens will be created in paint() using palette colors
        self.setPen(QPen(Qt.GlobalColor.black, constants.CONNECTION_WIDTH)) # Placeholder, will be overridden in paint
        self.setZValue(-1) # Draw behind nodes/ports

        self.update_path()

    def update_path(self):
        """Recalculates the bezier curve path based on port positions."""
        if not self.source_port or not self.dest_port: return # Port removed?

        p1 = self.source_port.get_connection_point()
        p2 = self.dest_port.get_connection_point()

        path = QPainterPath()
        path.moveTo(p1)

        # Determine the connection factor
        # A self-connection is when source and destination ports belong to the same node item
        is_self_connection = (self.source_port.parent_node == self.dest_port.parent_node)
        
        connection_factor = constants.SELF_CONNECTION_FACTOR if is_self_connection else constants.DEFAULT_CONNECTION_FACTOR

        # Control points for bezier curve
        dx = abs(p1.x() - p2.x())
        
        # This is the robust logic for control points:
        # c1x will be offset from p1.x by (dx * connection_factor)
        # c2x will be offset from p2.x by -(dx * connection_factor)
        # This creates a symmetrical curve.
        # If p1.x < p2.x (standard left to right):
        #   c1x = p1.x + offset (moves right from p1)
        #   c2x = p2.x - offset (moves left from p2)
        # If p1.x > p2.x (loop back, e.g. self-connection from output on right to input on left):
        #   dx is still positive.
        #   c1x = p1.x + offset (moves further right from p1, creating the outward loop)
        #   c2x = p2.x - offset (moves further left from p2, creating the outward loop)
        
        c1x = p1.x() + dx * connection_factor
        c1y = p1.y()
        c2x = p2.x() - dx * connection_factor # Note the minus sign here is key
        c2y = p2.y()

        path.cubicTo(c1x, c1y, c2x, c2y, p2.x(), p2.y())
        self.setPath(path)

    # --- Add this method ---
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        """Paints the connection, highlighting if connected ports are selected."""
        is_highlighted = False
        # Check source_port validity before accessing isSelected()
        if self.source_port and self.source_port.isSelected():
            is_highlighted = True
        # Check dest_port validity before accessing isSelected()
        if self.dest_port and self.dest_port.isSelected():
            is_highlighted = True

        # Create pens dynamically using palette colors
        palette = option.palette if option else self.scene().palette() # Get palette from option or scene

        if is_highlighted:
            # current_pen = self._highlight_pen
            highlight_color = palette.color(QPalette.ColorRole.Highlight)
            current_pen = QPen(highlight_color, constants.CONNECTION_HIGHLIGHT_WIDTH)
        else:
            # current_pen = self._base_pen
            base_color = palette.color(QPalette.ColorRole.Link) # Use Link color for connections
            current_pen = QPen(base_color, constants.CONNECTION_WIDTH)

        painter.setPen(current_pen)
        painter.drawPath(self.path()) # Draw the path with the selected pen

        # Optionally, draw selection highlight if the connection itself is selected
        # if option.state & QStyle.StateFlag.State_Selected:
        #     painter.setPen(QPen(constants.SELECTION_BORDER_COLOR, 1, Qt.PenStyle.DashLine))
        #     painter.drawPath(self.shape()) # Draw outline using shape
    # --- End Add ---

    # --- Ensure this method is correctly indented ---
    def destroy(self):
        """Remove connection from ports and scene."""
        # Check source_port validity before accessing connections
        if self.source_port and self in self.source_port.connections:
             self.source_port.connections.remove(self)
        # Check dest_port validity before accessing connections
        if self.dest_port and self in self.dest_port.connections:
             self.dest_port.connections.remove(self)
        if self.scene():
             self.scene().removeItem(self)
        self.source_port = None # Break references
        self.dest_port = None