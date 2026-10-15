"""Window-geometry persistence helpers extracted from JackConnectionManager.

Two small functions that read/write the serialized main-window geometry to
the config store. Kept dependency-light (``window`` is duck-typed) so they
can be unit-tested with a stub QMainWindow.
"""

import base64
from typing import Any

from cable_core import app_config
from cable_core import config_keys as keys


def restore_window_geometry(window: Any, config_manager: Any) -> None:
    """Restore saved window geometry, or apply first-launch defaults."""
    saved = config_manager.get_str_setting(keys.CONN_MANAGER_GEOMETRY, "")
    if saved:
        from PyQt6.QtCore import QByteArray

        window.restoreGeometry(QByteArray(base64.b64decode(saved)))
    else:
        window.resize(
            app_config.CONN_MANAGER_INITIAL_WIDTH,
            app_config.CONN_MANAGER_INITIAL_HEIGHT,
        )


def save_window_geometry(window: Any, config_manager: Any) -> None:
    """Persist current window geometry to config."""
    data = base64.b64encode(bytes(window.saveGeometry())).decode("ascii")
    config_manager.set_str_setting(keys.CONN_MANAGER_GEOMETRY, data)
