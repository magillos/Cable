import os

class AutostartManager:
    """Manages autostart functionality using XDG autostart"""
    def __init__(self, flatpak_env=False):
        self.autostart_dir = os.path.expanduser("~/.config/autostart")
        self.desktop_file = os.path.join(self.autostart_dir, "cable-autostart.desktop")

        # Set the appropriate Exec line based on environment
        exec_line = "/usr/bin/flatpak run com.github.magillos.cable --minimized" if flatpak_env else "pw-jack cable --minimized"

        self.desktop_content = f"""[Desktop Entry]
Type=Application
Name=Cable
Exec={exec_line}
Icon=jack-plug
Terminal=false
X-GNOME-Autostart-enabled=true"""

    def enable_autostart(self):

        try:
            os.makedirs(self.autostart_dir, exist_ok=True)
            with open(self.desktop_file, 'w') as f:
                f.write(self.desktop_content)
            os.chmod(self.desktop_file, 0o755)
            return True
        except Exception as e:
            print(f"Error enabling autostart: {e}")
            return False

    def disable_autostart(self):

        try:
            if os.path.exists(self.desktop_file):
                os.remove(self.desktop_file)
            return True
        except Exception as e:
            print(f"Error disabling autostart: {e}")
            return False

    def is_autostart_enabled(self):

        return os.path.exists(self.desktop_file)