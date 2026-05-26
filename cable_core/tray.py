"""
System tray icon and menu management for Cable.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional
from PyQt6.QtWidgets import (
    QDialog,
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

from cable_core.app_config import load_app_icon, load_tray_icon
from cable_core import config_keys as keys
from cable_core.other_settings_dialog import OtherSettingsDialog
from cable_core.dialogs import AppImagePathDialog, QuickSettingsDialog


class TrayManager:
    def __init__(
        self,
        app: QWidget,
        config_manager: Any = None,
        is_tray_checked_cb=None,
        set_tray_checkbox_cb=None,
        revert_tray_checkbox_cb=None,
        set_tray_checkbox_enabled_cb=None,
        set_apply_immediately_cb=None,
        set_show_confirmation_cb=None,
    ) -> None:
        self.app = app
        self._config_manager = config_manager
        self._is_tray_checked_cb = is_tray_checked_cb
        self._set_tray_checkbox_cb = set_tray_checkbox_cb
        self._revert_tray_checkbox_cb = revert_tray_checkbox_cb
        self._set_tray_checkbox_enabled_cb = set_tray_checkbox_enabled_cb
        self._set_apply_immediately_cb = set_apply_immediately_cb
        self._set_show_confirmation_cb = set_show_confirmation_cb
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.tray_menu: Optional[QMenu] = None
        self.autostart_action: Optional[QAction] = None
        self.autostart_version_action: Optional[QAction] = (
            None  # Add placeholder for version menu action
        )
        self.cable_action: Optional[QAction] = None
        self.cables_action: Optional[QAction] = None
        self._quick_setting_actions: List[QAction] = []

    def setup_tray_icon(self) -> None:
        if not self.tray_icon:
            # Check if integrated mode is enabled; respect CLI -i/-n override if present
            self.integrated_mode = self.app.get_integrated_mode()
            logger.debug(
                f"Setting up tray icon with tray_click_opens_cables: {self.app.tray_click_opens_cables}, integrated_mode: {self.integrated_mode}"
            )
            self.tray_icon = QSystemTrayIcon(self.app)  # Parent is the app

            # Check if monochrome tray icon is enabled
            monochrome_enabled = self.app.config_manager.get_bool(
                keys.MONOCHROME_TRAY_ICON, False
            )
            invert_enabled = (
                self.app.config_manager.get_bool(keys.INVERT_TRAY_ICON, False)
                if monochrome_enabled else False
            )
            app_icon = load_tray_icon(monochrome_enabled, invert_enabled)
            if app_icon:
                self.tray_icon.setIcon(app_icon)
            else:
                self.tray_icon.setIcon(QIcon.fromTheme("application-x-executable"))

            # Create the menu
            self.tray_menu = QMenu(self.app)  # Parent is the app
            tray_menu = self.tray_menu

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

            # --- Quick settings ---
            self._quick_settings_action = QAction("Quick settings", self.app)
            self._quick_settings_action.setToolTip(
                "Configure quick quantum and sample rate settings"
            )
            self._quick_settings_action.triggered.connect(
                self._show_quick_settings_dialog
            )
            tray_menu.addAction(self._quick_settings_action)

            # Load saved quick setting entries (directly below Quick settings, no separator)
            self._load_quick_settings(tray_menu)

            # Separator before quit
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

    def update_tray_icon(self) -> None:
        """Update tray icon based on monochrome setting and current theme."""
        if not self.tray_icon:
            return

        monochrome_enabled = self.app.config_manager.get_bool(
            keys.MONOCHROME_TRAY_ICON, False
        )
        invert_enabled = (
            self.app.config_manager.get_bool(keys.INVERT_TRAY_ICON, False)
            if monochrome_enabled else False
        )
        app_icon = load_tray_icon(monochrome_enabled, invert_enabled)
        if app_icon:
            self.tray_icon.setIcon(app_icon)

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
                if self._revert_tray_checkbox_cb:
                    self._revert_tray_checkbox_cb()
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
                    getattr(
                        self.app.process_manager.connection_manager_process, "state", None
                    ) is not None
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
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:  # Middle click
            # Middle click respects "Default App" setting and toggles visibility
            if getattr(self.app, "embedded", False):
                # When embedded, toggle the parent Cables window
                self._toggle_parent_window()
                return

            # In integrated mode (standalone Cable redirecting to Cables), open Cables
            if getattr(self, "integrated_mode", False):
                self.handle_cables_action()
                return

            if self.app.tray_click_opens_cables:  # Check the app's toggle
                if self.app.process_manager.connection_manager_process is None or (
                    getattr(
                        self.app.process_manager.connection_manager_process, "state", None
                    ) is not None
                    and self.app.process_manager.connection_manager_process.state()
                    == QProcess.ProcessState.NotRunning
                ):
                    # If Cables app is not running at all, launch it
                    self.app.process_manager.launch_connection_manager()
                else:
                    # Process is already running, just terminate it (toggle behavior)
                    logger.debug("Connection manager is already running, closing it (middle-click)")
                    self.app.process_manager.connection_manager_process.terminate()
            else:
                # Toggle Cable window visibility
                if self.app.isMinimized() or not self.app.isVisible():
                    # Force refresh settings before showing
                    logger.debug("Refreshing devices/nodes from middle-click")
                    self.app._apply_current_settings()
                    self.app._apply_devices()
                    self.app._apply_nodes()
                    self.app.show()
                    self.app.activateWindow()
                else:
                    self.app.hide()

    def quit_app(self) -> None:
        if self.tray_icon:
            self.tray_icon.hide()
        # The cleanup is handled by the aboutToQuit signal in Cable.py
        # This method should just quit the application.
        QApplication.instance().quit()

    def show_settings_menu(self, pos: QPoint) -> None:
        """Shows the settings context menu triggered by the Settings button."""
        context_menu = QMenu(self.app)  # Parent is the app

        # Add tray icon toggle at the top
        tray_action = QAction("Enable tray icon", self.app)
        tray_action.setCheckable(True)
        tray_action.setChecked(
            self._is_tray_checked_cb() if self._is_tray_checked_cb else False
        )
        # Disable the tray action if autostart is enabled
        tray_action.setEnabled(not self.app.autostart_enabled)
        if self._set_tray_checkbox_cb:
            def _on_tray_action_toggled(checked: bool) -> None:
                self._set_tray_checkbox_cb(checked)
                self.toggle_tray_icon(
                    Qt.CheckState.Checked.value if checked else Qt.CheckState.Unchecked.value
                )
            tray_action.toggled.connect(_on_tray_action_toggled)
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

        # Add remember settings toggle (reads/writes config directly)
        remember_action = QAction("Save quantum and sample rate", self.app)
        remember_action.setCheckable(True)
        remember_action.setChecked(
            self._config_manager.get_bool(keys.REMEMBER_SETTINGS, False)
            if self._config_manager else False
        )
        remember_action.toggled.connect(
            lambda checked: self._config_manager.set_bool(keys.REMEMBER_SETTINGS, checked)
            if self._config_manager else None
        )
        context_menu.addAction(remember_action)

        # Add restore only minimized toggle
        restore_minimized_action = QAction(
            "Restore above only when app is auto-started", self.app
        )
        restore_minimized_action.setCheckable(True)
        restore_minimized_action.setChecked(
            self._config_manager.get_bool(keys.RESTORE_ONLY_MINIMIZED, False)
            if self._config_manager else False
        )
        restore_minimized_action.setEnabled(
            self._config_manager.get_bool(keys.REMEMBER_SETTINGS, False)
            if self._config_manager else False
        )
        restore_minimized_action.toggled.connect(
            lambda checked: self._config_manager.set_bool(keys.RESTORE_ONLY_MINIMIZED, checked)
            if self._config_manager else None
        )
        context_menu.addAction(restore_minimized_action)

        # Add apply instantaneously toggle
        apply_immediately_action = QAction(
            "Apply Quantum and Sample Rate instantaneously", self.app
        )
        apply_immediately_action.setCheckable(True)
        apply_immediately_action.setChecked(
            self._config_manager.get_bool(keys.APPLY_QUANTUM_SAMPLE_RATE_INSTANTANEOUSLY, False)
            if self._config_manager else False
        )
        apply_immediately_action.toggled.connect(
            lambda checked: (
                self._set_apply_immediately_cb(checked)
                if self._set_apply_immediately_cb
                else None
            )
        )
        context_menu.addAction(apply_immediately_action)

        # Add show confirmation toggle
        show_confirmation_action = QAction(
            "Show confirmation after applying Quantum and Sample Rate", self.app
        )
        show_confirmation_action.setCheckable(True)
        show_confirmation_action.setChecked(
            self._config_manager.get_bool(keys.SHOW_QUANTUM_SAMPLE_RATE_CONFIRMATION, False)
            if self._config_manager else False
        )
        show_confirmation_action.toggled.connect(
            lambda checked: (
                self._set_show_confirmation_cb(checked)
                if self._set_show_confirmation_cb
                else None
            )
        )
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
                    if self._set_tray_checkbox_cb:
                        self._set_tray_checkbox_cb(True)
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
            if self._set_tray_checkbox_enabled_cb:
                self._set_tray_checkbox_enabled_cb(not self.app.autostart_enabled)

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

    # ------------------------------------------------------------------
    # Quick Settings helpers
    # ------------------------------------------------------------------

    def _get_quick_settings(self) -> List[Dict[str, str]]:
        """Load quick settings list from config."""
        raw = self.app.config_manager.get_str(keys.QUICK_SETTINGS, "")
        if not raw:
            return []
        try:
            settings = json.loads(raw)
            if isinstance(settings, list):
                return settings
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse quick_settings from config")
        return []

    def _save_quick_settings(self, settings: List[Dict[str, str]]) -> None:
        """Persist quick settings list to config."""
        self.app.config_manager.set_str(keys.QUICK_SETTINGS, json.dumps(settings))
        self.app.config_manager.flush()

    def _find_insertion_point(self) -> Optional[QAction]:
        """Find where to insert quick setting entries: after _quick_settings_action, before separator-before-quit."""
        if not self.tray_menu:
            return None
        actions = self.tray_menu.actions()
        # Find the separator that comes after _quick_settings_action and its entries
        # That separator is the one just before Quit
        found_quick = False
        for a in actions:
            if a is self._quick_settings_action:
                found_quick = True
                continue
            if found_quick and a.isSeparator():
                # This is the separator before Quit — insert before it
                return a
        return None

    def _load_quick_settings(self, menu: QMenu) -> None:
        """Populate the tray menu with saved quick setting entries."""
        self._quick_setting_actions.clear()
        settings = self._get_quick_settings()
        insert_before = self._find_insertion_point()
        for entry in settings:
            label = QuickSettingsDialog._make_label(entry)
            action = QAction(f"★ {label}", self.app)
            action.triggered.connect(
                lambda checked, e=entry: self._apply_quick_setting(e)
            )
            if insert_before:
                menu.insertAction(insert_before, action)
            else:
                menu.addAction(action)
            self._quick_setting_actions.append(action)

    def _add_quick_setting_to_menu(self, entry: Dict[str, str]) -> None:
        """Add a single quick setting entry to the tray menu."""
        if not self.tray_menu:
            return
        label = QuickSettingsDialog._make_label(entry)
        action = QAction(f"★ {label}", self.app)
        action.triggered.connect(lambda checked, e=entry: self._apply_quick_setting(e))
        insert_before = self._find_insertion_point()
        if insert_before:
            self.tray_menu.insertAction(insert_before, action)
        else:
            self.tray_menu.addAction(action)
        self._quick_setting_actions.append(action)

    def _rebuild_quick_settings_menu(self) -> None:
        """Remove existing quick setting actions from the menu and re-add from config."""
        if not self.tray_menu:
            return
        for action in self._quick_setting_actions:
            self.tray_menu.removeAction(action)
        self._quick_setting_actions.clear()
        settings = self._get_quick_settings()
        for entry in settings:
            self._add_quick_setting_to_menu(entry)

    def _show_quick_settings_dialog(self) -> None:
        """Open the Quick Settings dialog and handle the result."""
        existing = self._get_quick_settings()
        # Use get_all_values_from_config to show ALL available values (including commented-out ones)
        quantum_values = self.app.config_manager.get_all_values_from_config(
            "quantum_values",
            [16, 32, 48, 64, 96, 128, 144, 192, 240, 256, 512, 1024, 2048, 4096, 8192],
        )
        sample_rate_values = self.app.config_manager.get_all_values_from_config(
            "sample_rate_values", [44100, 48000, 88200, 96000, 176400, 192000]
        )

        dialog = QuickSettingsDialog(
            existing_settings=existing,
            quantum_values=quantum_values,
            sample_rate_values=sample_rate_values,
            parent=self.app,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the full settings list (additions/removals already applied in dialog)
            settings = dialog.get_quick_settings()

            # Save and rebuild menu
            self._save_quick_settings(settings)
            self._rebuild_quick_settings_menu()

    def _apply_quick_setting(self, entry: Dict[str, str]) -> None:
        """Apply a quick setting: set quantum and/or sample rate via PipeWire."""
        quantum = entry.get("quantum", "")
        sample_rate = entry.get("sample_rate", "")
        force_reset_quantum = False
        force_reset_sample_rate = False
        confirmation_messages: List[str] = []

        if quantum and quantum != "default":
            # Apply quantum via pw-metadata
            self.app.pipewire_manager.apply_quantum_settings(
                value_str=str(quantum),
                skip_save=False,
                remember_settings=self.app.remember_settings,
                initial_load=False,
                quantum_was_reset=False,
            )
            logger.info(f"Quick setting: applied quantum={quantum}")
            confirmation_messages.append(f"{quantum} quantum applied")
        elif quantum == "default":
            # Reset quantum to default
            self.app.pipewire_manager.reset_quantum_settings()
            force_reset_quantum = True
            logger.info("Quick setting: reset quantum to default")
            confirmation_messages.append("Default quantum restored")

        if sample_rate and sample_rate != "default":
            # Apply sample rate via pw-metadata
            self.app.pipewire_manager.apply_sample_rate_settings(
                value_str=str(sample_rate),
                skip_save=False,
                remember_settings=self.app.remember_settings,
                initial_load=False,
                sample_rate_was_reset=False,
            )
            logger.info(f"Quick setting: applied sample_rate={sample_rate}")
            confirmation_messages.append(f"{sample_rate} sample rate applied")
        elif sample_rate == "default":
            # Reset sample rate to default
            self.app.pipewire_manager.reset_sample_rate_settings()
            force_reset_sample_rate = True
            logger.info("Quick setting: reset sample rate to default")
            confirmation_messages.append("Default sample rate restored")

        # Refresh the Cable UI to reflect the new settings
        self.app._apply_current_settings(
            force_reset_quantum=force_reset_quantum,
            force_reset_sample_rate=force_reset_sample_rate,
        )

        # Show confirmation dialog if enabled
        if self.app.show_confirmation and confirmation_messages:
            self._show_quick_setting_confirmation(confirmation_messages)

    def _show_quick_setting_confirmation(self, messages: List[str]) -> None:
        """Show confirmation dialog for quick setting changes.

        Handles the case where the app window may be hidden by using the tray icon
        as a visual anchor point for the dialog.
        """
        from cable_core.dialogs import QuantumSampleRateConfirmationDialog
        from cable_core.app_config import QUANTUM_SAMPLE_RATE_CONFIRMATION_DURATION_MS

        # Combine messages if both quantum and sample rate were changed
        if len(messages) == 2:
            message = f"{messages[0]}\n{messages[1]}"
        else:
            message = messages[0]

        # Use the app as parent; the dialog will center on it if visible,
        # or appear near the tray icon area if the app is hidden
        dialog = QuantumSampleRateConfirmationDialog(
            message=message,
            duration_ms=QUANTUM_SAMPLE_RATE_CONFIRMATION_DURATION_MS,
            parent=self.app,
        )
        dialog.show()
