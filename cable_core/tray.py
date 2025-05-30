import os
import sys
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QMessageBox
from PyQt6.QtGui import QIcon, QAction, QActionGroup
from PyQt6.QtCore import Qt, QProcess

from cable_core.other_settings_dialog import OtherSettingsDialog # Import the new dialog

class TrayManager:
    def __init__(self, app):
        self.app = app
        self.tray_icon = None
        self.autostart_action = None
        self.autostart_version_action = None # Add placeholder for version menu action
        self.cable_action = None
        self.cables_action = None

    def setup_tray_icon(self):
        if not self.tray_icon:
            print(f"Setting up tray icon with tray_click_opens_cables: {self.app.tray_click_opens_cables}")
            self.tray_icon = QSystemTrayIcon(self.app) # Parent is the app

            # --- Icon Loading Logic ---
            app_icon = None
            icon_name = "jack-plug.svg" # Icon filename
            icon_theme_name = "jack-plug" # Theme icon name (without extension)

            # Determine base path - prioritize PyInstaller bundle path if available
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                # Running as a PyInstaller bundle (AppImage)
                base_path = sys._MEIPASS
                print(f"Running frozen, using base path: {base_path}")
                # 1. Try loading from PyInstaller bundle path (_MEIPASS)
                #    (--add-data "jack-plug.svg:." places it in the root of _MEIPASS)
                bundle_icon_path = os.path.join(base_path, icon_name)
                print(f"Attempting to load icon from bundle path: {bundle_icon_path}")
                if os.path.exists(bundle_icon_path):
                    bundle_icon = QIcon(bundle_icon_path)
                    if not bundle_icon.isNull():
                        print("Found valid icon in bundle directory.")
                        app_icon = bundle_icon
                    else:
                        print(f"Warning: Found file at {bundle_icon_path}, but it's not a valid icon.")
                else:
                    print("Icon not found in bundle directory.")
            else:
                # Running as a normal script
                base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
                print(f"Running as script, using base path: {base_path}")
                # 1. Try loading from the script's directory
                local_icon_path = os.path.join(base_path, icon_name)
                print(f"Attempting to load icon from local path: {local_icon_path}")
                if os.path.exists(local_icon_path):
                    local_icon = QIcon(local_icon_path)
                    if not local_icon.isNull():
                        print("Found valid icon in script directory.")
                        app_icon = local_icon
                    else:
                        print(f"Warning: Found file at {local_icon_path}, but it's not a valid icon.")
                else:
                    print("Icon not found in script directory.")

            # 2. If local/bundle icon not found/valid, try loading from the theme
            if app_icon is None:
                print(f"Attempting to load icon '{icon_theme_name}' from theme.")
                theme_icon = QIcon.fromTheme(icon_theme_name)
                if not theme_icon.isNull():
                    print("Found valid icon in theme.")
                    app_icon = theme_icon
                else:
                    print(f"Warning: Icon '{icon_theme_name}' not found in theme.")

            # 3. Set the icon (use fallback if all else failed)
            if app_icon:
                self.tray_icon.setIcon(app_icon)
            else:
                print("Using fallback icon 'application-x-executable'.")
                self.tray_icon.setIcon(QIcon.fromTheme("application-x-executable"))
            # --- End Icon Loading Logic ---

            # Create the menu
            tray_menu = QMenu(self.app) # Parent is the app

            # Create regular menu items for direct access
            show_cable_action = QAction("Cable", self.app)
            show_cables_action = QAction("Cables", self.app)

            # Connect the regular menu items
            show_cable_action.triggered.connect(self.handle_show_action) # Internal call
            show_cables_action.triggered.connect(self.handle_cables_action) # Internal call

            # Create a submenu for click behavior selection
            click_menu = QMenu("Default App", self.app) # Parent is the app

            # Create actions for the radio buttons
            self.cable_action = QAction("Cable", self.app) # Store reference
            self.cables_action = QAction("Cables", self.app) # Store reference

            # Make them checkable and exclusive
            self.cable_action.setCheckable(True)
            self.cables_action.setCheckable(True)

            # Set initial state based on loaded setting (now guaranteed to be boolean)
            self.cable_action.setChecked(not bool(self.app.tray_click_opens_cables))
            self.cables_action.setChecked(bool(self.app.tray_click_opens_cables))

            # Create an action group to make the selection exclusive
            action_group = QActionGroup(self.app) # Parent is the app
            action_group.addAction(self.cable_action)
            action_group.addAction(self.cables_action)
            action_group.setExclusive(True)

            # Connect the actions to update the tray click behavior
            self.cable_action.triggered.connect(lambda: self.set_tray_click_target(False)) # Internal call
            self.cables_action.triggered.connect(lambda: self.set_tray_click_target(True)) # Internal call

            # Add actions to the click submenu
            click_menu.addAction(self.cable_action)
            click_menu.addAction(self.cables_action)

            # Build the complete menu
            tray_menu.addAction(show_cable_action)
            tray_menu.addAction(show_cables_action)
            tray_menu.addSeparator()
            tray_menu.addMenu(click_menu)
            tray_menu.addSeparator()

            # Add autostart toggle
            self.autostart_action = QAction("Autostart", self.app) # Store reference
            self.autostart_action.setCheckable(True)
            self.autostart_action.setChecked(self.app.autostart_enabled) # Use app state
            self.autostart_action.triggered.connect(self.toggle_autostart) # Connect to internal method
            tray_menu.addAction(self.autostart_action)
            tray_menu.addSeparator()

            # Add quit action
            quit_action = QAction("Quit", self.app)
            quit_action.triggered.connect(self.quit_app) # Internal call
            tray_menu.addAction(quit_action)

            # Set the menu for the tray icon
            self.tray_icon.setContextMenu(tray_menu)

            # Connect left-click to show the app
            self.tray_icon.activated.connect(self.tray_icon_activated) # Internal call

        # Show the tray icon
        self.tray_icon.show()

    def set_tray_click_target(self, opens_cables):
        """Update which application opens on tray icon click"""
        print(f"Setting tray click target - opens_cables: {opens_cables}")
        self.app.tray_click_opens_cables = opens_cables

        # Update the menu item checked states (handled by action group)
        if self.cable_action and self.cables_action:
             self.cable_action.setChecked(not opens_cables)
             self.cables_action.setChecked(opens_cables)

        self.app.config_manager.save_settings() # Use app's config manager

    def toggle_tray_icon(self, state):
        state_enum = Qt.CheckState(state)
        if state_enum == Qt.CheckState.Checked:
            self.app.tray_enabled = True # Update app state
            self.setup_tray_icon() # Internal call
        else: # Trying to disable the tray icon
            # Prevent disabling tray if autostart is enabled
            if self.app.autostart_enabled:
                print("Cannot disable tray icon while autostart is enabled.")
                # Block signals to prevent recursion, revert the checkbox, then unblock
                self.app.tray_toggle_checkbox.blockSignals(True)
                self.app.tray_toggle_checkbox.setChecked(True)
                self.app.tray_toggle_checkbox.blockSignals(False)
                # Also ensure the corresponding menu action is checked
                # Find the action in the version context menu (if it exists)
                # This is a bit indirect, maybe better to have a direct reference?
                # For now, let's assume the checkbox state change handles the menu via connections.
                return # Stop processing

            # Proceed with disabling if autostart is off
            self.app.tray_enabled = False # Update app state
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon = None
        self.app.config_manager.save_settings() # Use app's config manager

    def handle_show_action(self):
        """Show the main Cable window"""
        if not self.app.isVisible():
            # Force refresh settings when showing from tray
            self.app.pipewire_manager.load_current_settings() # Use pipewire_manager
            # Refresh device and node lists when shown from tray
            print("Refreshing devices/nodes from handle_show_action") # Debug print
            self.app.pipewire_manager.load_devices() # Use pipewire_manager
            self.app.pipewire_manager.load_nodes() # Use pipewire_manager
            self.app.show()  # Use app method
            self.app.activateWindow() # Use app method

    def handle_cables_action(self):
        """Handle selection of 'Cables' from tray menu"""
        self.app.process_manager._ensure_connection_manager_visible() # Use process_manager

    def tray_icon_activated(self, reason):
        """Handle tray icon activation (clicks)"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            if self.app.tray_click_opens_cables:  # Check the app's toggle
                if self.app.process_manager.connection_manager_process is None or (
                    hasattr(self.app.process_manager.connection_manager_process, 'state') and
                    self.app.process_manager.connection_manager_process.state() == QProcess.ProcessState.NotRunning
                ):
                    # If Cables app is not running at all, launch it
                    self.app.process_manager.launch_connection_manager() # Use process_manager
                else:
                    # Process is already running, just terminate it (toggle behavior)
                    print("Connection manager is already running, closing it")
                    self.app.process_manager.connection_manager_process.terminate() # Use process_manager
                    # Don't schedule a relaunch
            else:
                if self.app.isMinimized() or not self.app.isVisible():
                    # Force refresh settings before showing
                    print("Refreshing devices/nodes from tray_icon_activated") # Debug print
                    self.app.pipewire_manager.load_current_settings() # Use pipewire_manager
                    self.app.pipewire_manager.load_devices() # Use pipewire_manager
                    self.app.pipewire_manager.load_nodes() # Use pipewire_manager
                    self.app.show()  # Use app method
                    self.app.activateWindow()  # Use app method
                else:
                    self.app.hide()  # Use app method

    def quit_app(self):
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit() # Static method

    def show_version_context_menu(self, pos):
        """Shows the context menu for the version label."""
        context_menu = QMenu(self.app) # Parent is the app

        # Add tray icon toggle at the top
        tray_action = QAction("Enable tray icon", self.app)
        tray_action.setCheckable(True)
        tray_action.setChecked(self.app.tray_toggle_checkbox.isChecked())
        # Disable the tray action if autostart is enabled
        tray_action.setEnabled(not self.app.autostart_enabled)
        tray_action.toggled.connect(self.app.tray_toggle_checkbox.setChecked) # Connect action toggle to app's checkbox
        context_menu.addAction(tray_action)

        # Add Autostart toggle (below tray icon toggle)
        # Create action only if it doesn't exist, otherwise update state
        # Note: self.app.autostart_version_action might not be initialized yet if menu is shown before tray setup
        # We should probably manage this action within TrayManager or ensure it's created in app.__init__
        # For now, assume it might exist on the app.
        # Create or update the version menu autostart action
        if self.autostart_version_action is None:
            self.autostart_version_action = QAction("Autostart", self.app)
            self.autostart_version_action.setCheckable(True)
            # Connect only once during creation
            self.autostart_version_action.triggered.connect(self.toggle_autostart) # Connect to internal method
        # Always update checked state when menu is shown
        self.autostart_version_action.setChecked(self.app.autostart_enabled) # Check app state
        context_menu.addAction(self.autostart_version_action)


        # Add remember settings toggle
        remember_action = QAction("Save quantum and sample rate", self.app)
        remember_action.setCheckable(True)
        remember_action.setChecked(self.app.remember_settings_checkbox.isChecked())
        remember_action.toggled.connect(self.app.remember_settings_checkbox.setChecked) # Connect action toggle to app's checkbox
        context_menu.addAction(remember_action)

        # Add restore only minimized toggle
        restore_minimized_action = QAction("Restore above only when app is auto-started", self.app)
        restore_minimized_action.setCheckable(True)
        restore_minimized_action.setChecked(self.app.restore_only_minimized_checkbox.isChecked())
        restore_minimized_action.setEnabled(self.app.remember_settings_checkbox.isChecked()) # Sync enabled state from app's checkbox
        restore_minimized_action.toggled.connect(self.app.restore_only_minimized_checkbox.setChecked) # Connect action toggle to app's checkbox
        context_menu.addAction(restore_minimized_action)


        check_now_action = QAction("Check for new version", self.app)
        # Use lambda to pass manual_check=True
        check_now_action.triggered.connect(lambda: self.app.update_manager.check_for_updates(manual_check=True))
        context_menu.addAction(check_now_action)

        # Checkable action to toggle startup check
        startup_check_action = QAction("Check for new version at start", self.app)
        startup_check_action.setCheckable(True)
        startup_check_action.setChecked(self.app.check_updates_at_start) # Check app state
        startup_check_action.toggled.connect(self.app.config_manager.toggle_startup_check) # Connect to config_manager method (already correct, just confirming)
        context_menu.addAction(startup_check_action)

        download_action = QAction("Download from GitHub", self.app)
        download_action.triggered.connect(self.app.update_manager.open_download_page) # Connect to update_manager method
        context_menu.addAction(download_action)
        
        context_menu.addSeparator() # Add separator before "Other Settings"

        # Add "Other Settings" menu item at the very bottom
        other_settings_action = QAction("Other Settings", self.app)
        other_settings_action.triggered.connect(self._show_other_settings_dialog)
        context_menu.addAction(other_settings_action)

        # Show the menu at the global position of the click
        context_menu.exec(self.app.version_label.mapToGlobal(pos)) # Use app's label

    def _show_other_settings_dialog(self):
        """Opens the Other Settings dialog."""
        dialog = OtherSettingsDialog(parent=self.app, config_manager=self.app.config_manager)
        dialog.exec()

    def toggle_autostart(self, checked):
        """Toggle autostart setting and sync menu actions."""
        try:
            if checked:
                if self.app.autostart_manager.enable_autostart():
                    self.app.autostart_enabled = True # Update app state
                    # Also enable the tray icon when enabling autostart
                    self.app.tray_toggle_checkbox.setChecked(True)
                    print("Autostart enabled (and tray icon)")
                else:
                    QMessageBox.critical(self.app, "Error", # Use self.app as parent
                                      "Failed to enable autostart.\nCheck permissions and try again.")
                    # Revert checkbox if failed - Use internal references
                    if self.autostart_action: self.autostart_action.setChecked(False)
                    if self.autostart_version_action: self.autostart_version_action.setChecked(False)
                    return
            else:
                if self.app.autostart_manager.disable_autostart():
                    self.app.autostart_enabled = False # Update app state
                    print("Autostart disabled")
                else:
                    QMessageBox.critical(self.app, "Error", # Use self.app as parent
                                      "Failed to disable autostart.\nCheck permissions and try again.")
                    # Revert checkbox if failed - Use internal references
                    if self.autostart_action: self.autostart_action.setChecked(True)
                    if self.autostart_version_action: self.autostart_version_action.setChecked(True)
                    return

            # Save settings via ConfigManager *after* successful toggle
            self.app.config_manager.save_settings() # Use app's config manager

            # Update the enabled state of the main checkbox based on autostart state
            self.app.tray_toggle_checkbox.setEnabled(not self.app.autostart_enabled)

        except Exception as e:
            QMessageBox.critical(self.app, "Error", # Use self.app as parent
                              f"Error toggling autostart: {str(e)}")
            # Revert the checkbox state if an error occurred during save or other exception
            # Use internal references and app state
            if self.autostart_action:
                self.autostart_action.setChecked(self.app.autostart_enabled)
            if self.autostart_version_action:
                self.autostart_version_action.setChecked(self.app.autostart_enabled)

        # Update the visual state of BOTH actions if they exist - Use internal references and app state
        if self.autostart_action:
             self.autostart_action.setChecked(self.app.autostart_enabled)
        if self.autostart_version_action:
             self.autostart_version_action.setChecked(self.app.autostart_enabled)
