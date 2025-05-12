"""
PresetHandler - Handles preset loading, saving, and management
"""

from PyQt6.QtWidgets import QMenu, QMessageBox, QWidgetAction, QLineEdit
from PyQt6.QtCore import QPoint, QTimer, QProcess
from PyQt6.QtGui import QKeySequence, QAction, QActionGroup

from cables.utils.helpers import show_timed_messagebox

class PresetHandler:
    """
    Handles preset management functionality including loading, saving, and UI interactions.
    """
    def __init__(self, manager):
        """
        Initialize the PresetHandler.
        
        Args:
            manager: Reference to the JackConnectionManager
        """
        self.manager = manager  # Reference to JackConnectionManager
        # Initialize preset state from config manager
        self.startup_preset_name = self.manager.config_manager.get_str('startup_preset')
        # Initialize current_preset_name based on the last run's active preset
        self.current_preset_name = self.manager.config_manager.get_str('active_preset')
        # Temporary attribute for the save preset name line edit in the menu
        self._preset_menu_name_edit = None

    def _show_preset_menu(self):
        """Populates the preset management menu. Assumes menu is sender()."""
        menu = self.manager.sender() # Get the menu that emitted aboutToShow
        if not menu or not isinstance(menu, QMenu):
            print("Error: _show_preset_menu called without a valid QMenu sender.")
            return
        
        menu.clear() # Clear previous items before repopulating
        
        preset_names = self.manager.preset_manager.get_preset_names()

        # --- Save Section ---
        # Use a temporary attribute to hold the line edit for the save action
        self._preset_menu_name_edit = QLineEdit()
        self._preset_menu_name_edit.setPlaceholderText("Enter New Preset Name...")
        self._preset_menu_name_edit.returnPressed.connect(self._save_current_preset_from_menu)  # Connect Enter key
        self._preset_menu_name_edit.setMinimumWidth(200)  # Give it some space
        
        # Apply similar styling as filter edits
        filter_style = f"""
            QLineEdit {{
                background-color: {self.manager.background_color.name()};
                color: {self.manager.text_color.name()};
                border: 1px solid {self.manager.text_color.name()};
                padding: 2px;
                border-radius: 3px;
            }}
        """
        self._preset_menu_name_edit.setStyleSheet(filter_style)

        name_action = QWidgetAction(menu)
        name_action.setDefaultWidget(self._preset_menu_name_edit)
        menu.addAction(name_action)

        save_action = QAction("Save Current as New Preset", menu)
        save_action.triggered.connect(self._save_current_preset_from_menu)
        menu.addAction(save_action)

        # --- Add "Save" action for currently loaded preset ---
        save_loaded_action = QAction("Save", menu)
        save_loaded_action.setShortcut(QKeySequence("Ctrl+S"))
        save_loaded_action.setEnabled(bool(self.current_preset_name))
        save_loaded_action.triggered.connect(self._save_current_loaded_preset)
        menu.addAction(save_loaded_action)
        # --- End Add "Save" action ---

        menu.addSeparator()

        # --- Load Section ---
        load_menu = menu.addMenu("Load Preset")  # Create menu even if no presets exist

        # --- MODIFICATION START ---
        # Add the global "Default" action from ActionManager
        if hasattr(self.manager, 'action_manager') and \
           hasattr(self.manager.action_manager, 'default_preset_action') and \
           self.manager.action_manager.default_preset_action:
            load_menu.addAction(self.manager.action_manager.default_preset_action)
        else:
            # Fallback or error logging if the action isn't found
            error_action = QAction("Default (Action Init Error)", load_menu)
            error_action.setEnabled(False)
            load_menu.addAction(error_action)
            print("Error: Could not find global default_preset_action in PresetHandler.")

        load_menu.addSeparator()  # Add separator after "Default"
        # --- MODIFICATION END ---

        if preset_names:
            for name in preset_names:
                load_action = QAction(name, load_menu)
                # Highlight if this is the currently active preset
                if name == self.current_preset_name:
                    font = load_action.font()
                    font.setBold(True)
                    load_action.setFont(font)
                # Use lambda to capture the correct name and call the new handler
                load_action.triggered.connect(lambda checked=False, n=name: self._handle_gui_preset_load(n))
                load_menu.addAction(load_action)
        else:
            no_load_action = QAction("No Saved Presets", menu)
            no_load_action.setEnabled(False)
            menu.addAction(no_load_action)

        # --- Delete Section ---
        if preset_names:
            menu.addSeparator()
            delete_menu = menu.addMenu("Delete Preset")
            for name in preset_names:
                delete_action = QAction(name, delete_menu)
                # Use lambda to capture the correct name for the slot
                delete_action.triggered.connect(lambda checked=False, n=name: self._delete_selected_preset(n))
                delete_menu.addAction(delete_action)

        # --- Startup Preset Section ---
        menu.addSeparator()
        startup_menu = menu.addMenu("Preset to load at (auto)start")
        startup_group = QActionGroup(startup_menu)  # Use QActionGroup for exclusivity
        startup_group.setExclusive(True)

        # Add "None" option
        none_action = QAction("None", startup_menu)
        none_action.setCheckable(True)
        none_action.setChecked(not self.startup_preset_name or self.startup_preset_name == 'None')
        none_action.triggered.connect(lambda checked=False: self._set_startup_preset(None))
        startup_menu.addAction(none_action)
        startup_group.addAction(none_action)  # Add to group
        startup_menu.addSeparator()  # Add spacer after 'None'

        # Add existing presets
        for name in preset_names:
            startup_action = QAction(name, startup_menu)
            startup_action.setCheckable(True)
            startup_action.setChecked(name == self.startup_preset_name)
            # Use lambda to capture the correct name
            startup_action.triggered.connect(lambda checked=False, n=name: self._set_startup_preset(n))
            startup_menu.addAction(startup_action)
            startup_group.addAction(startup_action)  # Add to group

        # Menu is now shown automatically by the QToolButton.
        # The positioning logic (button_to_use, menu.exec) is no longer needed here.
        # self._preset_menu_name_edit is handled because the QLineEdit is a child of the menu,
        # and the menu is cleared/repopulated on each aboutToShow.
        # If _save_current_preset_from_menu is not called, _preset_menu_name_edit might point
        # to a deleted widget if not careful, but it's reassigned at the start of _show_preset_menu
        # or when the QLineEdit is created.
        # The QLineEdit is created fresh each time, so self._preset_menu_name_edit is always updated.
        # No explicit cleanup of self._preset_menu_name_edit is needed here after menu.exec removal.

    def _save_current_preset_from_menu(self):
        """Saves the current connections using the name from the menu's line edit."""
        # Retrieve name from the temporary attribute holding the QLineEdit
        if not self._preset_menu_name_edit:  # Safety check
            print("Error: Preset menu name edit not found.")
            return
        preset_name = self._preset_menu_name_edit.text().strip()
        if not preset_name:
            QMessageBox.warning(self.manager, "Save Preset", "Enter a name for the preset.")
            return

        current_connections = self.manager._get_current_connections()
        if not current_connections:
            QMessageBox.information(self.manager, "Save Preset", "No connections to save.")
            return

        if self.manager.preset_manager.save_preset(preset_name, current_connections, self.manager):
            print(f"Preset '{preset_name}' saved.")
            show_timed_messagebox(self.manager, QMessageBox.Icon.Information, 
                                 "Preset Saved", f"Preset '{preset_name}' saved successfully.")

    def _set_startup_preset(self, name):
        """Sets the selected preset name as the startup preset in the config."""
        print(f"Setting startup preset to: {name}")
        self.startup_preset_name = name  # Update internal state
        # Save the actual preset name, or None (which ConfigManager saves as empty string)
        self.manager.config_manager.set_str('startup_preset', name)

    def _load_selected_preset(self, name, is_startup=False):
        """
        Loads the connections from the selected preset.
        Updates self.current_preset_name and returns True on success, False otherwise.
        is_startup flag prevents showing success message on startup load.
        """
        print(f"Loading preset: {name}")
        preset_connections = self.manager.preset_manager.get_preset(name)
        if preset_connections is None:
            if not is_startup:  # Only show message box in GUI mode
                QMessageBox.critical(self.manager, "Load Preset", f"Could not find preset '{name}'.")
            else:
                print(f"Error: Could not find preset '{name}'.")
            self.current_preset_name = None  # Clear preset name on failure
            self.manager.config_manager.set_str('active_preset', None)  # Clear in config too
            if hasattr(self.manager, 'save_preset_action'):  # Disable global save shortcut
                self.manager.save_preset_action.setEnabled(False)
            print("Load Fail: Cleared active_preset in config.")
            return False  # Indicate failure

        # 1. Get current connections
        current_connections = self.manager._get_current_connections()

        # 2. Disconnect all current connections
        print("Disconnecting existing connections...")
        connections_to_restore_on_error = []  # Keep track if disconnect fails mid-way
        try:
            for conn in current_connections:
                conn_type = conn.get("type", "audio")  # Default to audio if type missing
                output_name = conn.get("output")
                input_name = conn.get("input")
                if output_name and input_name:
                    connections_to_restore_on_error.append(conn)  # Add before attempting disconnect
                    print(f"  Disconnecting {output_name} -> {input_name} ({conn_type})")
                    self.manager.client.disconnect(output_name, input_name)
                    # Remove from restore list on success
                    connections_to_restore_on_error.pop()
        except Exception as e:
            print(f"Error during disconnection phase: {e}. Attempting to restore...")
            # Attempt to restore connections that were successfully disconnected before the error
            for restore_conn in connections_to_restore_on_error:
                try:
                    self.manager.client.connect(restore_conn["output"], restore_conn["input"])
                except Exception:
                    pass  # Ignore restore errors
            if not is_startup:
                QMessageBox.warning(self.manager, "Load Preset Error", 
                                   f"An error occurred disconnecting existing connections: {e}\nPreset loading aborted.")
            else:
                print(f"Error during disconnection phase: {e}. Preset loading aborted.")
            self.manager.refresh_ports()  # Refresh UI to show potentially restored state
            self.current_preset_name = None  # Clear preset name on failure
            self.manager.config_manager.set_str('active_preset', None)  # Clear in config too
            if hasattr(self.manager, 'save_preset_action'):  # Disable global save shortcut
                self.manager.save_preset_action.setEnabled(False)
            print("Load Fail (Disconnect): Cleared active_preset in config.")
            return False  # Indicate failure

        # 3. Connect preset connections
        print(f"Connecting preset '{name}' connections...")
        connections_made = []
        errors_occurred = False
        try:
            for conn in preset_connections:
                conn_type = conn.get("type", "audio")
                output_name = conn.get("output")
                input_name = conn.get("input")
                if output_name and input_name:
                    try:
                        print(f"  Connecting {output_name} -> {input_name} ({conn_type})")
                        # Check if ports exist before connecting
                        out_port_exists = any(p.name == output_name for p in 
                                             self.manager.client.get_ports(is_output=True, is_midi=(conn_type == "midi")))
                        in_port_exists = any(p.name == input_name for p in 
                                            self.manager.client.get_ports(is_input=True, is_midi=(conn_type == "midi")))

                        if out_port_exists and in_port_exists:
                            self.manager.client.connect(output_name, input_name)
                            connections_made.append(conn)  # Track successful connections
                        else:
                            print(f"    Skipping connection: Port(s) not found (Output: {out_port_exists}, Input: {in_port_exists})")
                            errors_occurred = True  # Flag that some connections were skipped

                    except Exception as e:
                        print(f"    Error connecting {output_name} -> {input_name}: {e}")
                        errors_occurred = True  # Flag that errors occurred

        except Exception as e:  # Catch broader errors during the connection loop setup itself
            print(f"Unexpected error during connection phase setup: {e}")
            if not is_startup:
                QMessageBox.critical(self.manager, "Load Preset Error", 
                                    f"An unexpected error occurred during connection phase: {e}\nPreset loading failed.")
            else:
                print(f"Unexpected error during connection phase: {e}. Preset loading failed.")
            self.manager.refresh_ports()
            self.current_preset_name = None  # Clear preset name on failure
            self.manager.config_manager.set_str('active_preset', None)  # Clear in config too
            if hasattr(self.manager, 'save_preset_action'):  # Disable global save shortcut
                self.manager.save_preset_action.setEnabled(False)
            print("Load Fail (Connect Exception): Cleared active_preset in config.")
            return False  # Indicate failure - This was a setup error, not a connection error

        # 4. Refresh UI and update state
        print("Preset load complete. Refreshing UI.")
        self.current_preset_name = name  # Set the current preset name on success/partial success
        self.manager.config_manager.set_str('active_preset', name)  # Save to config on success
        if hasattr(self.manager, 'save_preset_action'):  # Enable global save shortcut
            self.manager.save_preset_action.setEnabled(True)
        print(f"Load Success: Set active_preset in config to '{name}'")
        self.manager.refresh_ports()  # This updates visuals and button states

        if errors_occurred:
            # Only show message if not loading at startup
            if not is_startup:
                QMessageBox.information(self.manager, "Load Preset", 
                                       f"Preset '{name}' loaded, but some connections could not be made (ports might be missing).")
        else:
            # Only show message if not loading at startup
            if not is_startup:
                show_timed_messagebox(self.manager, QMessageBox.Icon.Information, 
                                     "Load Preset", f"Preset '{name}' loaded successfully.")

        return True  # Indicate success

    def _delete_selected_preset(self, name):
        """Deletes the selected preset after confirmation."""
        reply = QMessageBox.question(self.manager, 'Delete Preset',
                                    f"Are you sure you want to delete the preset '{name}'?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            if self.manager.preset_manager.delete_preset(name):
                print(f"Preset '{name}' deleted.")
                show_timed_messagebox(self.manager, QMessageBox.Icon.Information, 
                                     "Preset Deleted", f"Preset '{name}' deleted.")
                # If the deleted preset was the current one, clear it
                if name == self.current_preset_name:
                    self.current_preset_name = None
                    self.manager.config_manager.set_str('active_preset', None)
                    if hasattr(self.manager, 'save_preset_action'):  # Disable global save shortcut
                        self.manager.save_preset_action.setEnabled(False)
                    print("Cleared active_preset in config as current preset was deleted.")
                # If the deleted preset was the startup one, clear it
                if name == self.startup_preset_name:
                    self.startup_preset_name = None
                    self.manager.config_manager.set_str('startup_preset', None)
                    print("Cleared startup_preset in config as it was deleted.")
            else:
                QMessageBox.warning(self.manager, "Delete Preset", f"Could not find or delete preset '{name}'.")

    def _handle_gui_preset_load(self, name):
        """Handles loading a preset via the GUI menu click."""
        self._load_selected_preset(name)  # This updates self.current_preset_name and saves config

    def _handle_default_preset_action(self):
        """Handles the 'Default' preset action: disconnects all connections, then restarts the session manager."""
        reply = QMessageBox.question(self.manager, 'Confirm Reset',
                                    "This will disconnect all current connections and then restart WirePlumber"
                                    " to restore default connections.\n\n"
                                    "Do you want to proceed?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)  # Default to No

        if reply == QMessageBox.StandardButton.Yes:
            print("User confirmed default connection reset.")

            # --- Step 1: Disconnect All Connections ---
            print("Step 1: Disconnecting all existing JACK connections...")
            current_connections = self.manager._get_current_connections()
            disconnect_errors = []
            disconnected_count = 0

            if current_connections:
                for conn in current_connections:
                    output_name = conn.get("output")
                    input_name = conn.get("input")
                    if output_name and input_name:
                        try:
                            self.manager.client.disconnect(output_name, input_name)
                            disconnected_count += 1
                        except Exception as e:
                            print(f"    Unexpected error disconnecting {output_name} -> {input_name}: {e}")
                            disconnect_errors.append(f"{output_name} -> {input_name}: {e}")
                print(f"Step 1: Disconnected {disconnected_count} connections.")
                if disconnect_errors:
                    print(f"Step 1: Encountered unexpected errors during disconnection: {disconnect_errors}")
            else:
                print("Step 1: No active JACK connections found to disconnect.")

            # --- Step 2: Restart Session Manager ---
            print("Step 2: Restarting PipeWire session manager...")
            service_name = "wireplumber.service"  # Default to WirePlumber
            command = []
            if self.manager.flatpak_env:
                print(f"  Running in Flatpak environment. Using flatpak-spawn to restart {service_name}.")
                command = ["flatpak-spawn", "--host", "systemctl", "restart", "--user", service_name]
            else:
                print(f"  Running outside Flatpak environment. Using systemctl to restart {service_name}.")
                command = ["systemctl", "restart", "--user", service_name]

            print(f"  Executing command: {' '.join(command)}")
            success = QProcess.startDetached(command[0], command[1:])

            # --- Finalization ---
            # Clear the active preset regardless of restart success
            self.manager.config_manager.set_str('active_preset', None)
            self.current_preset_name = None
            if hasattr(self.manager, 'save_preset_action'):  # Disable global save shortcut
                self.manager.save_preset_action.setEnabled(False)
            print("Cleared active_preset in config after selecting 'Default'.")

            if success:
                print("Step 2: Session manager restart command initiated successfully.")
                show_timed_messagebox(self.manager, QMessageBox.Icon.Information, "Resetting Connections",
                                     f"Disconnected {disconnected_count} connections.\nSession manager ({service_name}) restart initiated.", 2500)
                # Trigger a refresh after a delay to allow session manager to restart and apply defaults
                QTimer.singleShot(2000, self.manager.refresh_ports)
            else:
                error_message = f"Failed to execute session manager restart command: {' '.join(command)}\n\n" \
                               f"Connections were disconnected, but defaults may not be restored.\n" \
                               f"If you are not using WirePlumber, you might need to manually restart your session manager."
                print(error_message)
                QMessageBox.critical(self.manager, "Reset Error", error_message)
                # Refresh immediately to show the disconnected state
                self.manager.refresh_ports()

    def _save_current_loaded_preset(self):
        """Saves the current connections to the currently loaded preset file without confirmation."""
        if not self.current_preset_name:
            QMessageBox.warning(self.manager, "Save Preset Error", "No preset is currently loaded.")
            return

        preset_name = self.current_preset_name
        print(f"Saving current connections to loaded preset: '{preset_name}'")
        current_connections = self.manager._get_current_connections()
        # Pass confirm_overwrite=False to skip the dialog
        if self.manager.preset_manager.save_preset(preset_name, current_connections, 
                                                  parent_widget=self.manager, confirm_overwrite=False):
            print(f"Preset '{preset_name}' saved.")
            show_timed_messagebox(self.manager, QMessageBox.Icon.Information, 
                                 "Preset Saved", f"Preset '{preset_name}' saved successfully.")
