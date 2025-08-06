# cable_core/app_config.py

# --- Application Version ---
APP_VERSION = "0.9.13"
# Main App Window (Cable.py)
MAIN_WINDOW_MIN_WIDTH = 300
MAIN_WINDOW_MIN_HEIGHT = 600
MAIN_WINDOW_INITIAL_WIDTH = 474
MAIN_WINDOW_INITIAL_HEIGHT = 855

# Connection Manager Window (cables/connection_manager.py)
CONN_MANAGER_INITIAL_X = 100
CONN_MANAGER_INITIAL_Y = 100
CONN_MANAGER_INITIAL_WIDTH = 1368
CONN_MANAGER_INITIAL_HEIGHT = 1000

# Connection View Refresh Rates (cables/connection_manager.py)
REFRESH_RATE_FOCUSED_MS = 1
REFRESH_RATE_UNFOCUSED_MS = 100
REFRESH_RATE_SPECIAL_TABS_MS = 1000

# Connection View Width (cables/ui/tab_ui_manager.py)
CONNECTION_VIEW_INITIAL_WIDTH = 250

# PW-Top Tab Font Size (cables/ui/tab_ui_manager.py)
PWTOP_FONT_SIZE_PT = 13

# Graph View Settings (graph/main_window.py)
DEFAULT_UNTANGLE_VALUES = [3, 4, 5, 2]
