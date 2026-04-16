# cable_core/app_config.py
"""
Application constants, version, and shared configuration values.
"""

import os
import sys
from typing import Optional

from PyQt6.QtGui import QIcon

# --- Application Version ---
APP_VERSION = "0.10.5"

# --- Shared Constants ---
EDIT_LIST_TEXT = "Edit List..."


def load_app_icon(icon_name: str = "jack-plug.svg", theme_name: str = "jack-plug") -> Optional[QIcon]:
    """Load the application icon, checking frozen/script dir then theme."""
    app_icon = None

    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))

    local_icon_path = os.path.join(base_path, icon_name)
    if os.path.exists(local_icon_path):
        app_icon = QIcon(local_icon_path)
        if app_icon.isNull():
            app_icon = None

    if app_icon is None:
        theme_icon = QIcon.fromTheme(theme_name)
        if not theme_icon.isNull():
            app_icon = theme_icon

    return app_icon
# Main App Window (Cable.py) — first-launch defaults
MAIN_WINDOW_INITIAL_WIDTH = 474
MAIN_WINDOW_INITIAL_HEIGHT = 855

# Connection Manager Window (cables/connection_manager.py) — first-launch defaults
CONN_MANAGER_INITIAL_WIDTH = 1368
CONN_MANAGER_INITIAL_HEIGHT = 1000



# Connection View Width (cables/ui/tab_ui_manager.py)
CONNECTION_VIEW_INITIAL_WIDTH = 250

# PW-Top Tab Font Size (cables/ui/tab_ui_manager.py)
PWTOP_FONT_SIZE_PT = 13

# Connection Line Thickness (cables/connection_visualizer.py)
CONNECTION_LINE_THICKNESS = 2

# Graph View Settings (graph/main_window.py)
DEFAULT_UNTANGLE_VALUES = [2, 3, 4]

# Quantum/Sample Rate Confirmation Dialog Duration (milliseconds)
QUANTUM_SAMPLE_RATE_CONFIRMATION_DURATION_MS = 1500
