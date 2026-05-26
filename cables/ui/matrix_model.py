"""
MatrixModel - Unified data model for the matrix connection view (MIDI and Audio).

Manages port lists, connections, and client color assignments
independently of the UI rendering. Parameterized by port_type ('midi' or 'audio')
to handle both MIDI and Audio matrices in a single class.
"""

import random
import logging

from PyQt6.QtGui import QColor

from typing import TYPE_CHECKING, List, Tuple, Set, Dict, Optional, Any, Literal

if TYPE_CHECKING:
    from cables.jack_service import JackService
    from cables.features.node_visibility_manager import NodeVisibilityManager

logger = logging.getLogger(__name__)

PortType = Literal["midi", "audio"]


class MatrixModel:
    """Data model for matrix port connections and colors (MIDI or Audio)."""

    def __init__(
        self, jack_service: "JackService", port_type: PortType = "midi"
    ) -> None:
        self.jack_service = jack_service
        self.port_type = port_type
        self.node_visibility_manager: Optional["NodeVisibilityManager"] = None

        # Port data: lists of (client_name, port_name, display_name) tuples
        self.output_ports: List[Tuple[str, str, str]] = []
        self.input_ports: List[Tuple[str, str, str]] = []

        # Connection data: set of (output_port_name, input_port_name) tuples
        self.connections: Set[Tuple[str, str]] = set()

        # Color data
        self.client_colors: Dict[str, QColor] = {}
        self.color_generator = random.Random()
        self.color_seed_offset = 0

    def set_node_visibility_manager(
        self, node_visibility_manager: "NodeVisibilityManager"
    ) -> None:
        self.node_visibility_manager = node_visibility_manager

    def _get_ports_for_type(self) -> list:
        """Get JACK ports filtered by this model's port type."""
        if self.port_type == "midi":
            return list(self.jack_service.get_ports(is_midi=True))
        else:
            return list(self.jack_service.get_ports(is_audio=True))

    def _is_port_of_type(self, port: Any) -> bool:
        """Check if a port matches this model's port type."""
        if self.port_type == "midi":
            return port.is_midi
        else:
            return not port.is_midi

    def _is_port_visible(self, port_name: str, is_input: bool) -> bool:
        """Check if a port is visible using the node visibility manager."""
        if not self.node_visibility_manager:
            return True
        method_suffix = "input" if is_input else "output"
        method_name = f"is_{self.port_type}_matrix_{method_suffix}_visible"
        check_method = getattr(self.node_visibility_manager, method_name, None)
        if check_method:
            return check_method(port_name)
        return True

    def load_ports(self, is_dark_mode: Optional[bool] = None) -> None:
        """Load ports from JACK and organize them by client."""
        if is_dark_mode is None:
            from cable_core.theme import get_theme_manager
            is_dark_mode = get_theme_manager().is_dark_mode()
        self.output_ports = []
        self.input_ports = []
        self.client_colors = {}

        try:
            # Get ports of this type
            ports = []
            if self.jack_service.client:
                ports = self._get_ports_for_type()

            # Group ports by client and filter by visibility
            client_ports: Dict[str, Dict[str, list]] = {}
            for port in ports:
                client_name = (
                    port.name.split(":", 1)[0] if ":" in port.name else port.name
                )
                port_name = port.name

                # Check visibility if manager is available
                if not self._is_port_visible(port_name, port.is_input):
                    continue

                if client_name not in client_ports:
                    client_ports[client_name] = {"inputs": [], "outputs": []}
                client_ports[client_name][
                    "inputs" if port.is_input else "outputs"
                ].append(port.name)

            from cables.utils.sort_utils import natural_sort_key_for_full_port_name
            # Sort clients
            sorted_clients = sorted(client_ports.keys(), key=natural_sort_key_for_full_port_name)

            # Assign colors
            self._assign_client_colors(sorted_clients, client_ports, is_dark_mode)

            # Organize ports for matrix display
            for client_name in sorted_clients:
                client_data = client_ports[client_name]

                # Add client color
                self.client_colors[client_name] = client_data["color"]

                # Add output ports (vertical axis)
                for port_name in sorted(client_data["outputs"], key=natural_sort_key_for_full_port_name):
                    full_display_name = (
                        port_name.split(":", 1)[1] if ":" in port_name else port_name
                    )
                    display_name = full_display_name
                    self.output_ports.append((client_name, port_name, display_name))

                # Add input ports (horizontal axis)
                for port_name in sorted(client_data["inputs"], key=natural_sort_key_for_full_port_name):
                    full_display_name = (
                        port_name.split(":", 1)[1] if ":" in port_name else port_name
                    )
                    display_name = full_display_name
                    self.input_ports.append((client_name, port_name, display_name))

            # Reverse the entire input ports order
            self.input_ports = self.input_ports[::-1]

        except Exception as e:
            logger.error(f"Error loading {self.port_type.upper()} ports: {e}")

    def load_connections(self) -> None:
        """Load current connections for this port type."""
        self.connections = set()
        try:
            if not self.jack_service.client:
                return

            for output_port in self.output_ports:
                port_name = output_port[1]  # port_name
                connections = self.jack_service.get_all_connections(port_name)
                for input_port in connections:
                    if self._is_port_of_type(input_port):
                        input_port_name = input_port.name
                        # Find if this input port is in our matrix
                        for input_tuple in self.input_ports:
                            if input_tuple[1] == input_port_name:  # port_name match
                                self.connections.add((port_name, input_port_name))
                                break
        except Exception as e:
            logger.error(f"Error loading connections: {e}")

    def is_connected(self, output_port: str, input_port: str) -> bool:
        """Check if two ports are connected."""
        return (output_port, input_port) in self.connections

    def reshuffle_colors(self) -> None:
        """Reshuffle client colors (requires reload to take effect)."""
        self.color_seed_offset = self.color_generator.randint(0, 10000)

    def _assign_client_colors(
        self,
        sorted_clients: List[str],
        client_ports: Dict[str, Any],
        is_dark_mode: bool = False,
    ) -> None:
        """Assign unique colors to clients."""
        palette = self._get_color_palette(is_dark_mode)
        used_indices = set()

        for client_name in sorted_clients:
            # Generate a consistent starting index for this client
            hash_value = hash(client_name) + self.color_seed_offset
            # Ensure positive index
            start_index = abs(hash_value) % len(palette)

            index = start_index
            # Linear probe to find unused color
            attempts = 0
            while index in used_indices and attempts < len(palette):
                index = (index + 1) % len(palette)
                attempts += 1

            # Assign color
            client_ports[client_name]["color"] = palette[index]
            used_indices.add(index)

    def _get_color_palette(self, is_dark_mode: Optional[bool] = None) -> List[QColor]:
        """Get the color palette based on the theme."""
        if is_dark_mode is None:
            from cable_core.theme import get_theme_manager
            is_dark_mode = get_theme_manager().is_dark_mode()
        if is_dark_mode:
            return [
                QColor(255, 128, 0),  # Bright orange
                QColor(255, 255, 0),  # Bright yellow
                QColor(0, 255, 0),  # Bright green
                QColor(0, 255, 255),  # Bright cyan
                QColor(255, 0, 255),  # Bright magenta
                QColor(255, 255, 255),  # White
                QColor(255, 192, 203),  # Pink
                QColor(255, 165, 0),  # Orange
                QColor(173, 216, 230),  # Light blue
                QColor(144, 238, 144),  # Light green
                QColor(255, 182, 193),  # Light pink
                QColor(240, 230, 140),  # Khaki
                QColor(255, 215, 0),  # Gold
                QColor(255, 99, 71),  # Tomato
                QColor(127, 255, 212),  # Aquamarine
                QColor(220, 20, 60),  # Crimson
                QColor(173, 255, 47),  # GreenYellow
                QColor(255, 105, 180),  # HotPink
                QColor(0, 250, 154),  # MediumSpringGreen
                QColor(255, 140, 0),  # DarkOrange
            ]
        else:
            colors = []
            count = 20
            for i in range(count):
                hue = int(i * 360 / count)
                saturation = 200 + (i % 3) * 20
                value = 80 + (i % 2) * 50
                colors.append(QColor.fromHsv(hue, saturation, value))
            return colors
