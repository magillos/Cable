"""
PresetHandler - Handles preset loading, saving, and management
"""

import os
from PyQt6.QtWidgets import (QMenu, QMessageBox, QWidgetAction, QLineEdit, QCheckBox, 
                            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton)
from PyQt6.QtCore import QPoint, QTimer, QProcess
from PyQt6.QtGui import QKeySequence, QAction, QActionGroup

from cables.utils.helpers import show_timed_messagebox


class DefaultResetConfirmDialog(QDialog):
    """Custom dialog for Default preset confirmation with 'Don't show again' option."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Reset")
        self.setModal(True)
        self.dont_show_again = False
        
        # Set up the dialog layout
        layout = QVBoxLayout(self)
        
        # Message label
        message = QLabel(
            "This will disconnect all current connections, unhide and unfold all nodes/clients, "
            "and then restart WirePlumber to restore default connections.\n\n"
            "Do you want to proceed?"
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        
        # Don't show again checkbox
        self.dont_show_checkbox = QCheckBox("Don't show this confirmation again")
        layout.addWidget(self.dont_show_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.yes_button = QPushButton("Yes")
        self.yes_button.clicked.connect(self.accept)
        
        self.no_button = QPushButton("No")
        self.no_button.clicked.connect(self.reject)
        self.no_button.setDefault(True)  # Make No the default button
        
        button_layout.addStretch()
        button_layout.addWidget(self.yes_button)
        button_layout.addWidget(self.no_button)
        
        layout.addLayout(button_layout)
        
        # Set reasonable size
        self.resize(400, 150)
    
    def accept(self):
        """Override accept to capture the checkbox state."""
        self.dont_show_again = self.dont_show_checkbox.isChecked()
        super().accept()


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

        # Add attributes to track original preset state for change detection
        self.original_preset_connections = None
        self.original_preset_layout_data = None
        self.save_button_initially_enabled = False
        self.unified_clients = {}

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

        # --- Restore Layout Checkbox ---
        menu.addSeparator()
        restore_layout_action = QWidgetAction(menu)
        restore_layout_checkbox = QCheckBox("Restore layout")
        restore_layout_checkbox.setToolTip("In Graph, loading a preset will also restore clients' positions, visibility, split and fold states, and the zoom level.")
        
        # Initialize checkbox state from config
        initial_restore_layout = self.manager.config_manager.get_bool('load_preset_restore_layout', True)
        
        # Check if I/O layout is active (untangle setting == 0)
        is_io_active = (
            hasattr(self.manager, 'graph_main_window') and
            self.manager.graph_main_window and
            hasattr(self.manager.graph_main_window, 'current_untangle_setting') and
            self.manager.graph_main_window.current_untangle_setting == 0
        )
        
        effective_state = initial_restore_layout if not is_io_active else False
        restore_layout_checkbox.setChecked(effective_state)
        restore_layout_checkbox.setEnabled(not is_io_active)
        
        if is_io_active:
            restore_layout_checkbox.setToolTip("Restore layout (Disabled during I/O layout - dynamic sorting)")
        else:
            restore_layout_checkbox.setToolTip("In Graph, loading a preset will also restore clients' positions, visibility, split and fold states, and the zoom level.")
        
        # Connect to a handler to save the state
        restore_layout_checkbox.toggled.connect(self._set_restore_layout_mode)
        
        restore_layout_action.setDefaultWidget(restore_layout_checkbox)
        menu.addAction(restore_layout_action)
        # --- End Restore Layout Checkbox ---

        # --- Strict Mode Checkbox ---
        strict_action = QWidgetAction(menu)
        strict_checkbox = QCheckBox("Strict")
        strict_checkbox.setToolTip("When on, connections not stored in the loaded preset will be deactivated.")
        
        # Initialize checkbox state from config
        initial_strict_mode = self.manager.config_manager.get_bool('load_preset_strict_mode', False)
        strict_checkbox.setChecked(initial_strict_mode)
        
        # Connect to a handler to save the state
        strict_checkbox.toggled.connect(self._set_strict_mode)
        
        strict_action.setDefaultWidget(strict_checkbox)
        menu.addAction(strict_action)
        # --- End Strict Mode Checkbox ---

        # --- Daemon Mode Checkbox ---
        daemon_action = QWidgetAction(menu)
        daemon_checkbox = QCheckBox("Daemon mode")
        daemon_checkbox.setToolTip("Background mode: restores connections automatically if present in loaded preset.")
        
        # Initialize checkbox state from config
        initial_daemon_mode = self.manager.config_manager.get_bool('load_preset_daemon_mode', False)
        daemon_checkbox.setChecked(initial_daemon_mode)
        
        # Connect to a handler to save the state
        daemon_checkbox.toggled.connect(self._set_daemon_mode)
        
        daemon_action.setDefaultWidget(daemon_checkbox)
        menu.addAction(daemon_action)
        # --- End Daemon Mode Checkbox ---

    def _save_current_preset_from_menu(self):
        """Saves the current connections and layout using the name from the menu's line edit."""
        if not self._preset_menu_name_edit:  # Safety check
            print("Error: Preset menu name edit not found.")
            return
        preset_name = self._preset_menu_name_edit.text().strip()
        if not preset_name:
            QMessageBox.warning(self.manager, "Save Preset", "Enter a name for the preset.")
            return

        # Use QTimer to defer the save operation to avoid menu/dialog interaction issues
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._perform_preset_save(preset_name))

    def _perform_preset_save(self, preset_name):
        """Performs the actual preset save operation, called after menu closes."""
        print(f"Starting preset save operation for: '{preset_name}'")
        
        # Check if preset already exists and ask for confirmation first
        preset_file = os.path.join(self.manager.preset_manager.presets_dir, f"{preset_name}.snap")
        if os.path.exists(preset_file):
            print(f"Preset '{preset_name}' already exists, asking for confirmation")
            try:
                reply = QMessageBox.question(
                    self.manager, 
                    'Confirm Overwrite',
                    f"A preset named '{preset_name}' already exists.\nDo you want to overwrite it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    print(f"User cancelled overwrite for preset '{preset_name}'")
                    return
            except Exception as e:
                print(f"Error showing confirmation dialog: {e}")
                return
        
        # Try a direct approach - save connections first, then layout separately
        try:
            print("Saving connections with aj-snapshot...")
            import subprocess
            
            # Save connections directly with aj-snapshot
            command = ["aj-snapshot", "-f", preset_file]  # Force overwrite since we confirmed
            print(f"Executing: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
            print(f"aj-snapshot completed successfully")
            
            # Now save layout data if available
            if hasattr(self.manager, 'graph_main_window') and self.manager.graph_main_window:
                try:
                    print("Saving layout data...")
                    node_states = None
                    graph_zoom_level = None
                    node_visibility_data = None
                    
                    # Get current node states from the graph scene
                    if hasattr(self.manager.graph_main_window, 'scene') and self.manager.graph_main_window.scene:
                        node_states = self.manager.graph_main_window.scene.get_node_states()
                    
                    # Get current zoom level from the graph view
                    if hasattr(self.manager.graph_main_window, 'view') and self.manager.graph_main_window.view:
                        graph_zoom_level = self.manager.graph_main_window.view.get_zoom_level()
                    
                    # Get current node visibility settings
                    if hasattr(self.manager, 'node_visibility_manager') and self.manager.node_visibility_manager:
                        node_visibility_data = {
                            'audio_input': dict(self.manager.node_visibility_manager.audio_input_visibility),
                            'audio_output': dict(self.manager.node_visibility_manager.audio_output_visibility),
                            'midi_input': dict(self.manager.node_visibility_manager.midi_input_visibility),
                            'midi_output': dict(self.manager.node_visibility_manager.midi_output_visibility)
                        }
                        print(f"Collected node visibility data: {len(node_visibility_data.get('audio_input', {}))} audio input, {len(node_visibility_data.get('audio_output', {}))} audio output, {len(node_visibility_data.get('midi_input', {}))} MIDI input, {len(node_visibility_data.get('midi_output', {}))} MIDI output settings")
                    
                    if node_states is not None or node_visibility_data is not None:
                        # Save layout data directly
                        layout_presets_dir = os.path.join(self.manager.preset_manager.config_dir, 'layout_presets')
                        os.makedirs(layout_presets_dir, exist_ok=True)
                        layout_file = os.path.join(layout_presets_dir, f"{preset_name}.json")
                        
                        layout_data = {
                            'node_states': node_states,
                            'graph_zoom_level': graph_zoom_level,
                            'node_visibility': node_visibility_data,
                            'split_audio_midi': self.manager.config_manager.get_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', False)
                        }
                        
                        import json
                        with open(layout_file, 'w') as f:
                            json.dump(layout_data, f, indent=4, default=self._json_serializer_simple)
                        
                        print(f"Layout data saved to {layout_file}")
                    
                except Exception as e:
                    print(f"Warning: Could not save layout data: {e}")
                    # Don't fail the entire operation for layout issues
            
            print(f"Preset '{preset_name}' saved successfully. Loading as active preset.")
            # Automatically load the newly saved preset to make it active
            self._load_selected_preset(preset_name, is_startup=True)
            show_timed_messagebox(self.manager, QMessageBox.Icon.Information,
                                 "Preset Saved", f"Preset '{preset_name}' saved successfully.")
                                 
        except subprocess.TimeoutExpired:
            print("aj-snapshot command timed out")
            QMessageBox.critical(self.manager, "Save Error", "Preset save timed out. The aj-snapshot command took too long.")
        except subprocess.CalledProcessError as e:
            print(f"aj-snapshot command failed: {e}")
            QMessageBox.critical(self.manager, "Save Error", f"Failed to save preset: {e}")
        except Exception as e:
            print(f"Exception during preset save: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self.manager, "Save Error", f"An error occurred while saving the preset: {e}")
    
    def _json_serializer_simple(self, obj):
        """Simple JSON serializer for Qt objects."""
        # Handle QPointF objects
        if hasattr(obj, 'x') and hasattr(obj, 'y') and callable(obj.x) and callable(obj.y):
            return {"x": obj.x(), "y": obj.y()}
        
        # Handle other objects by converting to string
        return str(obj)

    def _set_startup_preset(self, name):
        """Sets the selected preset name as the startup preset in the config."""
        print(f"Setting startup preset to: {name}")
        self.startup_preset_name = name  # Update internal state
        self.manager.config_manager.set_str('startup_preset', name)

    def _load_selected_preset(self, name, is_startup=False):
        """
        Loads the connections and layout from the selected preset.
        Updates self.current_preset_name and returns True on success, False otherwise.
        is_startup flag prevents showing success message on startup load.
        """
        print(f"Loading preset: {name}")

        strict_mode = self.manager.config_manager.get_bool('load_preset_strict_mode', False)
        daemon_mode = self.manager.config_manager.get_bool('load_preset_daemon_mode', False)
        restore_layout = self.manager.config_manager.get_bool('load_preset_restore_layout', True)

        # First, stop any existing daemon to avoid multiple instances
        if daemon_mode:
            self.manager.preset_manager.stop_daemon_mode()

        # Capture the original state before loading for change detection
        self._capture_current_state()

        # Use enhanced preset manager if available, otherwise fall back to basic
        if hasattr(self.manager.preset_manager, 'load_and_apply_preset_with_layout'):
            self.manager.disconnect_all_unified()
            success, layout_data = self.manager.preset_manager.load_and_apply_preset_with_layout(
                name, strict_mode=strict_mode, daemon_mode=daemon_mode, apply_layout=restore_layout
            )
            self.manager.reconnect_all_unified()

            # Store the original preset state for change detection
            self.original_preset_connections = self.manager._get_current_connections()
            self.original_preset_layout_data = layout_data

            # Apply layout data if available and restore_layout is enabled, regardless of connection success
            if layout_data and restore_layout:
                self._apply_layout_data(layout_data)

        else:
            success = self.manager.preset_manager.load_and_apply_preset(name, strict_mode=strict_mode, daemon_mode=daemon_mode)
            # For basic preset manager, only store connection state
            self.original_preset_connections = self.manager._get_current_connections()
            self.original_preset_layout_data = None

        if success:
            print("Preset load complete. Refreshing UI.")
            self.current_preset_name = name
            self.manager.config_manager.set_str('active_preset', name)
            # Initially set save button to disabled since we just loaded the preset (no changes yet)
            self.save_button_initially_enabled = False
            if hasattr(self.manager, 'save_preset_action'):
                self.manager.save_preset_action.setEnabled(False)
            print(f"Load Success: Set active_preset in config to '{name}'")
            self.manager.refresh_ports()

            if not is_startup:
                show_timed_messagebox(self.manager, QMessageBox.Icon.Information,
                                     "Preset Loaded", f"Preset '{name}' loaded successfully.")

            return True
        else:
            if not is_startup:
                show_timed_messagebox(self.manager, QMessageBox.Icon.Information,
                                     "Preset Loaded", f"Preset '{name}' loaded but some connections could not be restored. Missing client?")
            else:
                print(f"Preset '{name}' loaded but some connections could not be restored (missing client?).")
            self.current_preset_name = name
            self.manager.config_manager.set_str('active_preset', name)
            # Initially set save button to disabled since we just loaded the preset (no changes yet)
            self.save_button_initially_enabled = False
            if hasattr(self.manager, 'save_preset_action'):
                self.manager.save_preset_action.setEnabled(False)
            print("Load Success (partial): Set active_preset in config.")
            self.manager.refresh_ports()
            return True

    def _delete_selected_preset(self, name):
        """Deletes the selected preset after confirmation."""
        reply = QMessageBox.question(self.manager, 'Delete Preset',
                                     f"Are you sure you want to delete the preset '{name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            # Use enhanced preset manager if available, otherwise fall back to basic
            if hasattr(self.manager.preset_manager, 'delete_preset_with_layout'):
                success = self.manager.preset_manager.delete_preset_with_layout(name)
            else:
                success = self.manager.preset_manager.delete_preset(name)
                
            if success:
                print(f"Preset '{name}' deleted.")
                show_timed_messagebox(self.manager, QMessageBox.Icon.Information,
                                      "Preset Deleted", f"Preset '{name}' deleted.")
                if name == self.current_preset_name:
                    self.current_preset_name = None
                    self.manager.config_manager.set_str('active_preset', None)
                    if hasattr(self.manager, 'save_preset_action'):
                        self.manager.save_preset_action.setEnabled(False)
                    print("Cleared active_preset in config as current preset was deleted.")
                if name == self.startup_preset_name:
                    self.startup_preset_name = None
                    self.manager.config_manager.set_str('startup_preset', None)
                    print("Cleared startup_preset in config as it was deleted.")
                self.manager.refresh_ports()
            else:
                QMessageBox.warning(self.manager, "Delete Preset", f"Could not find or delete preset '{name}'.")

    def _handle_gui_preset_load(self, name):
        """Handles loading a preset via the GUI menu click."""
        self._load_selected_preset(name)

    def _handle_default_preset_action(self):
        """Handles the 'Default' preset action: disconnects all connections, unhides and unfolds all nodes, then restarts the session manager."""
        # Check if user has disabled the confirmation dialog
        skip_confirmation = self.manager.config_manager.get_bool('default_preset_skip_confirmation', False)
        
        if not skip_confirmation:
            dialog = DefaultResetConfirmDialog(self.manager)
            reply = dialog.exec()
            
            if reply != QDialog.DialogCode.Accepted:
                return  # User cancelled
            
            # Save the "don't show again" preference if checked
            if dialog.dont_show_again:
                self.manager.config_manager.set_bool('default_preset_skip_confirmation', True)
                print("User chose to skip Default preset confirmation in the future.")
        
        # Proceed with the reset
        print("User confirmed default connection reset.")

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

        print("Step 2: Unhiding all nodes/clients...")
        self._unhide_all_nodes()

        print("Step 3: Unfolding all nodes in graph...")
        self._unfold_all_nodes()

        print("Step 4: Restarting PipeWire session manager...")
        service_name = "wireplumber.service"
        command = []
        if self.manager.flatpak_env:
            print(f"  Running in Flatpak environment. Using flatpak-spawn to restart {service_name}.")
            command = ["flatpak-spawn", "--host", "systemctl", "restart", "--user", service_name]
        else:
            print(f"  Running outside Flatpak environment. Using systemctl to restart {service_name}.")
            command = ["systemctl", "restart", "--user", service_name]

        print(f"  Executing command: {' '.join(command)}")
        success = QProcess.startDetached(command[0], command[1:])

        self.manager.config_manager.set_str('active_preset', None)
        self.current_preset_name = None
        if hasattr(self.manager, 'save_preset_action'):
            self.manager.save_preset_action.setEnabled(False)
        print("Cleared active_preset in config after selecting 'Default'.")

        if success:
            print("Step 4: Session manager restart command initiated successfully.")
            show_timed_messagebox(self.manager, QMessageBox.Icon.Information, "Resetting Connections",
                                 f"Disconnected {disconnected_count} connections.\nUnhid and unfolded all nodes.\nSession manager ({service_name}) restart initiated.", 3000)
            QTimer.singleShot(2000, self.manager.refresh_ports)
        else:
            error_message = f"Failed to execute session manager restart command: {' '.join(command)}\n\n" \
                           f"Connections were disconnected, but defaults may not be restored.\n" \
                           f"If you are not using WirePlumber, you might need to manually restart your session manager."
            print(error_message)
            QMessageBox.critical(self.manager, "Reset Error", error_message)
            self.manager.refresh_ports()

    def _save_current_loaded_preset(self):
        """Saves the current connections and layout to the currently loaded preset file without confirmation."""
        if not self.current_preset_name:
            QMessageBox.warning(self.manager, "Save Preset Error", "No preset is currently loaded.")
            return
 
        preset_name = self.current_preset_name
        print(f"Saving current connections and layout to loaded preset: '{preset_name}'")
        
        # Get layout data from the graph tab if available
        node_states = None
        graph_zoom_level = None
        node_visibility_data = None
        
        if hasattr(self.manager, 'graph_main_window') and self.manager.graph_main_window:
            try:
                # Get current node states from the graph scene
                if hasattr(self.manager.graph_main_window, 'scene') and self.manager.graph_main_window.scene:
                    node_states = self.manager.graph_main_window.scene.get_node_states()
                
                # Get current zoom level from the graph view
                if hasattr(self.manager.graph_main_window, 'view') and self.manager.graph_main_window.view:
                    graph_zoom_level = self.manager.graph_main_window.view.get_zoom_level()
                    
            except Exception as e:
                print(f"Warning: Could not get layout data for preset save: {e}")

        # Get current node visibility settings
        if hasattr(self.manager, 'node_visibility_manager') and self.manager.node_visibility_manager:
            try:
                node_visibility_data = {
                    'audio_input': dict(self.manager.node_visibility_manager.audio_input_visibility),
                    'audio_output': dict(self.manager.node_visibility_manager.audio_output_visibility),
                    'midi_input': dict(self.manager.node_visibility_manager.midi_input_visibility),
                    'midi_output': dict(self.manager.node_visibility_manager.midi_output_visibility)
                }
                print(f"Collected node visibility data for save: {len(node_visibility_data.get('audio_input', {}))} audio input, {len(node_visibility_data.get('audio_output', {}))} audio output, {len(node_visibility_data.get('midi_input', {}))} MIDI input, {len(node_visibility_data.get('midi_output', {}))} MIDI output settings")
            except Exception as e:
                print(f"Warning: Could not get node visibility data for preset save: {e}")

        # Use enhanced preset manager if available, otherwise fall back to basic
        if hasattr(self.manager.preset_manager, 'save_preset_with_layout'):
            success = self.manager.preset_manager.save_preset_with_layout(
                preset_name, 
                node_states=node_states, 
                graph_zoom_level=graph_zoom_level,
                node_visibility_data=node_visibility_data,
                parent_widget=self.manager, 
                confirm_overwrite=False
            )
        else:
            success = self.manager.preset_manager.save_preset(preset_name, 
                                                              parent_widget=self.manager, confirm_overwrite=False)
        
        if success:
            print(f"Preset '{preset_name}' saved.")
            # Update the original state to reflect the current (saved) state
            self.original_preset_connections = self.manager._get_current_connections()
            self.original_preset_layout_data = {
                'node_states': node_states,
                'graph_zoom_level': graph_zoom_level,
                'node_visibility': node_visibility_data
            }
            # Update save button state since changes have been saved
            self._update_save_button_enabled_state()
            show_timed_messagebox(self.manager, QMessageBox.Icon.Information,
                                 "Preset Saved", f"Preset '{preset_name}' saved successfully.")

    def _set_strict_mode(self, checked):
        """Sets the strict mode for preset loading in the config."""
        print(f"Setting strict mode for preset loading to: {checked}")
        self.manager.config_manager.set_bool('load_preset_strict_mode', checked)

    def _set_daemon_mode(self, checked):
        """Sets the daemon mode for preset loading in the config and starts/stops the daemon."""
        print(f"Setting daemon mode for preset loading to: {checked}")
        self.manager.config_manager.set_bool('load_preset_daemon_mode', checked)

        if checked:
            if self.current_preset_name:
                strict_mode = self.manager.config_manager.get_bool('load_preset_strict_mode', False)
                self.manager.preset_manager.start_daemon_mode(self.current_preset_name, strict_mode)
            else:
                print("No active preset to start daemon mode with.")
        else:
            self.manager.preset_manager.stop_daemon_mode()

    def _unhide_all_nodes(self):
        """Unhide all nodes by resetting node visibility settings."""
        try:
            if hasattr(self.manager, 'node_visibility_manager') and self.manager.node_visibility_manager:
                # Clear all visibility settings (empty dictionaries mean all nodes are visible)
                self.manager.node_visibility_manager.audio_input_visibility = {}
                self.manager.node_visibility_manager.audio_output_visibility = {}
                self.manager.node_visibility_manager.midi_input_visibility = {}
                self.manager.node_visibility_manager.midi_output_visibility = {}
                
                # Save the cleared settings
                self.manager.node_visibility_manager.save_visibility_settings()
                
                # Apply the visibility settings to refresh the UI
                self.manager.node_visibility_manager.apply_visibility_settings()
                
                print("  All nodes unhidden successfully.")
            else:
                print("  Node visibility manager not available.")
        except Exception as e:
            print(f"  Error unhiding nodes: {e}")

    def _unfold_all_nodes(self):
        """Unfold all nodes in the graph view."""
        try:
            if (hasattr(self.manager, 'graph_main_window') and self.manager.graph_main_window and
                hasattr(self.manager.graph_main_window, 'scene') and self.manager.graph_main_window.scene):
                
                scene = self.manager.graph_main_window.scene
                unfolded_count = 0
                
                # Iterate through all nodes in the scene
                for client_name, node in scene.nodes.items():
                    try:
                        if node.is_split_origin:
                            # Handle split nodes - unfold their parts
                            if node.split_input_node and hasattr(node.split_input_node, 'input_part_folded'):
                                if node.split_input_node.input_part_folded:
                                    node.split_input_node.fold_handler.toggle_input_part_fold(fold_state=False)
                                    unfolded_count += 1
                            
                            if node.split_output_node and hasattr(node.split_output_node, 'output_part_folded'):
                                if node.split_output_node.output_part_folded:
                                    node.split_output_node.fold_handler.toggle_output_part_fold(fold_state=False)
                                    unfolded_count += 1
                        
                        elif not node.is_split_part:
                            # Handle regular (non-split) nodes
                            if hasattr(node, 'is_folded') and node.is_folded:
                                node.fold_handler.toggle_main_fold_state()
                                unfolded_count += 1
                    
                    except Exception as e:
                        print(f"  Error unfolding node {client_name}: {e}")
                
                print(f"  Unfolded {unfolded_count} nodes successfully.")
            else:
                print("  Graph scene not available.")
        except Exception as e:
            print(f"  Error unfolding nodes: {e}")

    def reset_default_preset_confirmation(self):
        """Reset the 'don't show again' setting for Default preset confirmation."""
        self.manager.config_manager.set_bool('default_preset_skip_confirmation', False)
        print("Default preset confirmation dialog has been re-enabled.")

    def _set_restore_layout_mode(self, checked):
        """Sets the restore layout mode for preset loading in the config."""
        print(f"Setting restore layout mode for preset loading to: {checked}")
        self.manager.config_manager.set_bool('load_preset_restore_layout', checked)

    def _apply_layout_data(self, layout_data):
        """
        Apply layout data to the graph scene and node visibility settings.

        Args:
            layout_data (dict): Layout data containing node_states, graph_zoom_level, and node_visibility
        """
        if not layout_data:
            return

        try:
            # Apply node states if available
            if 'node_states' in layout_data and hasattr(self.manager, 'graph_main_window'):
                if self.manager.graph_main_window and hasattr(self.manager.graph_main_window, 'scene'):
                    scene = self.manager.graph_main_window.scene
                    if scene and hasattr(scene, 'restore_node_states'):
                        scene.restore_node_states(layout_data['node_states'])
                        print("Applied node states from preset")

            # Apply zoom level if available
            if 'graph_zoom_level' in layout_data and hasattr(self.manager, 'graph_main_window'):
                if self.manager.graph_main_window and hasattr(self.manager.graph_main_window, 'view'):
                    view = self.manager.graph_main_window.view
                    if view and hasattr(view, 'set_zoom_level'):
                        view.set_zoom_level(layout_data['graph_zoom_level'])
                        print(f"Applied zoom level {layout_data['graph_zoom_level']} from preset")

            # Apply node visibility settings if available
            if 'node_visibility' in layout_data and layout_data['node_visibility']:
                if hasattr(self.manager, 'node_visibility_manager') and self.manager.node_visibility_manager:
                    visibility_data = layout_data['node_visibility']

                    # Replace the node visibility manager's settings (not update)
                    if 'audio_input' in visibility_data:
                        self.manager.node_visibility_manager.audio_input_visibility = dict(visibility_data['audio_input'])
                    if 'audio_output' in visibility_data:
                        self.manager.node_visibility_manager.audio_output_visibility = dict(visibility_data['audio_output'])
                    if 'midi_input' in visibility_data:
                        self.manager.node_visibility_manager.midi_input_visibility = dict(visibility_data['midi_input'])
                    if 'midi_output' in visibility_data:
                        self.manager.node_visibility_manager.midi_output_visibility = dict(visibility_data['midi_output'])

                    # Save the updated settings to the config file
                    self.manager.node_visibility_manager.save_visibility_settings()

                    # Apply the visibility settings to refresh the UI
                    self.manager.node_visibility_manager.apply_visibility_settings()

                    print("Applied node visibility settings from preset")

            # Apply unified clients if available
            if 'unified_clients' in layout_data and hasattr(self.manager, 'graph_main_window'):
                if self.manager.graph_main_window and hasattr(self.manager.graph_main_window, 'scene'):
                    scene = self.manager.graph_main_window.scene
                    if scene and hasattr(scene, 'apply_unified_states'):
                        self.unified_clients = layout_data.get('unified_clients', {})
                        scene.apply_unified_states(self.unified_clients)
                        print("Applied unified clients from preset")
            
            # Apply split audio/midi setting if available
            if 'split_audio_midi' in layout_data:
                split_audio_midi = layout_data['split_audio_midi']
                self.manager.config_manager.set_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', split_audio_midi)
                print(f"Applied split audio/midi setting from preset: {split_audio_midi}")
                # We need to trigger a full refresh of the graph for this to take effect
                if hasattr(self.manager, 'graph_main_window') and self.manager.graph_main_window:
                    if hasattr(self.manager.graph_main_window, 'scene') and self.manager.graph_main_window.scene:
                        self.manager.graph_main_window.scene.full_graph_refresh()

        except Exception as e:
            print(f"Error applying layout data: {e}")

    def _capture_current_state(self):
        """Capture the current state of connections and layout for comparison when preset is loaded."""
        try:
            # This method would be called before loading a preset to compare against after loading
            # For now, we'll capture when preset is actually loaded
            pass
        except Exception as e:
            print(f"Error capturing current state: {e}")

    def _connections_have_changed(self):
        """
        Check if the current connections have changed compared to the originally loaded preset.

        Returns:
            bool: True if connections have changed, False otherwise
        """
        if not self.current_preset_name or self.original_preset_connections is None:
            return False

        try:
            current_connections = self.manager._get_current_connections()
            current_set = set()
            original_set = set()

            # Convert current connections to a comparable set
            for conn in current_connections:
                output = conn.get("output", "")
                input_ = conn.get("input", "")
                if output and input_:
                    current_set.add((output, input_))

            # Convert original connections to a comparable set
            for conn in self.original_preset_connections:
                output = conn.get("output", "")
                input_ = conn.get("input", "")
                if output and input_:
                    original_set.add((output, input_))

            return current_set != original_set

        except Exception as e:
            print(f"Error comparing connections: {e}")
            return False

    def _layout_has_changed(self):
        """
        Check if the current layout has changed compared to the originally loaded preset.

        Returns:
            bool: True if layout has changed, False otherwise
        """
        if not self.current_preset_name or not self.original_preset_layout_data:
            return False

        try:
            layout_changed = False

            # Check node states
            if hasattr(self.manager, 'graph_main_window') and self.manager.graph_main_window:
                if hasattr(self.manager.graph_main_window, 'scene') and self.manager.graph_main_window.scene:
                    current_node_states = self.manager.graph_main_window.scene.get_node_states()
                    original_node_states = self.original_preset_layout_data.get('node_states')

                    if current_node_states != original_node_states:
                        layout_changed = True

                # Check zoom level
                if hasattr(self.manager.graph_main_window, 'view') and self.manager.graph_main_window.view:
                    current_zoom = self.manager.graph_main_window.view.get_zoom_level()
                    original_zoom = self.original_preset_layout_data.get('graph_zoom_level')

                    if current_zoom != original_zoom:
                        layout_changed = True

            # Check node visibility
            if hasattr(self.manager, 'node_visibility_manager') and self.manager.node_visibility_manager:
                current_visibility = {
                    'audio_input': dict(self.manager.node_visibility_manager.audio_input_visibility),
                    'audio_output': dict(self.manager.node_visibility_manager.audio_output_visibility),
                    'midi_input': dict(self.manager.node_visibility_manager.midi_input_visibility),
                    'midi_output': dict(self.manager.node_visibility_manager.midi_output_visibility)
                }
                original_visibility = self.original_preset_layout_data.get('node_visibility')

                if current_visibility != original_visibility:
                    layout_changed = True

            return layout_changed

        except Exception as e:
            print(f"Error comparing layout: {e}")
            return False

    def _preset_has_changes(self):
        """
        Check if the currently loaded preset has any changes.

        Returns:
            bool: True if there are changes, False otherwise
        """
        # Check both connections and layout for changes
        connections_changed = self._connections_have_changed()
        layout_changed = self._layout_has_changed()

        has_changes = connections_changed or layout_changed

        if has_changes:
            print(f"Preset '{self.current_preset_name}' has changes: connections={connections_changed}, layout={layout_changed}")

        return has_changes

    def _update_save_button_enabled_state(self):
        """Update the save button enabled state based on whether the loaded preset has changes."""
        if not self.current_preset_name:
            # No preset loaded, disable save button
            enabled = False
        else:
            # Preset loaded, enable save button only if there are changes
            enabled = self._preset_has_changes()

        # Update the button state if it's different from current state
        if hasattr(self.manager, 'save_preset_action') and self.manager.save_preset_action:
            current_enabled = self.manager.save_preset_action.isEnabled()
            if current_enabled != enabled:
                self.manager.save_preset_action.setEnabled(enabled)
                print(f"Save button {'enabled' if enabled else 'disabled'} for preset '{self.current_preset_name}'")
