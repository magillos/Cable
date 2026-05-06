# --- PyQt Graphical Items - ConnectionItem ---
"""
QGraphicsPathItem representing a visual connection line between two ports.
"""

from PyQt6.QtWidgets import (
    QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget, QStyle
)
from PyQt6.QtGui import (
    QPainter, QPen, QPainterPath, QPalette, QColor
)
from PyQt6.QtCore import (
    Qt, QPointF
)

from cable_core import config_keys as keys

from . import constants # Import the new constants module

# Forward declaration for type hinting
# from port_item import PortItem # Avoid circular import here, use string literal


class ConnectionItem(QGraphicsPathItem):
    """A bezier curve connecting two PortItems."""
    def __init__(self, source_port: 'PortItem', dest_port: 'PortItem', client_color: QColor | None = None) -> None:
        super().__init__()
        self.source_port = source_port
        self.dest_port = dest_port
        self._client_color = client_color

        # Add this connection to the ports' lists
        self.source_port.connections.append(self)
        self.dest_port.connections.append(self)

        # Store base pen properties, paint method will adjust width/color
        self.setPen(QPen(Qt.GlobalColor.black, constants.CONNECTION_WIDTH)) # Placeholder, will be overridden in paint
        self.setZValue(-1) # Draw behind nodes/ports

        self.update_path()

    def update_path(self) -> None:
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
        
        c1x = p1.x() + dx * connection_factor
        c1y = p1.y()
        c2x = p2.x() - dx * connection_factor
        c2y = p2.y()

        path.cubicTo(c1x, c1y, c2x, c2y, p2.x(), p2.y())
        self.setPath(path)

    def _get_line_thickness(self) -> float:
        """Get connection line thickness from config, falling back to constants."""
        scene = self.scene()
        config_mgr = getattr(scene, 'main_config_manager', None) if scene else None
        if config_mgr is not None:
            return config_mgr.get_int_setting(
                keys.CONNECTION_LINE_THICKNESS, constants.CONNECTION_WIDTH)
        return constants.CONNECTION_WIDTH

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        """Paints the connection, highlighting if connected ports are selected."""
        is_highlighted = False
        if self.source_port and self.source_port.isSelected():
            is_highlighted = True
        if self.dest_port and self.dest_port.isSelected():
            is_highlighted = True

        width = self._get_line_thickness()
        highlight_width = width * 2

        if is_highlighted:
            highlight_color = constants.CONNECTION_HIGHLIGHT_COLOR
            current_pen = QPen(highlight_color, highlight_width)
        elif self._client_color is not None:
            current_pen = QPen(self._client_color, width)
        else:
            base_color = constants.CONNECTION_COLOR
            current_pen = QPen(base_color, width)

        painter.setPen(current_pen)
        painter.drawPath(self.path())

    def destroy(self) -> None:
        """Remove connection from ports and scene."""
        if self.source_port and self in self.source_port.connections:
             self.source_port.connections.remove(self)
        if self.dest_port and self in self.dest_port.connections:
             self.dest_port.connections.remove(self)
        if self.scene():
             self.scene().removeItem(self)
        self.source_port = None # Break references
        self.dest_port = None
