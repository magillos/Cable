"""
XDG autostart management for launching Cable on login.
"""

import os
from typing import Optional

import logging
logger = logging.getLogger(__name__)

class AutostartManager:
    """Manages autostart functionality using XDG autostart"""
    def __init__(self, flatpak_env: bool = False, appimage_path: Optional[str] = None) -> None:
        self.autostart_dir = os.path.expanduser("~/.config/autostart")
        self.desktop_file = os.path.join(self.autostart_dir, "cable-autostart.desktop")
        self.appimage_path = appimage_path

        # Set the appropriate Exec line based on environment
        if appimage_path:
            # For AppImage, use the full path to the AppImage with --minimized
            exec_line = f"{appimage_path} --minimized"
        elif flatpak_env:
            exec_line = "/usr/bin/flatpak run com.github.magillos.cable --minimized"
        else:
            exec_line = "pw-jack cable --minimized"

        self.desktop_content = f"""[Desktop Entry]
Type=Application
Name=Cable
Exec={exec_line}
Icon=jack-plug
Terminal=false
X-GNOME-Autostart-enabled=true"""

    def enable_autostart(self) -> bool:

        try:
            os.makedirs(self.autostart_dir, exist_ok=True)
            with open(self.desktop_file, 'w') as f:
                f.write(self.desktop_content)
            os.chmod(self.desktop_file, 0o755)
            return True
        except Exception as e:
            logger.error(f"Error enabling autostart: {e}")
            return False

    def disable_autostart(self) -> bool:

        try:
            if os.path.exists(self.desktop_file):
                os.remove(self.desktop_file)
            return True
        except Exception as e:
            logger.error(f"Error disabling autostart: {e}")
            return False

    def is_autostart_enabled(self) -> bool:

        return os.path.exists(self.desktop_file)