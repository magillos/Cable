import dbus
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer
import configparser # Needed for perform_reload
import os # Needed for perform_reload

class SystemManager:
    def __init__(self, app):
        """
        Initializes the SystemManager.

        Args:
            app: The main PipeWireSettingsApp instance.
        """
        self.app = app

    def confirm_restart_wireplumber(self):
        reply = QMessageBox.question(self.app, 'Confirm Restart',
                                     "Are you sure you want to restart Wireplumber?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.restart_wireplumber()

    def confirm_restart_pipewire(self):
        reply = QMessageBox.question(self.app, 'Confirm Restart',
                                     "Are you sure you want to restart Pipewire?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.restart_pipewire()

    def _restart_systemd_service(self, service_name, service_display_name):
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

    def restart_wireplumber(self):
        self._restart_systemd_service('wireplumber', 'Wireplumber') # Internal call

    def restart_pipewire(self):
        self._restart_systemd_service('pipewire', 'Pipewire') # Internal call

    def reload_app_settings(self):
        # Schedule the reload after a short delay to allow services to fully restart
        QTimer.singleShot(1000, self.perform_reload) # Internal call

    def perform_reload(self):
        # Reload all settings and update UI
        # Use pipewire_manager for these calls
        self.app.pipewire_manager.load_current_settings()
        self.app.pipewire_manager.load_devices()
        self.app.pipewire_manager.load_nodes()

        # Reset device and node selections
        self.app.device_combo.setCurrentIndex(0)
        self.app.node_combo.setCurrentIndex(0)

        # Clear profile and latency input
        self.app.profile_combo.clear()
        self.app.latency_input.clear()

        # If remember settings is enabled and we have saved values, restore them
        # without triggering saves
        if self.app.remember_settings: # Use self.app.remember_settings
            config = configparser.ConfigParser()
            config_path = os.path.expanduser("~/.config/cable/config.ini")

            if os.path.exists(config_path):
                try:
                    config.read(config_path)

                    if 'DEFAULT' in config:
                        # Block signals during reload apply
                        self.app.quantum_combo.blockSignals(True)
                        self.app.sample_rate_combo.blockSignals(True)
                        try:
                            if 'saved_quantum' in config['DEFAULT']:
                                quantum = config['DEFAULT']['saved_quantum']
                                # Find or insert
                                index = self.app.quantum_combo.findText(quantum)
                                if index >= 0:
                                    self.app.quantum_combo.setCurrentIndex(index)
                                    self.app.last_valid_quantum_index = index
                                else: # Insert before "Edit List..."
                                    edit_item_index = self.app.quantum_combo.count() - 1
                                    if edit_item_index >= 0:
                                        self.app.quantum_combo.insertItem(edit_item_index, quantum)
                                        self.app.quantum_combo.setCurrentIndex(edit_item_index)
                                        self.app.last_valid_quantum_index = edit_item_index
                                        print(f"Inserted saved quantum '{quantum}' during reload.")
                                    else: print("Warning: Edit item not found in quantum_combo during reload")
                                self.app.apply_quantum_settings(skip_save=True)

                            if 'saved_sample_rate' in config['DEFAULT']:
                                sample_rate = config['DEFAULT']['saved_sample_rate']
                                # Find or insert
                                index = self.app.sample_rate_combo.findText(sample_rate)
                                if index >= 0:
                                    self.app.sample_rate_combo.setCurrentIndex(index)
                                    self.app.last_valid_sample_rate_index = index
                                else: # Insert before "Edit List..."
                                    edit_item_index = self.app.sample_rate_combo.count() - 1
                                    if edit_item_index >= 0:
                                        self.app.sample_rate_combo.insertItem(edit_item_index, sample_rate)
                                        self.app.sample_rate_combo.setCurrentIndex(edit_item_index)
                                        self.app.last_valid_sample_rate_index = edit_item_index
                                        print(f"Inserted saved sample rate '{sample_rate}' during reload.")
                                    else: print("Warning: Edit item not found in sample_rate_combo during reload")
                                # Use pipewire_manager for this call
                                self.app.pipewire_manager.apply_sample_rate_settings(skip_save=True)
                        finally:
                            self.app.quantum_combo.blockSignals(False)
                            self.app.sample_rate_combo.blockSignals(False)
                            self.app.update_latency_display() # Update latency after changes

                except Exception as e:
                    print(f"Error restoring saved settings during reload: {e}")