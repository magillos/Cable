"""
System-level operations: session restart via D-Bus (logout/reboot/shutdown).
"""

import dbus
from PyQt6.QtWidgets import QMessageBox, QWidget
from PyQt6.QtCore import QTimer

import logging
logger = logging.getLogger(__name__)

class SystemManager:
    def __init__(self, app: QWidget) -> None:
        """
        Initializes the SystemManager.

        Args:
            app: The main PipeWireSettingsApp instance.
        """
        self.app = app

    def confirm_restart_wireplumber(self) -> None:
        reply = QMessageBox.question(self.app, 'Confirm Restart',
                                     "Are you sure you want to restart Wireplumber?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.restart_wireplumber()

    def confirm_restart_pipewire(self) -> None:
        reply = QMessageBox.question(self.app, 'Confirm Restart',
                                     "Are you sure you want to restart Pipewire?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.restart_pipewire()

    def _restart_systemd_service(self, service_name: str, service_display_name: str) -> bool:
        """Helper method to restart a systemd user service via DBus."""
        try:
            bus = dbus.SessionBus()  # Connect to the session bus for user services
            systemd_user = bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
            manager = dbus.Interface(systemd_user, 'org.freedesktop.systemd1.Manager')
            manager.RestartUnit(f'{service_name}.service', 'replace') # Use service name without --user
            QMessageBox.information(self.app, "Success", f"{service_display_name} restarted successfully")
            self.reload_app_settings() # Internal call
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name()
            error_message = str(e)
            error_title = f"Error restarting {service_display_name}"
            detailed_message = f"{error_title}:\n"

            if "org.freedesktop.DBus.Error.UnknownObject" in error_name:
                detailed_message += ("Systemd user manager not found.\n"
                                     "This might be due to Flatpak sandboxing restrictions.\n")
            elif "org.freedesktop.systemd1.Error.UnitNotFound" in error_name:
                detailed_message += (f"{service_display_name} user service not found.\n"
                                     f"Ensure {service_display_name} is installed and the user service is enabled.\n")
            elif "org.freedesktop.systemd1.Error.Failed" in error_name:
                 detailed_message += ("Restart operation failed.\n"
                                      f"Check {service_display_name} logs for more details.\n")
            else: # General DBus error
                 detailed_message += "A DBus error occurred.\n"

            detailed_message += f"Details: {error_message}"
            QMessageBox.critical(self.app, "Error", detailed_message)
            return False
        except Exception as e: # Catch other potential errors
             QMessageBox.critical(self.app, "Error", f"An unexpected error occurred while restarting {service_display_name}: {e}")
             return False

    def restart_wireplumber(self) -> None:
        self._restart_systemd_service('wireplumber', 'Wireplumber') # Internal call

    def restart_pipewire(self) -> None:
        self._restart_systemd_service('pipewire', 'Pipewire') # Internal call

    def reload_app_settings(self) -> None:
        # Schedule the reload after a short delay to allow services to fully restart
        QTimer.singleShot(1000, self.perform_reload) # Internal call

    def perform_reload(self) -> None:
        self.app._apply_current_settings()
        self.app._apply_devices()
        self.app._apply_nodes()
        self.app.reload_after_service_restart()