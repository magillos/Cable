import sys
import subprocess
import json
import re
import os
import dbus
import configparser
import argparse
import shutil
import requests
from packaging import version
import webbrowser # Might not be needed if setOpenExternalLinks works directly
from PyQt6.QtCore import Qt, QTimer, QFile, QMargins, QProcess, QEvent
from PyQt6.QtGui import QFont, QIcon, QGuiApplication, QActionGroup, QAction
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QComboBox, QLineEdit, QPushButton, QLabel,
                             QSpacerItem, QSizePolicy, QMessageBox, QGroupBox,
                             QCheckBox, QSystemTrayIcon, QMenu, QDialog, QDialogButtonBox,
                             QScrollArea)

# --- Application Version ---
APP_VERSION = "0.9.5"
# -------------------------

# --- Constants ---
EDIT_LIST_TEXT = "Edit List..." # New constant for dialog trigger
# -----------------

# --- New Dialog for Value Selection ---
class ValueSelectorDialog(QDialog):
    """Dialog to select active values from a list using checkboxes."""
    def __init__(self, title, all_values, active_values, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300) # Set a minimum width

        self.checkboxes = []
        layout = QVBoxLayout(self)

        # Scroll Area for potentially long lists
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        for value in all_values:
            checkbox = QCheckBox(str(value))
            if value in active_values:
                checkbox.setChecked(True)
            self.checkboxes.append(checkbox)
            scroll_layout.addWidget(checkbox)

        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # OK and Cancel buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def get_selected_values(self):
        """Returns a list of integer values corresponding to checked boxes."""
        selected = []
        for checkbox in self.checkboxes:
            if checkbox.isChecked():
                try:
                    selected.append(int(checkbox.text()))
                except ValueError:
                    print(f"Warning: Could not convert checkbox text '{checkbox.text()}' to int.")
        return selected
# ------------------------------------


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


class CableApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)


        # This needs to match your .desktop file name exactly
        QGuiApplication.setDesktopFileName("com.github.magillos.cable")


        # Set the application name to match the .desktop file
        self.setApplicationName("Cable")

class PipeWireSettingsApp(QWidget):

    DEFAULT_QUANTUM_VALUES     = [16, 32, 48, 64, 96, 128, 144, 192, 240, 256, 512, 1024, 2048, 4096, 8192]
    DEFAULT_SAMPLE_RATE_VALUES = [44100, 48000, 88200, 96000, 176400, 192000]
    # Comment block to ensure it stays in config.ini

    def __init__(self):
        super().__init__()
        # make sure our config file has editable list entries
        self.ensure_config_lists()
        self.flatpak_env = os.path.exists('/.flatpak-info')
        self.tray_icon = None  # Initialize tray_icon here
        self.tray_enabled = False
        self.connection_manager_process = None
        self.tray_click_opens_cables = True
        self.profile_index_map = {}
        self.cables_executable_path = None  # Will be set during init
        self.autostart_manager = AutostartManager(self.flatpak_env)
        self.remember_settings = False
        self.saved_quantum = 0
        self.saved_sample_rate = 0
        self.autostart_enabled = False
        self.quantum_was_reset = False
        self.sample_rate_was_reset = False
        self.check_updates_at_start = False # Default: Do not check for updates on startup
        self.values_initialized = False  # Flag to track if values have been initialized
        
        # Store last valid indices (still needed for resetting selection)
        self.last_valid_quantum_index = 0
        self.last_valid_sample_rate_index = 0
        
        # Initialize UI first
        self.initUI()
        
        # Flag to prevent saving during initial load
        self.initial_load = True
        
        # First load current system settings as fallback
        self.load_current_settings()
        
        # Then load settings from config, which will override system settings if available
        self.load_settings()
        
        # Now allow saving of user changes
        self.initial_load = False
        
        # Mark values as initialized
        self.values_initialized = True

        # Update latency display after everything is loaded
        self.update_latency_display()

        # Conditionally check for updates shortly after startup
        QTimer.singleShot(2000, self._initial_update_check) # Check after 2 seconds if enabled


    def get_metadata_value(self, key):
        """Get pipewire metadata values without shell pipelines"""
        output = self.run_command(['pw-metadata', '-n', 'settings'])
        if not output:
            return None

        for line in output.split('\n'):
            if key in line:
                try:
                    return line.split("'")[3]  # Extract value from metadata line
                except IndexError:
                    continue
        return None


    def create_section_group(self, title, layout):
        group = QGroupBox()
        group.setLayout(layout)
        group.setContentsMargins(QMargins(5, 10, 5, 10))  # Adjust margins

        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)

        title_label = QLabel(title)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.insertWidget(0, title_label)

        return group

    def _create_audio_setting_section(self, title, combo_box, apply_button, reset_button, refresh_button, apply_slot, reset_slot, refresh_slot, default_values_key, default_values_list):
        """Helper method to create UI sections for Quantum and Sample Rate."""
        layout = QVBoxLayout()
        select_layout = QHBoxLayout()
        label = QLabel(f"{title}:")
        combo_box.setEditable(True) # Make combo box editable again
        values = self.get_list_from_config(default_values_key, default_values_list)
        for value in values:
            combo_box.addItem(str(value))
        combo_box.addItem(EDIT_LIST_TEXT) # Add edit option back to combo
        edit_item_index = combo_box.count() - 1
        combo_box.setItemData(edit_item_index, "Select, then press Enter to edit list", Qt.ItemDataRole.ToolTipRole)
        select_layout.addWidget(label)
        select_layout.addWidget(combo_box)


        layout.addLayout(select_layout)

        buttons_layout = QHBoxLayout()
        apply_button.setText(f"Apply {title}")
        apply_button.clicked.connect(apply_slot)
        buttons_layout.addWidget(apply_button)
        combo_box.lineEdit().returnPressed.connect(apply_slot) # Reconnect Enter key press

        reset_button.setText(f"Reset {title}")
        reset_button.clicked.connect(reset_slot)
        buttons_layout.addWidget(reset_button)

        refresh_button.setText("Refresh")
        refresh_button.clicked.connect(refresh_slot)
        refresh_button.setToolTip(f"Refreshes {title.lower()}, as well as the other audio setting, audio devices, nodes, and dropdown lists")
        buttons_layout.addWidget(refresh_button)

        layout.addLayout(buttons_layout)

        # Special handling for Quantum section's latency display
        if title == "Quantum":
            latency_display_layout = QHBoxLayout()
            self.latency_display_label = QLabel("Latency:")
            self.latency_display_value = QLabel("0.00 ms")
            latency_display_layout.addStretch()
            latency_display_layout.addWidget(self.latency_display_label)
            latency_display_layout.addWidget(self.latency_display_value)
            layout.addLayout(latency_display_layout)

        return self.create_section_group(title, layout)

    def _edit_value_list(self, title, config_key, default_values_list):
        """Handles editing the list of values in the config file via a dialog."""
        config_path = os.path.expanduser("~/.config/cable/config.ini")
        # Ensure the config file exists and has the keys before reading
        self.ensure_config_lists()

        # Get currently active values from config
        active_values = self.get_list_from_config(config_key, default_values_list)

        # Show the dialog
        dialog = ValueSelectorDialog(f"Select Active {title} Values", default_values_list, active_values, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_values = dialog.get_selected_values()
            print(f"Dialog accepted for {title}. Selected values: {selected_values}")

            # Update the config file
            config = configparser.ConfigParser(allow_no_value=True)
            try:
                # Read existing config first to preserve other settings
                config.read(config_path)
                if 'DEFAULT' not in config:
                    config['DEFAULT'] = {} # Should not happen due to ensure_config_lists, but safety first

                # Construct the new comma-separated string, commenting out unselected values
                new_value_parts = []
                for val in default_values_list:
                    if val in selected_values:
                        new_value_parts.append(str(val))
                    else:
                        new_value_parts.append(f"#{val}") # Comment out unselected values

                config['DEFAULT'][config_key] = ','.join(new_value_parts)

                # Write the updated config back using the helper
                self._write_config(config, config_path)
                print(f"Updated '{config_key}' in {config_path}")

                # Refresh the UI to reflect changes
                self.refresh_all_settings()

            except Exception as e:
                print(f"Error updating config file {config_path} for key '{config_key}': {e}")
                QMessageBox.critical(self, "Config Error", f"Failed to update configuration file:\n{e}")

    def edit_quantum_list(self):
        """Opens the dialog to edit the quantum values list."""
        self._edit_value_list("Quantum", 'quantum_values', self.DEFAULT_QUANTUM_VALUES)

    def edit_sample_rate_list(self):
        """Opens the dialog to edit the sample rate values list."""
        self._edit_value_list("Sample Rate", 'sample_rate_values', self.DEFAULT_SAMPLE_RATE_VALUES)

    def initUI(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10) # Adjust main layout spacing

        # Audio Profile Section
        profile_layout = QVBoxLayout()

        # Device layout
        device_layout = QHBoxLayout()
        device_label = QLabel("Audio Device:")
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        profile_layout.addLayout(device_layout)

        # Profile layout
        profile_select_layout = QHBoxLayout()
        profile_label = QLabel("Device Profile:")
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        profile_select_layout.addWidget(profile_label)
        profile_select_layout.addWidget(self.profile_combo)
        profile_layout.addLayout(profile_select_layout)

        # Ensure labels have the same width
        device_label.setFixedWidth(device_label.sizeHint().width())
        profile_label.setFixedWidth(device_label.width())

        self.apply_profile_button = QPushButton("Apply Profile")
        self.apply_profile_button.clicked.connect(self.apply_profile_settings)
        profile_layout.addWidget(self.apply_profile_button)

        main_layout.addWidget(self.create_section_group("Audio Profile", profile_layout))

        # Initialize widgets before passing them to the helper
        self.quantum_combo = QComboBox()
        self.apply_quantum_button = QPushButton()
        self.reset_quantum_button = QPushButton()
        self.refresh_quantum_button = QPushButton()

        self.sample_rate_combo = QComboBox()
        self.apply_sample_rate_button = QPushButton()
        self.reset_sample_rate_button = QPushButton()
        self.refresh_sample_rate_button = QPushButton()

        # Quantum Section using helper
        quantum_group = self._create_audio_setting_section(
            title="Quantum",
            combo_box=self.quantum_combo,
            apply_button=self.apply_quantum_button,
            reset_button=self.reset_quantum_button,
            refresh_button=self.refresh_quantum_button,
            apply_slot=self.apply_quantum_settings,
            reset_slot=self.reset_quantum_settings,
            refresh_slot=self.refresh_all_settings,
            default_values_key='quantum_values',
            default_values_list=self.DEFAULT_QUANTUM_VALUES
        )
        main_layout.addWidget(quantum_group)

        # Sample Rate Section using helper
        sample_rate_group = self._create_audio_setting_section(
            title="Sample Rate",
            combo_box=self.sample_rate_combo,
            apply_button=self.apply_sample_rate_button,
            reset_button=self.reset_sample_rate_button,
            refresh_button=self.refresh_sample_rate_button,
            apply_slot=self.apply_sample_rate_settings,
            reset_slot=self.reset_sample_rate_settings,
            refresh_slot=self.refresh_all_settings,
            default_values_key='sample_rate_values',
            default_values_list=self.DEFAULT_SAMPLE_RATE_VALUES
        )
        main_layout.addWidget(sample_rate_group)


        # Latency Section
        latency_layout = QVBoxLayout()
        node_select_layout = QHBoxLayout()
        node_label = QLabel("Audio Node:")
        self.node_combo = QComboBox()
        self.node_combo.addItem("Choose Node")
        node_select_layout.addWidget(node_label)
        node_select_layout.addWidget(self.node_combo)
        latency_layout.addLayout(node_select_layout)

        latency_input_layout = QHBoxLayout()
        latency_label = QLabel("Latency Offset (default in samples):")
        self.latency_input = QLineEdit()
        self.nanoseconds_checkbox = QCheckBox("nanoseconds")
        latency_input_layout.addWidget(latency_label)
        latency_input_layout.addWidget(self.latency_input)
        latency_input_layout.addWidget(self.nanoseconds_checkbox)
        latency_layout.addLayout(latency_input_layout)

        self.apply_latency_button = QPushButton("Apply Latency")
        self.apply_latency_button.clicked.connect(self.apply_latency_settings)
        latency_layout.addWidget(self.apply_latency_button)
        self.latency_input.returnPressed.connect(self.apply_latency_settings)

        main_layout.addWidget(self.create_section_group("Latency Offset", latency_layout))

        # Restart Buttons Section
        restart_layout = QVBoxLayout()
        restart_buttons_layout = QHBoxLayout()
        self.restart_wireplumber_button = QPushButton("Restart Wireplumber")
        self.restart_wireplumber_button.clicked.connect(self.confirm_restart_wireplumber)
        self.set_button_style(self.restart_wireplumber_button)
        restart_buttons_layout.addWidget(self.restart_wireplumber_button)

        self.restart_pipewire_button = QPushButton("Restart Pipewire")
        self.restart_pipewire_button.clicked.connect(self.confirm_restart_pipewire)
        self.set_button_style(self.restart_pipewire_button)
        restart_buttons_layout.addWidget(self.restart_pipewire_button)

        restart_layout.addLayout(restart_buttons_layout)
        main_layout.addWidget(self.create_section_group("Restart Services", restart_layout))



        #Connections button
        connections_button = QPushButton("Cables")
        connections_button.clicked.connect(self.launch_connection_manager)
        main_layout.addWidget(connections_button)

        self.setLayout(main_layout)
        self.setWindowTitle('Cable')
        self.setMinimumSize(300, 600)  # Set minimum window size
        self.resize(474, 900)  # Set initial size to the minimum

        self.load_nodes()
        self.load_devices()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.node_combo.currentIndexChanged.connect(self.on_node_changed)
        self.quantum_combo.currentIndexChanged.connect(self.on_quantum_index_changed)
        self.sample_rate_combo.currentIndexChanged.connect(self.on_sample_rate_index_changed)


        # System Tray Toggle Section
        tray_toggle_layout = QHBoxLayout()
        self.tray_toggle_checkbox = QCheckBox("Enable tray icon")
        self.tray_toggle_checkbox.setChecked(False)
        self.tray_toggle_checkbox.stateChanged.connect(self.toggle_tray_icon)
        tray_toggle_layout.addWidget(self.tray_toggle_checkbox)
        main_layout.addLayout(tray_toggle_layout)

        # Remember Settings Section
        remember_settings_layout = QHBoxLayout()
        self.remember_settings_checkbox = QCheckBox("Save buffer and sample rate")
        self.remember_settings_checkbox.setChecked(False)
        self.remember_settings_checkbox.stateChanged.connect(self.toggle_remember_settings)
        remember_settings_layout.addWidget(self.remember_settings_checkbox)
        main_layout.addLayout(remember_settings_layout)

        # Add version label at the bottom right
        version_layout = QHBoxLayout()
        version_layout.addStretch() # Push label to the right
        self.version_label = QLabel()
        self.version_label.setTextFormat(Qt.TextFormat.RichText) # Allow HTML links


        self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">{APP_VERSION}</a>')
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)


        version_layout.addWidget(self.version_label)
        self.version_label.installEventFilter(self) # Add event filter for left-click menu
        main_layout.addLayout(version_layout) # Add to the main layout


    def load_settings(self):
        """Load saved settings from config file"""
        config = configparser.ConfigParser()
        config_path = os.path.expanduser("~/.config/cable/config.ini")

        # Default settings
        tray_enabled = False
        tray_click_opens_cables = True
        self.remember_settings = False
        self.saved_quantum = 0
        self.saved_sample_rate = 0
        self.autostart_enabled = False
        self.check_updates_at_start = False # Default value

        if os.path.exists(config_path):
            try:
                config.read(config_path)
                # Load tray enabled state
                tray_enabled = config.getboolean('DEFAULT', 'tray_enabled', fallback=False)
                # Load default app setting
                tray_click_opens_cables = config.getboolean(
                    'DEFAULT', 'tray_click_opens_cables', fallback=True
                )
                # Load audio settings
                self.remember_settings = config.getboolean('DEFAULT', 'remember_settings', fallback=False)
                
                # Load saved audio settings if they exist
                has_saved_quantum = 'DEFAULT' in config and 'saved_quantum' in config['DEFAULT']
                has_saved_sample_rate = 'DEFAULT' in config and 'saved_sample_rate' in config['DEFAULT']
                
                if has_saved_quantum:
                    self.saved_quantum = config.getint('DEFAULT', 'saved_quantum', fallback=0)
                if has_saved_sample_rate:
                    self.saved_sample_rate = config.getint('DEFAULT', 'saved_sample_rate', fallback=0)
                
                # Only mark settings as not reset if we actually have saved values
                if has_saved_quantum:
                    self.quantum_was_reset = False
                if has_saved_sample_rate:
                    self.sample_rate_was_reset = False
                
                # Load autostart setting
                self.autostart_enabled = config.getboolean('DEFAULT', 'autostart_enabled', fallback=False)
                # Load startup update check setting
                self.check_updates_at_start = config.getboolean('DEFAULT', 'check_updates_at_start', fallback=False)

                print(f"Loaded tray_click_opens_cables from config: {tray_click_opens_cables}")
                print(f"Loaded remember_settings: {self.remember_settings}")
                print(f"Loaded autostart_enabled: {self.autostart_enabled}")
                print(f"Loaded check_updates_at_start: {self.check_updates_at_start}")

                # Sync autostart file with config
                if self.autostart_enabled != self.autostart_manager.is_autostart_enabled():
                    if self.autostart_enabled:
                        self.autostart_manager.enable_autostart()
                    else:
                        self.autostart_manager.disable_autostart()
            except Exception as e:
                print(f"Error loading settings: {e}")

        # Set the checkbox states
        self.tray_toggle_checkbox.setChecked(tray_enabled)
        # Block signals temporarily while setting the state based on config
        self.remember_settings_checkbox.blockSignals(True)
        self.remember_settings_checkbox.setChecked(self.remember_settings)
        self.remember_settings_checkbox.blockSignals(False) # Unblock signals
        self.tray_click_opens_cables = tray_click_opens_cables

        if tray_enabled:
            # Remove the old tray icon first if it exists
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon = None
            # Then create a new one with updated settings
            self.toggle_tray_icon(Qt.CheckState.Checked)

        # Block signals while potentially setting combo indices during load
        self.quantum_combo.blockSignals(True)
        self.sample_rate_combo.blockSignals(True)

        # Apply saved audio settings if enabled, but don't save them again during startup
        if self.remember_settings:
            try:
                # Only apply saved settings if they exist and are non-zero
                if self.saved_quantum > 0:
                    quantum_str = str(self.saved_quantum)
                    print(f"Applying saved quantum: {quantum_str}")
                    # Find or insert the saved value
                    index = self.quantum_combo.findText(quantum_str)
                    # Check if index is valid
                    if index >= 0:
                       self.quantum_combo.setCurrentIndex(index)
                       self.last_valid_quantum_index = index # Store initial index
                    else: # Saved value not in list, insert it before "Edit List..."
                        edit_item_index = self.quantum_combo.count() - 1 # Index of EDIT_LIST_TEXT
                        if edit_item_index >= 0:
                            self.quantum_combo.insertItem(edit_item_index, quantum_str)
                            self.quantum_combo.setCurrentIndex(edit_item_index)
                            self.last_valid_quantum_index = edit_item_index
                            print(f"Inserted saved quantum '{quantum_str}' into dropdown.")
                        else: # Should not happen if EDIT_LIST_TEXT was added
                             print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert saved quantum '{quantum_str}' before.")
                    self.apply_quantum_settings(skip_save=True) # Apply after setting index

                if self.saved_sample_rate > 0:
                    sample_rate_str = str(self.saved_sample_rate)
                    print(f"Applying saved sample rate: {sample_rate_str}")
                    # Find or insert the saved value
                    index = self.sample_rate_combo.findText(sample_rate_str)
                    # Check if index is valid
                    if index >= 0:
                       self.sample_rate_combo.setCurrentIndex(index)
                       self.last_valid_sample_rate_index = index # Store initial index
                    else: # Saved value not in list, insert it before "Edit List..."
                        edit_item_index = self.sample_rate_combo.count() - 1 # Index of EDIT_LIST_TEXT
                        if edit_item_index >= 0:
                            self.sample_rate_combo.insertItem(edit_item_index, sample_rate_str)
                            self.sample_rate_combo.setCurrentIndex(edit_item_index)
                            self.last_valid_sample_rate_index = edit_item_index
                            print(f"Inserted saved sample rate '{sample_rate_str}' into dropdown.")
                        else: # Should not happen
                             print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert saved sample rate '{sample_rate_str}' before.")
                    self.apply_sample_rate_settings(skip_save=True) # Apply after setting index
            except Exception as e:
                print(f"Error applying saved audio settings: {e}")
        else:
            # If not remembering settings, ensure the initial last_valid index is set
            # based on the currently selected item (likely the first item or system default)
            # This assumes load_current_settings runs *before* this point if needed
             current_quantum_index = self.quantum_combo.currentIndex()
             # Ensure the initial index is not the "Edit List..." item
             if current_quantum_index >= 0 and self.quantum_combo.itemText(current_quantum_index) != EDIT_LIST_TEXT:
                 self.last_valid_quantum_index = current_quantum_index
             elif self.quantum_combo.count() > 1: # Fallback to 0 if "Edit List..." is selected initially
                 self.last_valid_quantum_index = 0
                 self.quantum_combo.setCurrentIndex(0)
             else: # Combo box is empty except for "Edit List..."
                 self.last_valid_quantum_index = -1 # Or handle appropriately

             current_sample_rate_index = self.sample_rate_combo.currentIndex()
             # Ensure the initial index is not the "Edit List..." item
             if current_sample_rate_index >= 0 and self.sample_rate_combo.itemText(current_sample_rate_index) != EDIT_LIST_TEXT:
                 self.last_valid_sample_rate_index = current_sample_rate_index
             elif self.sample_rate_combo.count() > 1: # Fallback to 0
                 self.last_valid_sample_rate_index = 0
                 self.sample_rate_combo.setCurrentIndex(0)
             else: # Combo box is empty except for "Edit List..."
                 self.last_valid_sample_rate_index = -1

        # Unblock signals after potentially setting indices
        self.quantum_combo.blockSignals(False)
        self.sample_rate_combo.blockSignals(False)

        # Manually call update_latency_display after potentially changing indices without signals
        self.update_latency_display()

    def _write_config(self, config, config_path):
        """Helper method to write config.""" # Removed reference to comment block
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w') as configfile:
                config.write(configfile)                    # Write configparser content
        except Exception as e:
            print(f"Error writing config file {config_path}: {e}")
            # Optionally raise or show a message box here

    def save_settings(self):
        """Save UI settings to config file (does not save audio settings)"""
        config = configparser.ConfigParser()
        config_path = os.path.expanduser("~/.config/cable/config.ini")
        
        # Load existing config if it exists
        if os.path.exists(config_path):
            config.read(config_path)
            
        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}
            
        # Update UI settings
        config['DEFAULT'].update({
            'tray_enabled': str(self.tray_toggle_checkbox.isChecked()),
            'tray_click_opens_cables': str(self.tray_click_opens_cables),
            'remember_settings': str(self.remember_settings),
            'autostart_enabled': str(self.autostart_enabled),
            'check_updates_at_start': str(self.check_updates_at_start) # Save the new setting
        })
        

        
        # Use the helper method to write the config
        self._write_config(config, config_path)

    def toggle_remember_settings(self, state):
        """Handle remember settings checkbox state changes"""
        remember = bool(state)
        self.remember_settings = remember
        
        # Update config
        config = configparser.ConfigParser()
        config_path = os.path.expanduser("~/.config/cable/config.ini")
        
        if os.path.exists(config_path):
            config.read(config_path)
        
        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}
        
        if remember:
            # Save current settings immediately when enabling
            config['DEFAULT']['remember_settings'] = 'True'
            

            current_quantum = self.quantum_combo.currentText()
            if current_quantum and not self.quantum_was_reset:
                config['DEFAULT']['saved_quantum'] = current_quantum
                print(f"Remember settings: Saved quantum {current_quantum}")
            
            current_sample_rate = self.sample_rate_combo.currentText()
            if current_sample_rate and not self.sample_rate_was_reset:
                config['DEFAULT']['saved_sample_rate'] = current_sample_rate
                print(f"Remember settings: Saved sample rate {current_sample_rate}")
                
            print("Audio settings will be remembered and restored on startup")
        else:
            # Remove saved audio settings when disabling
            config['DEFAULT']['remember_settings'] = 'False'
            if 'saved_quantum' in config['DEFAULT']:
                del config['DEFAULT']['saved_quantum']
            if 'saved_sample_rate' in config['DEFAULT']:
                del config['DEFAULT']['saved_sample_rate']
            print("Audio settings will not be remembered")
        
        # Save other settings that might exist
        if 'tray_enabled' in config['DEFAULT']:
            config['DEFAULT']['tray_enabled'] = str(self.tray_toggle_checkbox.isChecked())
        if 'tray_click_opens_cables' in config['DEFAULT']:
            config['DEFAULT']['tray_click_opens_cables'] = str(self.tray_click_opens_cables)
        
        # Use the helper method to write the config
        self._write_config(config, config_path)

    def setup_tray_icon(self):
        if not self.tray_icon:
            print(f"Setting up tray icon with tray_click_opens_cables: {self.tray_click_opens_cables}")
            self.tray_icon = QSystemTrayIcon(self)

            # List of possible icon locations
            icon_locations = [
                "/usr/share/icons/hicolor/scalable/apps/jack-plug.svg",  # System-wide installation
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "jack-plug.svg"),  # Same directory as the script
                os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "jack-plug.svg")  # Directory of the executed file
            ]

            icon_path = next((path for path in icon_locations if os.path.exists(path)), None)

            if icon_path:
                self.tray_icon.setIcon(QIcon(icon_path))
            else:
                print("Warning: Icon file not found. Using fallback icon.")
                self.tray_icon.setIcon(QIcon.fromTheme("application-x-executable"))

            # Create the menu
            tray_menu = QMenu()

            # Create regular menu items for direct access
            show_cable_action = QAction("Cable", self)
            show_cables_action = QAction("Cables", self)

            # Connect the regular menu items
            show_cable_action.triggered.connect(self.handle_show_action)
            show_cables_action.triggered.connect(self.handle_cables_action)

            # Create a submenu for click behavior selection
            click_menu = QMenu("Default App", self)

            # Create actions for the radio buttons
            cable_action = QAction("Cable", self)
            cables_action = QAction("Cables", self)

            # Make them checkable and exclusive
            cable_action.setCheckable(True)
            cables_action.setCheckable(True)

            # Set initial state based on loaded setting (now guaranteed to be boolean)
            cable_action.setChecked(not bool(self.tray_click_opens_cables))
            cables_action.setChecked(bool(self.tray_click_opens_cables))

            # Create an action group to make the selection exclusive
            action_group = QActionGroup(self)
            action_group.addAction(cable_action)
            action_group.addAction(cables_action)
            action_group.setExclusive(True)

            # Connect the actions to update the tray click behavior
            cable_action.triggered.connect(lambda: self.set_tray_click_target(False))
            cables_action.triggered.connect(lambda: self.set_tray_click_target(True))

            # Add actions to the click submenu
            click_menu.addAction(cable_action)
            click_menu.addAction(cables_action)

            # Build the complete menu
            tray_menu.addAction(show_cable_action)
            tray_menu.addAction(show_cables_action)
            tray_menu.addSeparator()
            tray_menu.addMenu(click_menu)
            tray_menu.addSeparator()

            # Add autostart toggle
            autostart_action = QAction("Autostart", self)
            autostart_action.setCheckable(True)
            autostart_action.setChecked(self.autostart_enabled)
            autostart_action.triggered.connect(self.toggle_autostart)
            tray_menu.addAction(autostart_action)
            tray_menu.addSeparator()

            # Add quit action
            quit_action = QAction("Quit", self)
            quit_action.triggered.connect(self.quit_app)
            tray_menu.addAction(quit_action)

            # Set the menu for the tray icon
            self.tray_icon.setContextMenu(tray_menu)

            # Connect left-click to show the app
            self.tray_icon.activated.connect(self.tray_icon_activated)

        # Show the tray icon
        self.tray_icon.show()

    def set_tray_click_target(self, opens_cables):
        """Update which application opens on tray icon click"""
        print(f"Setting tray click target - opens_cables: {opens_cables}")
        self.tray_click_opens_cables = opens_cables

        # Update the menu item checked states
        if hasattr(self, 'cable_action') and hasattr(self, 'cables_action'):
            self.cable_action.setChecked(not opens_cables)
            self.cables_action.setChecked(opens_cables)

        self.save_settings()

    def _ensure_connection_manager_visible(self):
        """Launches connection manager if not running, otherwise terminates and relaunches to bring to front."""
        if self.connection_manager_process is None or (
            hasattr(self.connection_manager_process, 'state') and
            self.connection_manager_process.state() == QProcess.ProcessState.NotRunning
        ):
            # If Cables app is not running, launch it
            self.launch_connection_manager()
        else:
            # As a workaround, kill and restart it to bring to front
            print("Connection manager process already running, bringing to front")
            self.connection_manager_process.terminate()
            # Wait a brief moment for termination before relaunching
            QTimer.singleShot(500, self.launch_connection_manager)

    def toggle_tray_icon(self, state):
        state_enum = Qt.CheckState(state)
        if state_enum == Qt.CheckState.Checked:
            self.tray_enabled = True
            self.setup_tray_icon()
        else:
            self.tray_enabled = False
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon = None
        self.save_settings()


    def handle_show_action(self):
        """Show the main Cable window"""
        if not self.isVisible():
            # Force refresh settings when showing from tray
            self.load_current_settings()
            # Refresh device and node lists when shown from tray
            print("Refreshing devices/nodes from handle_show_action") # Debug print
            self.load_devices()
            self.load_nodes()
            self.show()  # PyQt6: showNormal() is now show() for restoring
            self.activateWindow()

    def handle_cables_action(self):
        """Handle selection of 'Cables' from tray menu"""
        self._ensure_connection_manager_visible()

    def open_cables(self):
        """Open the Cables window (used by main app button)"""
        self._ensure_connection_manager_visible()

    def tray_icon_activated(self, reason):
        """Handle tray icon activation (clicks)"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            if self.tray_click_opens_cables:  # Check the toggle
                if self.connection_manager_process is None or (
                    hasattr(self.connection_manager_process, 'state') and 
                    self.connection_manager_process.state() == QProcess.ProcessState.NotRunning
                ):
                    # If Cables app is not running at all, launch it
                    self.launch_connection_manager()
                else:
                    # Process is already running, just terminate it (toggle behavior)
                    print("Connection manager is already running, closing it")
                    self.connection_manager_process.terminate()
                    # Don't schedule a relaunch
            else:
                if self.isMinimized() or not self.isVisible():
                    # Force refresh settings before showing
                    print("Refreshing devices/nodes from tray_icon_activated") # Debug print
                    self.load_current_settings()
                    self.load_devices()
                    self.load_nodes()
                    self.show()  # Restore window if minimized
                    self.activateWindow()  # Bring window to the front
                else:
                    self.hide()  # Minimize to tray

    def launch_connection_manager(self, headless=False): # Add headless parameter
        """Launch connection-manager.py as an independent process to avoid JACK errors in the main process"""
        try:
            # Define possible paths
            possible_paths = [
                os.path.join(sys._MEIPASS, 'connection-manager.py') if getattr(sys, 'frozen', False) else None,  # PyInstaller bundle path
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'connection-manager.py'),  # Same directory
                '/usr/share/cable/connection-manager.py'  # System installation path
            ]
            
            # Find first existing path
            module_path = next((path for path in possible_paths if path and os.path.exists(path)), None)
            if not module_path:
                raise FileNotFoundError("Could not find connection-manager.py in any of the expected locations")

            # Create a QProcess for running connection-manager.py if it's not already running
            if self.connection_manager_process is None:
                self.connection_manager_process = QProcess()
                
                # Connect signals to handle process state
                self.connection_manager_process.finished.connect(self.on_connection_manager_closed)

                # Prepare arguments
                arguments = [module_path]
                if headless:
                    arguments.append('--headless') # Add headless argument if requested

                # Set up the command
                if self.flatpak_env:
                    # In Flatpak, we need to use flatpak-spawn to run the Python interpreter
                    self.connection_manager_process.setProgram('flatpak-spawn')
                    self.connection_manager_process.setArguments(['--host', 'python3'] + arguments) # Pass arguments
                else:
                    # Normal execution
                    self.connection_manager_process.setProgram('python3')
                    self.connection_manager_process.setArguments(arguments) # Pass arguments

                # Start the process
                self.connection_manager_process.start()
                print(f"Started connection manager {'headless ' if headless else ''}using {module_path}") # Update log
            else:
                # Process exists but it might be terminated
                if self.connection_manager_process.state() == QProcess.ProcessState.NotRunning:
                    # Restart the process
                    self.connection_manager_process.start()
                    print("Restarting connection manager process")
                else:
                    print("Connection manager process already running")
        except Exception as e:
            print(f"Error launching connection manager: {e}")
    
    def on_connection_manager_closed(self, exitCode, exitStatus):
        """Handle the connection manager process closing"""
        print(f"Connection manager process exited with code {exitCode}, status {exitStatus}")
        # Reset the process object so we can create a new one next time
        self.connection_manager_process = None

    def closeEvent(self, event):
        # If remember settings is enabled, check if we need to save current values
        # Handle the tray icon and other close events as before
        if self.tray_enabled and self.tray_icon:
            event.ignore()
            self.hide()
        else:
            event.accept()

    def eventFilter(self, obj, event):
        """Handle left-clicks on the version label."""
        if obj is self.version_label and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.show_version_context_menu(event.pos())
                return True # Event handled
        # Pass the event on to the parent class if it's not for the version label or not a left-click
        return super().eventFilter(obj, event)

    def quit_app(self):
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()

    def update_latency_display(self):
        # Block signals from the combo boxes to prevent loops when resetting index
        self.quantum_combo.blockSignals(True)
        self.sample_rate_combo.blockSignals(True)
        try:
            # Get text from the combo box, could be non-numeric or special text
            quantum_text = self.quantum_combo.currentText()
            sample_rate_text = self.sample_rate_combo.currentText()

            # Try to convert to int, default to 0 if fails or special text
            try:
                quantum = int(quantum_text) if quantum_text != EDIT_LIST_TEXT else 0
            except ValueError:
                quantum = 0 # Treat non-numeric input as 0 for calculation

            try:
                sample_rate = int(sample_rate_text) if sample_rate_text != EDIT_LIST_TEXT else 0
            except ValueError:
                sample_rate = 0 # Treat non-numeric input as 0 for calculation


            if sample_rate == 0 or quantum == 0:
                self.latency_display_value.setText("N/A")
            else:
                latency_ms = quantum / sample_rate * 1000
                self.latency_display_value.setText(f"{latency_ms:.2f} ms")
                print(f"Updated latency display: {latency_ms:.2f} ms (quantum={quantum}, sample_rate={sample_rate})")
        finally:
            # Always unblock signals
            self.quantum_combo.blockSignals(False)
            self.sample_rate_combo.blockSignals(False)


    def set_button_style(self, button):
        button.setStyleSheet("""
            QPushButton {
                color: red;
                font-weight: bold;
            }
        """)

    def confirm_restart_wireplumber(self):
        reply = QMessageBox.question(self, 'Confirm Restart',
                                     "Are you sure you want to restart Wireplumber?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.restart_wireplumber()

    def confirm_restart_pipewire(self):
        reply = QMessageBox.question(self, 'Confirm Restart',
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
            QMessageBox.information(self, "Success", f"{service_display_name} restarted successfully")
            self.reload_app_settings()
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
            QMessageBox.critical(self, "Error", detailed_message)
            return False
        except Exception as e: # Catch other potential errors
             QMessageBox.critical(self, "Error", f"An unexpected error occurred while restarting {service_display_name}: {e}")
             return False

    def restart_wireplumber(self):
        self._restart_systemd_service('wireplumber', 'Wireplumber')

    def restart_pipewire(self):
        self._restart_systemd_service('pipewire', 'Pipewire')

    def reload_app_settings(self):
        # Schedule the reload after a short delay to allow services to fully restart
        QTimer.singleShot(1000, self.perform_reload)

    def perform_reload(self):
        # Reload all settings and update UI
        self.load_current_settings()
        self.load_devices()
        self.load_nodes()
        
        # Reset device and node selections
        self.device_combo.setCurrentIndex(0)
        self.node_combo.setCurrentIndex(0)
        
        # Clear profile and latency input
        self.profile_combo.clear()
        self.latency_input.clear()
        
        # If remember settings is enabled and we have saved values, restore them
        # without triggering saves
        if self.remember_settings:
            config = configparser.ConfigParser()
            config_path = os.path.expanduser("~/.config/cable/config.ini")
            
            if os.path.exists(config_path):
                try:
                    config.read(config_path)
                    
                    if 'DEFAULT' in config:
                        # Block signals during reload apply
                        self.quantum_combo.blockSignals(True)
                        self.sample_rate_combo.blockSignals(True)
                        try:
                            if 'saved_quantum' in config['DEFAULT']:
                                quantum = config['DEFAULT']['saved_quantum']
                                # Find or insert
                                index = self.quantum_combo.findText(quantum)
                                if index >= 0:
                                    self.quantum_combo.setCurrentIndex(index)
                                    self.last_valid_quantum_index = index
                                else: # Insert before "Edit List..."
                                    edit_item_index = self.quantum_combo.count() - 1
                                    if edit_item_index >= 0:
                                        self.quantum_combo.insertItem(edit_item_index, quantum)
                                        self.quantum_combo.setCurrentIndex(edit_item_index)
                                        self.last_valid_quantum_index = edit_item_index
                                        print(f"Inserted saved quantum '{quantum}' during reload.")
                                    else: print("Warning: Edit item not found in quantum_combo during reload")
                                self.apply_quantum_settings(skip_save=True)

                            if 'saved_sample_rate' in config['DEFAULT']:
                                sample_rate = config['DEFAULT']['saved_sample_rate']
                                # Find or insert
                                index = self.sample_rate_combo.findText(sample_rate)
                                if index >= 0:
                                    self.sample_rate_combo.setCurrentIndex(index)
                                    self.last_valid_sample_rate_index = index
                                else: # Insert before "Edit List..."
                                    edit_item_index = self.sample_rate_combo.count() - 1
                                    if edit_item_index >= 0:
                                        self.sample_rate_combo.insertItem(edit_item_index, sample_rate)
                                        self.sample_rate_combo.setCurrentIndex(edit_item_index)
                                        self.last_valid_sample_rate_index = edit_item_index
                                        print(f"Inserted saved sample rate '{sample_rate}' during reload.")
                                    else: print("Warning: Edit item not found in sample_rate_combo during reload")
                                self.apply_sample_rate_settings(skip_save=True)
                        finally:
                            self.quantum_combo.blockSignals(False)
                            self.sample_rate_combo.blockSignals(False)
                            self.update_latency_display() # Update latency after changes

                except Exception as e:
                    print(f"Error restoring saved settings during reload: {e}")
        


    def _load_pw_cli_items(self, item_type, combo_box, initial_text):
        """Helper to load items (Devices or Nodes) from 'pw-cli ls' output."""
        combo_box.clear()
        combo_box.addItem(initial_text)
        try:
            output = self.run_command(['pw-cli', 'ls', item_type])
            if not output:
                print(f"Error: Empty response from pw-cli ls {item_type}")
                return

            items = output.split('\n')
            current_item_id = None
            current_item_description = None
            current_item_name = None
            desc_key = f"{item_type.lower()}.description"
            name_key = f"{item_type.lower()}.name"

            for line in items:
                line = line.strip()
                if line.startswith("id "):
                    # Extract ID, handling potential extra info after comma
                    try:
                        current_item_id = line.split(',')[0].split()[-1].strip()
                    except IndexError:
                        print(f"Warning: Could not parse ID from line: {line}")
                        current_item_id = None # Reset ID if parsing fails
                        continue # Skip to next line
                elif desc_key in line:
                    try:
                        current_item_description = line.split('=', 1)[1].strip().strip('"')
                    except IndexError:
                         print(f"Warning: Could not parse description from line: {line}")
                         current_item_description = None
                elif name_key in line:
                    try:
                        current_item_name = line.split('=', 1)[1].strip().strip('"')
                    except IndexError:
                         print(f"Warning: Could not parse name from line: {line}")
                         current_item_name = None

                    # Once we have name, check if we have enough info and if it's an ALSA item
                    if current_item_id and current_item_description and current_item_name and current_item_name.startswith("alsa_"):
                        label = f"{current_item_description} (ID: {current_item_id})"
                        # Add I/O type for Nodes
                        if item_type == 'Node':
                            io_type = "Unknown"
                            if "input" in current_item_name.lower():
                                io_type = "Input"
                            elif "output" in current_item_name.lower():
                                io_type = "Output"
                            label = f"{current_item_description} ({io_type}) (ID: {current_item_id})"

                        combo_box.addItem(label)

                    # Reset for next item after processing name line
                    current_item_id = None
                    current_item_description = None
                    current_item_name = None

        except Exception as e:
            print(f"Error loading {item_type}s: {e}")
            QMessageBox.critical(self, "Error",
                f"Could not retrieve {item_type}s:\n{str(e)}")

    def load_devices(self):
        self._load_pw_cli_items('Device', self.device_combo, "Choose device")

    def load_nodes(self):
        self._load_pw_cli_items('Node', self.node_combo, "Choose Node")

    def on_device_changed(self, index):
        if index > 0:  # Ignore the "Choose device" option
            self.load_profiles()
        else:
            self.profile_combo.clear()

    def on_node_changed(self, index):
        if index > 0:  # Ignore the "Choose Node" option
            selected_node = self.node_combo.currentText()
            node_id = selected_node.split('(ID: ')[-1].strip(')')
            self.load_latency_offset(node_id)
        else:
            self.latency_input.setText("")

    def load_latency_offset(self, node_id):
        try:
            output = subprocess.check_output(["pw-cli", "e", node_id, "ProcessLatency"], universal_newlines=True)

            # First, check for Long (nanoseconds) value
            ns_match = re.search(r'Long\s+(\d+)', output)
            if ns_match and int(ns_match.group(1)) > 0:
                latency_rate = ns_match.group(1)
                self.nanoseconds_checkbox.setChecked(True)
                self.latency_input.setText(latency_rate)
            else:
                # If Long is not present or zero, check for Int (samples) value
                rate_match = re.search(r'Int\s+(\d+)', output)
                if rate_match:
                    latency_rate = rate_match.group(1)
                    self.nanoseconds_checkbox.setChecked(False)
                    self.latency_input.setText(latency_rate)
                else:
                    self.latency_input.setText("")
                    self.nanoseconds_checkbox.setChecked(False)
                    print(f"Error: Unable to parse latency offset for node {node_id}")
        except subprocess.CalledProcessError:
            self.latency_input.setText("")
            self.nanoseconds_checkbox.setChecked(False)
            print(f"Error: Unable to retrieve latency offset for node {node_id}")

    def load_profiles(self):
        self.profile_combo.clear()
        self.profile_index_map.clear()
        selected_device = self.device_combo.currentText()
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        try:
            output = subprocess.check_output(["pw-dump", device_id], universal_newlines=True)
            data = json.loads(output)
            active_profile_index = None
            profiles = None

            for item in data:
                if 'info' in item and 'params' in item['info']:
                    params = item['info']['params']
                    if 'Profile' in params:
                        active_profile_index = params['Profile'][0]['index']
                    if 'EnumProfile' in params:
                        profiles = params['EnumProfile']

            if profiles:
                for profile in profiles:
                    index = profile.get('index', 'Unknown')
                    description = profile.get('description', 'Unknown Profile')
                    self.profile_combo.addItem(description)
                    self.profile_index_map[description] = index

                    # Set the active profile
                    if active_profile_index is not None and index == active_profile_index:
                        self.profile_combo.setCurrentText(description)
        except subprocess.CalledProcessError:
            print(f"Error: Unable to retrieve profiles for device {selected_device}")

    def apply_latency_settings(self):
        selected_node = self.node_combo.currentText()
        node_id = selected_node.split('(ID: ')[-1].strip(')')
        latency_offset = self.latency_input.text()
        try:
            # Build base command
            command = [
                'pw-cli',
                's',
                node_id,
                'ProcessLatency'
            ]
            # Add latency parameter
            if self.nanoseconds_checkbox.isChecked():
                command.append(f'{{ ns = {latency_offset} }}')
            else:
                command.append(f'{{ rate = {latency_offset} }}')
            # Add Flatpak prefix if needed
            if self.flatpak_env:
                command = ['flatpak-spawn', '--host'] + command
            # Run command
            result = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            print(f"Applied latency offset {latency_offset} to node {selected_node}")
            print(f"Command output: {result.stdout}")

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to apply latency settings:\n{e.stderr}"
            print(error_msg)
            QMessageBox.critical(
                self,
                "Latency Error",
                f"{error_msg}\n\n"
                "Possible solutions:\n"
                "1. Ensure PipeWire is running\n"
                "2. Check Flatpak permissions\n"
                "3. Verify node ID is correct"
            )
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(error_msg)
            QMessageBox.critical(
                self,
                "Error",
                error_msg
            )

    def apply_profile_settings(self):
        selected_device = self.device_combo.currentText()
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        selected_profile = self.profile_combo.currentText()
        profile_index = self.profile_index_map.get(selected_profile)
        try:
            self.run_command(['wpctl', 'set-profile', device_id, str(profile_index)], check_output=False)
            print(f"Applied profile {selected_profile} to device {selected_device}")
        except Exception as e:
            print(f"Error applying profile: {e}")

    def _apply_metadata_setting(self, setting_name, metadata_key, combo_box, last_valid_index_attr, was_reset_attr, save_setting_func, skip_save=False):
        """Helper to apply PipeWire metadata settings for quantum or sample rate."""
        value_str = combo_box.currentText()
        last_valid_index = getattr(self, last_valid_index_attr)

        # Prevent applying if value is empty or the special edit text
        if not value_str or value_str == EDIT_LIST_TEXT:
             print(f"Skipping apply for invalid/special text: '{value_str}'")
             # Reset to last valid value if user typed it and pressed Enter/Apply
             QTimer.singleShot(0, lambda: combo_box.setCurrentIndex(last_valid_index))
             return False # Indicate failure

        try:
            # Check if it's a valid integer before proceeding
            int(value_str)

            success = self.run_command([
                'pw-metadata',
                '-n', 'settings',
                '0', metadata_key,
                value_str
            ], check_output=False)

            if success:
                print(f"Applied {setting_name} setting: {value_str}")
                # Clear the reset flag since we're explicitly applying a setting
                # But only if we're not in initial load
                if not self.initial_load:
                    setattr(self, was_reset_attr, False)

                # Save setting if remember settings is enabled, we're not skipping save,
                # and we're not in initial load
                if self.remember_settings_checkbox.isChecked() and not skip_save and not self.initial_load:
                    save_setting_func()

                # Update the last valid index to the newly applied value's index
                # Do this *after* successful application
                new_index = combo_box.findText(value_str)
                if new_index >= 0: # Ensure the applied value exists in the combo (it should)
                    setattr(self, last_valid_index_attr, new_index)
                    print(f"Updated last valid index for {setting_name} to {new_index} after applying '{value_str}'")

                return True # Indicate success
            else:
                print(f"Failed to apply {setting_name} setting: {value_str} (run_command failed)")
                # Optionally show error message here?
                return False # Indicate failure

        except ValueError:
             print(f"Invalid {setting_name} value entered: {value_str}. Cannot apply.")
             QMessageBox.warning(self, "Invalid Input", f"{setting_name} value must be an integer: '{value_str}'")
             # Reset to last valid index
             QTimer.singleShot(0, lambda: combo_box.setCurrentIndex(last_valid_index))
             return False # Indicate failure
        except Exception as e:
            print(f"Error applying {setting_name}: {e}")
            # Optionally show error message here?
            return False # Indicate failure

    def apply_quantum_settings(self, skip_save=False):
        # Check if "Edit List..." is selected and open the dialog if so
        if self.quantum_combo.currentText() == EDIT_LIST_TEXT:
            self.edit_quantum_list()
            # Reset to last valid selection after dialog
            QTimer.singleShot(0, lambda: self.quantum_combo.setCurrentIndex(self.last_valid_quantum_index))
            return
            
        self._apply_metadata_setting(
            setting_name="quantum/buffer",
            metadata_key='clock.force-quantum',
            combo_box=self.quantum_combo,
            last_valid_index_attr='last_valid_quantum_index',
            was_reset_attr='quantum_was_reset',
            save_setting_func=self.save_quantum_setting,
            skip_save=skip_save
        )

    def _save_audio_setting(self, setting_name, config_key, combo_box, was_reset_attr):
        """Helper method to save quantum or sample rate setting to config file."""
        was_reset = getattr(self, was_reset_attr)
        # Don't save if we've explicitly reset the value and haven't changed it
        if was_reset:
            print(f"Skipping save of {setting_name} setting after reset")
            return

        config = configparser.ConfigParser()
        config_path = os.path.expanduser("~/.config/cable/config.ini")

        # Load existing config if it exists
        if os.path.exists(config_path):
            try:
                config.read(config_path)
            except configparser.ParsingError as e:
                 print(f"Warning: Could not parse config file {config_path} during save. Error: {e}")
                 # Continue with potentially empty config object

        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}

        # Save the specific setting
        current_value = combo_box.currentText()
        # Ensure we don't save empty strings or the edit text
        if current_value and current_value != EDIT_LIST_TEXT:
            config['DEFAULT'][config_key] = current_value
            print(f"Saved {setting_name} setting: {current_value}")
        elif config_key in config['DEFAULT']:
            # If the current value is invalid/empty/edit text, remove the key if it exists
            del config['DEFAULT'][config_key]
            print(f"Removed invalid/empty {setting_name} setting ({config_key}) from config")


        # Use the helper method to write the config
        self._write_config(config, config_path)

    def save_quantum_setting(self):
        """Save only the quantum setting to config file"""
        self._save_audio_setting(
            setting_name="quantum",
            config_key='saved_quantum',
            combo_box=self.quantum_combo,
            was_reset_attr='quantum_was_reset'
        )

    def _reset_metadata_setting(self, setting_name, metadata_key, config_key, was_reset_attr, force_reset_kwarg):
        """Helper to reset PipeWire metadata settings and update config."""
        try:
            # Reset PipeWire setting
            command = ["pw-metadata", "-n", "settings", "0", metadata_key, "0"]
            success = self.run_command(command, check_output=False)

            if not success:
                 print(f"Reset {setting_name} failed (run_command).")
                 QMessageBox.critical(
                     self,
                     "Error",
                     f"Failed to reset {setting_name} settings.\n"
                     "Check PipeWire status and permissions."
                 )
                 return

            print(f"Reset {setting_name} setting to default")

            # Set the reset flag to prevent saving default values
            setattr(self, was_reset_attr, True)
            print(f"Loading default {setting_name} value from system, marked as reset")

            # Remove saved setting from config if it exists
            config = configparser.ConfigParser()
            config_path = os.path.expanduser("~/.config/cable/config.ini")
            config_modified = False
            if os.path.exists(config_path):
                config.read(config_path)
                if 'DEFAULT' in config and config_key in config['DEFAULT']:
                    del config['DEFAULT'][config_key]
                    config_modified = True

            if config_modified:
                # Use the helper method to write the config after deletion
                self._write_config(config, config_path)
                print(f"Removed {config_key} setting from config")

            # Reload current settings but don't save them
            # Pass the force_reset flag dynamically
            load_kwargs = {force_reset_kwarg: True}
            self.load_current_settings(**load_kwargs)

        except subprocess.CalledProcessError as e: # Keep specific check for CalledProcessError if run_command raises it
            print(f"Reset {setting_name} failed: {e.stderr.decode() if e.stderr else str(e)}")
            QMessageBox.critical(
                self,
                "Permission Error",
                f"Failed to reset {setting_name} settings:\n"
                "Ensure Flatpak permissions are properly configured\n"
                f"Details: {e.stderr.decode() if e.stderr else str(e)}"
            )
        except Exception as e:
            print(f"Error during reset {setting_name}: {e}")
            QMessageBox.critical(self, "Error", f"An unexpected error occurred while resetting {setting_name}: {e}")


    def reset_quantum_settings(self):
        self._reset_metadata_setting(
            setting_name="quantum/buffer",
            metadata_key='clock.force-quantum',
            config_key='saved_quantum',
            was_reset_attr='quantum_was_reset',
            force_reset_kwarg='force_reset_quantum'
        )

    def apply_sample_rate_settings(self, skip_save=False):
        # Check if "Edit List..." is selected and open the dialog if so
        if self.sample_rate_combo.currentText() == EDIT_LIST_TEXT:
            self.edit_sample_rate_list()
            # Reset to last valid selection after dialog
            QTimer.singleShot(0, lambda: self.sample_rate_combo.setCurrentIndex(self.last_valid_sample_rate_index))
            return
            
        self._apply_metadata_setting(
            setting_name="sample rate",
            metadata_key='clock.force-rate',
            combo_box=self.sample_rate_combo,
            last_valid_index_attr='last_valid_sample_rate_index',
            was_reset_attr='sample_rate_was_reset',
            save_setting_func=self.save_sample_rate_setting,
            skip_save=skip_save
        )

    def save_sample_rate_setting(self):
        """Save only the sample rate setting to config file"""
        self._save_audio_setting(
            setting_name="sample rate",
            config_key='saved_sample_rate',
            combo_box=self.sample_rate_combo,
            was_reset_attr='sample_rate_was_reset'
        )

    def reset_sample_rate_settings(self):
        self._reset_metadata_setting(
            setting_name="sample rate",
            metadata_key='clock.force-rate',
            config_key='saved_sample_rate',
            was_reset_attr='sample_rate_was_reset',
            force_reset_kwarg='force_reset_sample_rate'
        )

    def load_current_settings(self, force_reset_quantum=False, force_reset_sample_rate=False):
        # Block signals during programmatic changes
        self.quantum_combo.blockSignals(True)
        self.sample_rate_combo.blockSignals(True)
        try:

            sample_rate = None
            quantum = None
            try:
                forced_rate = self.get_metadata_value('clock.force-rate')
                if forced_rate in (None, "0"):
                    sample_rate = self.get_metadata_value('clock.rate')
                else:
                    sample_rate = forced_rate

                forced_quantum = self.get_metadata_value('clock.force-quantum')
                if forced_quantum in (None, "0"):
                    quantum = self.get_metadata_value('clock.quantum')
                else:
                    quantum = forced_quantum
            except Exception as meta_e:
                print(f"Error getting metadata values: {meta_e}")
                # Continue, UI might show defaults or be empty


            if force_reset_quantum and forced_quantum in (None, "0"):
                self.quantum_was_reset = True

            if force_reset_sample_rate and forced_rate in (None, "0"):
                self.sample_rate_was_reset = True

            # --- Update UI elements with the new logic ---
            if sample_rate:
                index = self.sample_rate_combo.findText(sample_rate)
                # Ensure the found index is for a valid numerical item
                if index >= 0:
                    self.sample_rate_combo.setCurrentIndex(index)
                    self.last_valid_sample_rate_index = index # Store initial valid index
                else:
                    # System value not in list, insert it before "Edit List..."
                    edit_item_index = self.sample_rate_combo.count() - 1
                    if edit_item_index >= 0:
                        self.sample_rate_combo.insertItem(edit_item_index, sample_rate)
                        self.sample_rate_combo.setCurrentIndex(edit_item_index)
                        self.last_valid_sample_rate_index = edit_item_index
                        print(f"Inserted system sample rate '{sample_rate}' into dropdown.")
                    else: # Fallback if edit item not found
                         print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert system sample rate '{sample_rate}' before.")


            if quantum:
                index = self.quantum_combo.findText(quantum)
                 # Ensure the found index is for a valid numerical item
                if index >= 0:
                    self.quantum_combo.setCurrentIndex(index)
                    self.last_valid_quantum_index = index # Store initial valid index
                else:
                    # System value not in list, insert it before "Edit List..."
                    edit_item_index = self.quantum_combo.count() - 1
                    if edit_item_index >= 0:
                        self.quantum_combo.insertItem(edit_item_index, quantum)
                        self.quantum_combo.setCurrentIndex(edit_item_index)
                        self.last_valid_quantum_index = edit_item_index
                        print(f"Inserted system quantum '{quantum}' into dropdown.")
                    else: # Fallback if edit item not found
                         print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert system quantum '{quantum}' before.")

        except Exception as e:
            # Catch exceptions during the process
            print(f"Error loading current settings: {e}")
        finally:
            # Unblock signals
            self.quantum_combo.blockSignals(False)
            self.sample_rate_combo.blockSignals(False)

            self.update_latency_display()

    def refresh_all_settings(self):

        print("Refreshing all settings...") # Debug print

        # --- Preserve current selections before clearing ---
        current_quantum_text = self.quantum_combo.currentText()
        current_sample_rate_text = self.sample_rate_combo.currentText()
        # ---

        # --- Reload devices and nodes first ---
        self.load_devices()
        self.load_nodes()
        # ---

        # --- Reload dropdowns from config ---
        # Block signals while repopulating
        self.quantum_combo.blockSignals(True)
        self.sample_rate_combo.blockSignals(True)

        try:
            # Reload Quantum values
            self.quantum_combo.clear()
            quantum_values = self.get_list_from_config('quantum_values', self.DEFAULT_QUANTUM_VALUES)
            for value in quantum_values:
                self.quantum_combo.addItem(str(value))
            self.quantum_combo.addItem(EDIT_LIST_TEXT) # Add edit item back
            edit_item_index = self.quantum_combo.count() - 1
            self.quantum_combo.setItemData(edit_item_index, "Select, then press Enter to edit list", Qt.ItemDataRole.ToolTipRole)
            print(f"Reloaded quantum dropdown with: {quantum_values}")

            # Reload Sample Rate values
            self.sample_rate_combo.clear()
            sample_rate_values = self.get_list_from_config('sample_rate_values', self.DEFAULT_SAMPLE_RATE_VALUES)
            for value in sample_rate_values:
                self.sample_rate_combo.addItem(str(value))
            self.sample_rate_combo.addItem(EDIT_LIST_TEXT) # Add edit item back
            edit_item_index = self.sample_rate_combo.count() - 1
            self.sample_rate_combo.setItemData(edit_item_index, "Select, then press Enter to edit list", Qt.ItemDataRole.ToolTipRole)
            print(f"Reloaded sample rate dropdown with: {sample_rate_values}")

        finally:
            # Unblock signals before loading current settings
            self.quantum_combo.blockSignals(False)
            self.sample_rate_combo.blockSignals(False)

        self.load_current_settings()
        # ---

        # --- Update latency display after all changes ---
        self.update_latency_display()
        # ---
        print("Finished refreshing all settings.")

    def run_command(self, command_args, check_output=True):
        """Generic command runner with Flatpak support"""
        if self.flatpak_env:
            command_args = ['flatpak-spawn', '--host'] + command_args

        try:
            if check_output:
                result = subprocess.check_output(
                    command_args,
                    universal_newlines=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()
            else:
                subprocess.run(
                    command_args,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
        except subprocess.CalledProcessError as e:
            print(f"Command failed: {e}")
            return None

    def toggle_autostart(self, checked):
        """Toggle autostart setting"""
        try:
            if checked:
                if self.autostart_manager.enable_autostart():
                    self.autostart_enabled = True
                    print("Autostart enabled")
                else:
                    QMessageBox.critical(self, "Error",
                                      "Failed to enable autostart.\nCheck permissions and try again.")
                    return
            else:
                if self.autostart_manager.disable_autostart():
                    self.autostart_enabled = False
                    print("Autostart disabled")
                else:
                    QMessageBox.critical(self, "Error",
                                      "Failed to disable autostart.\nCheck permissions and try again.")
                    return
            
            self.save_settings()
        except Exception as e:
            QMessageBox.critical(self, "Error",
                              f"Error toggling autostart: {str(e)}")

    def _initial_update_check(self):
        """Performs the update check only if the setting is enabled."""
        if self.check_updates_at_start:
            print("Performing initial update check as configured...")
            self.check_for_updates()
        else:
            print("Skipping initial update check as configured.")

    def check_for_updates(self):
        """Checks GitHub for newer versions and updates the version label color."""
        print("Checking for updates...")
        try:
            # Use a timeout to prevent hanging indefinitely
            response = requests.get("https://api.github.com/repos/magillos/Cable/tags", timeout=10)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            tags = response.json()

            if not tags:
                print("No tags found on GitHub.")
                # Indicate check completed, no update found
                self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">{APP_VERSION}</a>')
                # QMessageBox.information(self, "Update Check", "Could not find any release tags on GitHub.") # Removed popup
                return

            # Extract version numbers from tag names (assuming tags are like 'vX.Y.Z' or 'X.Y.Z')
            latest_version = None
            for tag in tags:
                tag_name = tag.get('name', '').lstrip('v') # Remove leading 'v' if present
                try:
                    current_tag_version = version.parse(tag_name)
                    if latest_version is None or current_tag_version > latest_version:
                        latest_version = current_tag_version
                except version.InvalidVersion:
                    print(f"Skipping invalid tag name: {tag.get('name')}")
                    continue # Skip tags that don't parse as versions

            if latest_version:
                current_app_version = version.parse(APP_VERSION)
                print(f"Current version: {current_app_version}, Latest GitHub version: {latest_version}")
                if latest_version > current_app_version:
                    print("Newer version found!")
                    # Update label style to orange and add update info
                    self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: orange; text-decoration: none;">{APP_VERSION} (Update available: {latest_version})</a>')
                    # QMessageBox.information(self, "Update Available", f"A newer version ({latest_version}) is available!") # Removed popup
                else:
                    print("Application is up to date.")
                    # Ensure label is default color (grey) if already up-to-date
                    self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">{APP_VERSION}</a>')
                    # QMessageBox.information(self, "Update Check", "You are running the latest version.") # Removed popup
            else:
                print("Could not determine the latest version from tags.")
                self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">{APP_VERSION}</a>')
                # QMessageBox.warning(self, "Update Check", "Could not determine the latest version from the available tags.") # Removed popup


        except requests.exceptions.RequestException as e:
            # Handle network errors, timeouts, etc.
            print(f"Error checking for updates (network issue): {e}")

        except json.JSONDecodeError as e:
            print(f"Error checking for updates (invalid JSON response): {e}")
            # QMessageBox.warning(self, "Update Check Failed", f"Received an invalid response from GitHub:\n{e}") # Removed popup
        except Exception as e:
            # Catch any other unexpected errors
            print(f"An unexpected error occurred during update check: {e}")
            # QMessageBox.critical(self, "Update Check Error", f"An unexpected error occurred:\n{e}") # Removed popup

    def show_version_context_menu(self, pos):
        """Shows the context menu for the version label."""
        context_menu = QMenu(self)

        check_now_action = QAction("Check for new version", self)
        check_now_action.triggered.connect(self.check_for_updates)
        context_menu.addAction(check_now_action)

        download_action = QAction("Download from GitHub", self)
        download_action.triggered.connect(self.open_download_page)
        context_menu.addAction(download_action)

        context_menu.addSeparator()

        # Checkable action to toggle startup check
        startup_check_action = QAction("Check for new version at start", self)
        startup_check_action.setCheckable(True)
        startup_check_action.setChecked(self.check_updates_at_start)
        startup_check_action.toggled.connect(self.toggle_startup_check)
        context_menu.addAction(startup_check_action)

        # Show the menu at the global position of the click
        context_menu.exec(self.version_label.mapToGlobal(pos))

    def toggle_startup_check(self, checked):
        """Updates the startup check setting and saves it."""
        self.check_updates_at_start = checked
        print(f"Set check_updates_at_start to: {self.check_updates_at_start}")
        self.save_settings()

    def open_download_page(self):
        """Opens the GitHub releases page in the default web browser."""
        url = "https://github.com/magillos/Cable/releases"
        print(f"Opening download page: {url}")
        webbrowser.open(url)

    def ensure_config_lists(self):
        """Ensure config.ini contains quantum_values and sample_rate_values keys.""" # Updated docstring
        config = configparser.ConfigParser(allow_no_value=True) # Allow comments without values
        config_path = os.path.expanduser("~/.config/cable/config.ini")

        if os.path.exists(config_path):
            # Read existing config to preserve other settings
            try:
                config.read(config_path)
            except configparser.ParsingError as e:
                print(f"Warning: Could not parse existing config file {config_path}. It might be overwritten. Error: {e}")
                # Start with an empty config object if parsing fails
                config = configparser.ConfigParser(allow_no_value=True)
        else:
            # If file doesn't exist, ensure the directory does
            os.makedirs(os.path.dirname(config_path), exist_ok=True)

        # Ensure DEFAULT section exists
        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}

        default_section = config['DEFAULT']
        config_updated = False # Flag to track if keys were added

        # Add quantum_values if missing
        if 'quantum_values' not in default_section:
            default_section['quantum_values'] = ','.join(str(x) for x in self.DEFAULT_QUANTUM_VALUES)
            config_updated = True

        # Add sample_rate_values if missing
        if 'sample_rate_values' not in default_section:
            default_section['sample_rate_values'] = ','.join(str(x) for x in self.DEFAULT_SAMPLE_RATE_VALUES)
            config_updated = True

        # Write the config only if it was updated
        if config_updated:
            self._write_config(config, config_path)
            print("Added missing default list(s) to config.ini")
    def get_list_from_config(self, key, default_values):
        """

        """
        config = configparser.ConfigParser()
        config_path = os.path.expanduser("~/.config/cable/config.ini")
        try:
            if os.path.exists(config_path):
                config.read(config_path)
                raw = config['DEFAULT'].get(key, None)
                if raw is not None:
                    parts = [x.strip() for x in raw.split(',')]
                    vals = []
                    for p in parts:
                        if p and not p.startswith('#'): # Ignore empty strings and commented out values
                            try:
                                vals.append(int(p))
                            except ValueError:
                                # Only print warning if it's not a comment
                                print(f"Invalid integer '{p}' in config key '{key}'")
                    if vals:
                        return vals
        except Exception as e:
            print(f"Error reading '{key}' from config: {e}")

        return default_values



    def on_quantum_index_changed(self, index):

        self.quantum_combo.blockSignals(True)
        try:
            if index >= 0: # Ensure index is valid
                text = self.quantum_combo.itemText(index)
                if text == EDIT_LIST_TEXT:

                    pass
                else:
                    # Update last valid index and latency display for normal selections
                    self.last_valid_quantum_index = index
                    self.update_latency_display()
        finally:
            # Ensure signals are unblocked
            self.quantum_combo.blockSignals(False)


    def on_sample_rate_index_changed(self, index):

        self.sample_rate_combo.blockSignals(True)
        try:
            if index >= 0: # Ensure index is valid
                text = self.sample_rate_combo.itemText(index)
                if text == EDIT_LIST_TEXT:

                    pass
                else:
                    # Update last valid index and latency display for normal selections
                    self.last_valid_sample_rate_index = index
                    self.update_latency_display()
        finally:
            # Ensure signals are unblocked
            self.sample_rate_combo.blockSignals(False)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Cable - PipeWire Settings Manager')
    parser.add_argument('--minimized', action='store_true',
                      help='Start application minimized to tray')
    args = parser.parse_args(sys.argv[1:])  # Skip the first argument (script name)
    
    # Create application instance
    app = CableApp(sys.argv)
    
    # Create main window
    ex = PipeWireSettingsApp()
    
    # Handle initial window state
    if args.minimized:
        # Ensure tray is enabled when starting minimized
        if not ex.tray_enabled:
            ex.tray_toggle_checkbox.setChecked(True)
            ex.toggle_tray_icon(Qt.CheckState.Checked)
        # Start hidden
        ex.hide()
        # Force a complete refresh of settings after a short delay
        # This simulates clicking the "Refresh" button when starting minimized
        # Also launch connection manager to load startup preset if configured
        print("Cable started minimized, launching connection manager...") # Add log
        ex.launch_connection_manager(headless=True) # Pass headless=True when Cable starts minimized
        QTimer.singleShot(1000, ex.load_current_settings)
    else:
        # Show window normally
        ex.show()
    
    # Run the application and exit
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
