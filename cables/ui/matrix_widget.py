"""
MatrixWidget - Unified matrix-style connection view widget for MIDI and Audio ports.

This module provides a matrix-style view for MIDI or Audio port connections,
parameterized by port_type. It uses the MatrixInterface to access the capabilities
it needs from the main application, enabling better testability and reduced coupling.
"""

import dataclasses

import logging

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QScrollArea,
    QFrame,
    QVBoxLayout,
    QSizePolicy,
    QSplitter,
)
from PyQt6.QtCore import (
    Qt,
    QSize,
    QRect,
    QRectF,
    QTimer,
    QPointF,
    pyqtSignal,
    QEvent,
    QObject,
)
from PyQt6.QtGui import QPolygonF
from PyQt6.QtGui import (
    QFont,
    QColor,
    QPainter,
    QPen,
    QBrush,
    QPalette,
    QPainterPath,
    QLinearGradient,
)

from cables.jack_service import get_jack_service
from .matrix_model import MatrixModel
from .midi_matrix_grid import _MatrixGridWidget, _OutputLabelsWidget
from cable_core import config_keys as keys

from typing import TYPE_CHECKING, Optional, Any, Union, List, Tuple, Dict, Literal

if TYPE_CHECKING:
    from cables.interfaces import MatrixInterface
    from cables.features.node_visibility_manager import NodeVisibilityManager
    from PyQt6.QtGui import QEvent
    from PyQt6.QtCore import QPoint, QSize

PortType = Literal["midi", "audio"]

# Config key mapping per port type
_MATRIX_CONFIG_KEYS: Dict[str, Dict[str, str]] = {
    "midi": {
        "zoom_level": keys.MIDI_MATRIX_ZOOM_LEVEL,
        "splitter_sizes": keys.MIDI_MATRIX_SPLITTER_SIZES,
        "make_connection": "make_midi_connection",
        "break_connection": "break_midi_connection",
    },
    "audio": {
        "zoom_level": keys.AUDIO_MATRIX_ZOOM_LEVEL,
        "splitter_sizes": keys.AUDIO_MATRIX_SPLITTER_SIZES,
        "make_connection": "make_connection",
        "break_connection": "break_connection",
    },
}


@dataclasses.dataclass
class MatrixStyleConfig:
    """Configuration for visual styling of the Matrix."""

    # --- Input Labels (Bottom) ---
    # Rotation angle for input port labels.
    input_label_rotation: int = 55
    # Horizontal positioning factor for input labels showing clients and ports combo. Smaller values move labels left.
    input_label_x_pos_factor_client_port: float = 1.15
    # Horizontal positioning factor for input labels showing ports only. Smaller values move labels left.
    input_label_x_pos_factor_ports_only: float = 1.4
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


# Backward compatibility aliases
MidiMatrixStyleConfig = MatrixStyleConfig
AudioMatrixStyleConfig = MatrixStyleConfig


class MatrixWidget(QWidget):
    """
    A matrix-style widget for displaying and managing MIDI or Audio port connections.
    Shows output ports (sources) on the vertical left axis and input ports (destinations)
    on the horizontal bottom axis.

    This class uses the MatrixInterface protocol to access capabilities
    from the main application. The connection_manager parameter must implement:
    - ConfigProvider: for config_manager access
    - ConnectionOperations: for make_connection, break_connection, make_midi_connection, break_midi_connection
    - ColorProvider: for background_color
    """

    fullscreen_request_signal = pyqtSignal()

    def __init__(
        self,
        connection_manager: "MatrixInterface",
        parent: Optional[QWidget] = None,
        port_type: PortType = "midi",
    ) -> None:
        """
        Initialize the matrix widget.

        Args:
            connection_manager: Reference to an object implementing MatrixInterface.
                               Typically the JackConnectionManager instance.
            parent: The parent widget
            port_type: Either 'midi' or 'audio' to determine which ports to display
        """
        super().__init__(parent)
        self.connection_manager = connection_manager
        self.port_type = port_type
        self._jack_service = get_jack_service()
        self.style_config = MatrixStyleConfig()
        self.node_visibility_manager: Optional["NodeVisibilityManager"] = None
        self._config_keys = _MATRIX_CONFIG_KEYS[port_type]

        # Data model for ports, connections, and colors
        self.model = MatrixModel(self._jack_service, port_type=port_type)

        # Zoom configuration
        self.zoom_level = connection_manager.config_manager.get_float_setting(
            self._config_keys["zoom_level"], 10.0
        )

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()

        # Connect to JACK signals
        jack_service = get_jack_service()
        jack_service.port_added.connect(self.on_port_added_or_removed)
        jack_service.port_removed.connect(self.on_port_added_or_removed)
        jack_service.client_removed.connect(self.on_client_removed)
        jack_service.connection_made.connect(self.on_connection_changed)
        jack_service.connection_broken.connect(self.on_connection_changed)

        # Initial refresh
        self.refresh_matrix()

    def set_node_visibility_manager(
        self, node_visibility_manager: "NodeVisibilityManager"
    ) -> None:
        """
        Set the node visibility manager for this widget.

        Args:
            node_visibility_manager: The NodeVisibilityManager instance
        """
        self.node_visibility_manager = node_visibility_manager
        self.model.set_node_visibility_manager(node_visibility_manager)
        # Refresh the matrix to apply visibility settings
        self.refresh_matrix()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create a single outer scroll area that contains the entire splitter
        self.main_scroll_area = QScrollArea()
        self.main_scroll_area.setWidgetResizable(
            True
        )  # Resize content to fit, but we'll override for scrolling
        self.main_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.main_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        # Create horizontal splitter for adjustable output label area
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(True)
        self.main_splitter.setHandleWidth(0)  # Make splitter handle invisible
        self.main_splitter.setStyleSheet(
            "QSplitter::handle { background-color: transparent; border: none; }"
        )  # Ensure complete invisibility
        self.main_splitter.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )

        # Left panel - Output labels (no individual scroll area)
        self.output_labels_widget = _OutputLabelsWidget(self)
        self.output_labels_widget.setMinimumWidth(
            20
        )  # Allow collapse but prevent disappearing

        # Right panel - Grid (no individual scroll area)
        self.matrix_widget = _MatrixGridWidget(self)

        # Add panels directly to splitter (no nested scroll areas)
        self.main_splitter.addWidget(self.output_labels_widget)
        self.main_splitter.addWidget(self.matrix_widget)

        # Set the splitter as the widget for the main scroll area
        self.main_scroll_area.setWidget(self.main_splitter)

        # Load and set splitter proportions from config - give more space to the matrix grid
        splitter_sizes_str = self.connection_manager.config_manager.get_str(
            self._config_keys["splitter_sizes"], "200,800"
        )
        try:
            sizes = [int(x.strip()) for x in splitter_sizes_str.split(",")]
            if len(sizes) == 2:
                self.main_splitter.setSizes(sizes)
            else:
                self.main_splitter.setSizes(
                    [200, 800]
                )  # Fallback to defaults - more space for grid
        except (ValueError, IndexError):
            self.main_splitter.setSizes(
                [200, 800]
            )  # Fallback to defaults - more space for grid

        # Connect splitter signals (only horizontal splitter)
        self.main_splitter.splitterMoved.connect(self._on_main_splitter_moved)

        layout.addWidget(self.main_scroll_area)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Install event filter on scroll area viewport to intercept Ctrl+scroll for zooming
        self.main_scroll_area.viewport().installEventFilter(self)

    def resizeEvent(self, event: Optional["QEvent"]) -> None:
        """Handle resize event to ensure proper layout."""
        super().resizeEvent(event)
        # Force the matrix widget to recalculate its size
        if hasattr(self, "matrix_widget"):
            self.matrix_widget.update_matrix()
            # Defer the call to prevent potential resize loops
            QTimer.singleShot(0, self._update_scroll_behavior)

    def keyPressEvent(self, event: "QEvent") -> None:
        from PyQt6.QtGui import QKeyEvent

        if isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_F:
                self.fullscreen_request_signal.emit()
                event.accept()
            elif event.key() == Qt.Key.Key_Escape:
                if self.window().isFullScreen():
                    self.fullscreen_request_signal.emit()
                event.accept()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj: Optional[QObject], event: Optional[QEvent]) -> bool:
        """Intercept Ctrl+scroll wheel events on the scroll area viewport for zooming."""
        if event is not None and event.type() == QEvent.Type.Wheel:
            from PyQt6.QtGui import QWheelEvent

            if isinstance(event, QWheelEvent) and (
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                if event.angleDelta().y() > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True  # Consume the event
        return super().eventFilter(obj, event)

    def _on_main_splitter_moved(self, pos: int, index: int) -> None:
        """Handle main splitter movement to update output label truncation and save position."""
        # Update output labels when main splitter moves (changes output label width)
        self.output_labels_widget._calculate_truncation_lengths()
        self.output_labels_widget.update()

        # Save splitter sizes to config
        sizes = self.main_splitter.sizes()
        if len(sizes) == 2:
            sizes_str = f"{sizes[0]},{sizes[1]}"
            self.connection_manager.config_manager.set_str(
                self._config_keys["splitter_sizes"], sizes_str
            )

    def _is_dark_mode(self) -> bool:
        """Check if the current theme is dark mode."""
        window_color = self.palette().color(QPalette.ColorRole.Window)
        return (
            window_color.red() + window_color.green() + window_color.blue()
        ) / 3 < 128

    def refresh_matrix(self) -> None:
        """Refresh the entire matrix by reloading ports and connections."""
        self.model.load_ports(self._is_dark_mode())
        self.model.load_connections()
        self.matrix_widget.update_matrix()
        self.output_labels_widget.update_labels()
        # Update scroll behavior so scrollbars adjust to new grid size
        # when ports are added/removed without needing a zoom or resize.
        QTimer.singleShot(0, self._update_scroll_behavior)

    def is_connected(self, output_port: str, input_port: str) -> bool:
        """Check if two ports are connected."""
        return self.model.is_connected(output_port, input_port)

    def toggle_connection(self, output_port: str, input_port: str) -> None:
        """Toggle the connection between two ports."""
        connected = self.is_connected(output_port, input_port)
        handler = self.connection_manager.jack_handler

        if self.port_type == "midi":
            if connected:
                handler.break_midi_connection(output_port, input_port)
            else:
                handler.make_midi_connection(output_port, input_port)
        else:
            if connected:
                handler.break_connection(output_port, input_port)
            else:
                handler.make_connection(output_port, input_port)

    def on_port_added_or_removed(
        self,
        port_name: str,
        client_name: Optional[str] = None,
        port_flags: Any = None,
        port_type: Optional[str] = None,
        is_input: Optional[bool] = None,
    ) -> None:
        """Handle port addition/removal events."""
        should_refresh = False

        if port_type == self.port_type:
            should_refresh = True
        elif port_name and self._jack_service.client:
            try:
                kwarg = (
                    {"is_midi": True}
                    if self.port_type == "midi"
                    else {"is_audio": True}
                )
                should_refresh = any(
                    p.name == port_name for p in self._jack_service.get_ports(**kwarg)
                )
            except Exception:
                # If we can't get ports (e.g., JackError), assume it's related to be safe
                should_refresh = True

        if should_refresh:
            QTimer.singleShot(10, self.refresh_matrix)  # Debounce updates

    def on_client_removed(self, client_name: str) -> None:
        """Handle client removal events."""
        QTimer.singleShot(10, self.refresh_matrix)  # Debounce updates

    def on_connection_changed(self, output_port: str, input_port: str) -> None:
        """Handle connection change events."""
        # Check if this affects our port type's connections
        is_relevant_connection = False
        try:
            kwarg = (
                {"is_midi": True, "is_output": True}
                if self.port_type == "midi"
                else {"is_audio": True, "is_output": True}
            )
            if any(
                p.name == output_port for p in self._jack_service.get_ports(**kwarg)
            ):
                is_relevant_connection = True
        except Exception as e:
            logger.warning(
                f"Could not check {self.port_type.upper()} port status for connection change: {e}"
            )

        if is_relevant_connection:
            QTimer.singleShot(10, self.refresh_matrix)  # Debounce updates

    def reshuffle_colors(self) -> None:
        """Reshuffle client colors."""
        self.model.reshuffle_colors()
        self.refresh_matrix()

    def zoom_in(self) -> None:
        """Increase zoom level."""
        max_zoom = 20.0
        zoom_step = 0.25
        if self.zoom_level < max_zoom:
            self.zoom_level = min(self.zoom_level + zoom_step, max_zoom)
            self.connection_manager.config_manager.set_float_setting(
                self._config_keys["zoom_level"], self.zoom_level
            )
            self.matrix_widget.font_size = int(self.zoom_level)
            self.matrix_widget.client_name_font_size = int(self.zoom_level) + 2
            self.matrix_widget.grid_cell_scaling = self._calculate_grid_scaling(
                self.zoom_level
            )
            self.output_labels_widget.font_size = int(self.zoom_level)
            self.output_labels_widget.client_name_font_size = int(self.zoom_level) + 2
            self.refresh_matrix()
            QTimer.singleShot(0, self._update_scroll_behavior)

    def zoom_out(self) -> None:
        """Decrease zoom level."""
        min_zoom = 4.0
        zoom_step = 0.25
        if self.zoom_level > min_zoom:
            self.zoom_level = max(self.zoom_level - zoom_step, min_zoom)
            self.connection_manager.config_manager.set_float_setting(
                self._config_keys["zoom_level"], self.zoom_level
            )
            self.matrix_widget.font_size = int(self.zoom_level)
            self.matrix_widget.client_name_font_size = int(self.zoom_level) + 2
            self.matrix_widget.grid_cell_scaling = self._calculate_grid_scaling(
                self.zoom_level
            )
            self.output_labels_widget.font_size = int(self.zoom_level)
            self.output_labels_widget.client_name_font_size = int(self.zoom_level) + 2
            self.refresh_matrix()
            QTimer.singleShot(0, self._update_scroll_behavior)

    def _calculate_grid_scaling(self, zoom_level: float) -> float:
        """Calculate grid cell scaling factor based on zoom level."""
        # Base zoom level is 10, base minimum size is 35px
        # Scale proportionally
        base_zoom = 10.0
        base_size = 35.0

        # Scale factor: at zoom 10 = 1.0, zoom 6 = 0.6, zoom 20 = 2.0
        scale_factor = zoom_level / base_zoom

        # Apply scaling but ensure minimum size stays reasonable
        return max(scale_factor, 0.3)

    def _update_scroll_behavior(self) -> None:
        """Update scroll area behavior based on content size vs viewport size."""
        if not hasattr(self, "main_scroll_area") or not hasattr(self, "main_splitter"):
            return

        # Calculate proper minimum size accounting for angled input labels
        proper_min_size = self._calculate_proper_minimum_size()

        # Explicitly set the minimum size of the splitter. This is the key.
        # It forces the splitter to have a minimum size that reflects its content.
        self.main_splitter.setMinimumSize(proper_min_size)

        # Get the scroll area's viewport size
        viewport_size = self.main_scroll_area.viewport().size()

        # Check if content exceeds viewport in either dimension
        content_too_large = (
            proper_min_size.width() > viewport_size.width()
            or proper_min_size.height() > viewport_size.height()
        )

        # If content is too large, disable widget resizing to show scrollbars.
        # The scroll area will then respect the splitter's minimum size.
        # If content fits, enable widget resizing to fill the space.
        self.main_scroll_area.setWidgetResizable(not content_too_large)

    def _calculate_proper_minimum_size(self) -> "QSize":
        """Calculate the proper minimum size for the splitter accounting for angled input labels."""
        if (
            not hasattr(self, "main_splitter")
            or not hasattr(self, "output_labels_widget")
            or not hasattr(self, "matrix_widget")
        ):
            return QSize(200, 200)

        # Get the output labels widget's current width from the splitter
        splitter_sizes = self.main_splitter.sizes()
        output_min_width = (
            splitter_sizes[0]
            if splitter_sizes
            else self.output_labels_widget.minimumWidth()
        )

        # Get the matrix widget minimum size
        matrix_min_size = self.matrix_widget.minimumSize()

        # Calculate total width: output labels + matrix + some padding for angled labels
        total_width = (
            output_min_width
            + matrix_min_size.width()
            + self.style_config.horizontal_padding
        )

        # Height is determined by the taller of the two widgets
        total_height = (
            max(self.output_labels_widget.minimumHeight(), matrix_min_size.height())
            + self.style_config.vertical_padding
        )

        return QSize(total_width, total_height)


# Backward compatibility aliases
MIDIMatrixWidget = MatrixWidget
AudioMatrixWidget = MatrixWidget
