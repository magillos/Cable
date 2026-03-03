from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from PyQt6.QtGui import (QPolygonF, QFont, QColor, QPainter, QPen, QBrush, 
                         QPalette, QPainterPath, QLinearGradient)

from typing import TYPE_CHECKING, Optional, Any, Union, List, Tuple, Dict

if TYPE_CHECKING:
    from PyQt6.QtGui import QEvent
    from cables.ui.midi_matrix_widget import MIDIMatrixWidget

"""
Internal widget that handles the actual matrix rendering and interaction.
"""

class _MatrixGridWidget(QWidget):
    def __init__(self, parent_matrix: MIDIMatrixWidget) -> None:
        """
        Initialize the matrix grid widget.

        Args:
            parent_matrix: The parent MIDIMatrixWidget instance
        """
        super().__init__()
        self.parent_matrix = parent_matrix
        self.column_positions: List[int] = []
        self.column_widths: List[int] = []
        self.row_positions: List[int] = []
        self.row_heights: List[int] = []
        self.total_width: int = 0
        self.grid_width: int = 0
        self.grid_height: int = 0
        self.input_client_port_counts: Dict[str, int] = {}
        self.output_client_port_counts: Dict[str, int] = {}

        # Layout parameters - cell_size is now dynamic
        self.base_cell_width: int = 24  # Base width per port
        self.font_size: int = int(self.parent_matrix.zoom_level)
        self.client_name_font_size: int = int(self.parent_matrix.zoom_level) + 2
        self.grid_cell_scaling: float = self.parent_matrix._calculate_grid_scaling(self.parent_matrix.zoom_level)

        # Margins for labels - reduced since all labels are now in separate panels
        self.top_margin: int = 10    # Minimal space at top
        self.left_margin: int = 10   # Minimal space on left (grid starts immediately)
        self.bottom_margin: int = 120 # Minimal space at bottom (input labels are separate)
        self.right_margin: int = 20

        # Drag selection state
        self.is_dragging: bool = False
        self.drag_start_pos: Optional['QPoint'] = None
        self.drag_end_pos: Optional['QPoint'] = None
        self.selected_rect: QRect = QRect()  # Rectangle for visual feedback

        # Hover selection state
        self.hover_row = -1
        self.hover_col = -1
        self.setMouseTracking(True)

        # Set size policy to allow expansion to fill available space
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Set minimum size
        self.update_matrix()

    def update_matrix(self) -> None:
        """Update the matrix dimensions and trigger repaint."""
        output_count = len(self.parent_matrix.model.output_ports)
        input_count = len(self.parent_matrix.model.input_ports)

        # Calculate dynamic column widths and row heights based on text measurements
        self._calculate_sizes_from_text()

        # Calculate total dimensions
        total_height = sum(self.row_heights) if hasattr(self, 'row_heights') else (output_count * self.cell_height)
        total_width = getattr(self, 'total_width', 0)

        # Set minimum size based on content
        min_height = self.top_margin + total_height + self.bottom_margin

        # If the calculated total_width is very small (i.e., there are no input ports),
        # we set the minimum width to 0. When combined with the Expanding size policy,
        # this allows the widget to grow to fill the available space within the splitter,
        # preventing it from collapsing to a small fixed width.
        min_width = total_width
        if min_width < 50:  # A small threshold to detect when there's no content
            min_width = 0

        self.setMinimumSize(min_width, min_height)
        self.updateGeometry()
        
        # Set size policy to allow expansion
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.update()

    def _calculate_sizes_from_text(self) -> None:
        """Calculate label positions, sizes, and grid dimensions for perfect alignment."""
        from collections import defaultdict
        import math

        # Create font objects for measurements
        client_font = QFont()
        client_font.setPointSize(self.client_name_font_size)
        client_font.setBold(True)

        port_font = QFont()
        port_font.setPointSize(self.font_size)

        # Create a temporary painter for text measurements
        painter = QPainter(self)

        # Group ports by client and count ports to support grouped labels
        input_client_groups = defaultdict(list)
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.model.input_ports):
            input_client_groups[client_name].append((i, port_name, display_name))

        # Also precompute how many ports each input client has
        input_client_port_counts = {
            client: len(ports) for client, ports in input_client_groups.items()
        }
        self.input_client_port_counts = input_client_port_counts

        output_client_groups = defaultdict(list)
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.model.output_ports):
            output_client_groups[client_name].append((i, port_name, display_name))

        # Also precompute how many ports each output client has
        output_client_port_counts = {
            client: len(ports) for client, ports in output_client_groups.items()
        }
        self.output_client_port_counts = output_client_port_counts

        # Calculate row heights and positions based on output labels (left side)
        self.row_heights = []
        self.row_positions = []  # Y positions for each row
        current_y = self.top_margin

        # Pre-calculate client heights
        client_heights = {}
        painter.setFont(client_font)
        for client_name in output_client_groups.keys():
            client_rect = painter.boundingRect(0, 0, 1000, 100, Qt.AlignmentFlag.AlignLeft, _truncate_text(client_name, 20))
            client_heights[client_name] = client_rect.height() + 4  # Padding

        # Calculate port heights and combined heights
        painter.setFont(port_font)
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.model.output_ports):
            port_rect = painter.boundingRect(0, 0, 1000, 100, Qt.AlignmentFlag.AlignLeft, _truncate_text(display_name, 20))
            port_height = port_rect.height() + 4  # Padding

            client_height = client_heights[client_name]

            # Row height to accommodate both client and port
            min_row_height = int(35 * self.grid_cell_scaling)  # Scale minimum row height with zoom
            row_height = max(client_height + port_height + 8, min_row_height)  # Minimum scaled for clickability

            self.row_heights.append(row_height)
            self.row_positions.append(current_y)
            current_y += row_height

        # Calculate column widths and positions based on rotated input labels (bottom)
        self.column_widths = []
        self.column_positions = []  # X positions for each column
        current_x = self.left_margin

        # Pre-calculate client rects
        client_rects = {}
        painter.setFont(client_font)
        for client_name in input_client_groups.keys():
            client_rects[client_name] = painter.boundingRect(0, 0, 1000, 100, Qt.AlignmentFlag.AlignLeft, _truncate_text(client_name, 25))

        # Calculate port widths and combined widths
        painter.setFont(port_font)
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.model.input_ports):
            port_rect = painter.boundingRect(0, 0, 1000, 100, Qt.AlignmentFlag.AlignLeft, _truncate_text(display_name, 25))
            client_rect = client_rects[client_name]

            # Labels are vertical, so width is max, and height is sum
            unrotated_width = max(client_rect.width(), port_rect.width())
            unrotated_height = client_rect.height() + port_rect.height() - 4

            # Approximate width for 45-degree rotation
            rotated_width = (unrotated_width + unrotated_height) * 0.707 + 15  # Padding

            min_column_width = int(35 * self.grid_cell_scaling)  # Scale minimum column width with zoom
            column_width = max(rotated_width, min_column_width)  # Minimum scaled for clickability

            self.column_widths.append(column_width)
            self.column_positions.append(current_x)
            current_x += column_width

        painter.end()

        # Calculate grid dimensions
        self.grid_width = sum(self.column_widths) if self.column_widths else 0
        self.grid_height = sum(self.row_heights) if self.row_heights else 0
        self.total_width = self.left_margin + self.grid_width + self.right_margin
        self.total_height = self.top_margin + self.grid_height + self.bottom_margin

        # Fallback if calculations failed - use scaled minimum sizes
        min_scaled_size = int(35 * self.grid_cell_scaling)
        if not self.column_widths:
            self.column_widths = [min_scaled_size] * len(self.parent_matrix.model.input_ports)
            self.column_positions = [self.left_margin + i * min_scaled_size for i in range(len(self.parent_matrix.model.input_ports))]
        if not self.row_heights:
            self.row_heights = [min_scaled_size] * len(self.parent_matrix.model.output_ports)
            self.row_positions = [self.top_margin + i * min_scaled_size for i in range(len(self.parent_matrix.model.output_ports))]

    @property
    def cell_height(self) -> int:
        """Get the fixed height for each row (output port)."""
        return self.base_cell_width  # Keep rows at fixed height for now

    @property
    def cell_size(self) -> int:
        """Backward compatibility - return base cell width."""
        return self.base_cell_width

    def paintEvent(self, event: Optional['QEvent']) -> None:
        """Paint the matrix grid."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Save painter state
        painter.save()

        # Get widget dimensions
        width = self.width()
        height = self.height()

        # Define regions - ensure grid fills available space
        available_width = width - self.left_margin - self.right_margin
        grid_width = getattr(self, 'grid_width', 0)

        # Use full available width for drawing even if content is smaller
        grid_rect = QRect(
            self.left_margin,
            self.top_margin,
            max(available_width, grid_width),
            height - self.top_margin - self.bottom_margin,
        )

        # Draw background
        painter.fillRect(self.rect(), self.parent_matrix.connection_manager.background_color)

        # Draw input labels first (underneath squares)
        self._draw_input_labels(painter)

        # Draw grid
        self._draw_grid(painter, grid_rect)

        # Draw connection squares
        self._draw_connection_squares(painter, grid_rect)

        # Draw connection guide lines for existing connections so users
        # can visually follow which ports a highlighted cell represents.
        self._draw_connection_guides(painter, grid_rect)

        # Draw selection rectangle / drag arrow if dragging
        if self.is_dragging and not self.selected_rect.isEmpty():
            self._draw_selection_rectangle(painter)

        # Restore painter state
        painter.restore()



    def _draw_grid(self, painter: QPainter, grid_rect: QRect) -> None:
        """Draw the grid lines using pre-calculated positions."""
        painter.setPen(QPen(QColor(200, 200, 200), self.parent_matrix.style_config.grid_line_width))

        # Calculate the bottom y-coordinate for the grid content
        grid_bottom_y = self.row_positions[-1] + self.row_heights[-1] if self.row_positions and self.row_heights else grid_rect.bottom()

        # Calculate the right x-coordinate for the grid content
        grid_right_x = self.left_margin
        if self.column_positions and self.column_widths:
            grid_right_x = self.column_positions[-1] + self.column_widths[-1]

        # Vertical lines (columns) - using pre-calculated column positions
        for col_x in self.column_positions:
            painter.drawLine(col_x, grid_rect.top(), col_x, grid_bottom_y)

        # Draw final right boundary of content
        painter.drawLine(grid_right_x, grid_rect.top(), grid_right_x, grid_bottom_y)

        # Horizontal lines (rows) - using pre-calculated row positions
        for row_y in self.row_positions:
            painter.drawLine(self.left_margin, row_y, grid_right_x, row_y)

        # Draw final bottom boundary of content
        painter.drawLine(self.left_margin, grid_bottom_y, grid_right_x, grid_bottom_y)

    def _are_corresponding(self, name1: str, name2: str) -> bool:
        n1 = name1.lower()
        n2 = name2.lower()

        if n1 == n2:
            return True

        pairs = [
            ("in", "out"),
            ("capture", "playback"),
        ]

        for p1, p2 in pairs:
            if n1.replace(p1, p2) == n2:
                return True
            if n1.replace(p2, p1) == n2:
                return True
        
        return False

    def _draw_connection_squares(self, painter: QPainter, grid_rect: QRect) -> None:
        """Draw the connection status squares using pre-calculated positions."""
        output_ports = self.parent_matrix.model.output_ports
        input_ports = self.parent_matrix.model.input_ports

        # Determine theme-aware colors for unconnected squares
        palette = self.palette()
        is_dark_mode = palette.color(QPalette.ColorRole.Window).lightness() < 128
        style_config = self.parent_matrix.style_config

        if is_dark_mode:
            # Darker background for dark mode to provide contrast
            disconnected_color = QColor(*style_config.disconnected_square_color_dark)
            self_connection_color = QColor(*style_config.self_connection_square_color_dark)
            hover_highlight_color = QColor(*style_config.hover_highlight_square_color_dark)
        else:
            # Lighter background for light mode
            disconnected_color = QColor(*style_config.disconnected_square_color_light)
            self_connection_color = QColor(*style_config.self_connection_square_color_light)
            hover_highlight_color = QColor(*style_config.hover_highlight_square_color_light)

        for col, (input_client, input_port, input_display_name) in enumerate(input_ports):
            col_x = self.column_positions[col]
            column_width = self.column_widths[col]

            for row, (output_client, output_port, output_display_name) in enumerate(output_ports):
                row_y = self.row_positions[row]
                row_height = self.row_heights[row]

                # Ensure square fits within available grid width
                square_width = min(column_width - 2, grid_rect.width() - col_x + grid_rect.left() - 2)
                rect = QRect(col_x + 1, row_y + 1, square_width, row_height - 2)

                is_connected = self.parent_matrix.model.is_connected(output_port, input_port)

                is_self_connection_square = (output_client == input_client and self._are_corresponding(output_display_name, input_display_name))

                # Check if this square should be highlighted due to hover (squares leading to hovered square)
                # Only highlight when not dragging (arrow not drawn)
                is_hover_highlighted = (not self.is_dragging and
                                       self.hover_row >= 0 and self.hover_col >= 0 and
                                       ((row == self.hover_row and col <= self.hover_col) or  # same row, left of or at hovered
                                        (col == self.hover_col and row >= self.hover_row)))   # same column, below or at hovered

                # Check if this square should be highlighted due to arrow path during dragging
                is_arrow_highlighted = False
                if self.is_dragging and self.drag_start_pos and self.drag_end_pos:
                    start_row, start_col = self._get_square_at_position(self.drag_start_pos)
                    end_row, end_col = self._get_square_at_position(self.drag_end_pos)
                    if start_row >= 0 and start_col >= 0 and end_row >= 0 and end_col >= 0:
                        arrow_path = self._get_diagonal_path(start_row, start_col, end_row, end_col)
                        is_arrow_highlighted = (row, col) in arrow_path

                if is_connected:
                    # Connected - filled with dark color
                    painter.fillRect(rect, QBrush(QColor(69, 97, 139)))
                elif is_arrow_highlighted:
                    # Arrow highlighted - use special color for squares that will be connected by arrow
                    painter.fillRect(rect, QBrush(hover_highlight_color))
                elif is_hover_highlighted:
                    # Hover highlighted - use special color for squares in same row/column as hovered square
                    painter.fillRect(rect, QBrush(hover_highlight_color))
                elif is_self_connection_square:
                    painter.fillRect(rect, QBrush(self_connection_color))
                else:
                    # Not connected - theme-aware background
                    painter.fillRect(rect, QBrush(disconnected_color))

                # Border
                painter.setPen(QPen(QColor(200, 200, 200), self.parent_matrix.style_config.square_border_width))
                painter.drawRect(rect)

    def _draw_connection_guides(self, painter: QPainter, grid_rect: QRect) -> None:
        """
        Draw subtle guide lines for connected cells from:
          - the center of the connection square
          - to the center of its output label row (left)
          - and to the center of its input label column (bottom)

        This makes it easy to see which ports a highlighted connection square represents,
        especially on large matrices.
        """
        output_ports = self.parent_matrix.model.output_ports
        input_ports = self.parent_matrix.model.input_ports

        if not output_ports or not input_ports:
            return

        # Determine hover target: only emphasize guides for the hovered connected cell.
        hover_row = self.hover_row
        hover_col = self.hover_col

        # Helper function to make color less vibrant
        def make_less_vibrant(color: QColor) -> QColor:
            h, s, v, a = color.getHsv()
            s = max(0, s - 50)  # reduce saturation
            return QColor.fromHsv(h, s, v, a)

        # Iterate through all cells and draw guides only for connected ones
        for col, (input_client, input_port, _) in enumerate(input_ports):
            if col >= len(self.column_positions) or col >= len(self.column_widths):
                continue
            col_x = self.column_positions[col]
            column_width = self.column_widths[col]

            # X position for the connection square center
            cell_center_x = col_x + column_width / 2.0

            for row, (output_client, output_port, _) in enumerate(output_ports):
                if row >= len(self.row_positions) or row >= len(self.row_heights):
                    continue

                if not self.parent_matrix.model.is_connected(output_port, input_port):
                    continue

                row_y = self.row_positions[row]
                row_height = self.row_heights[row]

                # Rect for this connection cell (same as in _draw_connection_squares)
                square_width = min(
                    column_width - 2,
                    grid_rect.width() - col_x + grid_rect.left() - 2,
                )
                cell_rect = QRect(
                    int(col_x + 1),
                    int(row_y + 1),
                    int(square_width),
                    int(row_height - 2),
                )

                # Cell center point
                cell_cx = cell_rect.center().x()
                cell_cy = cell_rect.center().y()

                # Determine if this is the hovered connected cell
                is_hover_cell = (
                    hover_row == row
                    and hover_col == col
                )

                # Get port colors
                output_color = self.parent_matrix.model.client_colors.get(output_client, QColor(Qt.GlobalColor.black))
                input_color = self.parent_matrix.model.client_colors.get(input_client, QColor(Qt.GlobalColor.black))

                # 1 & 2) Draw a rounded path from the output port to the input port
                # passing through the connection cell.
                radius = 10.0
                path = QPainterPath()

                # Define start, end, and corner points for the path
                output_row_center_y = row_y + row_height / 2.0
                grid_bottom_y = (
                    getattr(self, "top_margin", 10)
                    + getattr(self, "grid_height", self.height() - 20)
                )
                input_label_anchor_y = grid_bottom_y + 5

                start_x = self.left_margin / 2.0
                start_y = output_row_center_y

                end_y = input_label_anchor_y

                corner_x = cell_cx
                # corner_y is the same as start_y and cell_cy

                # Build the path with a rounded corner using a quadratic Bezier curve
                path.moveTo(start_x, start_y)
                path.lineTo(corner_x - radius, start_y)
                path.quadTo(corner_x, start_y, corner_x, start_y + radius)
                path.lineTo(corner_x, end_y)

                # Determine line color based on port colors
                if output_color == input_color:
                    line_color = output_color
                else:
                    # Create gradient for different colors
                    line_color = output_color  # Use output color as base, gradient will be applied

                # Adjust for hover state
                if is_hover_cell:
                    # Full vibrant color on hover
                    final_color = line_color
                    line_width = self.parent_matrix.style_config.guide_line_hover_width
                else:
                    # Less vibrant when not hovered
                    final_color = make_less_vibrant(line_color)
                    line_width = self.parent_matrix.style_config.guide_line_width

                # Create pen or brush for gradient
                style_cfg = self.parent_matrix.style_config
                if output_color == input_color:
                    pen = QPen(final_color, line_width, Qt.PenStyle.SolidLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    # Create gradient from output to input color
                    gradient = QLinearGradient(start_x, start_y, corner_x, end_y)
                    gradient.setColorAt(0, final_color if is_hover_cell else make_less_vibrant(output_color))
                    gradient.setColorAt(1, final_color if is_hover_cell else make_less_vibrant(input_color))
                    pen = QPen(QBrush(gradient), line_width, Qt.PenStyle.SolidLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)

                pen.setCosmetic(True)  # keep width consistent regardless of zoom

                # Draw dot at the start of the path (near output labels)
                # Use output color for dot when there's a gradient, otherwise use final_color
                if output_color == input_color:
                    dot_color = final_color
                else:
                    dot_color = output_color if is_hover_cell else make_less_vibrant(output_color)
                self._draw_connection_dot(painter, start_x, start_y, dot_color)

                painter.drawPath(path)

                # Draw arrow head at the end of the path (near input labels)
                # Use input color for arrow head when there's a gradient, otherwise use final_color
                if output_color == input_color:
                    arrow_color = final_color
                else:
                    arrow_color = input_color if is_hover_cell else make_less_vibrant(input_color)
                self._draw_connection_arrowhead(painter, corner_x, end_y, arrow_color)

    def _draw_rotated_text(self, painter: QPainter, text: str, x: float, y: float, font: QFont, color: QColor, is_hovered: bool = False) -> None:
        painter.save()
        current_font = QFont(font)
        if is_hovered:
            current_font.setBold(True)
        painter.setFont(current_font)
        painter.setPen(QPen(color))

        painter.translate(x, y)
        painter.rotate(self.parent_matrix.style_config.input_label_rotation)

        text_rect = painter.boundingRect(QRect(0, -50, 500, 100), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        if is_hovered:
            y = text_rect.bottom() + 1
            painter.drawLine(text_rect.left(), y, text_rect.right(), y)
        
        painter.restore()

    def _draw_input_labels(self, painter: QPainter) -> None:
        """Draw input labels underneath the squares at a 45-degree angle."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        client_font = QFont()
        client_font.setPointSize(self.client_name_font_size)
        client_font.setBold(True)

        port_font = QFont()
        port_font.setPointSize(self.font_size)

        # Access grouped input clients info to draw client name once per group
        input_client_port_counts = getattr(self.parent_matrix.matrix_widget, "input_client_port_counts", {})
        ports = self.parent_matrix.model.input_ports

        idx = 0
        while idx < len(ports):
            client_name, _, _ = ports[idx]
            count = input_client_port_counts.get(client_name, 1)

            # Draw client label on the first (rightmost) port column for this client block.
            first_col_index = idx + count - 1

            for offset in range(count):
                col_index = idx + offset
                if col_index >= len(self.column_positions):
                    break

                _, port_name, display_name = ports[col_index]
                col_x = self.column_positions[col_index]
                column_width = self.column_widths[col_index]
                is_hovered = (col_index == self.hover_col)

                # Common setup for both client and port labels
                grid_bottom_y = getattr(self, 'top_margin', 10) + getattr(self, 'grid_height', self.height() - 20)
                label_start_y = grid_bottom_y + 5  # Adjust margin to be smaller

                painter.save()

                # --- Draw Client Name (only on the rightmost column of this client block) ---
                if col_index == first_col_index:
                    # Position for labels showing clients and ports combo
                    x_pos = col_x + column_width / self.parent_matrix.style_config.input_label_x_pos_factor_client_port
                    painter.translate(x_pos, label_start_y)
                    painter.rotate(self.parent_matrix.style_config.input_label_rotation)

                    current_client_font = QFont(client_font)
                    if is_hovered:
                        current_client_font.setPointSize(self.client_name_font_size + 1)
                    painter.setFont(current_client_font)
                    painter.setPen(QPen(self.parent_matrix.model.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))

                    client_text = client_name.upper()
                    client_text_rect = painter.boundingRect(
                        QRect(0, 0, 500, 100),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                        client_text,
                    )
                    painter.drawText(
                        client_text_rect,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                        client_text,
                    )

                    # --- Draw Port Name (always) ---
                    current_port_font = QFont(port_font)
                    if is_hovered:
                        current_port_font.setBold(True)
                    painter.setFont(current_port_font)
                    painter.setPen(QPen(self.parent_matrix.model.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))

                    # Offset the port name to be below the reserved client label area
                    port_y_start = client_text_rect.height() + self.parent_matrix.style_config.input_label_port_y_offset
                    port_text_rect = QRect(0, port_y_start, 500, 100)
                    painter.drawText(
                        port_text_rect,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                        display_name,
                    )
                else:
                    # Position for labels showing ports only
                    x_pos = col_x + column_width / self.parent_matrix.style_config.input_label_x_pos_factor_ports_only
                    painter.translate(x_pos, label_start_y)
                    painter.rotate(self.parent_matrix.style_config.input_label_rotation)

                    # This is a subsequent port, draw only the port name, centered and shifted.
                    current_port_font = QFont(port_font)
                    if is_hovered:
                        current_port_font.setBold(True)
                    painter.setFont(current_port_font)
                    painter.setPen(QPen(self.parent_matrix.model.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))

                    # No vertical offset, and a slight horizontal shift to the right
                    port_text_rect = QRect(5, 0, 500, 100)  # 5px right
                    painter.drawText(
                        port_text_rect,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                        display_name,
                    )

                painter.restore()

            idx += count

        painter.restore()

    def _draw_selection_rectangle(self, painter: QPainter) -> None:
        """Draw the selection arrow/line during drag operations."""
        if not self.drag_start_pos or not self.drag_end_pos:
            return

        painter.save()

        # Set pen for selection line - bright blue with thickness
        selection_color = QColor(175, 97, 136)  # Royal blue
        selection_pen = QPen(selection_color, self.parent_matrix.style_config.selection_arrow_line_width, Qt.PenStyle.SolidLine)
        painter.setPen(selection_pen)

        # Draw the line from start to end
        start_point = self.drag_start_pos
        end_point = self.drag_end_pos
        painter.drawLine(start_point, end_point)

        # Draw arrowhead at the end
        self._draw_arrowhead(painter, start_point, end_point, selection_color)

        painter.restore()

    def _draw_arrowhead(self, painter: QPainter, start: Union['QPoint', QPointF], end: Union['QPoint', QPointF], color: QColor) -> None:
        """Draw an arrowhead at the end of the selection line."""
        import math

        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(color))

        # Convert to QPointF to ensure floating point precision
        start_f = QPointF(start)
        end_f = QPointF(end)

        # Vector from start to end
        dx = end_f.x() - start_f.x()
        dy = end_f.y() - start_f.y()

        # Length of vector
        length = math.sqrt(dx*dx + dy*dy)
        if length == 0:
            return

        # Unit vector in direction of line
        ux = dx / length
        uy = dy / length

        # Perpendicular vector (left and right wings)
        px = -uy
        py = ux

        # Arrowhead size (fixed, not proportional to line length for simplicity)
        style_config = self.parent_matrix.style_config
        arrowhead_length = style_config.selection_arrowhead_length
        arrowhead_width = style_config.selection_arrowhead_width

        # Arrowhead points (angled backward from the end point)
        arrow_base = QPointF(end_f.x() - arrowhead_length * ux, end_f.y() - arrowhead_length * uy)

        left_wing = QPointF(
            arrow_base.x() + arrowhead_width * px,
            arrow_base.y() + arrowhead_width * py
        )

        right_wing = QPointF(
            arrow_base.x() - arrowhead_width * px,
            arrow_base.y() - arrowhead_width * py
        )

        # Draw arrowhead as filled triangle
        arrow_polygon = QPolygonF([end_f, left_wing, right_wing])
        painter.drawPolygon(arrow_polygon)

        painter.restore()

    def _draw_connection_dot(self, painter: QPainter, x: float, y: float, color: QColor) -> None:
        """Draw a small dot for connection guide lines at the output end."""
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(color))

        # Dot radius from style config
        radius = self.parent_matrix.style_config.guide_dot_radius

        # Draw filled circle
        painter.drawEllipse(QPointF(x, y), radius, radius)

        painter.restore()

    def _draw_connection_arrowhead(self, painter: QPainter, x: float, y: float, color: QColor) -> None:
        """Draw a small arrowhead for connection guide lines pointing downward."""
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(color))

        # Arrowhead size from style config
        arrowhead_length = self.parent_matrix.style_config.guide_arrowhead_length
        arrowhead_width = self.parent_matrix.style_config.guide_arrowhead_width

        # Arrow points for downward pointing arrow
        tip = QPointF(x, y)
        left = QPointF(x - arrowhead_width / 2, y - arrowhead_length)
        right = QPointF(x + arrowhead_width / 2, y - arrowhead_length)

        # Draw arrowhead as filled triangle
        arrow_polygon = QPolygonF([tip, left, right])
        painter.drawPolygon(arrow_polygon)

        painter.restore()

    def contextMenuEvent(self, event: Any) -> None:
        """Show context menu."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        context_menu = QMenu(self)
        reshuffle_action = QAction("Reshuffle colours", self)
        reshuffle_action.triggered.connect(self.parent_matrix.reshuffle_colors)
        context_menu.addAction(reshuffle_action)

        context_menu.exec(event.globalPos())

    def mousePressEvent(self, event: Any) -> None:
        """Handle mouse press for both click and drag operations."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Calculate grid position
        grid_rect = QRect(self.left_margin, self.top_margin,
                         self.width() - self.left_margin - self.right_margin,
                         self.height() - self.top_margin - self.bottom_margin)

        if not grid_rect.contains(event.pos()):
            return

        # Store drag start position
        self.is_dragging = False
        self.drag_start_pos = event.pos()
        self.selected_rect = QRect()

        # For now, set mouse tracking to receive move events
        # self.setMouseTracking(True)

    def mouseMoveEvent(self, event: Any) -> None:
        """Handle mouse move for drag selection."""
        # Handle hover effect
        row, col = self._get_square_at_position(event.pos())

        # Check if the mouse is within the grid area
        grid_rect = QRect(self.left_margin, self.top_margin, self.grid_width, self.grid_height)
        if not grid_rect.contains(event.pos()):
            row, col = -1, -1

        if row != self.hover_row or col != self.hover_col:
            self.hover_row = row
            self.hover_col = col
            self.update()
            self.parent_matrix.output_labels_widget.update()

        if not self.drag_start_pos:
            return

        # Calculate minimal drag distance to start dragging (prevents accidental tiny selections)
        drag_distance = (event.pos() - self.drag_start_pos).manhattanLength()
        if drag_distance < 5:  # Minimum drag distance
            return

        # Start dragging
        if not self.is_dragging:
            self.is_dragging = True

        # Update selection rectangle
        self.drag_end_pos = event.pos()

        # Calculate selection rectangle (normalized from start to end)
        start_x = min(self.drag_start_pos.x(), self.drag_end_pos.x())
        start_y = min(self.drag_start_pos.y(), self.drag_end_pos.y())
        end_x = max(self.drag_start_pos.x(), self.drag_end_pos.x())
        end_y = max(self.drag_start_pos.y(), self.drag_end_pos.y())

        self.selected_rect = QRect(start_x, start_y, end_x - start_x, end_y - start_y)

        # Trigger repaint to show selection
        self.update()

    def mouseReleaseEvent(self, event: Any) -> None:
        """Handle mouse release to finalize drag selection or handle click."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.is_dragging and self.drag_end_pos:
            # Handle drag selection completion
            self._apply_selection_toggle()
        else:
            # Handle single click (no drag)
            self._handle_click(event.pos())

        # Reset drag state
        self.is_dragging = False
        self.drag_start_pos = None
        self.drag_end_pos = None
        self.selected_rect = QRect()
        # self.setMouseTracking(False)

        # Trigger repaint to clear selection
        self.update()

    def leaveEvent(self, event: Optional['QEvent']) -> None:
        """Handle mouse leaving the widget to clear hover state."""
        if self.hover_row != -1 or self.hover_col != -1:
            self.hover_row = -1
            self.hover_col = -1
            self.update()
            self.parent_matrix.output_labels_widget.update()
        super().leaveEvent(event)

    def _handle_click(self, pos: Union['QPoint', QPointF]) -> None:
        """Handle single click to toggle connection."""
        # Calculate grid position
        grid_rect = QRect(self.left_margin, self.top_margin,
                         self.width() - self.left_margin - self.right_margin,
                         self.height() - self.top_margin - self.bottom_margin)

        if not grid_rect.contains(pos):
            return

        # Calculate clicked position relative to grid
        click_x = pos.x()
        click_y = pos.y()

        # Find column by checking which column position range the click falls into
        col = -1
        for i, col_x in enumerate(self.column_positions):
            col_width = self.column_widths[i]
            if click_x >= col_x and click_x < col_x + col_width:
                col = i
                break
        else:
            # Click was beyond the last column
            return

        # Find row by checking which row position range the click falls into
        row = -1
        for i, row_y in enumerate(self.row_positions):
            row_height = self.row_heights[i]
            if click_y >= row_y and click_y < row_y + row_height:
                row = i
                break
        else:
            # Click was beyond the last row
            return

        input_ports = self.parent_matrix.model.input_ports
        output_ports = self.parent_matrix.model.output_ports

        if col >= 0 and col < len(input_ports) and row >= 0 and row < len(output_ports):
            output_port_name = output_ports[row][1]  # port_name
            input_port_name = input_ports[col][1]    # port_name

            self.parent_matrix.toggle_connection(output_port_name, input_port_name)

    def _get_square_at_position(self, pos: Union['QPoint', QPointF]) -> Tuple[int, int]:
        """Find the matrix square (row, col) that contains the given position."""
        # Find column
        col = -1
        for i, col_x in enumerate(self.column_positions):
            col_width = self.column_widths[i]
            if pos.x() >= col_x and pos.x() < col_x + col_width:
                col = i
                break

        # Find row
        row = -1
        for i, row_y in enumerate(self.row_positions):
            row_height = self.row_heights[i]
            if pos.y() >= row_y and pos.y() < row_y + row_height:
                row = i
                break

        return row, col

    def _get_diagonal_path(self, start_row: int, start_col: int, end_row: int, end_col: int) -> List[Tuple[int, int]]:
        """Get all squares along the diagonal path from start to end square."""
        path = []
        row_diff = end_row - start_row
        col_diff = end_col - start_col

        # Only allow horizontal, vertical, and diagonal movements
        if row_diff == 0:
            # Horizontal line - all columns in the same row
            col_start = min(start_col, end_col)
            col_end = max(start_col, end_col)
            for col in range(col_start, col_end + 1):
                path.append((start_row, col))
        elif col_diff == 0:
            # Vertical line - all rows in the same column
            row_start = min(start_row, end_row)
            row_end = max(start_row, end_row)
            for row in range(row_start, row_end + 1):
                path.append((row, start_col))
        elif abs(row_diff) == abs(col_diff):
            # Diagonal line
            row_step = 1 if row_diff >= 0 else -1
            col_step = 1 if col_diff >= 0 else -1

            steps = abs(row_diff)

            current_row = start_row
            current_col = start_col

            # Add the start square
            path.append((current_row, current_col))

            # Add all squares along the diagonal
            for i in range(1, steps + 1):
                current_row = start_row + i * row_step
                current_col = start_col + i * col_step
                path.append((current_row, current_col))
        # If not horizontal, vertical, or diagonal, return empty path (no connection)

        return path

    def _apply_selection_toggle(self) -> None:
        """Toggle connections for all cells along the diagonal path between start and end squares."""
        if not self.drag_start_pos or not self.drag_end_pos:
            return

        input_ports = self.parent_matrix.model.input_ports
        output_ports = self.parent_matrix.model.output_ports

        # Find the start and end squares
        start_row, start_col = self._get_square_at_position(self.drag_start_pos)
        end_row, end_col = self._get_square_at_position(self.drag_end_pos)

        # If start or end square not found, return
        if start_row == -1 or start_col == -1 or end_row == -1 or end_col == -1:
            return

        # If start and end are the same square, don't make any connection
        if start_row == end_row and start_col == end_col:
            return

        # Get all squares along the diagonal path from start to end
        cells_to_toggle = self._get_diagonal_path(start_row, start_col, end_row, end_col)

        # Start batch processing
        self.parent_matrix.connection_manager.jack_handler.start_batch()
        try:
            # Toggle connections for all cells in the diagonal path
            for row, col in cells_to_toggle:
                if row < len(output_ports) and col < len(input_ports):
                    output_port_name = output_ports[row][1]  # port_name
                    input_port_name = input_ports[col][1]    # port_name
                    self.parent_matrix.toggle_connection(output_port_name, input_port_name)
        finally:
            # End batch processing and trigger a single refresh
            self.parent_matrix.connection_manager.jack_handler.end_batch()

    def _line_intersects_rect(self, line_start: QPointF, line_end: QPointF, rect: QRectF) -> bool:
        """Check if a line segment intersects with a rectangle."""
        # Check if either endpoint is inside the rectangle
        if rect.contains(line_start) or rect.contains(line_end):
            return True

        # Check intersection with all four sides of the rectangle
        rect_lines = [
            (QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top())),
            (QPointF(rect.right(), rect.top()), QPointF(rect.right(), rect.bottom())),
            (QPointF(rect.right(), rect.bottom()), QPointF(rect.left(), rect.bottom())),
            (QPointF(rect.left(), rect.bottom()), QPointF(rect.left(), rect.top()))
        ]

        for rect_line_start, rect_line_end in rect_lines:
            if self._lines_intersect(line_start, line_end, rect_line_start, rect_line_end):
                return True

        return False

    def _lines_intersect(self, p1: QPointF, q1: QPointF, p2: QPointF, q2: QPointF) -> bool:
        """Check if two line segments intersect."""
        def orientation(p: QPointF, q: QPointF, r: QPointF) -> int:
            val = (q.y() - p.y()) * (r.x() - q.x()) - (q.x() - p.x()) * (r.y() - q.y())
            if val == 0:
                return 0  # Collinear
            return 1 if val > 0 else 2  # Clockwise or counterclockwise

        def on_segment(p: QPointF, q: QPointF, r: QPointF) -> bool:
            return (q.x() <= max(p.x(), r.x()) and q.x() >= min(p.x(), r.x()) and
                    q.y() <= max(p.y(), r.y()) and q.y() >= min(p.y(), r.y()))

        o1 = orientation(p1, q1, p2)
        o2 = orientation(p1, q1, q2)
        o3 = orientation(p2, q2, p1)
        o4 = orientation(p2, q2, q1)

        if o1 != o2 and o3 != o4:
            return True

        if o1 == 0 and on_segment(p1, p2, q1): return True
        if o2 == 0 and on_segment(p1, q2, q1): return True
        if o3 == 0 and on_segment(p2, p1, q2): return True
        if o4 == 0 and on_segment(p2, q1, q2): return True

        return False

class _OutputLabelsWidget(QWidget):
    """
    Widget that displays output port labels in a separate scrollable area.
    This allows users to adjust the space allocated for output port names.
    """

    def __init__(self, parent_matrix: MIDIMatrixWidget) -> None:
        """
        Initialize the output labels widget.

        Args:
            parent_matrix: The parent MIDIMatrixWidget instance
        """
        super().__init__()
        self.parent_matrix = parent_matrix
        self.row_positions: List[int] = []
        self.row_heights: List[int] = []

        # Layout parameters matching the main grid
        self.font_size: int = int(self.parent_matrix.zoom_level)
        self.client_name_font_size: int = int(self.parent_matrix.zoom_level) + 2

        # Dynamic truncation based on available width
        self.max_client_chars: int = 10  # Will be calculated based on width
        self.max_port_chars: int = 15    # Will be calculated based on width

        # Set minimum width to display labels comfortably
        self.setMinimumWidth(100)
        self.update_labels()

    def update_labels(self) -> None:
        """Update the widget content when ports change."""
        # Get the same row height calculations as the main grid
        self._sync_with_main_grid()
        self.update()

    def resizeEvent(self, event: Optional['QEvent']) -> None:
        """Handle resize events to recalculate text truncation."""
        super().resizeEvent(event)
        self._calculate_truncation_lengths()
        self.update()

    def _calculate_truncation_lengths(self) -> None:
        """Calculate how many characters can fit based on current widget width."""
        if self.width() <= 0:
            return

        painter = QPainter(self)
        available_width = self.width() - 10  # padding

        # Client names
        client_font = QFont()
        client_font.setPointSize(self.client_name_font_size)
        client_font.setBold(True)
        painter.setFont(client_font)
        
        low = 0
        high = 100
        max_chars = 0
        while low <= high:
            mid = (low + high) // 2
            if mid == 0:
                low = 1
                continue
            rect = painter.boundingRect(0, 0, 1000, 100, 0, 'A' * mid)
            if rect.width() <= available_width:
                max_chars = mid
                low = mid + 1
            else:
                high = mid - 1
        self.max_client_chars = max_chars

        # Port names
        port_font = QFont()
        port_font.setPointSize(self.font_size)
        painter.setFont(port_font)

        low = 0
        high = 100
        max_chars = 0
        while low <= high:
            mid = (low + high) // 2
            if mid == 0:
                low = 1
                continue
            rect = painter.boundingRect(0, 0, 1000, 100, 0, 'A' * mid)
            if rect.width() <= available_width:
                max_chars = mid
                low = mid + 1
            else:
                high = mid - 1
        self.max_port_chars = max_chars
        
        painter.end()

    def _sync_with_main_grid(self) -> None:
        """Sync dimensions and positions with the main grid widget."""
        if hasattr(self.parent_matrix, 'matrix_widget') and self.parent_matrix.matrix_widget:
            grid_widget = self.parent_matrix.matrix_widget

            # Copy row dimensions from main grid
            self.row_heights = getattr(grid_widget, 'row_heights', [])
            self.row_positions = getattr(grid_widget, 'row_positions', [])

            # Calculate our required height (same as grid height)
            total_height = getattr(grid_widget, 'total_height', 200)

            self.setMinimumHeight(total_height)
            # Don't set minimum width since we're in a splitter that handles sizing

    def paintEvent(self, event: Optional['QEvent']) -> None:
        """Paint the output labels aligned with the main grid."""
        if not hasattr(self, 'row_heights') or not self.row_heights:
            self._sync_with_main_grid()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw background
        painter.fillRect(self.rect(), self.parent_matrix.connection_manager.background_color)

        # Create font objects for text measurements
        client_font = QFont()
        client_font.setPointSize(self.client_name_font_size)
        client_font.setBold(True)

        port_font = QFont()
        port_font.setPointSize(self.font_size)

        hover_row = -1
        if hasattr(self.parent_matrix, 'matrix_widget') and self.parent_matrix.matrix_widget:
            hover_row = self.parent_matrix.matrix_widget.hover_row

        # Access grouped output clients info to draw client name once per group
        output_client_port_counts = getattr(self.parent_matrix.matrix_widget, "output_client_port_counts", {})
        ports = self.parent_matrix.model.output_ports

        idx = 0
        while idx < len(ports):
            client_name, _, _ = ports[idx]
            count = output_client_port_counts.get(client_name, 1)

            for offset in range(count):
                row_index = idx + offset
                if row_index >= len(self.row_positions):
                    break

                _, port_name, display_name = ports[row_index]
                row_y = self.row_positions[row_index]
                row_height = self.row_heights[row_index]
                is_hovered = (row_index == hover_row)

                # Draw client and port names, centered vertically in the row
                painter.save()

                # Prepare fonts
                current_client_font = QFont(client_font)
                if is_hovered and offset == 0:
                    # Emphasize only on first row for this client
                    current_client_font.setPointSize(self.client_name_font_size + 1)
                
                current_port_font = QFont(port_font)
                if is_hovered:
                    current_port_font.setBold(True)

                # Prepare texts
                client_text = _truncate_text(client_name.upper(), self.max_client_chars)
                port_text = _truncate_text(display_name, self.max_port_chars)

                # Get text dimensions
                painter.setFont(current_client_font)
                client_text_h = painter.fontMetrics().height()
                
                painter.setFont(current_port_font)
                port_text_h = painter.fontMetrics().height()

                # Spacing between client and port labels
                port_v_offset = self.parent_matrix.style_config.output_label_port_v_offset

                # Draw client name only once (on the first port row of this client)
                if offset == 0:
                    # Calculate positions to center the text block vertically
                    total_text_height = client_text_h + port_text_h + port_v_offset
                    block_start_y = row_y + (row_height - total_text_height) / 2

                    client_y = block_start_y
                    port_y = block_start_y + client_text_h + port_v_offset

                    painter.setFont(current_client_font)
                    painter.setPen(QPen(self.parent_matrix.model.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))
                    client_rect = QRect(0, int(client_y), self.width() - 4, client_text_h)
                    painter.drawText(
                        client_rect,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        client_text,
                    )

                    # Draw port name on every row
                    painter.setFont(current_port_font)
                    painter.setPen(QPen(self.parent_matrix.model.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))
                    port_rect = QRect(0, int(port_y), self.width() - 4, port_text_h)
                    painter.drawText(
                        port_rect,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        port_text,
                    )
                else:
                    # This is a subsequent port, draw only the port name, centered and shifted.
                    # Center vertically and move up slightly
                    port_y = row_y + (row_height - port_text_h) / 2 - 3  # 3px up

                    # Draw port name
                    painter.setFont(current_port_font)
                    painter.setPen(QPen(self.parent_matrix.model.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))
                    port_rect = QRect(0, int(port_y), self.width() - 4, port_text_h)
                    painter.drawText(
                        port_rect,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        port_text,
                    )

                painter.restore()

            idx += count

    def _draw_client_separators(self, painter: QPainter) -> None:
        """Draw dashed line separators around each output port entry."""
        data = self.parent_matrix.model.output_ports
        if not data or not hasattr(self, 'row_positions') or not self.row_positions:
            return

        painter.save()

        # Set pen for solid lines
        painter.setPen(QPen(QColor(150, 150, 150), 1, Qt.PenStyle.SolidLine))

        # Draw separator before first entry
        separator_y = self.row_positions[0] - 2
        painter.drawLine(0, separator_y, self.width(), separator_y)

        # Draw separator after each entry
        for i in range(len(data)):
            separator_y = self.row_positions[i] + self.row_heights[i] + 1
            painter.drawLine(0, separator_y, self.width(), separator_y)

        painter.restore()

def _truncate_text(text: str, max_length: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..." if max_length > 3 else text[:max_length]
