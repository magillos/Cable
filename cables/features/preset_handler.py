"""
PresetHandler - Handles preset loading, saving, and management

This class manages preset operations including loading, saving, and deletion.
It uses the PresetHandlerInterface to access the capabilities it needs from
the main application, enabling better testability and reduced coupling.

Business logic (file I/O, state comparison, layout data collection) is
delegated to :class:`PresetOperations` in ``preset_operations.py``.
"""

import os
import json
import subprocess
from PyQt6.QtWidgets import (
    QMenu,
    QMessageBox,
    QWidgetAction,
    QLineEdit,
    QCheckBox,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from PyQt6.QtCore import QPoint, QTimer, QProcess
from PyQt6.QtGui import QKeySequence, QAction, QActionGroup

import logging

logger = logging.getLogger(__name__)

from cables.utils.helpers import show_timed_messagebox
from cable_core import config_keys as keys
from cables.features.preset_operations import PresetOperations
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Union

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget
    from cables.interfaces import PresetHandlerInterface


from cable_core.dialogs import DefaultResetConfirmDialog


class PresetHandler:
    """
    Handles preset management functionality including loading, saving, and UI interactions.

    This class uses the PresetHandlerInterface protocol to access capabilities
    from the main application. The manager parameter must implement:
    - ConfigProvider: for config_manager access
    - GraphAccessor: for _get_graph_main_window, _get_graph_scene, _get_graph_view
    - PresetOperations: for preset_manager, disconnect_all_unified, reconnect_all_unified
    - ConnectionOperations: for make_connection, break_connection
    - UIRefreshProvider: for refresh_ports
    - ColorProvider: for text_color, background_color, highlight_color
    - JACKClientProvider: for client access
    """

    def __init__(self, manager: "PresetHandlerInterface") -> None:
        """
        Initialize the PresetHandler.

        Args:
            manager: Reference to an object implementing PresetHandlerInterface.
                     Typically the JackConnectionManager instance.
        """
        self.manager = manager  # Reference to PresetHandlerInterface implementation
        # Initialize preset state from config manager
        self.startup_preset_name: Optional[str] = self.manager.config_manager.get_str(
            keys.STARTUP_PRESET
        )
        # Don't restore active_preset from config on fresh start - preset must actually be loaded
        # The active preset will be set when startup_preset is loaded or user loads a preset
        self.current_preset_name: Optional[str] = None
        # Clear the stored active_preset since we're starting fresh
        self.manager.config_manager.set_str(keys.ACTIVE_PRESET, None)
        # Temporary attribute for the save preset name line edit in the menu
        self._preset_menu_name_edit: Optional[QLineEdit] = None

        # Guard flag to prevent re-entrant calls to _perform_preset_save.
        # Pressing Enter in a QMenu-embedded QLineEdit can fire both returnPressed
        # (from the QLineEdit) AND triggered (from the highlighted QAction) for the
        # same key event, scheduling two QTimer.singleShot callbacks.  The first
        # save then calls show_timed_messagebox which runs an inner Qt event loop;
        # the second pending timer fires during that loop and sees the .snap file
        # the first call just created — producing the spurious "already exists" dialog.
        self._save_in_progress: bool = False

        # Add attributes to track original preset state for change detection
        self.original_preset_connections: Optional[List[Dict[str, str]]] = None
        self.original_preset_layout_data: Optional[Dict[str, Any]] = None
        self.save_button_initially_enabled: bool = False
        self.unified_clients: Dict[str, Any] = {}

    def show_preset_menu(self) -> None:
        """Populates the preset management menu. Assumes menu is sender()."""
        menu = self.manager.sender()  # Get the menu that emitted aboutToShow
        if not menu or not isinstance(menu, QMenu):
            logger.error("Error: show_preset_menu called without a valid QMenu sender.")
            return

        # Update preset button styles based on daemon state
        self._update_preset_button_styles()

        menu.clear()  # Clear previous items before repopulating

        preset_names = self.manager.preset_manager.get_preset_names()

        # --- Save Section ---
        # Use a temporary attribute to hold the line edit for the save action
        self._preset_menu_name_edit = QLineEdit()
        self._preset_menu_name_edit.setPlaceholderText("Enter New Preset Name...")
        self._preset_menu_name_edit.returnPressed.connect(
            self._save_current_preset_from_menu
        )  # Connect Enter key
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
        save_loaded_action.triggered.connect(self.save_current_loaded_preset)
        menu.addAction(save_loaded_action)
        # --- End Add "Save" action ---

        menu.addSeparator()

        # --- Load Section ---
        load_menu = menu.addMenu("Load Preset")  # Create menu even if no presets exist

        # --- MODIFICATION START ---
        # Add the global "Default" action from ActionManager
        if (
            self.manager.action_manager is not None
            and self.manager.action_manager.default_preset_action is not None
        ):
            load_menu.addAction(self.manager.action_manager.default_preset_action)
        else:
            # Fallback or error logging if the action isn't found
            error_action = QAction("Default (Action Init Error)", load_menu)
            error_action.setEnabled(False)
            load_menu.addAction(error_action)
            logger.error(
                "Error: Could not find global default_preset_action in PresetHandler."
            )

        load_menu.addSeparator()  # Add separator after "Default"
        # --- MODIFICATION END ---

        load_group = QActionGroup(
            load_menu
        )  # Use QActionGroup for radio button behavior
        load_group.setExclusive(True)

        if preset_names:
            for name in preset_names:
                load_action = QAction(name, load_menu)
                load_action.setCheckable(True)
                load_action.setChecked(name == self.current_preset_name)
                load_action.triggered.connect(
                    lambda checked=False, n=name: self._handle_gui_preset_load(n)
                )
                load_menu.addAction(load_action)
                load_group.addAction(load_action)
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
                delete_action.triggered.connect(
                    lambda checked=False, n=name: self._delete_selected_preset(n)
                )
                delete_menu.addAction(delete_action)

        # --- Startup Preset Section ---
        menu.addSeparator()
        startup_menu = menu.addMenu("Preset to load at autostart")
        startup_group = QActionGroup(startup_menu)  # Use QActionGroup for exclusivity
        startup_group.setExclusive(True)

        # Add "None" option
        none_action = QAction("None", startup_menu)
        none_action.setCheckable(True)
        none_action.setChecked(
            not self.startup_preset_name or self.startup_preset_name == "None"
        )
        none_action.triggered.connect(
            lambda checked=False: self._set_startup_preset(None)
        )
        startup_menu.addAction(none_action)
        startup_group.addAction(none_action)  # Add to group
        startup_menu.addSeparator()  # Add spacer after 'None'

        # Add existing presets
        for name in preset_names:
            startup_action = QAction(name, startup_menu)
            startup_action.setCheckable(True)
            startup_action.setChecked(name == self.startup_preset_name)
            # Use lambda to capture the correct name
            startup_action.triggered.connect(
                lambda checked=False, n=name: self._set_startup_preset(n)
            )
            startup_menu.addAction(startup_action)
            startup_group.addAction(startup_action)  # Add to group

        # --- Restore Layout Checkbox ---
        menu.addSeparator()
        restore_layout_action = QWidgetAction(menu)
        restore_layout_checkbox = QCheckBox("Restore layout")
        restore_layout_checkbox.setToolTip(
            "In Graph, loading a preset will also restore clients' positions, visibility, split and fold states, and the zoom level."
        )

        # Initialize checkbox state from config
        initial_restore_layout = self.manager.config_manager.get_bool(
            keys.LOAD_PRESET_RESTORE_LAYOUT, True
        )

        # Check if I/O layout is active (untangle setting == 0)
        graph_window = self.manager._get_graph_main_window()
        untangle_setting = (
            getattr(graph_window, "current_untangle_setting", None)
            if graph_window
            else None
        )
        is_io_active = graph_window is not None and untangle_setting == 0

        effective_state = initial_restore_layout if not is_io_active else False
        restore_layout_checkbox.setChecked(effective_state)
        restore_layout_checkbox.setEnabled(not is_io_active)

        if is_io_active:
            restore_layout_checkbox.setToolTip(
                "Restore layout (Disabled during I/O layout - dynamic sorting)"
            )
        else:
            restore_layout_checkbox.setToolTip(
                "In Graph, loading a preset will also restore clients' positions, visibility, split and fold states, and the zoom level."
            )

        # Connect to a handler to save the state
        restore_layout_checkbox.toggled.connect(self._set_restore_layout_mode)

        restore_layout_action.setDefaultWidget(restore_layout_checkbox)
        menu.addAction(restore_layout_action)
        # --- End Restore Layout Checkbox ---

        # --- Strict Mode Checkbox ---
        strict_action = QWidgetAction(menu)
        strict_checkbox = QCheckBox("Strict")
        strict_checkbox.setToolTip(
            "When on, connections not stored in the loaded preset will be deactivated."
        )

        # Initialize checkbox state from config
        initial_strict_mode = self.manager.config_manager.get_bool(
            keys.LOAD_PRESET_STRICT_MODE, False
        )
        strict_checkbox.setChecked(initial_strict_mode)

        # Connect to a handler to save the state
        strict_checkbox.toggled.connect(self._set_strict_mode)

        strict_action.setDefaultWidget(strict_checkbox)
        menu.addAction(strict_action)
        # --- End Strict Mode Checkbox ---

        # --- Daemon Mode Checkbox ---
        daemon_action = QWidgetAction(menu)
        daemon_checkbox = QCheckBox("Daemon mode")
        daemon_checkbox.setToolTip(
            "Background mode: restores connections automatically if present in loaded preset."
        )

        # Initialize checkbox state from config
        initial_daemon_mode = self.manager.config_manager.get_bool(
            keys.LOAD_PRESET_DAEMON_MODE, False
        )
        daemon_checkbox.setChecked(initial_daemon_mode)

        # Connect to a handler to save the state
        daemon_checkbox.toggled.connect(self._set_daemon_mode)

        daemon_action.setDefaultWidget(daemon_checkbox)
        menu.addAction(daemon_action)
        # --- End Daemon Mode Checkbox ---

    def _save_current_preset_from_menu(self) -> None:
        """Saves the current connections and layout using the name from the menu's line edit."""
        if not self._preset_menu_name_edit:  # Safety check
            logger.error("Error: Preset menu name edit not found.")
            return
        preset_name = self._preset_menu_name_edit.text().strip()
        if not preset_name:
            QMessageBox.warning(
                self.manager, "Save Preset", "Enter a name for the preset."
            )
            return

        # Guard against double-trigger: pressing Enter in a QMenu-embedded QLineEdit
        # can fire both returnPressed AND the highlighted action's triggered signal.
        if self._save_in_progress:
            logger.debug(
                f"Save already in progress, ignoring duplicate trigger for '{preset_name}'"
            )
            return

        # Use QTimer to defer the save operation to avoid menu/dialog interaction issues
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(100, lambda: self._perform_preset_save(preset_name))

    def _perform_preset_save(self, preset_name: str) -> None:
        """Performs the actual preset save operation, called after menu closes."""
        # Reentrancy guard: if a save is already running (e.g. a second timer fired
        # during show_timed_messagebox's inner event loop), silently skip.
        if self._save_in_progress:
            logger.debug(f"_perform_preset_save re-entry blocked for '{preset_name}'")
            return
        self._save_in_progress = True
        logger.debug(f"Starting preset save operation for: '{preset_name}'")

        try:
            self._perform_preset_save_impl(preset_name)
        finally:
            self._save_in_progress = False

    def _perform_preset_save_impl(self, preset_name: str) -> None:
        """Internal implementation of preset save (called by _perform_preset_save)."""
        # Check if preset already exists and ask for confirmation first
        preset_file = os.path.join(
            self.manager.preset_manager.presets_dir, f"{preset_name}.snap"
        )
        if os.path.exists(preset_file):
            logger.debug(
                f"Preset '{preset_name}' already exists, asking for confirmation"
            )
            try:
                reply = QMessageBox.question(
                    self.manager,
                    "Confirm Overwrite",
                    f"A preset named '{preset_name}' already exists.\nDo you want to overwrite it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    logger.debug(f"User cancelled overwrite for preset '{preset_name}'")
                    return
            except Exception as e:
                logger.error(f"Error showing confirmation dialog: {e}")
                return

        # Delegate to PresetOperations for the actual save
        try:
            # Save connections via aj-snapshot
            snap_ok = PresetOperations.save_snap_file(
                preset_name, self.manager.preset_manager.presets_dir
            )
            if not snap_ok:
                QMessageBox.critical(
                    self.manager,
                    "Save Error",
                    f"Failed to save preset '{preset_name}' via aj-snapshot.",
                )
                return

            # Collect and save layout data
            graph_window = self.manager._get_graph_main_window()
            if graph_window:
                try:
                    scene = self.manager._get_graph_scene()
                    view = self.manager._get_graph_view()
                    layout_data = PresetOperations.collect_layout_data(
                        scene=scene,
                        view=view,
                        node_visibility_manager=self.manager.node_visibility_manager,
                        config_manager=self.manager.config_manager,
                    )
                    if layout_data:
                        layout_presets_dir = os.path.join(
                            self.manager.preset_manager.config_dir, "layout_presets"
                        )
                        PresetOperations.save_layout_file(
                            preset_name, layout_presets_dir, layout_data
                        )
                except Exception as e:
                    logger.warning(f"Warning: Could not save layout data: {e}")

            logger.info(f"Preset '{preset_name}' saved successfully.")
            self.current_preset_name = preset_name
            self.manager.config_manager.set_str(keys.ACTIVE_PRESET, preset_name)
            show_timed_messagebox(
                self.manager,
                QMessageBox.Icon.Information,
                "Preset Saved",
                f"Preset '{preset_name}' saved successfully.",
            )

        except Exception as e:
            logger.debug(f"Exception during preset save: {e}")
            import traceback

            traceback.print_exc()
            QMessageBox.critical(
                self.manager,
                "Save Error",
                f"An error occurred while saving the preset: {e}",
            )

    def _json_serializer_simple(self, obj: Any) -> Any:
        """Simple JSON serializer for Qt objects."""
        return PresetOperations._json_serializer(obj)

    def _set_startup_preset(self, name: Optional[str]) -> None:
        """Sets the selected preset name as the startup preset in the config."""
        logger.debug(f"Setting startup preset to: {name}")
        self.startup_preset_name = name  # Update internal state
        self.manager.config_manager.set_str(keys.STARTUP_PRESET, name)

    def load_selected_preset(self, name: str, is_startup: bool = False) -> bool:
        """
        Loads the connections and layout from the selected preset.
        Updates self.current_preset_name and returns True on success, False otherwise.
        is_startup flag prevents showing success message on startup load.
        """
        logger.debug(f"Loading preset: {name}")

        strict_mode = self.manager.config_manager.get_bool(
            keys.LOAD_PRESET_STRICT_MODE, False
        )
        daemon_mode = self.manager.config_manager.get_bool(
            keys.LOAD_PRESET_DAEMON_MODE, False
        )
        restore_layout = self.manager.config_manager.get_bool(
            keys.LOAD_PRESET_RESTORE_LAYOUT, True
        )

        # First, stop any existing daemon to avoid multiple instances
        if daemon_mode:
            self.manager.preset_manager.stop_daemon_mode()

        # Capture the original state before loading for change detection
        self._capture_current_state()

        # Use enhanced preset manager if available, otherwise fall back to basic
        if getattr(
            self.manager.preset_manager, "load_and_apply_preset_with_layout", None
        ):
            self.manager.disconnect_all_unified()
            success, layout_data = (
                self.manager.preset_manager.load_and_apply_preset_with_layout(
                    name,
                    strict_mode=strict_mode,
                    daemon_mode=daemon_mode,
                    apply_layout=restore_layout,
                )
            )
            self.manager.reconnect_all_unified()

            # Store the original preset state for change detection
            self.original_preset_connections = self.manager._get_current_connections()
            self.original_preset_layout_data = layout_data

            # Apply layout data if available and restore_layout is enabled, regardless of connection success
            if layout_data and restore_layout:
                self._apply_layout_data(layout_data)

        else:
            success = self.manager.preset_manager.load_and_apply_preset(
                name, strict_mode=strict_mode, daemon_mode=daemon_mode
            )
            # For basic preset manager, only store connection state
            self.original_preset_connections = self.manager._get_current_connections()
            self.original_preset_layout_data = None

        if success:
            logger.debug("Preset load complete. Refreshing UI.")
            self.current_preset_name = name
            self.manager.config_manager.set_str(keys.ACTIVE_PRESET, name)
            # Initially set save button to disabled since we just loaded the preset (no changes yet)
            self.save_button_initially_enabled = False
            save_action = getattr(self.manager, "save_preset_action", None)
            if save_action:
                save_action.setEnabled(False)
            logger.debug(f"Load Success: Set active_preset in config to '{name}'")
            self.manager.refresh_ports()

            # Update preset button styles to reflect daemon state
            self._update_preset_button_styles()

            if not is_startup:
                show_timed_messagebox(
                    self.manager,
                    QMessageBox.Icon.Information,
                    "Preset Loaded",
                    f"Preset '{name}' loaded successfully.",
                )

            return True
        else:
            if not is_startup:
                show_timed_messagebox(
                    self.manager,
                    QMessageBox.Icon.Information,
                    "Preset Loaded",
                    f"Preset '{name}' loaded but some connections could not be restored. Missing client?",
                )
            else:
                logger.info(
                    f"Preset '{name}' loaded but some connections could not be restored (missing client?)."
                )
            self.current_preset_name = name
            self.manager.config_manager.set_str(keys.ACTIVE_PRESET, name)
            # Initially set save button to disabled since we just loaded the preset (no changes yet)
            self.save_button_initially_enabled = False
            save_action = getattr(self.manager, "save_preset_action", None)
            if save_action:
                save_action.setEnabled(False)
            logger.debug("Load Success (partial): Set active_preset in config.")
            self.manager.refresh_ports()
            # Update preset button styles to reflect daemon state
            self._update_preset_button_styles()
            return True

    def _delete_selected_preset(self, name: str) -> None:
        """Deletes the selected preset after confirmation."""
        reply = QMessageBox.question(
            self.manager,
            "Delete Preset",
            f"Are you sure you want to delete the preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Stop daemon before deletion to avoid it recreating the .snap file
            # after os.remove() removes it (daemon watches the file and may rewrite it)
            stop_daemon = getattr(self.manager.preset_manager, "stop_daemon_mode", None)
            if stop_daemon:
                stop_daemon()

            # Use enhanced preset manager if available, otherwise fall back to basic
            delete_with_layout = getattr(
                self.manager.preset_manager, "delete_preset_with_layout", None
            )
            if delete_with_layout:
                success = delete_with_layout(name)
            else:
                success = self.manager.preset_manager.delete_preset(name)

            if success:
                logger.debug(f"Preset '{name}' deleted.")
                show_timed_messagebox(
                    self.manager,
                    QMessageBox.Icon.Information,
                    "Preset Deleted",
                    f"Preset '{name}' deleted.",
                )
                if name == self.current_preset_name:
                    self.current_preset_name = None
                    self.manager.config_manager.set_str(keys.ACTIVE_PRESET, None)
                    save_action = getattr(self.manager, "save_preset_action", None)
                    if save_action:
                        save_action.setEnabled(False)
                    logger.debug(
                        "Cleared active_preset in config as current preset was deleted."
                    )
                if name == self.startup_preset_name:
                    self.startup_preset_name = None
                    self.manager.config_manager.set_str(keys.STARTUP_PRESET, None)
                    logger.debug("Cleared startup_preset in config as it was deleted.")
                self.manager.refresh_ports()
            else:
                QMessageBox.warning(
                    self.manager,
                    "Delete Preset",
                    f"Could not find or delete preset '{name}'.",
                )

    def _handle_gui_preset_load(self, name: str) -> None:
        """Handles loading a preset via the GUI menu click."""
        self.load_selected_preset(name)

    def handle_default_preset_action(self) -> None:
        """Handles the 'Default' preset action: disconnects all connections, unhides and unfolds all nodes, then restarts the session manager."""
        # Check if user has disabled the confirmation dialog
        skip_confirmation = self.manager.config_manager.get_bool(
            keys.DEFAULT_PRESET_SKIP_CONFIRMATION, False
        )

        if not skip_confirmation:
            dialog = DefaultResetConfirmDialog(self.manager)
            reply = dialog.exec()

            if reply != QDialog.DialogCode.Accepted:
                return  # User cancelled

            # Save the "don't show again" preference if checked
            if dialog.dont_show_again:
                self.manager.config_manager.set_bool(
                    keys.DEFAULT_PRESET_SKIP_CONFIRMATION, True
                )
                logger.debug(
                    "User chose to skip Default preset confirmation in the future."
                )

        # Proceed with the reset
        logger.debug("User confirmed default connection reset.")

        logger.debug("Step 1: Disconnecting all existing JACK connections...")
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
                        logger.debug(
                            f"    Unexpected error disconnecting {output_name} -> {input_name}: {e}"
                        )
                        disconnect_errors.append(f"{output_name} -> {input_name}: {e}")
            logger.debug(f"Step 1: Disconnected {disconnected_count} connections.")
            if disconnect_errors:
                logger.debug(
                    f"Step 1: Encountered unexpected errors during disconnection: {disconnect_errors}"
                )
        else:
            logger.debug("Step 1: No active JACK connections found to disconnect.")

        logger.debug("Step 2: Unhiding all nodes/clients...")
        self._unhide_all_nodes()

        logger.debug("Step 3: Unfolding all nodes in graph...")
        self._unfold_all_nodes()

        logger.debug("Step 4: Restarting PipeWire session manager...")
        service_name = "wireplumber.service"
        command = []
        if self.manager.flatpak_env:
            logger.debug(
                f"  Running in Flatpak environment. Using flatpak-spawn to restart {service_name}."
            )
            command = [
                "flatpak-spawn",
                "--host",
                "systemctl",
                "restart",
                "--user",
                service_name,
            ]
        else:
            logger.debug(
                f"  Running outside Flatpak environment. Using systemctl to restart {service_name}."
            )
            command = ["systemctl", "restart", "--user", service_name]

        logger.debug(f"  Executing command: {' '.join(command)}")
        success = QProcess.startDetached(command[0], command[1:])

        self.manager.config_manager.set_str(keys.ACTIVE_PRESET, None)
        self.current_preset_name = None
        save_action = getattr(self.manager, "save_preset_action", None)
        if save_action:
            save_action.setEnabled(False)
        logger.debug("Cleared active_preset in config after selecting 'Default'.")

        if success:
            logger.debug(
                "Step 4: Session manager restart command initiated successfully."
            )
            show_timed_messagebox(
                self.manager,
                QMessageBox.Icon.Information,
                "Resetting Connections",
                f"Disconnected {disconnected_count} connections.\nUnhid and unfolded all nodes.\nSession manager ({service_name}) restart initiated.",
                3000,
            )
            QTimer.singleShot(2000, self._clear_defaults_and_refresh)
        else:
            error_message = (
                f"Failed to execute session manager restart command: {' '.join(command)}\n\n"
                f"Connections were disconnected, but defaults may not be restored.\n"
                f"If you are not using WirePlumber, you might need to manually restart your session manager."
            )
            logger.debug(error_message)
            QMessageBox.critical(self.manager, "Reset Error", error_message)
            self.manager.refresh_ports()

    def _clear_defaults_and_refresh(self) -> None:
        """Clear all default sinks/sources after WirePlumber has restarted, then refresh ports."""
        clear_cmd = (
            ["flatpak-spawn", "--host", "wpctl", "clear-default"]
            if self.manager.flatpak_env
            else ["wpctl", "clear-default"]
        )
        try:
            subprocess.run(clear_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.debug("Cleared all default sinks/sources via wpctl after restart.")
        except Exception as e:
            logger.error(f"Failed to clear default sinks/sources: {e}")
        self.manager.refresh_ports()

    def save_current_loaded_preset(self) -> None:
        """Saves the current connections and layout to the currently loaded preset file without confirmation."""
        if not self.current_preset_name:
            QMessageBox.warning(
                self.manager, "Save Preset Error", "No preset is currently loaded."
            )
            return

        preset_name = self.current_preset_name
        logger.info(
            f"Saving current connections and layout to loaded preset: '{preset_name}'"
        )

        # Collect layout data via PresetOperations
        scene = self.manager._get_graph_scene()
        view = self.manager._get_graph_view()
        layout_data = PresetOperations.collect_layout_data(
            scene=scene,
            view=view,
            node_visibility_manager=self.manager.node_visibility_manager,
            config_manager=self.manager.config_manager,
        )

        # Use enhanced preset manager if available, otherwise fall back to basic
        save_with_layout = getattr(
            self.manager.preset_manager, "save_preset_with_layout", None
        )
        if save_with_layout:
            success = save_with_layout(
                preset_name,
                node_states=layout_data.get("node_states"),
                graph_zoom_level=layout_data.get("graph_zoom_level"),
                node_visibility_data=layout_data.get("node_visibility"),
                parent_widget=self.manager,
                confirm_overwrite=False,
            )
        else:
            success = self.manager.preset_manager.save_preset(
                preset_name, parent_widget=self.manager, confirm_overwrite=False
            )

        if success:
            logger.debug(f"Preset '{preset_name}' saved.")
            # Update the original state to reflect the current (saved) state
            self.original_preset_connections = self.manager._get_current_connections()
            self.original_preset_layout_data = layout_data
            # Update save button state since changes have been saved
            self.update_save_button_enabled_state()
            show_timed_messagebox(
                self.manager,
                QMessageBox.Icon.Information,
                "Preset Saved",
                f"Preset '{preset_name}' saved successfully.",
            )

    def _set_strict_mode(self, checked: bool) -> None:
        """Sets the strict mode for preset loading in the config and reloads preset if active."""
        logger.debug(f"Setting strict mode for preset loading to: {checked}")
        self.manager.config_manager.set_bool(keys.LOAD_PRESET_STRICT_MODE, checked)

        # Reload current preset to apply the new strict mode setting
        if self.current_preset_name:
            logger.debug(
                f"Reloading preset '{self.current_preset_name}' with strict={checked}"
            )
            self.load_selected_preset(self.current_preset_name)

    def _set_daemon_mode(self, checked: bool) -> None:
        """Sets the daemon mode for preset loading in the config and starts/stops the daemon."""
        logger.debug(f"Setting daemon mode for preset loading to: {checked}")
        self.manager.config_manager.set_bool(keys.LOAD_PRESET_DAEMON_MODE, checked)

        if self.current_preset_name:
            # Always stop existing daemon first
            self.manager.preset_manager.stop_daemon_mode()
            # Reload preset with new daemon mode setting
            logger.debug(
                f"Reloading preset '{self.current_preset_name}' with daemon={checked}"
            )
            self.load_selected_preset(self.current_preset_name)
        elif checked:
            logger.debug("No active preset to start daemon mode with.")

        # Update button styles to reflect the new daemon state
        # Use QTimer to ensure daemon state is updated after any preset loading
        QTimer.singleShot(100, self._update_preset_button_styles)

    def _update_preset_button_styles(self) -> None:
        """
        Update preset button text color based on daemon state.
        When aj-snapshot daemon is running, "Presets" text is shown in red.
        """
        # Check if daemon is running
        daemon_active = self.manager.preset_manager.is_daemon_running()

        # Get references to preset buttons
        bottom_button = None
        graph_button = None

        # Get bottom toolbar button from ui_manager
        ui_manager = getattr(self.manager, "ui_manager", None)
        if ui_manager:
            bottom_button = getattr(ui_manager, "bottom_presets_button", None)

        # Get graph tab button from graph_main_window
        graph_window = self.manager._get_graph_main_window()
        if graph_window:
            graph_button = getattr(graph_window, "preset_button", None)

        # Update button styles
        buttons_to_update = [b for b in [bottom_button, graph_button] if b is not None]

        for button in buttons_to_update:
            if daemon_active:
                button.setText("Presets ●")
            else:
                button.setText("Presets")

        if buttons_to_update:
            logger.debug(f"Preset button styles updated: daemon_active={daemon_active}")

    def _unhide_all_nodes(self) -> None:
        """Unhide all nodes by resetting node visibility settings."""
        try:
            node_vis_mgr = getattr(self.manager, "node_visibility_manager", None)
            if node_vis_mgr:
                # Clear all visibility settings (empty dictionaries mean all nodes are visible)
                self.manager.node_visibility_manager.audio_input_visibility = {}
                self.manager.node_visibility_manager.audio_output_visibility = {}
                self.manager.node_visibility_manager.midi_input_visibility = {}
                self.manager.node_visibility_manager.midi_output_visibility = {}

                # Save the cleared settings
                self.manager.node_visibility_manager.save_visibility_settings()

                # Apply the visibility settings to refresh the UI
                self.manager.node_visibility_manager.apply_visibility_settings()

                logger.debug("  All nodes unhidden successfully.")
            else:
                logger.debug("  Node visibility manager not available.")
        except Exception as e:
            logger.debug(f"  Error unhiding nodes: {e}")

    def _unfold_all_nodes(self) -> None:
        """Unfold all nodes in the graph view."""
        try:
            scene = self.manager._get_graph_scene()
            if scene:
                unfolded_count = 0

                # Iterate through all nodes in the scene
                for client_name, node in scene.nodes.items():
                    try:
                        if node.is_split_origin:
                            # Handle split nodes - unfold their parts
                            if node.split_input_node and getattr(
                                node.split_input_node, "input_part_folded", False
                            ):
                                if node.split_input_node.input_part_folded:
                                    node.split_input_node.fold_handler.toggle_input_part_fold(
                                        fold_state=False
                                    )
                                    unfolded_count += 1

                            if node.split_output_node and getattr(
                                node.split_output_node, "output_part_folded", False
                            ):
                                if node.split_output_node.output_part_folded:
                                    node.split_output_node.fold_handler.toggle_output_part_fold(
                                        fold_state=False
                                    )
                                    unfolded_count += 1

                        elif not node.is_split_part:
                            # Handle regular (non-split) nodes
                            if getattr(node, "is_folded", False):
                                node.fold_handler.toggle_main_fold_state()
                                unfolded_count += 1

                    except Exception as e:
                        logger.debug(f"  Error unfolding node {client_name}: {e}")

                logger.debug(f"  Unfolded {unfolded_count} nodes successfully.")
            else:
                logger.debug("  Graph scene not available.")
        except Exception as e:
            logger.debug(f"  Error unfolding nodes: {e}")

    def reset_default_preset_confirmation(self) -> None:
        """Reset the 'don't show again' setting for Default preset confirmation."""
        self.manager.config_manager.set_bool(
            keys.DEFAULT_PRESET_SKIP_CONFIRMATION, False
        )
        logger.info("Default preset confirmation dialog has been re-enabled.")

    def _set_restore_layout_mode(self, checked: bool) -> None:
        """Sets the restore layout mode for preset loading in the config."""
        logger.debug(f"Setting restore layout mode for preset loading to: {checked}")
        self.manager.config_manager.set_bool(keys.LOAD_PRESET_RESTORE_LAYOUT, checked)

    def _apply_layout_data(self, layout_data: Dict[str, Any]) -> None:
        """
        Apply layout data to the graph scene and node visibility settings.

        Args:
            layout_data (dict): Layout data containing node_states, graph_zoom_level, and node_visibility
        """
        if not layout_data:
            return

        try:
            # Apply node states if available
            if "node_states" in layout_data:
                scene = self.manager._get_graph_scene()
                restore_func = (
                    getattr(scene, "restore_node_states", None) if scene else None
                )
                if restore_func:
                    restore_func(layout_data["node_states"])
                    logger.info("Applied node states from preset")

            # Uncheck "persistent layout" when layout is restored from preset
            # This prevents the preset's layout from being overwritten by auto-untangle
            graph_window = self.manager._get_graph_main_window()
            if graph_window and getattr(graph_window, "keep_untangled", False):
                graph_window.keep_untangled = False
                # Also update the button visual state
                persistent_btn = getattr(graph_window, "persistent_layout_button", None)
                if persistent_btn:
                    persistent_btn.setChecked(False)
                # Save the setting to config
                scene = self.manager._get_graph_scene()
                node_config_mgr = (
                    getattr(scene, "node_config_manager", None) if scene else None
                )
                if node_config_mgr:
                    node_config_mgr.save_keep_untangled(False)
                logger.info("Unchecked 'persistent layout' to preserve preset layout")

            # Apply zoom level if available
            if "graph_zoom_level" in layout_data:
                view = self.manager._get_graph_view()
                set_zoom = getattr(view, "set_zoom_level", None) if view else None
                if set_zoom:
                    set_zoom(layout_data["graph_zoom_level"])
                    logger.info(
                        f"Applied zoom level {layout_data['graph_zoom_level']} from preset"
                    )

            # Apply node visibility settings if available
            if "node_visibility" in layout_data and layout_data["node_visibility"]:
                node_vis_mgr = getattr(self.manager, "node_visibility_manager", None)
                if node_vis_mgr:
                    visibility_data = layout_data["node_visibility"]

                    # Replace the node visibility manager's settings (not update)
                    if "audio_input" in visibility_data:
                        self.manager.node_visibility_manager.audio_input_visibility = (
                            dict(visibility_data["audio_input"])
                        )
                    if "audio_output" in visibility_data:
                        self.manager.node_visibility_manager.audio_output_visibility = (
                            dict(visibility_data["audio_output"])
                        )
                    if "midi_input" in visibility_data:
                        self.manager.node_visibility_manager.midi_input_visibility = (
                            dict(visibility_data["midi_input"])
                        )
                    if "midi_output" in visibility_data:
                        self.manager.node_visibility_manager.midi_output_visibility = (
                            dict(visibility_data["midi_output"])
                        )

                    # Save the updated settings to the config file
                    self.manager.node_visibility_manager.save_visibility_settings()

                    # Apply the visibility settings to refresh the UI
                    self.manager.node_visibility_manager.apply_visibility_settings()

                    logger.info("Applied node visibility settings from preset")

            # Apply unified clients if available
            if "unified_clients" in layout_data:
                scene = self.manager._get_graph_scene()
                apply_unified = (
                    getattr(scene, "apply_unified_states", None) if scene else None
                )
                if apply_unified:
                    self.unified_clients = layout_data.get("unified_clients", {})
                    apply_unified(self.unified_clients)
                    scene.apply_unified_states(self.unified_clients)
                    logger.info("Applied unified clients from preset")

            # Apply split audio/midi setting if available
            if "split_audio_midi" in layout_data:
                split_audio_midi = layout_data["split_audio_midi"]
                self.manager.config_manager.set_bool(
                    keys.GRAPH_SPLIT_AUDIO_MIDI_CLIENTS, split_audio_midi
                )
                logger.info(
                    f"Applied split audio/midi setting from preset: {split_audio_midi}"
                )
                # We need to trigger a full refresh of the graph for this to take effect
                scene = self.manager._get_graph_scene()
                if scene:
                    scene.full_graph_refresh()

        except Exception as e:
            logger.error(f"Error applying layout data: {e}")

    def _capture_current_state(self) -> None:
        """Capture the current state of connections and layout for comparison when preset is loaded."""
        try:
            # This method would be called before loading a preset to compare against after loading
            # For now, we'll capture when preset is actually loaded
            pass
        except Exception as e:
            logger.error(f"Error capturing current state: {e}")

    def _connections_have_changed(self) -> bool:
        """
        Check if the current connections have changed compared to the originally loaded preset.

        Returns:
            bool: True if connections have changed, False otherwise
        """
        if not self.current_preset_name or self.original_preset_connections is None:
            return False

        try:
            current_connections = self.manager._get_current_connections()
            return PresetOperations.connections_have_changed(
                current_connections, self.original_preset_connections
            )
        except Exception as e:
            logger.error(f"Error comparing connections: {e}")
            return False

    def _layout_has_changed(self) -> bool:
        """
        Check if the current layout has changed compared to the originally loaded preset.

        Returns:
            bool: True if layout has changed, False otherwise
        """
        if not self.current_preset_name or not self.original_preset_layout_data:
            return False

        try:
            scene = self.manager._get_graph_scene()
            view = self.manager._get_graph_view()
            current_layout_data = PresetOperations.collect_layout_data(
                scene=scene,
                view=view,
                node_visibility_manager=self.manager.node_visibility_manager,
                config_manager=self.manager.config_manager,
            )
            return PresetOperations.layout_has_changed(
                current_layout_data, self.original_preset_layout_data
            )
        except Exception as e:
            logger.error(f"Error comparing layout: {e}")
            return False

    def _preset_has_changes(self) -> bool:
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
            logger.debug(
                f"Preset '{self.current_preset_name}' has changes: connections={connections_changed}, layout={layout_changed}"
            )

        return has_changes

    def update_save_button_enabled_state(self) -> None:
        """Update the save button enabled state based on whether the loaded preset has changes."""
        if not self.current_preset_name:
            # No preset loaded, disable save button
            enabled = False
        else:
            # Preset loaded, enable save button only if there are changes
            enabled = self._preset_has_changes()

        # Update the button state if it's different from current state
        save_action = getattr(self.manager, "save_preset_action", None)
        if save_action:
            current_enabled = save_action.isEnabled()
            if current_enabled != enabled:
                save_action.setEnabled(enabled)
                logger.info(
                    f"Save button {'enabled' if enabled else 'disabled'} for preset '{self.current_preset_name}'"
                )
