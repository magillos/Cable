#!/usr/bin/env python3
"""
QuantumManager - Handles quantum (buffer size) and sample rate settings for Cable.

This module provides a manager class that handles:
- Loading and applying quantum (buffer size) settings
- Loading and applying sample rate settings
- Managing dropdown lists for quantum and sample rate values
- Coordinating with PipewireManager for audio settings
"""

import logging
from typing import TYPE_CHECKING, Optional, Any, Dict, List, Callable

from PyQt6.QtWidgets import QComboBox, QMessageBox, QDialog
from PyQt6.QtCore import QTimer, Qt

from cable_core.app_config import EDIT_LIST_TEXT
from cable_core.dialogs import ValueSelectorDialog

if TYPE_CHECKING:
    from cable_core.config import ConfigManager
    from cable_core.pipewire import PipewireManager

logger = logging.getLogger(__name__)

__all__ = ["QuantumManager"]


class QuantumManager:
    """
    Manages quantum (buffer size) and sample rate settings.

    This class handles the loading, display, and application of PipeWire
    quantum and sample rate settings.

    Usage:
        manager = QuantumManager(
            parent, config_manager, pipewire_manager,
            quantum_combo, sample_rate_combo
        )
        manager.load_current_settings()
        manager.apply_quantum_settings()
        manager.apply_sample_rate_settings()
    """

    DEFAULT_QUANTUM_VALUES = [
        16,
        32,
        48,
        64,
        96,
        128,
        144,
        192,
        240,
        256,
        512,
        1024,
        2048,
        4096,
        8192,
    ]
    DEFAULT_SAMPLE_RATE_VALUES = [44100, 48000, 88200, 96000, 176400, 192000]

    def __init__(
        self,
        parent: Any,
        config_manager: "ConfigManager",
        pipewire_manager: "PipewireManager",
        quantum_combo: QComboBox,
        sample_rate_combo: QComboBox,
        latency_display_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Initialize the QuantumManager.

        Args:
            parent: Parent widget for dialog parenting
            config_manager: ConfigManager instance for settings
            pipewire_manager: PipewireManager instance for backend operations
            quantum_combo: Combo box for quantum selection
            sample_rate_combo: Combo box for sample rate selection
            latency_display_callback: Optional callback to update latency display
        """
        self.parent = parent
        self.config_manager = config_manager
        self.pipewire_manager = pipewire_manager
        self.quantum_combo = quantum_combo
        self.sample_rate_combo = sample_rate_combo
        self.latency_display_callback = latency_display_callback

        # Track last valid indices for reverting on invalid input
        self.last_valid_quantum_index = 0
        self.last_valid_sample_rate_index = 0

        # Track reset states
        self.quantum_was_reset = False
        self.sample_rate_was_reset = False

        # Flag to prevent saving during initial load
        self.initial_load = True

        # Connect signals
        self.quantum_combo.currentIndexChanged.connect(self._on_quantum_index_changed)
        self.sample_rate_combo.currentIndexChanged.connect(
            self._on_sample_rate_index_changed
        )

    def populate_dropdowns(self) -> None:
        """Populate quantum and sample rate dropdowns from config."""
        self._populate_quantum_dropdown()
        self._populate_sample_rate_dropdown()

    def _populate_quantum_dropdown(self) -> None:
        """Populate the quantum dropdown from config."""
        self.quantum_combo.blockSignals(True)
        try:
            self.quantum_combo.clear()
            values = self.config_manager.get_list_from_config(
                "quantum_values", self.DEFAULT_QUANTUM_VALUES
            )
            for value in values:
                self.quantum_combo.addItem(str(value))
            self.quantum_combo.addItem(EDIT_LIST_TEXT)
            edit_item_index = self.quantum_combo.count() - 1
            self.quantum_combo.setItemData(
                edit_item_index,
                "Select, then press Enter to edit list",
                Qt.ItemDataRole.ToolTipRole,
            )
        finally:
            self.quantum_combo.blockSignals(False)

    def _populate_sample_rate_dropdown(self) -> None:
        """Populate the sample rate dropdown from config."""
        self.sample_rate_combo.blockSignals(True)
        try:
            self.sample_rate_combo.clear()
            values = self.config_manager.get_list_from_config(
                "sample_rate_values", self.DEFAULT_SAMPLE_RATE_VALUES
            )
            for value in values:
                self.sample_rate_combo.addItem(str(value))
            self.sample_rate_combo.addItem(EDIT_LIST_TEXT)
            edit_item_index = self.sample_rate_combo.count() - 1
            self.sample_rate_combo.setItemData(
                edit_item_index,
                "Select, then press Enter to edit list",
                Qt.ItemDataRole.ToolTipRole,
            )
        finally:
            self.sample_rate_combo.blockSignals(False)

    def _set_combo_to_value(
        self, combo: QComboBox, value_str: str, last_valid_attr: str
    ) -> None:
        """Set a combo box to the given value, inserting if not found."""
        index = combo.findText(value_str)
        if index >= 0:
            combo.setCurrentIndex(index)
            setattr(self, last_valid_attr, index)
        else:
            edit_item_index = combo.count() - 1
            if edit_item_index >= 0:
                combo.insertItem(edit_item_index, value_str)
                combo.setCurrentIndex(edit_item_index)
                setattr(self, last_valid_attr, edit_item_index)
                logger.info(f"Inserted '{value_str}' into dropdown.")
            else:
                logger.warning(
                    f"Could not find '{EDIT_LIST_TEXT}' to insert '{value_str}' before."
                )

    def load_current_settings(
        self, force_reset_quantum: bool = False, force_reset_sample_rate: bool = False
    ) -> None:
        """
        Load current PipeWire settings asynchronously.

        Args:
            force_reset_quantum: If True, mark quantum as reset if forced value is 0/None
            force_reset_sample_rate: If True, mark sample rate as reset if forced value is 0/None
        """
        # This would need to be called via async_runner in the parent
        # For now, we provide the callback mechanism
        self._pending_force_reset_quantum = force_reset_quantum
        self._pending_force_reset_sample_rate = force_reset_sample_rate

    def apply_loaded_settings(self, settings: Dict[str, Any]) -> None:
        """
        Apply loaded settings to the UI.

        Args:
            settings: Dictionary with 'quantum', 'sample_rate', 'forced_quantum', 'forced_rate'
        """
        force_reset_quantum = getattr(self, "_pending_force_reset_quantum", False)
        force_reset_sample_rate = getattr(
            self, "_pending_force_reset_sample_rate", False
        )

        self.quantum_combo.blockSignals(True)
        self.sample_rate_combo.blockSignals(True)
        try:
            if not settings:
                return

            sample_rate = settings.get("sample_rate")
            quantum = settings.get("quantum")
            forced_quantum = settings.get("forced_quantum")
            forced_rate = settings.get("forced_rate")

            if force_reset_quantum and forced_quantum in (None, "0"):
                self.quantum_was_reset = True
            if force_reset_sample_rate and forced_rate in (None, "0"):
                self.sample_rate_was_reset = True

            if sample_rate:
                self._set_combo_to_value(
                    self.sample_rate_combo, sample_rate, "last_valid_sample_rate_index"
                )

            if quantum:
                self._set_combo_to_value(
                    self.quantum_combo, quantum, "last_valid_quantum_index"
                )
        except Exception as e:
            logger.error(f"Error loading current settings: {e}")
        finally:
            self.quantum_combo.blockSignals(False)
            self.sample_rate_combo.blockSignals(False)

            if self.latency_display_callback:
                self.latency_display_callback()

    def apply_quantum_settings(
        self, skip_save: bool = False, remember_settings: bool = False
    ) -> bool:
        """
        Apply the current quantum settings.

        Args:
            skip_save: If True, don't save to config
            remember_settings: If True, save for restoration on startup

        Returns:
            True if successful, False otherwise
        """
        value_str = self.quantum_combo.currentText()
        result = self.pipewire_manager.apply_quantum_settings(
            value_str=value_str,
            skip_save=skip_save,
            remember_settings=remember_settings,
            initial_load=self.initial_load,
            quantum_was_reset=self.quantum_was_reset,
        )

        if not result:
            return False

        if result.get("ok"):
            data = result.get("data", {})
            self.quantum_was_reset = data.get("was_reset", self.quantum_was_reset)
            new_index = self.quantum_combo.findText(value_str)
            if new_index >= 0:
                self.last_valid_quantum_index = new_index
                logger.debug(
                    f"Updated last valid index for quantum to {new_index} after applying '{value_str}'"
                )
            return True
        else:
            ui = result.get("ui", {})
            if ui.get("edit_list") == "quantum":
                self.edit_quantum_list()

                def reset_quantum_index():
                    self.quantum_combo.blockSignals(True)
                    self.quantum_combo.setCurrentIndex(self.last_valid_quantum_index)
                    self.quantum_combo.blockSignals(False)

                QTimer.singleShot(0, reset_quantum_index)
                return False
            if ui.get("revert"):
                QTimer.singleShot(
                    0,
                    lambda: self.quantum_combo.setCurrentIndex(
                        self.last_valid_quantum_index
                    ),
                )
            error = result.get("error")
            if error:
                QMessageBox.warning(self.parent, error["title"], error["message"])
            return False

    def apply_sample_rate_settings(
        self, skip_save: bool = False, remember_settings: bool = False
    ) -> bool:
        """
        Apply the current sample rate settings.

        Args:
            skip_save: If True, don't save to config
            remember_settings: If True, save for restoration on startup

        Returns:
            True if successful, False otherwise
        """
        value_str = self.sample_rate_combo.currentText()
        result = self.pipewire_manager.apply_sample_rate_settings(
            value_str=value_str,
            skip_save=skip_save,
            remember_settings=remember_settings,
            initial_load=self.initial_load,
            sample_rate_was_reset=self.sample_rate_was_reset,
        )

        if not result:
            return False

        if result.get("ok"):
            data = result.get("data", {})
            self.sample_rate_was_reset = data.get(
                "was_reset", self.sample_rate_was_reset
            )
            new_index = self.sample_rate_combo.findText(value_str)
            if new_index >= 0:
                self.last_valid_sample_rate_index = new_index
                logger.debug(
                    f"Updated last valid index for sample rate to {new_index} after applying '{value_str}'"
                )
            return True
        else:
            ui = result.get("ui", {})
            if ui.get("edit_list") == "sample_rate":
                self.edit_sample_rate_list()

                def reset_sample_rate_index():
                    self.sample_rate_combo.blockSignals(True)
                    self.sample_rate_combo.setCurrentIndex(
                        self.last_valid_sample_rate_index
                    )
                    self.sample_rate_combo.blockSignals(False)

                QTimer.singleShot(0, reset_sample_rate_index)
                return False
            if ui.get("revert"):
                QTimer.singleShot(
                    0,
                    lambda: self.sample_rate_combo.setCurrentIndex(
                        self.last_valid_sample_rate_index
                    ),
                )
            error = result.get("error")
            if error:
                QMessageBox.warning(self.parent, error["title"], error["message"])
            return False

    def reset_quantum(self) -> bool:
        """
        Reset quantum to default.

        Returns:
            True if successful, False otherwise
        """
        result = self.pipewire_manager.reset_quantum_settings()
        if result.get("ok"):
            self.quantum_was_reset = True
            return True
        elif result.get("error"):
            QMessageBox.critical(
                self.parent, result["error"]["title"], result["error"]["message"]
            )
        return False

    def reset_sample_rate(self) -> bool:
        """
        Reset sample rate to default.

        Returns:
            True if successful, False otherwise
        """
        result = self.pipewire_manager.reset_sample_rate_settings()
        if result.get("ok"):
            self.sample_rate_was_reset = True
            return True
        elif result.get("error"):
            QMessageBox.critical(
                self.parent, result["error"]["title"], result["error"]["message"]
            )
        return False

    def edit_quantum_list(self) -> None:
        """Open dialog to edit quantum values list."""
        self._edit_value_list("Quantum", "quantum_values", self.DEFAULT_QUANTUM_VALUES)

    def edit_sample_rate_list(self) -> None:
        """Open dialog to edit sample rate values list."""
        self._edit_value_list(
            "Sample Rate", "sample_rate_values", self.DEFAULT_SAMPLE_RATE_VALUES
        )

    def _edit_value_list(
        self, title: str, config_key: str, default_values_list: List[int]
    ) -> None:
        """Handle editing the list of values in the config file via a dialog."""
        # Get all values from config (including commented ones) to show in dialog
        all_values = self.config_manager.get_all_values_from_config(
            config_key, default_values_list
        )
        # Get currently active values from config
        active_values = self.config_manager.get_list_from_config(
            config_key, default_values_list
        )

        # Show the dialog
        dialog = ValueSelectorDialog(
            f"Select Active {title} Values", all_values, active_values, self.parent
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_values = dialog.get_selected_values()
            logger.debug(
                f"Dialog accepted for {title}. Selected values: {selected_values}"
            )

            # Construct the new comma-separated string, commenting out unselected values
            new_value_parts = []
            for val in all_values:
                if val in selected_values:
                    new_value_parts.append(str(val))
                else:
                    new_value_parts.append(f"#{val}")  # Comment out unselected values

            self.config_manager.set_str_setting(config_key, ",".join(new_value_parts))
            self.config_manager.flush()
            logger.debug(f"Updated '{config_key}' in config")

            # Repopulate dropdowns
            self._populate_quantum_dropdown()
            self._populate_sample_rate_dropdown()

    def _on_quantum_index_changed(self, index: int) -> None:
        """Handle quantum combo index change."""
        self.quantum_combo.blockSignals(True)
        try:
            if index >= 0:
                text = self.quantum_combo.itemText(index)
                if text != EDIT_LIST_TEXT:
                    self.last_valid_quantum_index = index
                    if self.latency_display_callback:
                        self.latency_display_callback()
        finally:
            self.quantum_combo.blockSignals(False)

    def _on_sample_rate_index_changed(self, index: int) -> None:
        """Handle sample rate combo index change."""
        self.sample_rate_combo.blockSignals(True)
        try:
            if index >= 0:
                text = self.sample_rate_combo.itemText(index)
                if text != EDIT_LIST_TEXT:
                    self.last_valid_sample_rate_index = index
                    if self.latency_display_callback:
                        self.latency_display_callback()
        finally:
            self.sample_rate_combo.blockSignals(False)

    def set_initial_load(self, value: bool) -> None:
        """Set the initial load flag."""
        self.initial_load = value

    def get_quantum_value(self) -> int:
        """Get the current quantum value as integer."""
        text = self.quantum_combo.currentText()
        try:
            return int(text) if text != EDIT_LIST_TEXT else 0
        except ValueError:
            return 0

    def get_sample_rate_value(self) -> int:
        """Get the current sample rate value as integer."""
        text = self.sample_rate_combo.currentText()
        try:
            return int(text) if text != EDIT_LIST_TEXT else 0
        except ValueError:
            return 0

    def calculate_latency_ms(self) -> Optional[float]:
        """
        Calculate the current latency in milliseconds.

        Returns:
            Latency in ms or None if cannot calculate
        """
        quantum = self.get_quantum_value()
        sample_rate = self.get_sample_rate_value()

        if sample_rate == 0 or quantum == 0:
            return None

        return quantum / sample_rate * 1000
