"""
Visual constants for graph rendering — node dimensions, colors, fonts, and spacing.
"""

from PyQt6.QtGui import QColor

# --- Constants ---
NODE_WIDTH = 180
NODE_TITLE_HEIGHT = 35  # Increased to allow for ~2 lines of text
PORT_HEIGHT = 18
PORT_WIDTH_MIN = 90  # Minimum port width, will expand based on text length
PORT_MARGIN = 4
NODE_PADDING = 5
PORT_LABEL_OFFSET = 5
NODE_VMARGIN = 5  # Vertical margin inside node between title/ports/ports
NODE_CONTENT_PADDING = (
    1  # Inset for ports/bulk areas to avoid overlapping the node border
)

PORT_DRAG_COLOR = QColor(100, 200, 255, 150)
CONNECTION_COLOR = QColor(80, 150, 220)  # Slightly darker blue for normal connections
CONNECTION_WIDTH = 1.5
CONNECTION_HIGHLIGHT_WIDTH = 3.0
CONNECTION_HIGHLIGHT_COLOR = QColor(
    170, 230, 255
)  # Brighter blue for highlighted connections
DEFAULT_CONNECTION_FACTOR = 0.5  # Default Bezier curve factor
SELF_CONNECTION_FACTOR = (
    0.85  # Bezier curve factor for self-connections (node to itself)
)
NODE_BG_COLOR = QColor(45, 45, 45)
NODE_BORDER_COLOR = QColor(80, 80, 80)
NODE_TITLE_COLOR = QColor(210, 210, 210)
PORT_TEXT_COLOR = QColor(190, 190, 190)
PORT_AUDIO_COLOR = QColor("#6574aa")
PORT_DISCONNECT_DRAG_COLOR = QColor(
    220, 80, 80, 200
)  # Color for the drag line during disconnect
PORT_MIDI_COLOR = QColor("#840911")
PORT_OTHER_COLOR = QColor(150, 150, 150)
PORT_DRAG_HIGHLIGHT_COLOR = QColor(224, 128, 0)  # Dirty Orange for drag hover
DEFAULT_DRAG_LINE_COLOR = QColor(
    255, 255, 255, 200
)  # Semi-transparent white for initial drag line

HOVER_HIGHLIGHT_COLOR = QColor("#728dc1")  # Custom hover color
SELECTION_COLOR = QColor(
    70, 130, 180, 100
)  # Steel Blue, semi-transparent for port fill
SELECTION_BORDER_COLOR = QColor(
    100, 180, 255
)  # Similar to connection color but maybe brighter/different
# Bulk Connection Areas (per-pair)
NODE_BULK_AREA_HEIGHT = (
    15  # Legacy — kept for backward compat; prefer NODE_BULK_PAIR_AREA_HEIGHT
)
NODE_BULK_PAIR_AREA_HEIGHT = 12  # Height of per-pair bulk areas
NODE_BULK_AREA_COLOR = QColor(60, 60, 60, 180)  # Semi-transparent dark grey
NODE_BULK_AREA_HOVER_COLOR = QColor(85, 85, 85, 220)  # Slightly lighter on hover
NODE_BULK_AREA_HPADDING = 3  # Horizontal padding inside the port width area
NODE_BULK_GROUP_BORDER_OPACITY = (
    1  # Opacity of the subtle enclosure border around bulk groups
)
NODE_BULK_GROUP_BORDER_RADIUS = 1  # Corner radius for the enclosure rounded rect
NODE_BULK_GROUP_BORDER_WIDTH = 0.35  # Line thickness of the enclosure border
NODE_BULK_SEPARATOR_GAP = 1  # Extra vertical gap at bulk↔non-bulk boundaries


# Suffixes for Stereo Pair Matching during Node-on-Node drop
STEREO_LEFT_SUFFIXES = ["left", "_L", "_FL", "_SL", "_RL", "_1"]
STEREO_RIGHT_SUFFIXES = ["right", "_R", "_FR", "_SR", "_RR", "_2"]
# Suffixes for split node display names
SPLIT_INPUT_SUFFIX = " (Inputs)"
SPLIT_OUTPUT_SUFFIX = " (Outputs)"

# Node Horizontal Spacing (e.g. between split parts)
NODE_HSPACING = 30

# Minimum spacing between nodes for layout and overlap prevention
MIN_NODE_H_SPACING = 10.0
MIN_NODE_V_SPACING = 10.0

# Node push-away animation settings
PUSH_AWAY_ANIMATION_DURATION = 200  # milliseconds
PUSH_AWAY_ANIMATION_ENABLED = True  # Set to False for instant movement

# Layout transition animation settings (when applying automatic layouts)
LAYOUT_ANIMATION_ENABLED = True
LAYOUT_ANIMATION_DURATION = 220  # milliseconds
LAYOUT_ANIMATION_EASING = "OutCubic"  # QEasingCurve.Type name
LAYOUT_ANIMATION_MIN_DISTANCE = 6.0  # pixels

# General animation defaults
ANIMATION_DEFAULT_DURATION = 150  # milliseconds
ANIMATION_DEFAULT_EASING = "OutQuad"  # QEasingCurve.Type name

# UI Layout Fine-tuning
GRAPH_TOOLBAR_UNDO_REDO_OFFSET = (
    -65
)  # Adjust to shift Undo/Redo buttons in Graph tab toolbar, e.g., 10 or -10

# Padding for the QGraphicsView sceneRect to prevent items from touching edges
VIEW_PADDING = 50

# Hover tooltip delay for matrix grid cells (milliseconds)
HOVER_TOOLTIP_DELAY = 500
