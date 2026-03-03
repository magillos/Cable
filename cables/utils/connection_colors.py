"""
Shared per-client connection color generation.

Used by both the Graph tab (ConnectionItem) and Audio/MIDI tabs (ConnectionVisualizer)
to produce deterministic, visually distinct colors based on JACK client names.
"""

import random
from PyQt6.QtGui import QColor


def get_client_color(client_name: str, dark_mode: bool = False) -> QColor:
    """Generate a deterministic color for a JACK client name.

    Args:
        client_name: The JACK client base name (e.g. 'PipeWire').
        dark_mode: If True, boost saturation/value for dark backgrounds.

    Returns:
        A QColor unique to the given client name.
    """
    random.seed(client_name)
    base_color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    if dark_mode:
        h, s, v, a = base_color.getHsvF()
        s = min(1.0, s * 1.4)
        v = min(1.0, v * 1.3)
        base_color.setHsvF(h, s, v, a)

    return base_color


def client_name_from_port(port_name: str) -> str:
    """Extract the client base name from a full JACK port name.

    Args:
        port_name: Full port name like 'ClientName:port_FL'.

    Returns:
        The client portion before the colon.
    """
    return port_name.rsplit(':', 1)[0]
