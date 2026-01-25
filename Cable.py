import sys
import signal
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
from cable_core.dialogs import ValueSelectorDialog
from cable_core.autostart import AutostartManager
from cable_core.config import ConfigManager
from cable_core.system import SystemManager
from cable_core.tray import TrayManager # Added import
from cable_core.pipewire import PipewireManager # Added import
from cable_core.process import ProcessManager
from cable_core.updates import UpdateManager # Added import
from cable_core.app_config import APP_VERSION # Import APP_VERSION
from cable_core.embedded_settings_panel import EmbeddedSettingsPanel # Import embedded settings panel
from cable_core import app_config
from cables.config.preset_manager import PresetManager
from PyQt6.QtCore import Qt, QTimer, QFile, QMargins, QProcess, QEvent
from PyQt6.QtGui import QFont, QIcon, QGuiApplication, QActionGroup, QAction
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QComboBox, QLineEdit, QPushButton, QLabel,
                             QSpacerItem, QSizePolicy, QMessageBox, QGroupBox,
                             QCheckBox, QSystemTrayIcon, QMenu, QDialog, QDialogButtonBox,
                             QScrollArea, QWidgetAction, QSplitter)

# -------------------------

# --- Constants ---
EDIT_LIST_TEXT = "Edit List..." # New constant for dialog trigger
# -----------------

# --- New Dialog for Value Selection ---


class CableApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)


        # This needs to match your .desktop file name exactly
        QGuiApplication.setDesktopFileName("com.github.magillos.cable")


        # Set the application name to match the .desktop file
        self.setApplicationName("Cable")
        
        # Set window icon explicitly for title bar
        self._set_application_icon()
    
    def _set_application_icon(self):
        """Set the application window icon."""
        icon_name = "jack-plug.svg"
        icon_theme_name = "jack-plug"
        app_icon = None
        
        # Determine base path - prioritize PyInstaller bundle path if available
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
            bundle_icon_path = os.path.join(base_path, icon_name)
            if os.path.exists(bundle_icon_path):
                app_icon = QIcon(bundle_icon_path)
                if app_icon.isNull():
                    app_icon = None
        else:
            base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
            local_icon_path = os.path.join(base_path, icon_name)
            if os.path.exists(local_icon_path):
                app_icon = QIcon(local_icon_path)
                if app_icon.isNull():
                    app_icon = None
        
        # Try loading from theme if local/bundle icon not found
        if app_icon is None:
            theme_icon = QIcon.fromTheme(icon_theme_name)
            if not theme_icon.isNull():
                app_icon = theme_icon
        
        # Set the window icon
        if app_icon:
            self.setWindowIcon(app_icon)

class PipeWireSettingsApp(QWidget):

    DEFAULT_QUANTUM_VALUES     = [16, 32, 48, 64, 96, 128, 144, 192, 240, 256, 512, 1024, 2048, 4096, 8192]
    DEFAULT_SAMPLE_RATE_VALUES = [44100, 48000, 88200, 96000, 176400, 192000]
    # Comment block to ensure it stays in config.ini

    def __init__(self, is_minimized_startup=False, embedded=False, parent=None):
        super().__init__(parent)
        self.is_minimized_startup = is_minimized_startup # Store the flag
        self.embedded = embedded # Store embedded mode flag
        self.flatpak_env = os.path.exists('/.flatpak-info')
        self.appimage_path = self._detect_appimage_path()  # Detect AppImage path
        self.tray_icon = None  # Initialize tray_icon here
        self.tray_enabled = False
        self.connection_manager_process = None
        self.tray_click_opens_cables = True
        self.profile_index_map = {}
        self.cables_executable_path = None  # Will be set during init
        # Initialize autostart manager (will be updated after config is loaded)
        self.autostart_manager = AutostartManager(self.flatpak_env, self.appimage_path)
        # Instantiate ConfigManager
        self.config_manager = ConfigManager(self)
        self.system_manager = SystemManager(self) # Instantiate SystemManager
        self.tray_manager = TrayManager(self) # Instantiate TrayManager
        self.process_manager = ProcessManager(self) # Instantiate ProcessManager
        self.update_manager = UpdateManager(self, APP_VERSION) # Instantiate UpdateManager, passing APP_VERSION
        self.pipewire_manager = PipewireManager(self) # Instantiate PipewireManager
        # Flags managed by ConfigManager now, remove direct initialization here
        # self.remember_settings = False # Managed by ConfigManager
        # self.restore_only_minimized = False # Managed by ConfigManager
        # self.saved_quantum = 0 # Managed by ConfigManager
        # self.saved_sample_rate = 0 # Managed by ConfigManager
        # self.autostart_enabled = False # Managed by ConfigManager
        # self.check_updates_at_start = False # Managed by ConfigManager
        self.remember_settings = False # Keep placeholder for type hinting/attribute existence if needed elsewhere initially
        self.restore_only_minimized = False # New setting
        self.saved_quantum = 0
        self.saved_sample_rate = 0
        self.autostart_enabled = False
        self.quantum_was_reset = False
        self.sample_rate_was_reset = False
        self.check_updates_at_start = False # Default: Do not check for updates on startup
        self.values_initialized = False  # Flag to track if values have been initialized
        self.autostart_version_action = None # Action for version menu autostart toggle

        # Store last valid indices (still needed for resetting selection)
        self.last_valid_quantum_index = 0
        self.last_valid_sample_rate_index = 0
        
        # Initialize UI first
        self.initUI()
        
        # Flag to prevent saving during initial load
        self.initial_load = True
        
        # First load current system settings as fallback
        self.pipewire_manager.load_current_settings() # Use manager

        # Ensure config lists exist before loading settings
        self.config_manager.ensure_config_lists()

        # Then load settings from config using the manager
        self.config_manager.load_settings()

        # Now allow saving of user changes
        self.initial_load = False
        
        # Mark values as initialized
        self.values_initialized = True

        # Update autostart manager with configured AppImage path
        appimage_path_to_use = self.appimage_path if self.appimage_path else self._detect_appimage_path()
        if appimage_path_to_use:
            # Use configured path if available, otherwise use detected path
            self.autostart_manager = AutostartManager(self.flatpak_env, appimage_path_to_use)

        # Update latency display after everything is loaded
        self.update_latency_display()

        # Conditionally check for updates shortly after startup
        QTimer.singleShot(2000, self.update_manager._initial_update_check) # Check after 2 seconds if enabled (using UpdateManager)
        
        # Timer for debouncing splitter save (embedded mode)
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(500)
        self._splitter_save_timer.timeout.connect(self._perform_save_embedded_splitter_position)
        self._pending_splitter_pos = None

    def _detect_appimage_path(self):
        """Detect if the application is running from an AppImage and return the path."""
        # Check for APPIMAGE environment variable (set by AppImage runtime)
        appimage_path = os.environ.get('APPIMAGE')
        if appimage_path and os.path.exists(appimage_path):
            print(f"Detected AppImage path: {appimage_path}")
            return appimage_path
        return None

    # --- Method moved to PipewireManager ---
    # get_metadata_value (Removed)

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

    def _create_audio_setting_section(self, title, combo_box, apply_button, reset_button, refresh_button, apply_slot, reset_slot, refresh_slot, default_values_key, default_values_list, vertical_buttons=False):
        """Helper method to create UI sections for Quantum and Sample Rate."""
        layout = QVBoxLayout()
        select_layout = QHBoxLayout()
        label = QLabel(f"{title}:")
        combo_box.setEditable(True) # Make combo box editable again
        values = self.config_manager.get_list_from_config(default_values_key, default_values_list)
        for value in values:
            combo_box.addItem(str(value))
        combo_box.addItem(EDIT_LIST_TEXT) # Add edit option back to combo
        edit_item_index = combo_box.count() - 1
        combo_box.setItemData(edit_item_index, "Select, then press Enter to edit list", Qt.ItemDataRole.ToolTipRole)
        select_layout.addWidget(label)
        select_layout.addWidget(combo_box)


        layout.addLayout(select_layout)

        # Use vertical or horizontal button layout based on parameter
        if vertical_buttons:
            buttons_layout = QVBoxLayout()
        else:
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
        # Ensure the config file exists and has the keys before reading (handled by ConfigManager now)
        # self.config_manager.ensure_config_lists() # Called during init

        # Get all values from config (including commented ones) to show in dialog
        all_values = self.config_manager.get_all_values_from_config(config_key, default_values_list)
        # Get currently active values from config using the manager
        active_values = self.config_manager.get_list_from_config(config_key, default_values_list)

        # Show the dialog
        dialog = ValueSelectorDialog(f"Select Active {title} Values", all_values, active_values, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_values = dialog.get_selected_values()
            print(f"Dialog accepted for {title}. Selected values: {selected_values}")

            # Update the config file
            # Construct the new comma-separated string, commenting out unselected values
            new_value_parts = []
            for val in all_values:  # Use all_values instead of default_values_list
                if val in selected_values:
                    new_value_parts.append(str(val))
                else:
                    new_value_parts.append(f"#{val}") # Comment out unselected values

            self.config_manager.set_str_setting(config_key, ','.join(new_value_parts))
            self.config_manager.flush()
            print(f"Updated '{config_key}' in {config_path}")

            # Refresh the UI to reflect changes
            self.refresh_all_settings()

            # No exception handling needed here as ConfigManager handles internal errors, but keeping UI refresh is good.


    def edit_quantum_list(self):
        """Opens the dialog to edit the quantum values list."""
        self._edit_value_list("Quantum", 'quantum_values', self.DEFAULT_QUANTUM_VALUES)

    def edit_sample_rate_list(self):
        """Opens the dialog to edit the sample rate values list."""
        self._edit_value_list("Sample Rate", 'sample_rate_values', self.DEFAULT_SAMPLE_RATE_VALUES)

    def initUI(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10) # Adjust main layout spacing

        # Initialize widgets before passing them to the helper
        self.quantum_combo = QComboBox()
        self.apply_quantum_button = QPushButton()
        self.reset_quantum_button = QPushButton()
        self.refresh_quantum_button = QPushButton()

        self.sample_rate_combo = QComboBox()
        self.apply_sample_rate_button = QPushButton()
        self.reset_sample_rate_button = QPushButton()
        self.refresh_sample_rate_button = QPushButton()

        # Use vertical buttons in embedded mode
        use_vertical_buttons = self.embedded

        # Quantum Section using helper
        quantum_group = self._create_audio_setting_section(
            title="Quantum",
            combo_box=self.quantum_combo,
            apply_button=self.apply_quantum_button,
            reset_button=self.reset_quantum_button,
            refresh_button=self.refresh_quantum_button,
            apply_slot=self.pipewire_manager.apply_quantum_settings, # Use manager
            reset_slot=self.pipewire_manager.reset_quantum_settings, # Use manager
            refresh_slot=self.refresh_all_settings,
            default_values_key='quantum_values',
            default_values_list=self.DEFAULT_QUANTUM_VALUES,
            vertical_buttons=use_vertical_buttons
        )
        self.reset_quantum_button.setToolTip("Restores default quantum/buffer") # Add tooltip

        # Sample Rate Section using helper
        sample_rate_group = self._create_audio_setting_section(
            title="Sample Rate",
            combo_box=self.sample_rate_combo,
            apply_button=self.apply_sample_rate_button,
            reset_button=self.reset_sample_rate_button,
            refresh_button=self.refresh_sample_rate_button,
            apply_slot=self.pipewire_manager.apply_sample_rate_settings, # Use manager
            reset_slot=self.pipewire_manager.reset_sample_rate_settings, # Use manager
            refresh_slot=self.refresh_all_settings,
            default_values_key='sample_rate_values',
            default_values_list=self.DEFAULT_SAMPLE_RATE_VALUES,
            vertical_buttons=use_vertical_buttons
        )
        self.reset_sample_rate_button.setToolTip("Restores default sample rate") # Add tooltip

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
        self.apply_profile_button.clicked.connect(self.pipewire_manager.apply_profile_settings) # Use manager
        profile_layout.addWidget(self.apply_profile_button)

        profile_group = self.create_section_group("Audio Profile", profile_layout)

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
        self.apply_latency_button.clicked.connect(self.pipewire_manager.apply_latency_settings) # Use manager

        # Create a layout for the latency buttons
        if use_vertical_buttons:
            latency_buttons_layout = QVBoxLayout()
        else:
            latency_buttons_layout = QHBoxLayout()

        # Add the existing Apply button
        latency_buttons_layout.addWidget(self.apply_latency_button)

        # Create and add the Reset All Latency button
        self.reset_all_latency_button = QPushButton("Reset All Latency")
        self.reset_all_latency_button.clicked.connect(self._handle_reset_all_latency_and_refresh) # Connect to new handler
        self.reset_all_latency_button.setToolTip("Sets latency to '0' for all nodes") # Add tooltip
        latency_buttons_layout.addWidget(self.reset_all_latency_button)

        # Add the button layout to the main latency layout
        latency_layout.addLayout(latency_buttons_layout)

        self.latency_input.returnPressed.connect(self.pipewire_manager.apply_latency_settings) # Use manager

        latency_group = self.create_section_group("Latency Offset", latency_layout)

        # Restart Buttons Section
        restart_layout = QVBoxLayout()
        # Use vertical layout for restart buttons in embedded mode
        if self.embedded:
            restart_buttons_layout = QVBoxLayout()
        else:
            restart_buttons_layout = QHBoxLayout()
        
        self.restart_wireplumber_button = QPushButton("Restart Wireplumber")
        self.restart_wireplumber_button.clicked.connect(self.system_manager.confirm_restart_wireplumber) # Use system_manager
        self.set_button_style(self.restart_wireplumber_button)
        restart_buttons_layout.addWidget(self.restart_wireplumber_button)

        self.restart_pipewire_button = QPushButton("Restart Pipewire")
        self.restart_pipewire_button.clicked.connect(self.system_manager.confirm_restart_pipewire) # Use system_manager
        self.set_button_style(self.restart_pipewire_button)
        restart_buttons_layout.addWidget(self.restart_pipewire_button)

        restart_layout.addLayout(restart_buttons_layout)
        restart_group = self.create_section_group("Restart Services", restart_layout)

        # Layout arrangement depends on embedded mode
        if self.embedded:
            # Splitter layout: cable content (left) + spacer/settings panel (right)
            self.embedded_splitter = QSplitter(Qt.Orientation.Horizontal)
            
            # Create cable content column
            cable_column = QWidget()
            cable_column.setMinimumWidth(50)
            cable_layout = QVBoxLayout(cable_column)
            cable_layout.setContentsMargins(0, 0, 0, 0)
            cable_layout.addWidget(quantum_group)
            cable_layout.addWidget(sample_rate_group)
            cable_layout.addWidget(profile_group)
            cable_layout.addWidget(latency_group)
            cable_layout.addWidget(restart_group)
            cable_layout.addStretch()
            
            self.embedded_splitter.addWidget(cable_column)
            
            # Add empty spacer widget (visible when settings hidden)
            self.embedded_spacer = QWidget()
            self.embedded_splitter.addWidget(self.embedded_spacer)
            
            # Create settings panel (hidden by default, will replace spacer when shown)
            self.embedded_settings_panel = EmbeddedSettingsPanel(self)
            self.embedded_settings_panel.setVisible(False)
            self.embedded_splitter.addWidget(self.embedded_settings_panel)
            
            # Configure splitter
            self.embedded_splitter.setCollapsible(0, False)
            self.embedded_splitter.setHandleWidth(6)
            self.embedded_splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
            self.embedded_splitter.splitterMoved.connect(self._save_embedded_splitter_position)
            
            # Mark for restore after first show
            self._embedded_splitter_restored = False
            
            main_layout.addWidget(self.embedded_splitter)
        else:
            # Original vertical layout for standalone mode
            main_layout.addWidget(quantum_group)
            main_layout.addWidget(sample_rate_group)
            main_layout.addWidget(profile_group)
            main_layout.addWidget(latency_group)
            main_layout.addWidget(restart_group)



        #Connections button
        self.cables_button = QPushButton("Cables")
        self.cables_button.clicked.connect(self.process_manager.open_cables)
        main_layout.addWidget(self.cables_button)

        self.setLayout(main_layout)
        self.setWindowTitle('Cable')
        # Load window dimensions from config or use app_config defaults
        initial_width = self.config_manager.get_int_setting("MAIN_WINDOW_INITIAL_WIDTH", app_config.MAIN_WINDOW_INITIAL_WIDTH)
        initial_height = self.config_manager.get_int_setting("MAIN_WINDOW_INITIAL_HEIGHT", app_config.MAIN_WINDOW_INITIAL_HEIGHT)

        self.setMinimumSize(app_config.MAIN_WINDOW_MIN_WIDTH, app_config.MAIN_WINDOW_MIN_HEIGHT)  # Set minimum window size
        self.resize(initial_width, initial_height)  # Set initial size

        self.pipewire_manager.load_nodes() # Use manager
        self.pipewire_manager.load_devices() # Use manager
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.node_combo.currentIndexChanged.connect(self.on_node_changed)
        self.quantum_combo.currentIndexChanged.connect(self.on_quantum_index_changed)
        self.sample_rate_combo.currentIndexChanged.connect(self.on_sample_rate_index_changed)


        # Initialize the checkboxes (they will be added to version context menu)
        self.tray_toggle_checkbox = QCheckBox("Enable tray icon")
        self.tray_toggle_checkbox.setChecked(False)
        self.tray_toggle_checkbox.stateChanged.connect(self.tray_manager.toggle_tray_icon) # Use tray_manager

        self.remember_settings_checkbox = QCheckBox("Save buffer and sample rate")
        self.remember_settings_checkbox.setChecked(False)
        self.remember_settings_checkbox.stateChanged.connect(self.config_manager.toggle_remember_settings) # Use manager

        # New checkbox for restoring only when auto-started
        self.restore_only_minimized_checkbox = QCheckBox("Restore above only when app is auto-started")
        self.restore_only_minimized_checkbox.setChecked(False)
        self.restore_only_minimized_checkbox.setEnabled(False) # Initially disabled
        self.restore_only_minimized_checkbox.stateChanged.connect(self.config_manager.toggle_restore_only_minimized) # Use manager

        # Add Settings button at the bottom right
        version_layout = QHBoxLayout()
        version_layout.addStretch() # Push button to the right
        self.settings_button = QPushButton("Settings")
        self.settings_button.setToolTip("Click to access Settings")
        
        # In embedded mode, toggle inline settings panel; otherwise show popup menu
        if self.embedded:
            self.settings_button.clicked.connect(self._toggle_embedded_settings)
        else:
            self.settings_button.clicked.connect(lambda: self.tray_manager.show_version_context_menu(self.settings_button.rect().bottomLeft()))
        
        version_layout.addWidget(self.settings_button)
        main_layout.addLayout(version_layout) # Add to the main layout

        # Apply embedded mode UI modifications
        self._apply_embedded_mode_ui()

    def _apply_embedded_mode_ui(self):
        """Hide UI elements that shouldn't appear when embedded in Cables window."""
        if not self.embedded:
            # When not embedded, check if integrated mode is enabled and hide Cables button
            integrated = self.config_manager.get_bool('integrate_cable_and_cables', False)
            if integrated and hasattr(self, 'cables_button'):
                self.cables_button.hide()
            return
        
        # In embedded mode, hide elements that would be redundant or problematic
        # Keep settings_button visible for access to settings
        if hasattr(self, 'cables_button'):
            self.cables_button.hide()
        if hasattr(self, 'tray_toggle_checkbox'):
            self.tray_toggle_checkbox.hide()

    def _toggle_embedded_settings(self):
        """Toggle visibility of the embedded settings panel."""
        if hasattr(self, 'embedded_settings_panel') and hasattr(self, 'embedded_splitter'):
            is_visible = self.embedded_settings_panel.isVisible()
            
            # Preserve the left column width
            sizes = self.embedded_splitter.sizes()
            left_width = sizes[0]
            total_width = self.embedded_splitter.width()
            remaining = max(0, total_width - left_width)
            
            if is_visible:
                # Hiding settings, show spacer
                self.embedded_settings_panel.setVisible(False)
                self.embedded_spacer.setVisible(True)
                self.embedded_splitter.setSizes([left_width, remaining, 0])
            else:
                # Showing settings, hide spacer
                self.embedded_spacer.setVisible(False)
                self.embedded_settings_panel.setVisible(True)
                self.embedded_settings_panel.refresh_settings()
                self.embedded_splitter.setSizes([left_width, 0, remaining])

    def _save_embedded_splitter_position(self, pos, index):
        """Save the embedded splitter position to config with debounce."""
        if hasattr(self, 'embedded_splitter'):
            sizes = self.embedded_splitter.sizes()
            if sizes[0] > 0:
                self._pending_splitter_pos = sizes[0]
                self._splitter_save_timer.start()

    def _perform_save_embedded_splitter_position(self):
        """Actually save the splitter position to config."""
        if self._pending_splitter_pos is not None:
            self.config_manager.set_int_setting("EMBEDDED_COLUMN_WIDTH", self._pending_splitter_pos)
            self.config_manager.flush()

    def showEvent(self, event):
        """Handle show event to restore splitter size after widget is visible."""
        super().showEvent(event)
        if self.embedded and hasattr(self, '_embedded_splitter_restored') and not self._embedded_splitter_restored:
            self._embedded_splitter_restored = True
            QTimer.singleShot(0, self._restore_embedded_splitter_size)

    def _restore_embedded_splitter_size(self):
        """Restore the embedded splitter size from config."""
        if hasattr(self, 'embedded_splitter'):
            saved_width = self.config_manager.get_int_setting("EMBEDDED_COLUMN_WIDTH", 350)
            total_width = self.embedded_splitter.width()
            # Distribute remaining space between spacer and hidden settings panel
            remaining = max(0, total_width - saved_width)
            self.embedded_splitter.setSizes([saved_width, remaining, 0])

    def closeEvent(self, event):
        # If tray is enabled, hide the window instead of closing
        if self.tray_enabled and self.tray_manager.tray_icon and self.tray_manager.tray_icon.isVisible():
            event.ignore()
            self.hide()
        else:
            # If not hiding to tray, quit the application properly via tray manager
            self.tray_manager.quit_app()
            event.accept() # Accept the event after initiating quit

    def eventFilter(self, obj, event):
        """Handle events."""
        # Pass the event on to the parent class
        return super().eventFilter(obj, event)

    def update_version_display(self):
        """Updates the Settings button highlighting if a new version is available."""
        if self.update_manager.update_available:
            self.settings_button.setStyleSheet("color: orange; font-weight: bold;")
            self.settings_button.setToolTip(f"New version available: {self.update_manager.latest_version}")
        else:
            self.settings_button.setStyleSheet("")
            self.settings_button.setToolTip("Click to access Settings")


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


    def on_device_changed(self, index):
        if index > 0:  # Ignore the "Choose device" option
            self.pipewire_manager.load_profiles() # Use manager
        else:
            self.profile_combo.clear()

    def on_node_changed(self, index):
        if index > 0:  # Ignore the "Choose Node" option
            selected_node = self.node_combo.currentText()
            node_id = selected_node.split('(ID: ')[-1].strip(')')
            self.pipewire_manager.load_latency_offset(node_id) # Use manager
        else:
            self.latency_input.setText("")

    def _handle_reset_all_latency_and_refresh(self):
        """Handles resetting latency and then refreshing all settings."""
        print("Resetting all latency and refreshing settings...") # Debug print
        self.pipewire_manager.reset_all_latency()
        self.refresh_all_settings()
        print("Finished resetting latency and refreshing.") # Debug print

    def refresh_all_settings(self):

        print("Refreshing all settings...") # Debug print

        # --- Preserve current selections before clearing ---
        current_quantum_text = self.quantum_combo.currentText()
        current_sample_rate_text = self.sample_rate_combo.currentText()
        # ---

        # --- Reload devices and nodes first ---
        self.pipewire_manager.load_devices() # Use manager
        self.pipewire_manager.load_nodes() # Use manager
        # ---

        # --- Reload dropdowns from config ---
        # Block signals while repopulating
        self.quantum_combo.blockSignals(True)
        self.sample_rate_combo.blockSignals(True)

        try:
            # Reload Quantum values
            self.quantum_combo.clear()
            # Use config_manager directly
            quantum_values = self.config_manager.get_list_from_config('quantum_values', self.DEFAULT_QUANTUM_VALUES)
            for value in quantum_values:
                self.quantum_combo.addItem(str(value))
            self.quantum_combo.addItem(EDIT_LIST_TEXT) # Use global constant
            edit_item_index = self.quantum_combo.count() - 1
            self.quantum_combo.setItemData(edit_item_index, "Select, then press Enter to edit list", Qt.ItemDataRole.ToolTipRole)
            print(f"Reloaded quantum dropdown with: {quantum_values}")

            # Reload Sample Rate values
            self.sample_rate_combo.clear()
            # Use config_manager directly
            sample_rate_values = self.config_manager.get_list_from_config('sample_rate_values', self.DEFAULT_SAMPLE_RATE_VALUES)
            for value in sample_rate_values:
                self.sample_rate_combo.addItem(str(value))
            self.sample_rate_combo.addItem(EDIT_LIST_TEXT) # Use global constant
            edit_item_index = self.sample_rate_combo.count() - 1
            self.sample_rate_combo.setItemData(edit_item_index, "Select, then press Enter to edit list", Qt.ItemDataRole.ToolTipRole)
            print(f"Reloaded sample rate dropdown with: {sample_rate_values}")

        finally:
            # Unblock signals before loading current settings
            self.quantum_combo.blockSignals(False)
            self.sample_rate_combo.blockSignals(False)

        self.pipewire_manager.load_current_settings() # Use manager
        # ---

        # --- Update latency display after all changes ---
        self.update_latency_display()
        # ---
        print("Finished refreshing all settings.")


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

    def changeEvent(self, event):
        """Handle window state changes, refresh settings when gaining focus."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            # Refresh pipewire settings when window gains focus (non-embedded mode only)
            if not self.embedded and self.values_initialized:
                self.pipewire_manager.load_current_settings()
                self.pipewire_manager.load_devices()
                self.pipewire_manager.load_nodes()
                self.update_latency_display()

    def cleanup_before_quit(self):
        """Clean up resources before quitting."""
        print("Performing cleanup before quitting...")
        # Stop the daemon directly
        preset_manager = PresetManager()
        preset_manager.stop_daemon_mode()
        # Flush config to disk
        if hasattr(self, 'config_manager') and self.config_manager:
            self.config_manager.flush()

def _check_integrated_mode():
    """Check if integrated mode is enabled by reading config directly."""
    config_path = os.path.expanduser("~/.config/cable/config.ini")
    if os.path.exists(config_path):
        try:
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            return config.getboolean('DEFAULT', 'integrate_cable_and_cables', fallback=False)
        except (configparser.Error, ValueError):
            pass
    return False

def _find_connection_manager():
    """Find connection-manager.py in various possible locations."""
    # Possible locations to search
    search_paths = [
        # Same directory as this script (development mode)
        os.path.dirname(os.path.abspath(__file__)),
        # System-wide installation locations
        '/usr/share/cable',
        '/usr/local/share/cable',
        # Flatpak locations
        '/app/bin',  # Flatpak installs to /app/bin
        '/app/share/cable',
        # User local installation
        os.path.expanduser('~/.local/share/cable'),
        os.path.expanduser('~/.local/bin'),
    ]
    
    # Also check directories in sys.path (for pip-installed packages)
    for sys_path in sys.path:
        if sys_path and os.path.isdir(sys_path):
            search_paths.append(sys_path)
    
    for path in search_paths:
        candidate = os.path.join(path, 'connection-manager.py')
        if os.path.exists(candidate):
            return candidate
    
    # Also try using shutil.which to find it in PATH
    result = shutil.which('connection-manager.py')
    if result:
        return result
    
    return None

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Cable - PipeWire Settings Manager')
    parser.add_argument('--minimized', action='store_true',
                      help='Start application minimized to tray')
    args = parser.parse_args(sys.argv[1:])  # Skip the first argument (script name)
    
    # Check if integrated mode is enabled - if so, launch connection-manager.py instead
    if _check_integrated_mode():
        print("Integrated mode enabled, launching Cables (connection-manager.py) instead...")
        # Find the connection-manager.py script
        connection_manager_path = _find_connection_manager()
        
        if connection_manager_path:
            print(f"Found connection-manager.py at: {connection_manager_path}")
            # Replace current process with connection-manager.py
            os.execv(sys.executable, [sys.executable, connection_manager_path] + sys.argv[1:])
        else:
            print("Warning: connection-manager.py not found in any known location")
            print(f"Searched in: {os.path.dirname(os.path.abspath(__file__))}, /usr/share/cable, /app/bin, etc.")
            print("Falling back to standalone Cable mode.")
    
    # Create application instance
    app = CableApp(sys.argv)
    
    # Create main window, passing the minimized flag
    ex = PipeWireSettingsApp(is_minimized_startup=args.minimized)

    # Connect the cleanup function to the application's quit signal
    app.aboutToQuit.connect(ex.cleanup_before_quit)

    # Set up a signal handler for SIGINT (Ctrl+C) to gracefully quit
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # Use a timer to allow the Python interpreter to process signals
    timer = QTimer()
    timer.start(100)  # Check for signals every 100ms
    timer.timeout.connect(lambda: None)  # No-op to wake up the interpreter
    
    # Handle initial window state
    if args.minimized:
        # Ensure tray is enabled when starting minimized
        if not ex.tray_enabled:
            ex.tray_toggle_checkbox.setChecked(True)
            ex.tray_manager.toggle_tray_icon(Qt.CheckState.Checked) # Use tray_manager
        # Start hidden
        ex.hide()
        # Force a complete refresh of settings after a short delay
        # This simulates clicking the "Refresh" button when starting minimized
        # Also launch connection manager to load startup preset if configured
        print("Cable started minimized, launching connection manager...") # Add log
        ex.process_manager.launch_connection_manager(headless=True) # Pass headless=True when Cable starts minimized
        # load_current_settings is already called via pipewire_manager in __init__
        # QTimer.singleShot(1000, ex.pipewire_manager.load_current_settings) # Use manager - Redundant call removed
    else:
        # Show window normally
        ex.show()
    
    # Run the application and exit
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
