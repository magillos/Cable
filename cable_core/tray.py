"""
System tray icon and menu management for Cable.
"""

import os
import sys
from typing import Optional
from PyQt6.QtWidgets import (
    QSystemTrayIcon,
    QMenu,
    QApplication,
    QMessageBox,
    QLabel,
    QWidgetAction,
    QWidget,
)
from PyQt6.QtGui import QIcon, QAction, QActionGroup
from PyQt6.QtCore import Qt, QProcess, QPoint

import logging

logger = logging.getLogger(__name__)

from cable_core.app_config import load_app_icon
from cable_core import config_keys as keys
from cable_core.other_settings_dialog import OtherSettingsDialog
from cable_core.dialogs import AppImagePathDialog


class TrayManager:
    def __init__(self, app: QWidget) -> None:
        self.app = app
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.autostart_action: Optional[QAction] = None
        self.autostart_version_action: Optional[QAction] = (
            None  # Add placeholder for version menu action
        )
        self.cable_action: Optional[QAction] = None
        self.cables_action: Optional[QAction] = None

    def setup_tray_icon(self) -> None:
        if not self.tray_icon:
            # Check if integrated mode is enabled
            self.integrated_mode = self.app.config_manager.get_bool(
                keys.INTEGRATE_CABLE_AND_CABLES, False
            )
            logger.debug(
                f"Setting up tray icon with tray_click_opens_cables: {self.app.tray_click_opens_cables}, integrated_mode: {self.integrated_mode}"
            )
            self.tray_icon = QSystemTrayIcon(self.app)  # Parent is the app

            app_icon = load_app_icon()
            if app_icon:
                self.tray_icon.setIcon(app_icon)
            else:
                self.tray_icon.setIcon(QIcon.fromTheme("application-x-executable"))

            # Create the menu
            tray_menu = QMenu(self.app)  # Parent is the app

            if self.integrated_mode:
                # Simplified menu for integrated mode: just "Open" to launch Cables
                open_action = QAction("Open", self.app)
                open_action.triggered.connect(self.handle_cables_action)
                tray_menu.addAction(open_action)
                tray_menu.addSeparator()
            else:
                # Create regular menu items for direct access
                show_cable_action = QAction("Cable", self.app)
                show_cables_action = QAction("Cables", self.app)

                # Connect the regular menu items
                show_cable_action.triggered.connect(
                    self.handle_show_action
                )  # Internal call
                show_cables_action.triggered.connect(
                    self.handle_cables_action
                )  # Internal call

                # Create a submenu for click behavior selection
                click_menu = QMenu("Default App", self.app)  # Parent is the app

                # Create actions for the radio buttons
                self.cable_action = QAction("Cable", self.app)  # Store reference
                self.cables_action = QAction("Cables", self.app)  # Store reference

                # Make them checkable and exclusive
                self.cable_action.setCheckable(True)
                self.cables_action.setCheckable(True)

                # Set initial state based on loaded setting (now guaranteed to be boolean)
                self.cable_action.setChecked(not bool(self.app.tray_click_opens_cables))
                self.cables_action.setChecked(bool(self.app.tray_click_opens_cables))

                # Create an action group to make the selection exclusive
                action_group = QActionGroup(self.app)  # Parent is the app
                action_group.addAction(self.cable_action)
                action_group.addAction(self.cables_action)
                action_group.setExclusive(True)

                # Connect the actions to update the tray click behavior
                self.cable_action.triggered.connect(
                    lambda: self.set_tray_click_target(False)
                )  # Internal call
                self.cables_action.triggered.connect(
                    lambda: self.set_tray_click_target(True)
                )  # Internal call

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
            self.autostart_action = QAction("Autostart", self.app)  # Store reference
            self.autostart_action.setCheckable(True)
            self.autostart_action.setChecked(
                self.app.autostart_enabled
            )  # Use app state
            self.autostart_action.triggered.connect(
                self.toggle_autostart
            )  # Connect to internal method
            tray_menu.addAction(self.autostart_action)
            tray_menu.addSeparator()

            # Add quit action
            quit_action = QAction("Quit", self.app)
            quit_action.triggered.connect(self.quit_app)  # Internal call
            tray_menu.addAction(quit_action)

            # Set the menu for the tray icon
            self.tray_icon.setContextMenu(tray_menu)

            # Connect left-click to show the app
            self.tray_icon.activated.connect(self.tray_icon_activated)  # Internal call

        # Show the tray icon
        self.tray_icon.show()

    def set_tray_click_target(self, opens_cables: bool) -> None:
        """Update which application opens on tray icon click"""
        logger.debug(f"Setting tray click target - opens_cables: {opens_cables}")
        self.app.tray_click_opens_cables = opens_cables

        # Update the menu item checked states (handled by action group)
        if self.cable_action and self.cables_action:
            self.cable_action.setChecked(not opens_cables)
            self.cables_action.setChecked(opens_cables)

        self.app.config_manager.save_settings(self.app._get_settings_dict())

    def toggle_tray_icon(self, state: int) -> None:
        state_enum = Qt.CheckState(state)
        if state_enum == Qt.CheckState.Checked:
            self.app.tray_enabled = True  # Update app state
            self.setup_tray_icon()  # Internal call
        else:  # Trying to disable the tray icon
            # Prevent disabling tray if autostart is enabled
            if self.app.autostart_enabled:
                logger.info("Cannot disable tray icon while autostart is enabled.")
                # Block signals to prevent recursion, revert the checkbox, then unblock
                self.app.revert_tray_checkbox()
                return  # Stop processing

            # Proceed with disabling if autostart is off
            self.app.tray_enabled = False  # Update app state
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon = None
        self.app.config_manager.save_settings(self.app._get_settings_dict())

    def handle_show_action(self) -> None:
        """Show the main Cable window"""
        if not self.app.isVisible():
            # Force refresh settings when showing from tray
            self.app._apply_current_settings()
            logger.debug("Refreshing devices/nodes from handle_show_action")
            self.app._apply_devices()
            self.app._apply_nodes()
            self.app.show()  # Use app method
            self.app.activateWindow()  # Use app method

    def handle_cables_action(self) -> None:
        """Handle selection of 'Cables' from tray menu"""
        # When embedded, show/hide the parent Cables window instead of launching a new process
        if getattr(self.app, "embedded", False):
            self._toggle_parent_window()
            return
        self.app.process_manager._ensure_connection_manager_visible()  # Use process_manager

    def _toggle_parent_window(self) -> None:
        """Toggle visibility of the parent Cables window when embedded."""
        # Find the top-level parent window (Cables/JackConnectionManager)
        parent_window = self.app.window()
        if parent_window:
            if parent_window.isMinimized() or not parent_window.isVisible():
                parent_window.showNormal()
                parent_window.activateWindow()
                parent_window.raise_()
            else:
                parent_window.hide()

    def tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (clicks)"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            # When embedded, toggle the parent Cables window
            if getattr(self.app, "embedded", False):
                self._toggle_parent_window()
                return

            # In integrated mode (standalone Cable redirecting to Cables), open Cables
            if getattr(self, "integrated_mode", False):
                self.handle_cables_action()
                return

            if self.app.tray_click_opens_cables:  # Check the app's toggle
                if self.app.process_manager.connection_manager_process is None or (
                    hasattr(
                        self.app.process_manager.connection_manager_process, "state"
                    )
                    and self.app.process_manager.connection_manager_process.state()
                    == QProcess.ProcessState.NotRunning
                ):
                    # If Cables app is not running at all, launch it
                    self.app.process_manager.launch_connection_manager()  # Use process_manager
                else:
                    # Process is already running, just terminate it (toggle behavior)
                    logger.debug("Connection manager is already running, closing it")
                    self.app.process_manager.connection_manager_process.terminate()  # Use process_manager
                    # Don't schedule a relaunch
            else:
                if self.app.isMinimized() or not self.app.isVisible():
                    # Force refresh settings before showing
                    logger.debug("Refreshing devices/nodes from tray_icon_activated")
                    self.app._apply_current_settings()
                    self.app._apply_devices()
                    self.app._apply_nodes()
                    self.app.show()  # Use app method
                    self.app.activateWindow()  # Use app method
                else:
                    self.app.hide()  # Use app method

    def quit_app(self) -> None:
        if self.tray_icon:
            self.tray_icon.hide()
        # The cleanup is handled by the aboutToQuit signal in Cable.py
        # This method should just quit the application.
        QApplication.instance().quit()

    def show_version_context_menu(self, pos: QPoint) -> None:
        """Shows the context menu for the version label."""
        context_menu = QMenu(self.app)  # Parent is the app

        # Add tray icon toggle at the top
        tray_action = QAction("Enable tray icon", self.app)
        tray_action.setCheckable(True)
        tray_action.setChecked(self.app.is_tray_checked())
        # Disable the tray action if autostart is enabled
        tray_action.setEnabled(not self.app.autostart_enabled)
        tray_action.toggled.connect(self.app.set_tray_checkbox)
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
            self.autostart_version_action.triggered.connect(
                self.toggle_autostart
            )  # Connect to internal method
        # Always update checked state when menu is shown
        self.autostart_version_action.setChecked(
            self.app.autostart_enabled
        )  # Check app state
        context_menu.addAction(self.autostart_version_action)

        # Add remember settings toggle
        remember_action = QAction("Save quantum and sample rate", self.app)
        remember_action.setCheckable(True)
        remember_action.setChecked(self.app.is_remember_settings_checked())
        remember_action.toggled.connect(self.app.set_remember_settings_checked)
        context_menu.addAction(remember_action)

        # Add restore only minimized toggle
        restore_minimized_action = QAction(
            "Restore above only when app is auto-started", self.app
        )
        restore_minimized_action.setCheckable(True)
        restore_minimized_action.setChecked(
            self.app.is_restore_only_minimized_checked()
        )
        restore_minimized_action.setEnabled(self.app.is_remember_settings_checked())
        restore_minimized_action.toggled.connect(
            self.app.set_restore_only_minimized_checked
        )
        context_menu.addAction(restore_minimized_action)

        # Add apply instantaneously toggle
        apply_immediately_action = QAction(
            "Apply Quantum and Sample Rate instantaneously", self.app
        )
        apply_immediately_action.setCheckable(True)
        apply_immediately_action.setChecked(self.app.is_apply_immediately_checked())
        apply_immediately_action.toggled.connect(self.app.set_apply_immediately_checked)
        context_menu.addAction(apply_immediately_action)

        # Add show confirmation toggle
        show_confirmation_action = QAction(
            "Show confirmation after applying Quantum and Sample Rate", self.app
        )
        show_confirmation_action.setCheckable(True)
        show_confirmation_action.setChecked(self.app.is_show_confirmation_checked())
        show_confirmation_action.toggled.connect(self.app.set_show_confirmation_checked)
        context_menu.addAction(show_confirmation_action)

        # Add separator between restore settings and update options
        context_menu.addSeparator()

        # Add version label above check for updates
        version_container = QLabel()
        version_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_container.setContentsMargins(10, 5, 10, 5)

        curr_version = self.app.update_manager.app_version
        if self.app.update_manager.update_available:
            latest = self.app.update_manager.latest_version
            version_text = f'<a href="https://github.com/magillos/Cable/releases" style="color: orange; text-decoration: none;">Version: {curr_version} (Update: {latest})</a>'
        else:
            version_text = f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">Version: {curr_version}</a>'

        version_container.setText(version_text)
        version_container.setOpenExternalLinks(True)
        version_container.setTextFormat(Qt.TextFormat.RichText)

        version_widget_action = QWidgetAction(self.app)
        version_widget_action.setDefaultWidget(version_container)
        context_menu.addAction(version_widget_action)

        check_now_action = QAction("Check for new version", self.app)
        # Use lambda to pass manual_check=True
        check_now_action.triggered.connect(
            lambda: self.app.update_manager.check_for_updates(manual_check=True)
        )
        context_menu.addAction(check_now_action)

        # Checkable action to toggle startup check
        startup_check_action = QAction("Check for new version at start", self.app)
        startup_check_action.setCheckable(True)
        startup_check_action.setChecked(
            self.app.check_updates_at_start
        )  # Check app state
        startup_check_action.toggled.connect(self._handle_toggle_startup_check)
        context_menu.addAction(startup_check_action)

        download_action = QAction("Download from GitHub", self.app)
        download_action.triggered.connect(
            self.app.update_manager.open_download_page
        )  # Connect to update_manager method
        context_menu.addAction(download_action)

        context_menu.addSeparator()  # Add separator before "Other Settings"

        # Add "Other Settings" menu item
        other_settings_action = QAction("Other Settings", self.app)
        other_settings_action.triggered.connect(self._show_other_settings_dialog)
        context_menu.addAction(other_settings_action)

        context_menu.addSeparator()

        context_menu.addSeparator()

        # Add Buy Me a Coffee link at the very bottom
        coffee_container = QLabel()
        coffee_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        coffee_container.setContentsMargins(10, 0, 10, 10)

        coffee_text = '<a href="https://buymeacoffee.com/magillos" style="color: #FF813F; text-decoration: none; font-weight: bold;">☕ Buy me a coffee</a>'

        coffee_container.setText(coffee_text)
        coffee_container.setOpenExternalLinks(True)
        coffee_container.setTextFormat(Qt.TextFormat.RichText)

        coffee_widget_action = QWidgetAction(self.app)
        coffee_widget_action.setDefaultWidget(coffee_container)
        context_menu.addAction(coffee_widget_action)

        # Show the menu at the global position of the click
        context_menu.exec(self.app.get_settings_button_global_pos(pos))

    def _show_other_settings_dialog(self) -> None:
        """Opens the Other Settings dialog."""
        dialog = OtherSettingsDialog(
            parent=self.app, config_manager=self.app.config_manager
        )
        dialog.exec()

    def _handle_toggle_startup_check(self, checked: bool) -> None:
        """Handle startup check toggle — update app state and persist."""
        self.app.check_updates_at_start = checked
        self.app.config_manager.toggle_startup_check(checked)

    def toggle_autostart(self, checked: bool) -> None:
        """Toggle autostart setting and sync menu actions."""
        try:
            if checked:
                # Check if running from AppImage and need to configure path
                if self.app.appimage_path and not self.app.appimage_path:
                    # Running from AppImage but no path configured, prompt user
                    dialog = AppImagePathDialog(self.app.appimage_path, self.app)
                    if dialog.exec() == dialog.DialogCode.Accepted:
                        appimage_path = dialog.get_appimage_path()
                        if appimage_path and os.path.exists(appimage_path):
                            self.app.appimage_path = appimage_path
                            self.app.autostart_manager = (
                                self.app.autostart_manager.__class__(
                                    self.app.flatpak_env, appimage_path
                                )
                            )
                            self.app.config_manager.save_appimage_path(appimage_path)
                        else:
                            QMessageBox.warning(
                                self.app,
                                "Invalid Path",
                                "The selected AppImage file does not exist or is not accessible.\n"
                                "Please select a valid Cable AppImage file.",
                            )
                            # Revert checkbox if failed - Use internal references
                            if self.autostart_action:
                                self.autostart_action.setChecked(False)
                            if self.autostart_version_action:
                                self.autostart_version_action.setChecked(False)
                            return
                    else:
                        # User cancelled the dialog
                        # Revert checkbox if cancelled - Use internal references
                        if self.autostart_action:
                            self.autostart_action.setChecked(False)
                        if self.autostart_version_action:
                            self.autostart_version_action.setChecked(False)
                        return

                if self.app.autostart_manager.enable_autostart():
                    self.app.autostart_enabled = True  # Update app state
                    # Also enable the tray icon when enabling autostart
                    self.app.set_tray_checkbox(True)
                    self.toggle_tray_icon(Qt.CheckState.Checked)
                    logger.info("Autostart enabled (and tray icon)")
                else:
                    QMessageBox.critical(
                        self.app,
                        "Error",  # Use self.app as parent
                        "Failed to enable autostart.\nCheck permissions and try again.",
                    )
                    # Revert checkbox if failed - Use internal references
                    if self.autostart_action:
                        self.autostart_action.setChecked(False)
                    if self.autostart_version_action:
                        self.autostart_version_action.setChecked(False)
                    return
            else:
                if self.app.autostart_manager.disable_autostart():
                    self.app.autostart_enabled = False  # Update app state
                    logger.info("Autostart disabled")
                else:
                    QMessageBox.critical(
                        self.app,
                        "Error",  # Use self.app as parent
                        "Failed to disable autostart.\nCheck permissions and try again.",
                    )
                    # Revert checkbox if failed - Use internal references
                    if self.autostart_action:
                        self.autostart_action.setChecked(True)
                    if self.autostart_version_action:
                        self.autostart_version_action.setChecked(True)
                    return

            # Save settings via ConfigManager *after* successful toggle
            self.app.config_manager.save_settings(self.app._get_settings_dict())

            # Update the enabled state of the main checkbox based on autostart state
            self.app.set_tray_checkbox_enabled(not self.app.autostart_enabled)

        except Exception as e:
            QMessageBox.critical(
                self.app,
                "Error",  # Use self.app as parent
                f"Error toggling autostart: {str(e)}",
            )
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
