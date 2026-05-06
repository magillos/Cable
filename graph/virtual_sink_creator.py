"""
VirtualSinkCreator — Handles virtual sink/source creation, unloading, and management.

Extracted from :class:`JackGraphView` to separate virtual sink concerns from view logic.
"""

import json
import os
import subprocess
import logging
from typing import Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QPushButton,
    QDialogButtonBox,
)
from PyQt6.QtCore import QPointF

from cable_core import config_keys as keys
from cable_core.config import ConfigManager as CableCoreConfigManager
from cable_core.dialogs import CombinedSinkSourceDialog

logger = logging.getLogger(__name__)


# Shared ConfigManager instance
_cable_core_config: Optional[CableCoreConfigManager] = None


def _get_cable_core_config() -> CableCoreConfigManager:
    """Get or create the shared ConfigManager instance."""
    global _cable_core_config
    if _cable_core_config is None:
        _cable_core_config = CableCoreConfigManager()
    return _cable_core_config


class VirtualSinkCreator:
    """Handles creation, unloading, and management of virtual sinks/sources."""

    def __init__(self, scene, view) -> None:
        """
        Args:
            scene: The JackGraphScene instance.
            view: The JackGraphView instance (for parent dialogs).
        """
        self._scene = scene
        self._view = view

    # ------------------------------------------------------------------
    # Sink creation
    # ------------------------------------------------------------------

    def show_combined_sink_dialog(self, scene_pos: Optional[QPointF] = None) -> None:
        """Show the dialog for creating a combined virtual sink/source."""
        dialog = CombinedSinkSourceDialog(self._view)
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            sink_name, channel_map = dialog.get_values()
            self._create_combined_sink_source(sink_name, channel_map, scene_pos)

    def _create_combined_sink_source(
        self, sink_name: str, channel_map: str, scene_pos: Optional[QPointF] = None
    ) -> None:
        """Execute the pactl command to create the combined virtual sink/source.

        Delegates subprocess calls to ``UnifiedSinkManager.create_null_sink()``.
        """
        channel_map_param = "stereo"
        extra_params = []

        if channel_map == "Mono":
            channel_map_param = "mono"
            extra_params.append("media.class=Audio/Sink")
        elif channel_map == "5.1":
            channel_map_param = "surround-51"
        elif channel_map == "7.1":
            channel_map_param = "surround-71"

        cm = getattr(self._scene, "connection_manager", None) if self._scene else None
        sink_manager = getattr(cm, "unified_sink_manager", None) if cm else None

        # Register pending position before creation
        if (
            scene_pos is not None
            and self._scene is not None
            and getattr(self._scene, "register_pending_node_position", None) is not None
        ):
            logger.info(f"Registering pending position {scene_pos} for sink {sink_name}")
            self._scene.register_pending_node_position(sink_name, scene_pos)

        if sink_manager is not None:
            result = sink_manager.create_null_sink(sink_name, channel_map_param)
            if result is not None:
                module_id, actual_sink_name = result
                logger.info(
                    f"Created combined virtual sink/source: {actual_sink_name} with channel map {channel_map}"
                )
                if actual_sink_name != sink_name and scene_pos is not None and self._scene is not None:
                    self._scene.unregister_pending_node_position(sink_name)
                    self._scene.register_pending_node_position(actual_sink_name, scene_pos)
            else:
                if scene_pos is not None and self._scene is not None:
                    self._scene.unregister_pending_node_position(sink_name)
                logger.error(f"Failed to create combined virtual sink/source: {sink_name}")
        else:
            command = ["pactl", "load-module", "module-null-sink"]
            command.extend(extra_params)
            command.extend([f"sink_name={sink_name}", f"channel_map={channel_map_param}"])

            try:
                result = subprocess.run(command, check=True, capture_output=True, text=True)
                module_id = result.stdout.strip()
                self._save_module_id(sink_name, module_id)
                logger.info(
                    f"Created combined virtual sink/source: {sink_name} with channel map {channel_map}"
                )
            except subprocess.CalledProcessError as e:
                if scene_pos is not None and self._scene is not None:
                    self._scene.unregister_pending_node_position(sink_name)
                logger.error(f"Error creating combined virtual sink/source: {e}")

    # ------------------------------------------------------------------
    # Sink unloading
    # ------------------------------------------------------------------

    def unload_all_sinks(self) -> None:
        """Unload all virtual sinks in the system."""
        try:
            show_confirmation = True
            config_manager = None
            main_window = self._view.window()
            if main_window is not None:
                config_manager = getattr(main_window, "config_manager", None)
            else:
                config_manager = _get_cable_core_config()

            show_confirmation = True
            if config_manager:
                show_confirmation = config_manager.get_bool(
                    keys.SHOW_UNLOAD_ALL_SINKS_CONFIRMATION, default=True
                )

            if show_confirmation:
                confirmed, dont_show_again = self._show_unload_all_sinks_confirmation_dialog()
                if not confirmed:
                    return
                if dont_show_again and config_manager:
                    try:
                        config_manager.set_bool(
                            keys.SHOW_UNLOAD_ALL_SINKS_CONFIRMATION, False
                        )
                    except Exception as e:
                        logger.warning(f"Warning: Could not save config: {e}")

            null_sink_modules = self._find_null_sink_modules()
            if not null_sink_modules:
                logger.debug("No virtual sinks to unload")
                return

            unloaded_count = 0
            for module_id in null_sink_modules:
                try:
                    command = ["pactl", "unload-module", str(module_id)]
                    subprocess.run(command, check=True, capture_output=True, text=True)
                    logger.info(f"Unloaded virtual sink module {module_id}")
                    unloaded_count += 1
                except subprocess.CalledProcessError as e:
                    logger.error(f"Error unloading module {module_id}: {e}")

            if unloaded_count > 0:
                try:
                    _get_cable_core_config().set_str_setting(
                        keys.VIRTUAL_SINK_MODULE_IDS, "{}"
                    )
                except Exception as e:
                    logger.warning(f"Warning: Could not clear config: {e}")
                logger.info(f"Successfully unloaded {unloaded_count} virtual sink(s)")

        except Exception as e:
            logger.error(f"Error unloading virtual sinks: {e}")

    def remove_all_saved_virtual_sinks(self) -> None:
        """Clear all virtual sinks stored for recreation at auto-start."""
        try:
            cm = getattr(self._scene, "connection_manager", None) if self._scene else None
            config = (
                getattr(cm, "config_manager", None) if cm else _get_cable_core_config()
            )
            config.set_str_setting(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, "{}")
            logger.info("Removed all saved virtual sinks from autostart config")

            if self._scene:
                from .node_item import NodeItem
                for item in self._scene.items():
                    if isinstance(item, NodeItem) and getattr(
                        item, "is_virtual_sink", False
                    ):
                        item.update()
        except Exception as e:
            logger.error(f"Error removing saved virtual sinks: {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _show_unload_all_sinks_confirmation_dialog(self) -> Tuple[bool, bool]:
        """Show a confirmation dialog for unloading all sinks.

        Returns:
            tuple: (confirmed, dont_show_again)
        """
        dialog = QDialog(self._view.window())
        dialog.setWindowTitle("Unload All Sinks")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        message = (
            "This will unload ALL virtual sink modules from PulseAudio/PipeWire.\n\n"
            "This action cannot be undone and may affect active audio connections.\n\n"
            "Are you sure you want to continue?"
        )
        label = QLabel(message)
        layout.addWidget(label)

        checkbox = QCheckBox("Don't show this confirmation again")
        layout.addWidget(checkbox)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        result = dialog.exec() == QDialog.DialogCode.Accepted
        return result, checkbox.isChecked()

    def _find_null_sink_modules(self) -> list:
        """Parse pactl list modules output to find null-sink module IDs."""
        list_command = ["pactl", "list", "modules"]
        list_result = subprocess.run(
            list_command, check=True, capture_output=True, text=True
        )
        output_lines = list_result.stdout.split("\n")

        null_sink_modules = []
        current_module_id = None
        for line in output_lines:
            line = line.strip()
            if line.startswith("Module #"):
                current_module_id = line.split("#")[1].strip()
            elif line.startswith("Name: ") and "module-null-sink" in line:
                null_sink_modules.append(current_module_id)
                current_module_id = None

        return null_sink_modules

    def _save_module_id(self, sink_name: str, module_id: str) -> None:
        """Save the module ID to config file for later unloading."""
        try:
            config = _get_cable_core_config()
            module_ids_json = config.get_str_setting(keys.VIRTUAL_SINK_MODULE_IDS, "{}")
            try:
                module_ids = json.loads(module_ids_json) if module_ids_json else {}
            except json.JSONDecodeError:
                module_ids = {}

            module_ids[sink_name] = module_id
            config.set_str_setting(keys.VIRTUAL_SINK_MODULE_IDS, json.dumps(module_ids))
        except Exception as e:
            logger.error(f"Error saving module ID for {sink_name}: {e}")
