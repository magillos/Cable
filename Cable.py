import sys
import subprocess
import json
import re
import fcntl
import os
import dbus
import configparser
from PyQt5.QtCore import Qt, QTimer, QFile, QMargins
from PyQt5.QtGui import QFont, QIcon, QGuiApplication
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QComboBox, QLineEdit, QPushButton, QLabel,
                             QSpacerItem, QSizePolicy, QMessageBox, QGroupBox,
                             QCheckBox, QSystemTrayIcon, QMenu, QAction, QActionGroup)


class CableApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)

        # Set the desktop filename for Wayland
        # This needs to match your .desktop file name exactly
        QGuiApplication.setDesktopFileName("local.cable.Cable")

        # Set the application name to match the .desktop file
        self.setApplicationName("Cable")

class PipeWireSettingsApp(QWidget):
    def __init__(self):
        super().__init__()
        self.flatpak_env = os.path.exists('/.flatpak-info')
        self.tray_icon = None  # Initialize tray_icon here
        self.tray_enabled = False
        self.connection_manager_process = None
        self.tray_click_opens_cables = True #depreciated: [Change to 'False' to open Cable (main app) from tray icon rather than Cables (connections manager)]
        self.profile_index_map = {}

        self.initUI()  # Initialize UI first
        self.load_settings()  # Load settings after UI and attributes are initialized
        self.load_current_settings()


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
        title_label.setAlignment(Qt.AlignCenter)

        layout.insertWidget(0, title_label)

        return group

    def initUI(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10) # Adjust main layout spacing

        # Audio Profile Section
        profile_layout = QVBoxLayout()

        # Device layout
        device_layout = QHBoxLayout()
        device_label = QLabel("Audio Device:")
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        profile_layout.addLayout(device_layout)

        # Profile layout
        profile_select_layout = QHBoxLayout()
        profile_label = QLabel("Device Profile:")
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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

        # Quantum Section
        quantum_layout = QVBoxLayout()
        quantum_select_layout = QHBoxLayout()
        quantum_label = QLabel("Quantum/Buffer:")
        self.quantum_combo = QComboBox()
        self.quantum_combo.setEditable(True)
        quantum_values = [16, 32, 48, 64, 96, 128, 144, 192, 240, 256, 512, 1024, 2048]
        for value in quantum_values:
            self.quantum_combo.addItem(str(value))
        quantum_select_layout.addWidget(quantum_label)
        quantum_select_layout.addWidget(self.quantum_combo)
        quantum_layout.addLayout(quantum_select_layout)

        quantum_buttons_layout = QHBoxLayout()
        self.apply_quantum_button = QPushButton("Apply Quantum")
        self.apply_quantum_button.clicked.connect(self.apply_quantum_settings)
        quantum_buttons_layout.addWidget(self.apply_quantum_button)
        self.quantum_combo.lineEdit().returnPressed.connect(self.apply_quantum_settings)

        self.reset_quantum_button = QPushButton("Reset Quantum")
        self.reset_quantum_button.clicked.connect(self.reset_quantum_settings)
        quantum_buttons_layout.addWidget(self.reset_quantum_button)

        self.refresh_quantum_button = QPushButton("Refresh")
        self.refresh_quantum_button.clicked.connect(self.load_current_settings)
        quantum_buttons_layout.addWidget(self.refresh_quantum_button)

        quantum_layout.addLayout(quantum_buttons_layout)

        latency_display_layout = QHBoxLayout()
        self.latency_display_label = QLabel("Latency:")
        self.latency_display_value = QLabel("0.00 ms")
        latency_display_layout.addStretch()
        latency_display_layout.addWidget(self.latency_display_label)
        latency_display_layout.addWidget(self.latency_display_value)
        quantum_layout.addLayout(latency_display_layout)

        main_layout.addWidget(self.create_section_group("Quantum", quantum_layout))

        # Sample Rate Section
        sample_rate_layout = QVBoxLayout()
        sample_rate_select_layout = QHBoxLayout()
        sample_rate_label = QLabel("Sample Rate:")
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.setEditable(True)
        sample_rate_values = [44100, 48000, 88200, 96000, 176400, 192000]
        for value in sample_rate_values:
            self.sample_rate_combo.addItem(str(value))
        sample_rate_select_layout.addWidget(sample_rate_label)
        sample_rate_select_layout.addWidget(self.sample_rate_combo)
        sample_rate_layout.addLayout(sample_rate_select_layout)

        sample_rate_buttons_layout = QHBoxLayout()
        self.apply_sample_rate_button = QPushButton("Apply Sample Rate")
        self.apply_sample_rate_button.clicked.connect(self.apply_sample_rate_settings)
        sample_rate_buttons_layout.addWidget(self.apply_sample_rate_button)
        self.sample_rate_combo.lineEdit().returnPressed.connect(self.apply_sample_rate_settings)

        self.reset_sample_rate_button = QPushButton("Reset Sample Rate")
        self.reset_sample_rate_button.clicked.connect(self.reset_sample_rate_settings)
        sample_rate_buttons_layout.addWidget(self.reset_sample_rate_button)

        self.refresh_sample_rate_button = QPushButton("Refresh")
        self.refresh_sample_rate_button.clicked.connect(self.load_current_settings)
        sample_rate_buttons_layout.addWidget(self.refresh_sample_rate_button)

        sample_rate_layout.addLayout(sample_rate_buttons_layout)

        main_layout.addWidget(self.create_section_group("Sample Rate", sample_rate_layout))

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

        main_layout.addWidget(self.create_section_group("Latency", latency_layout))

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
        self.setMinimumSize(456, 820)  # Set minimum window size
        self.resize(454, 820)  # Set initial size to the minimum

        self.load_nodes()
        self.load_devices()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.node_combo.currentIndexChanged.connect(self.on_node_changed)
        self.quantum_combo.currentIndexChanged.connect(self.update_latency_display)
        self.sample_rate_combo.currentIndexChanged.connect(self.update_latency_display)


        # System Tray Toggle Section
        tray_toggle_layout = QHBoxLayout()
        self.tray_toggle_checkbox = QCheckBox("Enable System Tray Icon")
        self.tray_toggle_checkbox.setChecked(False)
        self.tray_toggle_checkbox.stateChanged.connect(self.toggle_tray_icon)
        tray_toggle_layout.addWidget(self.tray_toggle_checkbox)
        main_layout.addLayout(tray_toggle_layout)


    def load_settings(self):
        """Load saved settings from config file"""
        config = configparser.ConfigParser()
        config_path = os.path.expanduser("~/.config/cable/config.ini")

        # Default settings
        tray_enabled = False
        tray_click_opens_cables = True

        if os.path.exists(config_path):
            try:
                config.read(config_path)
                # Load tray enabled state
                tray_enabled = config.getboolean('DEFAULT', 'tray_enabled', fallback=False)
                # Load default app setting
                tray_click_opens_cables = config.getboolean(
                    'DEFAULT', 'tray_click_opens_cables', fallback=True
                )
                print(f"Loaded tray_click_opens_cables from config: {tray_click_opens_cables}")
            except Exception as e:
                print(f"Error loading settings: {e}")

        # Set the tray toggle checkbox state
        self.tray_toggle_checkbox.setChecked(tray_enabled)
        self.tray_click_opens_cables = tray_click_opens_cables

        if tray_enabled:
            # Remove the old tray icon first if it exists
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon = None
            # Then create a new one with updated settings
            self.toggle_tray_icon(Qt.Checked)

    def save_settings(self):
            """Save current settings to config file"""
            config = configparser.ConfigParser()
            config['DEFAULT'] = {
                'tray_enabled': str(self.tray_toggle_checkbox.isChecked()),
                'tray_click_opens_cables': str(self.tray_click_opens_cables)
            }
            config_path = os.path.expanduser("~/.config/cable/config.ini")
            try:
                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                with open(config_path, 'w') as configfile:
                    config.write(configfile)
            except Exception as e:
                print(f"Error saving settings: {e}")

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

    def toggle_tray_icon(self, state):
        if state == Qt.Checked:
            self.tray_enabled = True
            self.setup_tray_icon()
        else:
            self.tray_enabled = False
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon = None
        self.save_settings()  # Save settings when state changes


    def handle_show_action(self): # New handler function
        if not self.isVisible():
            self.showNormal()
            self.activateWindow()

    def handle_cables_action(self): # New handler for Cables menu
        if self.connection_manager_process is None or not self.connection_manager_process.isVisible():
            # If Cables app is not running, launch it
            self.launch_connection_manager()
        # else: Cables app is already running, do nothing


    def open_cables(self): # open_cables is now only used by the button in main app
        if self.connection_manager_process is None or not self.connection_manager_process.isVisible():
            # If Cables app is not running, launch it
            self.launch_connection_manager()
        # else: Cables app is already running, do nothing


    def tray_icon_activated(self, reason):
     if reason == QSystemTrayIcon.Trigger:  # Left click
        if self.tray_click_opens_cables: # Check the toggle
            if self.connection_manager_process is None or not self.connection_manager_process.isVisible():
                # If Cables app is not running, launch it
                self.launch_connection_manager()
            else:
                if self.connection_manager_process.isMinimized() or not self.connection_manager_process.isVisible():
                    self.connection_manager_process.showNormal()
                    self.connection_manager_process.activateWindow()
                else:
                    self.connection_manager_process.hide()
        else:
            if self.isMinimized() or not self.isVisible():
                self.showNormal()  # Restore window if minimized
                self.activateWindow()  # Bring window to the front
            else:
                self.hide()  # Minimize to tray


    def launch_connection_manager(self):
        try:
            # Import the connection manager module
            import importlib.util
            import os

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

            spec = importlib.util.spec_from_file_location("connection_manager", module_path)
            connection_manager = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(connection_manager)

            # Create and show the connection manager window
            if self.connection_manager_process is None or not self.connection_manager_process.isVisible():
                self.connection_manager_process = connection_manager.JackConnectionManager()
                self.connection_manager_process.show()
            else:
                self.connection_manager_process.activateWindow()

        except Exception as e:
            print(f"Error launching connection manager: {e}")


    def closeEvent(self, event):
        # Override the closeEvent to terminate the connection-manager process
      #  if self.connection_manager_process and self.connection_manager_process.isVisible(): # Check if process exists and window is visible
       #     self.connection_manager_process.close()  # Close the connection manager window

        # Handle the tray icon and other close events as before
        if self.tray_enabled and self.tray_icon:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Cable",
                "Application was minimized to the system tray",
                QSystemTrayIcon.Information,
                1500
            )
        else:
            event.accept()

    def quit_app(self):
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()

    def update_latency_display(self):
        try:
            quantum = int(self.quantum_combo.currentText())
            sample_rate = int(self.sample_rate_combo.currentText())
            latency_ms = quantum / sample_rate * 1000
            self.latency_display_value.setText(f"{latency_ms:.2f} ms")
        except ValueError:
            self.latency_display_value.setText("N/A")

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
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.restart_wireplumber()

    def confirm_restart_pipewire(self):
        reply = QMessageBox.question(self, 'Confirm Restart',
                                     "Are you sure you want to restart Pipewire?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.restart_pipewire()

    def restart_wireplumber(self):
        try:
            bus = dbus.SessionBus()  # Connect to the session bus for user services
            systemd_user = bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1') # changed path here
            manager = dbus.Interface(systemd_user, 'org.freedesktop.systemd1.Manager')
            manager.RestartUnit('wireplumber.service', 'replace') # Use service name without --user
            QMessageBox.information(self, "Success", "Wireplumber restarted successfully")
            self.reload_app_settings()

        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name()
            error_message = str(e)

            if "org.freedesktop.DBus.Error.UnknownObject" in error_name:
                QMessageBox.critical(self, "Error",
                                     "Error restarting Wireplumber: Systemd user manager not found.\n"
                                     "This might be due to Flatpak sandboxing restrictions.\n"
                                     f"Details: {error_message}")
            elif "org.freedesktop.systemd1.Error.UnitNotFound" in error_name:
                 QMessageBox.critical(self, "Error",
                                     "Error restarting Wireplumber: Wireplumber user service not found.\n"
                                     "Ensure Wireplumber is installed and the user service is enabled.\n"
                                     f"Details: {error_message}")
            elif "org.freedesktop.systemd1.Error.Failed" in error_name:
                 QMessageBox.critical(self, "Error",
                                     "Error restarting Wireplumber: Restart operation failed.\n"
                                     "Check Wireplumber logs for more details.\n"
                                     f"Details: {error_message}")
            else: # General DBus error
                QMessageBox.critical(self, "Error", f"Error restarting Wireplumber: {error_message}")


    def restart_pipewire(self):
        try:
            bus = dbus.SessionBus() # Connect to the session bus for user services
            systemd_user = bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1') # changed path here
            manager = dbus.Interface(systemd_user, 'org.freedesktop.systemd1.Manager')
            manager.RestartUnit('pipewire.service', 'replace') # Use service name without --user
            QMessageBox.information(self, "Success", "Pipewire restarted successfully")
            self.reload_app_settings()

        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name()
            error_message = str(e)

            if "org.freedesktop.DBus.Error.UnknownObject" in error_name:
                QMessageBox.critical(self, "Error",
                                     "Error restarting Pipewire: Systemd user manager not found.\n"
                                     "This might be due to Flatpak sandboxing restrictions.\n"
                                     f"Details: {error_message}")
            elif "org.freedesktop.systemd1.Error.UnitNotFound" in error_name:
                 QMessageBox.critical(self, "Error",
                                     "Error restarting Pipewire: Pipewire user service not found.\n"
                                     "Ensure Pipewire is installed and the user service is enabled.\n"
                                     f"Details: {error_message}")
            elif "org.freedesktop.systemd1.Error.Failed" in error_name:
                 QMessageBox.critical(self, "Error",
                                     "Error restarting Pipewire: Restart operation failed.\n"
                                     "Check Pipewire logs for more details.\n"
                                     f"Details: {error_message}")
            else: # General DBus error
                QMessageBox.critical(self, "Error", f"Error restarting Pipewire: {error_message}")

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

       # QMessageBox.information(self, "Reload Complete", "Application settings have been reloaded.")

    def load_devices(self):
        self.device_combo.clear()
        self.device_combo.addItem("Choose device")
        try:
            output = self.run_command(['pw-cli', 'ls', 'Device'])
            if not output:
                print("Error: Empty response from pw-cli")
                return

            devices = output.split('\n')
            current_device_id = None
            current_device_description = None
            current_device_name = None

            for line in devices:
                line = line.strip()
                if line.startswith("id "):
                    current_device_id = line.split(',')[0].split()[-1].strip()
                elif "device.description" in line:
                    current_device_description = line.split('=')[1].strip().strip('"')
                elif "device.name" in line:
                    current_device_name = line.split('=')[1].strip().strip('"')
                    if current_device_description and current_device_name and current_device_name.startswith("alsa_"):
                        device_label = f"{current_device_description} (ID: {current_device_id})"
                        self.device_combo.addItem(device_label)
                    # Reset for next device
                    current_device_id = None
                    current_device_description = None
                    current_device_name = None

        except Exception as e:
            print(f"Error loading devices: {e}")
            QMessageBox.critical(self, "Error",
                f"Could not retrieve devices:\n{str(e)}")

    def load_nodes(self):
        self.node_combo.clear()
        self.node_combo.addItem("Choose Node")
        try:
            output = self.run_command(['pw-cli', 'ls', 'Node'])
            if not output:
                print("Error: Empty response from pw-cli")
                return

            nodes = output.split('\n')
            current_node_id = None
            current_node_description = None
            current_node_name = None

            for line in nodes:
                line = line.strip()
                if line.startswith("id "):
                    current_node_id = line.split(',')[0].split()[-1].strip()
                elif "node.description" in line:
                    current_node_description = line.split('=')[1].strip().strip('"')
                elif "node.name" in line:
                    current_node_name = line.split('=')[1].strip().strip('"')
                    if current_node_description and current_node_name and current_node_name.startswith("alsa_"):
                        # Determine I/O type
                        io_type = "Unknown"
                        if "input" in current_node_name.lower():
                            io_type = "Input"
                        elif "output" in current_node_name.lower():
                            io_type = "Output"

                        node_label = f"{current_node_description} ({io_type}) (ID: {current_node_id})"
                        self.node_combo.addItem(node_label)
                    # Reset for next node
                    current_node_id = None
                    current_node_description = None
                    current_node_name = None

        except Exception as e:
            print(f"Error loading nodes: {e}")
            QMessageBox.critical(self, "Error",
                f"Could not retrieve nodes:\n{str(e)}")

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

    def apply_quantum_settings(self):
        quantum_value = self.quantum_combo.currentText()
        try:
            self.run_command([
                'pw-metadata',
                '-n', 'settings',
                '0', 'clock.force-quantum',
                quantum_value
            ], check_output=False)
            print(f"Applied quantum/buffer setting: {quantum_value}")
        except Exception as e:
            print(f"Error applying quantum: {e}")

    def reset_quantum_settings(self):
        try:
            command = ["pw-metadata", "-n", "settings", "0", "clock.force-quantum", "0"]
            if self.flatpak_env:
                command = ["flatpak-spawn", "--host"] + command

            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print("Reset quantum/buffer setting to default")
            self.load_current_settings()
        except subprocess.CalledProcessError as e:
            print(f"Reset quantum failed: {e.stderr.decode()}")
            QMessageBox.critical(
                self,
                "Permission Error",
                "Failed to reset quantum settings:\n"
                "Ensure Flatpak permissions are properly configured\n"
                f"Details: {e.stderr.decode()}"
            )

    def apply_sample_rate_settings(self):
        sample_rate = self.sample_rate_combo.currentText()
        try:
            self.run_command([
                'pw-metadata',
                '-n', 'settings',
                '0', 'clock.force-rate',
                sample_rate
            ], check_output=False)
            print(f"Applied sample rate setting: {sample_rate}")
        except Exception as e:
            print(f"Error applying sample rate: {e}")

    def reset_sample_rate_settings(self):
        try:
            command = ["pw-metadata", "-n", "settings", "0", "clock.force-rate", "0"]
            if self.flatpak_env:
                command = ["flatpak-spawn", "--host"] + command

            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print("Reset sample rate setting to default")
            self.load_current_settings()
        except subprocess.CalledProcessError as e:
            print(f"Reset sample rate failed: {e.stderr.decode()}")
            QMessageBox.critical(
                self,
                "Permission Error",
                "Failed to reset sample rate settings:\n"
                "Ensure Flatpak permissions are properly configured\n"
                f"Details: {e.stderr.decode()}"
            )
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to reset sample rate: {str(e)}"
            )

    def load_current_settings(self):
        try:
            # Get sample rate
            forced_rate = self.get_metadata_value('clock.force-rate')
            if forced_rate in (None, "0"):
                sample_rate = self.get_metadata_value('clock.rate')
            else:
                sample_rate = forced_rate

            # Get quantum
            forced_quantum = self.get_metadata_value('clock.force-quantum')
            if forced_quantum in (None, "0"):
                quantum = self.get_metadata_value('clock.quantum')
            else:
                quantum = forced_quantum

            # Update UI elements
            if sample_rate:
                index = self.sample_rate_combo.findText(sample_rate)
                if index >= 0:
                    self.sample_rate_combo.setCurrentIndex(index)
                else:
                    self.sample_rate_combo.addItem(sample_rate)
                    self.sample_rate_combo.setCurrentText(sample_rate)

            if quantum:
                index = self.quantum_combo.findText(quantum)
                if index >= 0:
                    self.quantum_combo.setCurrentIndex(index)
                else:
                    self.quantum_combo.addItem(quantum)
                    self.quantum_combo.setCurrentText(quantum)

            self.update_latency_display()

        except Exception as e:
            print(f"Error loading settings: {e}")


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

    def update_latency_display(self):
        try:
            quantum = int(self.quantum_combo.currentText())
            sample_rate = int(self.sample_rate_combo.currentText())
            if sample_rate == 0:
                self.latency_display_value.setText("N/A")
            else:
                latency_ms = quantum / sample_rate * 1000
                self.latency_display_value.setText(f"{latency_ms:.2f} ms")
        except ValueError:
            self.latency_display_value.setText("N/A")

def main():
    app = CableApp(sys.argv)  # Use CableApp instead of QApplication
    ex = PipeWireSettingsApp()
    ex.show()

    # Run the application
    exit_code = app.exec_()

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
