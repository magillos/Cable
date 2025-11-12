"""
MIDIMatrixWidget - A matrix-style connection view widget for MIDI ports
"""
import dataclasses
import random

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QScrollArea, QFrame,
                             QVBoxLayout, QSizePolicy, QSplitter)
from PyQt6.QtCore import Qt, QSize, QRect, QRectF, QTimer, QPointF
from PyQt6.QtGui import QPolygonF
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPalette, QPainterPath, QLinearGradient

@dataclasses.dataclass
class MidiMatrixStyleConfig:
    """Configuration for visual styling of the MIDI Matrix."""
    # --- Input Labels (Bottom) ---
    # Rotation angle for input port labels.
    input_label_rotation: int = 55
    # Horizontal positioning factor for input labels showing clients and ports combo. Smaller values move labels left.
    input_label_x_pos_factor_client_port: float = 1.15
    # Horizontal positioning factor for input labels showing ports only. Smaller values move labels left.
    input_label_x_pos_factor_ports_only: float = 1.4  # Deprecated: Use input_label_x_pos_factor_client_port and input_label_x_pos_factor_ports_only instead
    input_label_x_pos_factor: float = 1.5
    # Vertical offset between client and port names in input labels.
    input_label_port_y_offset: int = -7

    # --- Output Labels (Left) ---
    # Vertical offset between client and port names in output labels.
    output_label_port_v_offset: int = -7

    # --- Selection Arrow ---
    selection_arrow_line_width: int = 3
    selection_arrowhead_length: int = 15
    selection_arrowhead_width: int = 8

    # --- Connection Guide Lines ---
    # Line width for non-hovered connection guide lines.
    guide_line_width: int = 3
    # Line width for hovered connection guide lines (for the active cell).
    guide_line_hover_width: int = 3
    # Arrowhead size for connection guide lines
    guide_arrowhead_length: int = 12
    guide_arrowhead_width: int = 8
    # Dot size for connection guide lines (at output end)
    guide_dot_radius: int = 4

    # --- Grid Square Colors (Dark Theme) ---
    disconnected_square_color_dark: tuple = (32, 35, 38)
    self_connection_square_color_dark: tuple = (60, 63, 65)
    hover_highlight_square_color_dark: tuple = (51, 51, 70)

    # --- Grid Square Colors (Light Theme) ---
    disconnected_square_color_light: tuple = (226, 226, 226)
    self_connection_square_color_light: tuple = (215, 216, 217)
    hover_highlight_square_color_light: tuple = (195, 196, 197)

    # --- Grid Border Width --
    # Width of grid lines that separate squares
    grid_line_width: int = 0.3
    # Width of borders around individual squares
    square_border_width: int = 0.1

    # --- Scrollbar Trigger Padding --
    horizontal_padding: int = 400
    vertical_padding: int = 200

class MIDIMatrixWidget(QWidget):
    """
    A matrix-style widget for displaying and managing MIDI port connections.
    Shows output ports (sources) on the vertical left axis and input ports (destinations)
    on the horizontal bottom axis.
    """

    def __init__(self, connection_manager, parent=None):
        """
        Initialize the MIDI matrix widget.

        Args:
            connection_manager: The main JackConnectionManager instance
            parent: The parent widget
        """
        super().__init__(parent)
        self.connection_manager = connection_manager
        self.style_config = MidiMatrixStyleConfig()
        self.node_visibility_manager = None

        # Data structures for matrix organization
        self.output_ports = []  # List of (client_name, port_name, display_name) tuples for output ports
        self.input_ports = []   # List of (client_name, port_name, display_name) tuples for input ports
        self.client_colors = {}  # Map of client_name -> QColor
        self.connections = set()  # Set of (output_port, input_port) tuples for connections

        # Zoom configuration
        self.zoom_level = connection_manager.config_manager.get_float_setting('midi_matrix_zoom_level', 10.0)
        self.color_generator = random.Random()
        self.color_seed_offset = 0

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()

        # Connect to JACK signals
        self.connection_manager.port_added.connect(self.on_port_added_or_removed)
        self.connection_manager.port_removed.connect(self.on_port_added_or_removed)
        self.connection_manager.client_removed.connect(self.on_client_removed)
        self.connection_manager.connection_made.connect(self.on_connection_changed)
        self.connection_manager.connection_broken.connect(self.on_connection_changed)

        # Initial refresh
        self.refresh_matrix()

    def set_node_visibility_manager(self, node_visibility_manager):
        """
        Set the node visibility manager for this widget.

        Args:
            node_visibility_manager: The NodeVisibilityManager instance
        """
        self.node_visibility_manager = node_visibility_manager
        # Refresh the matrix to apply visibility settings
        self.refresh_matrix()

    def _setup_ui(self):
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create a single outer scroll area that contains the entire splitter
        self.main_scroll_area = QScrollArea()
        self.main_scroll_area.setWidgetResizable(True)  # Resize content to fit, but we'll override for scrolling
        self.main_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.main_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Create horizontal splitter for adjustable output label area
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(True)
        self.main_splitter.setHandleWidth(0)  # Make splitter handle invisible
        self.main_splitter.setStyleSheet("QSplitter::handle { background-color: transparent; border: none; }")  # Ensure complete invisibility
        self.main_splitter.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

        # Left panel - Output labels (no individual scroll area)
        self.output_labels_widget = _OutputLabelsWidget(self)
        self.output_labels_widget.setMinimumWidth(20)  # Allow collapse but prevent disappearing

        # Right panel - Grid (no individual scroll area)
        self.matrix_widget = _MatrixGridWidget(self)

        # Add panels directly to splitter (no nested scroll areas)
        self.main_splitter.addWidget(self.output_labels_widget)
        self.main_splitter.addWidget(self.matrix_widget)

        # Set the splitter as the widget for the main scroll area
        self.main_scroll_area.setWidget(self.main_splitter)

        # Load and set splitter proportions from config - give more space to the matrix grid
        splitter_sizes_str = self.connection_manager.config_manager.get_str('midi_matrix_splitter_sizes', '200,800')
        try:
            sizes = [int(x.strip()) for x in splitter_sizes_str.split(',')]
            if len(sizes) == 2:
                self.main_splitter.setSizes(sizes)
            else:
                self.main_splitter.setSizes([200, 800])  # Fallback to defaults - more space for grid
        except (ValueError, IndexError):
            self.main_splitter.setSizes([200, 800])  # Fallback to defaults - more space for grid

        # Connect splitter signals (only horizontal splitter)
        self.main_splitter.splitterMoved.connect(self._on_main_splitter_moved)

        layout.addWidget(self.main_scroll_area)

    def resizeEvent(self, event):
        """Handle resize event to ensure proper layout."""
        super().resizeEvent(event)
        # Force the matrix widget to recalculate its size
        if hasattr(self, 'matrix_widget'):
            self.matrix_widget.update_matrix()
            # Defer the call to prevent potential resize loops
            QTimer.singleShot(0, self._update_scroll_behavior)

    def _on_main_splitter_moved(self, pos, index):
        """Handle main splitter movement to update output label truncation and save position."""
        # Update output labels when main splitter moves (changes output label width)
        self.output_labels_widget._calculate_truncation_lengths()
        self.output_labels_widget.update()

        # Save splitter sizes to config
        sizes = self.main_splitter.sizes()
        if len(sizes) == 2:
            sizes_str = f"{sizes[0]},{sizes[1]}"
            self.connection_manager.config_manager.set_str('midi_matrix_splitter_sizes', sizes_str)

    def refresh_matrix(self):
        """Refresh the entire matrix by reloading ports and connections."""
        self._load_ports()
        self._load_connections()
        self.matrix_widget.update_matrix()
        self.output_labels_widget.update_labels()

    def _load_ports(self):
        """Load MIDI ports from JACK and organize them by client."""
        self.output_ports = []
        self.input_ports = []
        self.client_colors = {}

        try:
            # Get MIDI ports
            midi_ports = []
            if self.connection_manager.client:
                all_ports = self.connection_manager.client.get_ports(is_midi=True)
                midi_ports = [p for p in all_ports]

            # Group ports by client and filter by visibility
            client_ports = {}
            for port in midi_ports:
                client_name = port.name.split(':', 1)[0] if ':' in port.name else port.name
                port_name = port.name

                # Check visibility if manager is available
                if self.node_visibility_manager:
                    visible = self.connection_manager.node_visibility_manager.is_midi_matrix_input_visible(port_name) if port.is_input else \
                             self.connection_manager.node_visibility_manager.is_midi_matrix_output_visible(port_name)
                    if not visible:
                        continue

                if client_name not in client_ports:
                    client_ports[client_name] = {'inputs': [], 'outputs': [], 'color': self._generate_client_color(client_name)}
                client_ports[client_name]['inputs' if port.is_input else 'outputs'].append(port.name)

            # Sort clients
            sorted_clients = sorted(client_ports.keys())

            # Organize ports for matrix display
            for client_name in sorted_clients:
                client_data = client_ports[client_name]

                # Add client color
                self.client_colors[client_name] = client_data['color']

                # Add output ports (vertical axis)
                for port_name in sorted(client_data['outputs']):
                    # Include client name for clarity when multiple clients have similar port names
                    full_display_name = port_name.split(':', 1)[1] if ':' in port_name else port_name
                    display_name = full_display_name  # Only port name, client shown separately
                    self.output_ports.append((client_name, port_name, display_name))

                # Add input ports (horizontal axis)
                for port_name in sorted(client_data['inputs']):
                    # Include client name for clarity when multiple clients have similar port names
                    full_display_name = port_name.split(':', 1)[1] if ':' in port_name else port_name
                    display_name = full_display_name  # Only port name, client shown separately
                    self.input_ports.append((client_name, port_name, display_name))

            # Reverse the entire input ports order
            self.input_ports = self.input_ports[::-1]

        except Exception as e:
            print(f"Error loading MIDI ports: {e}")

    def _load_connections(self):
        """Load current MIDI connections."""
        self.connections = set()
        try:
            if not self.connection_manager.client:
                return

            for output_port in self.output_ports:
                port_name = output_port[1]  # port_name
                connections = self.connection_manager.client.get_all_connections(port_name)
                for input_port in connections:
                    if input_port.is_midi:  # Ensure it's MIDI
                        input_port_name = input_port.name
                        # Find if this input port is in our matrix
                        for input_tuple in self.input_ports:
                            if input_tuple[1] == input_port_name:  # port_name match
                                self.connections.add((port_name, input_port_name))
                                break
        except Exception as e:
            print(f"Error loading connections: {e}")

    def _generate_client_color(self, client_name):
        """Generate a consistent color for a client."""
        # Use client name to generate consistent color
        hash_value = hash(client_name) + self.color_seed_offset
        self.color_generator.seed(hash_value)

        # Determine if we're in dark mode or light mode
        window_color = self.palette().color(QPalette.ColorRole.Window)
        brightness = (window_color.red() + window_color.green() + window_color.blue()) / 3

        if brightness < 128:  # Dark mode - use high contrast colors against dark backgrounds
            # Predefined set of bright, high-contrast colors for dark mode
            # These colors provide excellent readability on dark backgrounds
            dark_mode_colors = [
                QColor(255, 128, 0),   # Bright orange
                QColor(255, 255, 0),   # Bright yellow
                QColor(0, 255, 0),     # Bright green
                QColor(0, 255, 255),   # Bright cyan
                QColor(255, 0, 255),   # Bright magenta
                QColor(255, 255, 255), # White
                QColor(255, 192, 203), # Pink
                QColor(255, 165, 0),   # Orange
                QColor(173, 216, 230), # Light blue
                QColor(144, 238, 144), # Light green
                QColor(255, 182, 193), # Light pink
                QColor(240, 230, 140), # Khaki
            ]
            # Use hash to consistently select from the color set
            color_index = hash_value % len(dark_mode_colors)
            return dark_mode_colors[color_index]
        else:  # Light mode - use dark colors
            # Generate darker HSV colors for light backgrounds
            hue = self.color_generator.randint(0, 359)
            saturation = 180 + self.color_generator.randint(0, 75)  # 180-255 for good saturation
            value = 50 + self.color_generator.randint(0, 100)      # 50-150 for dark colors
            return QColor.fromHsv(hue, saturation, value)

    def is_connected(self, output_port, input_port):
        """Check if two ports are connected."""
        return (output_port, input_port) in self.connections

    def toggle_connection(self, output_port, input_port):
        """Toggle the connection between two ports."""
        connected = self.is_connected(output_port, input_port)

        if connected:
            # Break connection
            self.connection_manager.break_midi_connection(output_port, input_port)
        else:
            # Make connection
            self.connection_manager.make_midi_connection(output_port, input_port)

    def on_port_added_or_removed(self, port_name, client_name=None, port_flags=None, port_type=None, is_input=None):
        """Handle port addition/removal events."""
        should_refresh = False

        if port_type == "midi":
            should_refresh = True
        elif port_name and self.connection_manager.client:
            try:
                should_refresh = any(p.name == port_name for p in self.connection_manager.client.get_ports(is_midi=True))
            except Exception:
                # If we can't get ports (e.g., JackError), assume it's MIDI-related to be safe
                should_refresh = True

        if should_refresh:
            QTimer.singleShot(10, self.refresh_matrix)  # Debounce updates

    def on_client_removed(self, client_name):
        """Handle client removal events."""
        QTimer.singleShot(10, self.refresh_matrix)  # Debounce updates

    def on_connection_changed(self, output_port, input_port):
        """Handle connection change events."""
        # Check if this affects MIDI connections
        is_midi_connection = False
        try:
            if self.connection_manager.client:
                if any(p.name == output_port for p in self.connection_manager.client.get_ports(is_midi=True, is_output=True)):
                    is_midi_connection = True
        except:
            pass

        if is_midi_connection:
            QTimer.singleShot(10, self.refresh_matrix)  # Debounce updates

    def reshuffle_colors(self):
        """Reshuffle client colors."""
        self.color_seed_offset = self.color_generator.randint(0, 10000)
        self.refresh_matrix()

    def zoom_in(self):
        """Increase zoom level."""
        max_zoom = 20.0
        zoom_step = 0.5
        if self.zoom_level < max_zoom:
            self.zoom_level = min(self.zoom_level + zoom_step, max_zoom)
            self.connection_manager.config_manager.set_float_setting('midi_matrix_zoom_level', self.zoom_level)
            self.matrix_widget.font_size = int(self.zoom_level)
            self.matrix_widget.client_name_font_size = int(self.zoom_level) + 2
            self.matrix_widget.grid_cell_scaling = self._calculate_grid_scaling(self.zoom_level)
            self.output_labels_widget.font_size = int(self.zoom_level)
            self.output_labels_widget.client_name_font_size = int(self.zoom_level) + 2
            self.refresh_matrix()
            QTimer.singleShot(0, self._update_scroll_behavior)

    def zoom_out(self):
        """Decrease zoom level."""
        min_zoom = 4.0
        zoom_step = 0.5
        if self.zoom_level > min_zoom:
            self.zoom_level = max(self.zoom_level - zoom_step, min_zoom)
            self.connection_manager.config_manager.set_float_setting('midi_matrix_zoom_level', self.zoom_level)
            self.matrix_widget.font_size = int(self.zoom_level)
            self.matrix_widget.client_name_font_size = int(self.zoom_level) + 2
            self.matrix_widget.grid_cell_scaling = self._calculate_grid_scaling(self.zoom_level)
            self.output_labels_widget.font_size = int(self.zoom_level)
            self.output_labels_widget.client_name_font_size = int(self.zoom_level) + 2
            self.refresh_matrix()
            QTimer.singleShot(0, self._update_scroll_behavior)

    def _calculate_grid_scaling(self, zoom_level):
        """Calculate grid cell scaling factor based on zoom level."""
        # Base zoom level is 10, base minimum size is 35px
        # Scale proportionally
        base_zoom = 10.0
        base_size = 35.0

        # Scale factor: at zoom 10 = 1.0, zoom 6 = 0.6, zoom 20 = 2.0
        scale_factor = zoom_level / base_zoom

        # Apply scaling but ensure minimum size stays reasonable
        return max(scale_factor, 0.3)

    def _update_scroll_behavior(self):
        """Update scroll area behavior based on content size vs viewport size."""
        if not hasattr(self, 'main_scroll_area') or not hasattr(self, 'main_splitter'):
            return

        # Calculate proper minimum size accounting for angled input labels
        proper_min_size = self._calculate_proper_minimum_size()

        # Explicitly set the minimum size of the splitter. This is the key.
        # It forces the splitter to have a minimum size that reflects its content.
        self.main_splitter.setMinimumSize(proper_min_size)

        # Get the scroll area's viewport size
        viewport_size = self.main_scroll_area.viewport().size()

        # Check if content exceeds viewport in either dimension
        content_too_large = (proper_min_size.width() > viewport_size.width() or
                           proper_min_size.height() > viewport_size.height())

        # If content is too large, disable widget resizing to show scrollbars.
        # The scroll area will then respect the splitter's minimum size.
        # If content fits, enable widget resizing to fill the space.
        self.main_scroll_area.setWidgetResizable(not content_too_large)

    def _calculate_proper_minimum_size(self):
        """Calculate the proper minimum size for the splitter accounting for angled input labels."""
        if not hasattr(self, 'main_splitter') or not hasattr(self, 'output_labels_widget') or not hasattr(self, 'matrix_widget'):
            return QSize(200, 200)

        # Get the output labels widget's current width from the splitter
        splitter_sizes = self.main_splitter.sizes()
        output_min_width = splitter_sizes[0] if splitter_sizes else self.output_labels_widget.minimumWidth()

        # Get the matrix widget minimum size
        matrix_min_size = self.matrix_widget.minimumSize()

        # Calculate total width: output labels + matrix + some padding for angled labels
        total_width = output_min_width + matrix_min_size.width() + self.style_config.horizontal_padding

        # Height is determined by the taller of the two widgets
        total_height = max(self.output_labels_widget.minimumHeight(), matrix_min_size.height()) + self.style_config.vertical_padding

        return QSize(total_width, total_height)


"""
Internal widget that handles the actual matrix rendering and interaction.
"""

class _MatrixGridWidget(QWidget):
    def __init__(self, parent_matrix):
        """
        Initialize the matrix grid widget.

        Args:
            parent_matrix: The parent MIDIMatrixWidget instance
        """
        super().__init__()
        self.parent_matrix = parent_matrix

        # Layout parameters - cell_size is now dynamic
        self.base_cell_width = 24  # Base width per port
        self.font_size = int(self.parent_matrix.zoom_level)
        self.client_name_font_size = int(self.parent_matrix.zoom_level) + 2
        self.grid_cell_scaling = self.parent_matrix._calculate_grid_scaling(self.parent_matrix.zoom_level)

        # Margins for labels - reduced since all labels are now in separate panels
        self.top_margin = 10    # Minimal space at top
        self.left_margin = 10   # Minimal space on left (grid starts immediately)
        self.bottom_margin = 120 # Minimal space at bottom (input labels are separate)
        self.right_margin = 20

        # Drag selection state
        self.is_dragging = False
        self.drag_start_pos = None
        self.drag_end_pos = None
        self.selected_rect = QRect()  # Rectangle for visual feedback

        # Hover selection state
        self.hover_row = -1
        self.hover_col = -1
        self.setMouseTracking(True)

        # Set size policy to allow expansion to fill available space
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Set minimum size
        self.update_matrix()

    def update_matrix(self):
        """Update the matrix dimensions and trigger repaint."""
        output_count = len(self.parent_matrix.output_ports)
        input_count = len(self.parent_matrix.input_ports)

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

    def _calculate_sizes_from_text(self):
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
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.input_ports):
            input_client_groups[client_name].append((i, port_name, display_name))

        # Also precompute how many ports each input client has
        input_client_port_counts = {
            client: len(ports) for client, ports in input_client_groups.items()
        }
        self.input_client_port_counts = input_client_port_counts

        output_client_groups = defaultdict(list)
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.output_ports):
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
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.output_ports):
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
        for i, (client_name, port_name, display_name) in enumerate(self.parent_matrix.input_ports):
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
            self.column_widths = [min_scaled_size] * len(self.parent_matrix.input_ports)
            self.column_positions = [self.left_margin + i * min_scaled_size for i in range(len(self.parent_matrix.input_ports))]
        if not self.row_heights:
            self.row_heights = [min_scaled_size] * len(self.parent_matrix.output_ports)
            self.row_positions = [self.top_margin + i * min_scaled_size for i in range(len(self.parent_matrix.output_ports))]

    @property
    def cell_height(self):
        """Get the fixed height for each row (output port)."""
        return self.base_cell_width  # Keep rows at fixed height for now

    @property
    def cell_size(self):
        """Backward compatibility - return base cell width."""
        return self.base_cell_width

    def paintEvent(self, event):
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



    def _draw_grid(self, painter, grid_rect):
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

    def _are_corresponding(self, name1, name2):
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

    def _draw_connection_squares(self, painter, grid_rect):
        """Draw the connection status squares using pre-calculated positions."""
        output_ports = self.parent_matrix.output_ports
        input_ports = self.parent_matrix.input_ports

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

                is_connected = self.parent_matrix.is_connected(output_port, input_port)

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

    def _draw_connection_guides(self, painter, grid_rect):
        """
        Draw subtle guide lines for connected cells from:
          - the center of the connection square
          - to the center of its output label row (left)
          - and to the center of its input label column (bottom)

        This makes it easy to see which ports a highlighted connection square represents,
        especially on large matrices.
        """
        output_ports = self.parent_matrix.output_ports
        input_ports = self.parent_matrix.input_ports

        if not output_ports or not input_ports:
            return

        # Determine hover target: only emphasize guides for the hovered connected cell.
        hover_row = self.hover_row
        hover_col = self.hover_col

        # Helper function to make color less vibrant
        def make_less_vibrant(color):
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

                if not self.parent_matrix.is_connected(output_port, input_port):
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
                output_color = self.parent_matrix.client_colors.get(output_client, QColor(Qt.GlobalColor.black))
                input_color = self.parent_matrix.client_colors.get(input_client, QColor(Qt.GlobalColor.black))

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

    def _draw_rotated_text(self, painter, text, x, y, font, color, is_hovered=False):
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

    def _draw_input_labels(self, painter):
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
        ports = self.parent_matrix.input_ports

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
                    painter.setPen(QPen(self.parent_matrix.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))

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
                    painter.setPen(QPen(self.parent_matrix.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))

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
                    painter.setPen(QPen(self.parent_matrix.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))

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

    def _draw_selection_rectangle(self, painter):
        """Draw the selection arrow/line during drag operations."""
        if not self.drag_start_pos or not self.drag_end_pos:
            return

        painter.save()

        # Set pen for selection line - bright blue with thickness
        selection_color = QColor(65, 105, 225)  # Royal blue
        selection_pen = QPen(selection_color, self.parent_matrix.style_config.selection_arrow_line_width, Qt.PenStyle.SolidLine)
        painter.setPen(selection_pen)

        # Draw the line from start to end
        start_point = self.drag_start_pos
        end_point = self.drag_end_pos
        painter.drawLine(start_point, end_point)

        # Draw arrowhead at the end
        self._draw_arrowhead(painter, start_point, end_point, selection_color)

        painter.restore()

    def _draw_arrowhead(self, painter, start, end, color):
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

    def _draw_connection_dot(self, painter, x, y, color):
        """Draw a small dot for connection guide lines at the output end."""
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(color))

        # Dot radius from style config
        radius = self.parent_matrix.style_config.guide_dot_radius

        # Draw filled circle
        painter.drawEllipse(QPointF(x, y), radius, radius)

        painter.restore()

    def _draw_connection_arrowhead(self, painter, x, y, color):
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

    def contextMenuEvent(self, event):
        """Show context menu."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        context_menu = QMenu(self)
        reshuffle_action = QAction("Reshuffle colours", self)
        reshuffle_action.triggered.connect(self.parent_matrix.reshuffle_colors)
        context_menu.addAction(reshuffle_action)

        context_menu.exec(event.globalPos())

    def mousePressEvent(self, event):
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

    def mouseMoveEvent(self, event):
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

    def mouseReleaseEvent(self, event):
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

    def leaveEvent(self, event):
        """Handle mouse leaving the widget to clear hover state."""
        if self.hover_row != -1 or self.hover_col != -1:
            self.hover_row = -1
            self.hover_col = -1
            self.update()
            self.parent_matrix.output_labels_widget.update()
        super().leaveEvent(event)

    def _handle_click(self, pos):
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

        input_ports = self.parent_matrix.input_ports
        output_ports = self.parent_matrix.output_ports

        if col >= 0 and col < len(input_ports) and row >= 0 and row < len(output_ports):
            output_port_name = output_ports[row][1]  # port_name
            input_port_name = input_ports[col][1]    # port_name

            self.parent_matrix.toggle_connection(output_port_name, input_port_name)

    def _get_square_at_position(self, pos):
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

    def _get_diagonal_path(self, start_row, start_col, end_row, end_col):
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

    def _apply_selection_toggle(self):
        """Toggle connections for all cells along the diagonal path between start and end squares."""
        if not self.drag_start_pos or not self.drag_end_pos:
            return

        input_ports = self.parent_matrix.input_ports
        output_ports = self.parent_matrix.output_ports

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

    def _line_intersects_rect(self, line_start, line_end, rect):
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

    def _lines_intersect(self, p1, q1, p2, q2):
        """Check if two line segments intersect."""
        def orientation(p, q, r):
            val = (q.y() - p.y()) * (r.x() - q.x()) - (q.x() - p.x()) * (r.y() - q.y())
            if val == 0:
                return 0  # Collinear
            return 1 if val > 0 else 2  # Clockwise or counterclockwise

        def on_segment(p, q, r):
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

    def __init__(self, parent_matrix):
        """
        Initialize the output labels widget.

        Args:
            parent_matrix: The parent MIDIMatrixWidget instance
        """
        super().__init__()
        self.parent_matrix = parent_matrix

        # Layout parameters matching the main grid
        self.font_size = int(self.parent_matrix.zoom_level)
        self.client_name_font_size = int(self.parent_matrix.zoom_level) + 2

        # Dynamic truncation based on available width
        self.max_client_chars = 10  # Will be calculated based on width
        self.max_port_chars = 15    # Will be calculated based on width

        # Set minimum width to display labels comfortably
        self.setMinimumWidth(100)
        self.update_labels()

    def update_labels(self):
        """Update the widget content when ports change."""
        # Get the same row height calculations as the main grid
        self._sync_with_main_grid()
        self.update()

    def resizeEvent(self, event):
        """Handle resize events to recalculate text truncation."""
        super().resizeEvent(event)
        self._calculate_truncation_lengths()
        self.update()

    def _calculate_truncation_lengths(self):
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

    def _sync_with_main_grid(self):
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

    def paintEvent(self, event):
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
        ports = self.parent_matrix.output_ports

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
                    painter.setPen(QPen(self.parent_matrix.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))
                    client_rect = QRect(0, int(client_y), self.width() - 4, client_text_h)
                    painter.drawText(
                        client_rect,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        client_text,
                    )

                    # Draw port name on every row
                    painter.setFont(current_port_font)
                    painter.setPen(QPen(self.parent_matrix.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))
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
                    painter.setPen(QPen(self.parent_matrix.client_colors.get(client_name, QColor(Qt.GlobalColor.black))))
                    port_rect = QRect(0, int(port_y), self.width() - 4, port_text_h)
                    painter.drawText(
                        port_rect,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        port_text,
                    )

                painter.restore()

            idx += count

    def _draw_client_separators(self, painter):
        """Draw dashed line separators around each output port entry."""
        data = self.parent_matrix.output_ports
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

def _truncate_text(text, max_length):
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..." if max_length > 3 else text[:max_length]
