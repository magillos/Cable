"""
Shared settings widget builder used by both OtherSettingsDialog and EmbeddedSettingsPanel.
Provides the settings_map, slider/checkbox creation, load, save, and reset logic.
"""

import os
import shutil
from typing import Dict, Optional

from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QFrame,
    QLineEdit,
    QCheckBox,
    QMessageBox,
    QWidget,
    QLayout,
)
from PyQt6.QtCore import Qt

import logging

logger = logging.getLogger(__name__)

from cable_core import app_config
from cable_core import config_keys as keys
from cable_core.config import ConfigManager

SETTINGS_MAP = {
    keys.PWTOP_FONT_SIZE_PT: {
        "label": "pw-top font size",
        "range": (8, 20),
        "default_key": "PWTOP_FONT_SIZE_PT",
    },
    keys.CONNECTION_LINE_THICKNESS: {
        "label": "Cables thickness",
        "range": (1, 6),
        "default_key": "CONNECTION_LINE_THICKNESS",
    },
}

SEPARATOR_AFTER = {keys.PWTOP_FONT_SIZE_PT}


class SettingsWidgetBuilder:
    """Builds and manages the shared 'Other Settings' widgets (sliders, checkboxes, untangle field).

    The host (dialog or panel) owns the layout; this class populates it and
    provides load/save/reset operations.
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        self.config_manager: ConfigManager = config_manager
        self.sliders: Dict[str, QSlider] = {}
        self.value_labels: Dict[str, QLabel] = {}
        self.slider_labels: Dict[str, QLabel] = {}
        self.text_fields: Dict[str, QLineEdit] = {}
        self.midi_matrix_checkbox: Optional[QCheckBox] = None
        self.audio_matrix_checkbox: Optional[QCheckBox] = None
        self.hide_matrix_splitters_checkbox: Optional[QCheckBox] = None
        self.straight_lines_checkbox: Optional[QCheckBox] = None
        self.split_audio_midi_checkbox: Optional[QCheckBox] = None
        self.auto_layout_split_checkbox: Optional[QCheckBox] = None
        self.colored_connections_checkbox: Optional[QCheckBox] = None
        self.verbose_output_checkbox: Optional[QCheckBox] = None
        self.integrate_checkbox: Optional[QCheckBox] = None
        self._settings_modified: bool = False
        self._apply_button: Optional[QWidget] = None
        self._on_apply_enabled_changed: Optional[callable] = None

    def build_widgets(
        self,
        target_layout: QLayout,
        label_width: Optional[int] = None,
        apply_button: Optional[QWidget] = None,
    ) -> None:
        """Add all 'Other Settings' widgets into target_layout.

        If label_width is None, it will be computed automatically.
        If apply_button is provided, it will be disabled until settings are changed.
        """
        if label_width is None:
            label_width = self._compute_label_width()

        self._apply_button = apply_button
        if apply_button is not None:
            apply_button.setEnabled(False)

        for key, setting_info in SETTINGS_MAP.items():
            h_layout = QHBoxLayout()

            label = QLabel(setting_info["label"])
            label.setFixedWidth(label_width)
            h_layout.addWidget(label)
            self.slider_labels[key] = label

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(setting_info["range"][0])
            slider.setMaximum(setting_info["range"][1])
            slider.setSingleStep(1)
            h_layout.addWidget(slider)
            self.sliders[key] = slider

            value_label = QLabel()
            value_label.setFixedWidth(50)
            h_layout.addWidget(value_label)
            self.value_labels[key] = value_label

            slider.valueChanged.connect(
                lambda v, k=key: self.value_labels[k].setText(str(v))
            )
            slider.valueChanged.connect(lambda _: self._mark_settings_modified())

            target_layout.addLayout(h_layout)

            if key in SEPARATOR_AFTER:
                target_layout.addWidget(self._make_separator())

        target_layout.addWidget(self._make_separator())

        # Untangle field
        untangle_layout = QHBoxLayout()
        untangle_label = QLabel(
            "Graph Untangle configuration\n(clients in a row and cycle order)"
        )
        untangle_label.setWordWrap(True)
        untangle_layout.addWidget(untangle_label)

        untangle_field = QLineEdit()
        untangle_field.setToolTip(
            "Enter comma-separated values (e.g., 4,5,6,7,2,3)\n"
            "'0' (I/O layout) dynamically arranges clients in columns according to their connections and type"
        )
        untangle_layout.addWidget(untangle_field)
        self.text_fields[keys.GRAPH_UNTANGLE_VALUES] = untangle_field
        untangle_field.textChanged.connect(lambda _: self._mark_settings_modified())
        target_layout.addLayout(untangle_layout)

        # Checkboxes
        self.midi_matrix_checkbox = QCheckBox("Enable MIDI Matrix - EXPERIMENTAL")
        self.midi_matrix_checkbox.setToolTip(
            "May require Pipewire 1.5.81 (1.6 RC1) or later"
        )
        self.midi_matrix_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.midi_matrix_checkbox)

        self.audio_matrix_checkbox = QCheckBox("Enable Audio Matrix - EXPERIMENTAL")
        self.audio_matrix_checkbox.setToolTip(
            "May require Pipewire 1.5.81 (1.6 RC1) or later"
        )
        self.audio_matrix_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.audio_matrix_checkbox)

        self.hide_matrix_splitters_checkbox = QCheckBox("Hide splitters in matrices")
        self.hide_matrix_splitters_checkbox.setToolTip(
            "When enabled, splitters in Audio and MIDI matrices are hidden.\n"
            "(Requires application restart)"
        )
        self.hide_matrix_splitters_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.hide_matrix_splitters_checkbox)

        self.straight_lines_checkbox = QCheckBox("Use straight connection lines")
        self.straight_lines_checkbox.setToolTip(
            "Use straight lines instead of curves in Audio/MIDI tabs"
        )
        self.straight_lines_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.straight_lines_checkbox)

        self.split_audio_midi_checkbox = QCheckBox("Split Audio/MIDI clients in Graph")
        self.split_audio_midi_checkbox.setToolTip(
            "Show clients with both, Audio and MIDI ports as separate nodes in Graph"
        )
        self.split_audio_midi_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.split_audio_midi_checkbox)

        self.auto_layout_split_checkbox = QCheckBox(
            "Split nodes in Auto layout in Graph"
        )
        self.auto_layout_split_checkbox.setToolTip(
            "When ON, Auto layout automatically splits nodes with connections on both sides.\n"
            "When OFF, Auto layout preserves the current split/unsplit state of nodes."
        )
        self.auto_layout_split_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.auto_layout_split_checkbox)

        self.colored_connections_checkbox = QCheckBox("Coloured connections")
        self.colored_connections_checkbox.setToolTip(
            "Use per-client colors for connection lines\n"
            "in all tabs (Audio, MIDI, and Graph)"
        )
        self.colored_connections_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.colored_connections_checkbox)

        self.verbose_output_checkbox = QCheckBox("Verbose output")
        self.verbose_output_checkbox.setToolTip(
            "Show debug messages in terminal when running from command line"
        )
        self.verbose_output_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.verbose_output_checkbox)

        target_layout.addWidget(self._make_separator())

        self.integrate_checkbox = QCheckBox("Integrate Cable and Cables")
        self.integrate_checkbox.setToolTip(
            "Show Cable as the first tab in Cables window.\n"
            "Simplifies tray menu to single 'Open' option.\n"
            "Requires application restart."
        )
        self.integrate_checkbox.stateChanged.connect(
            lambda _: self._mark_settings_modified()
        )
        target_layout.addWidget(self.integrate_checkbox)

        target_layout.addWidget(self._make_separator())

    def load_settings(self) -> None:
        """Load all 'Other Settings' values from config into the widgets."""
        # Block all signals to prevent triggering _mark_settings_modified during load
        for slider in self.sliders.values():
            slider.blockSignals(True)
        for field in self.text_fields.values():
            field.blockSignals(True)
        self.midi_matrix_checkbox.blockSignals(True)
        self.audio_matrix_checkbox.blockSignals(True)
        self.hide_matrix_splitters_checkbox.blockSignals(True)
        self.straight_lines_checkbox.blockSignals(True)
        self.split_audio_midi_checkbox.blockSignals(True)
        self.auto_layout_split_checkbox.blockSignals(True)
        self.colored_connections_checkbox.blockSignals(True)
        self.verbose_output_checkbox.blockSignals(True)
        self.integrate_checkbox.blockSignals(True)

        try:
            for key, setting_info in SETTINGS_MAP.items():
                default_value = getattr(app_config, setting_info["default_key"])
                current_value = self.config_manager.get_int_setting(key, default_value)
                self.sliders[key].setValue(current_value)
                self.value_labels[key].setText(str(current_value))

            default_untangle = app_config.DEFAULT_UNTANGLE_VALUES
            config = self.config_manager._get_config_parser()
            if "DEFAULT" in config and keys.GRAPH_UNTANGLE_VALUES in config["DEFAULT"]:
                untangle_str = config["DEFAULT"][keys.GRAPH_UNTANGLE_VALUES]
            else:
                untangle_str = ",".join(map(str, default_untangle))
            self.text_fields[keys.GRAPH_UNTANGLE_VALUES].setText(untangle_str)

            self.midi_matrix_checkbox.setChecked(
                self.config_manager.get_bool(keys.ENABLE_MIDI_MATRIX, False)
            )
            self.audio_matrix_checkbox.setChecked(
                self.config_manager.get_bool(keys.ENABLE_AUDIO_MATRIX, False)
            )
            self.hide_matrix_splitters_checkbox.setChecked(
                self.config_manager.get_bool(keys.HIDE_MATRIX_SPLITTERS, False)
            )
            self.straight_lines_checkbox.setChecked(
                self.config_manager.get_bool(keys.USE_STRAIGHT_LINES, False)
            )
            self.split_audio_midi_checkbox.setChecked(
                self.config_manager.get_bool(keys.GRAPH_SPLIT_AUDIO_MIDI_CLIENTS, False)
            )
            self.auto_layout_split_checkbox.setChecked(
                self.config_manager.get_bool(keys.GRAPH_AUTO_LAYOUT_SPLIT, False)
            )
            self.colored_connections_checkbox.setChecked(
                self.config_manager.get_bool(keys.GRAPH_COLORED_CONNECTIONS, False)
            )
            self.verbose_output_checkbox.setChecked(
                self.config_manager.get_bool(keys.VERBOSE_OUTPUT, False)
            )
            self.integrate_checkbox.setChecked(
                self.config_manager.get_bool(keys.INTEGRATE_CABLE_AND_CABLES, False)
            )
        finally:
            # Unblock all signals
            for slider in self.sliders.values():
                slider.blockSignals(False)
            for field in self.text_fields.values():
                field.blockSignals(False)
            self.midi_matrix_checkbox.blockSignals(False)
            self.audio_matrix_checkbox.blockSignals(False)
            self.hide_matrix_splitters_checkbox.blockSignals(False)
            self.straight_lines_checkbox.blockSignals(False)
            self.split_audio_midi_checkbox.blockSignals(False)
            self.auto_layout_split_checkbox.blockSignals(False)
            self.colored_connections_checkbox.blockSignals(False)
            self.verbose_output_checkbox.blockSignals(False)
            self.integrate_checkbox.blockSignals(False)

    def save_settings(self) -> None:
        """Save all 'Other Settings' values from widgets to config."""
        for key in SETTINGS_MAP:
            self.config_manager.set_int_setting(key, self.sliders[key].value())

        untangle_str = self.text_fields[keys.GRAPH_UNTANGLE_VALUES].text().strip()
        self.config_manager.set_str_setting(keys.GRAPH_UNTANGLE_VALUES, untangle_str)

        self.config_manager.set_bool(
            keys.ENABLE_MIDI_MATRIX, self.midi_matrix_checkbox.isChecked()
        )
        self.config_manager.set_bool(
            keys.ENABLE_AUDIO_MATRIX, self.audio_matrix_checkbox.isChecked()
        )
        self.config_manager.set_bool(
            keys.HIDE_MATRIX_SPLITTERS, self.hide_matrix_splitters_checkbox.isChecked()
        )
        self.config_manager.set_bool(
            keys.USE_STRAIGHT_LINES, self.straight_lines_checkbox.isChecked()
        )
        self.config_manager.set_bool(
            keys.GRAPH_SPLIT_AUDIO_MIDI_CLIENTS,
            self.split_audio_midi_checkbox.isChecked(),
        )
        self.config_manager.set_bool(
            keys.GRAPH_AUTO_LAYOUT_SPLIT, self.auto_layout_split_checkbox.isChecked()
        )
        self.config_manager.set_bool(
            keys.GRAPH_COLORED_CONNECTIONS,
            self.colored_connections_checkbox.isChecked(),
        )
        self.config_manager.set_bool(
            keys.VERBOSE_OUTPUT, self.verbose_output_checkbox.isChecked()
        )
        self.config_manager.set_bool(
            keys.INTEGRATE_CABLE_AND_CABLES, self.integrate_checkbox.isChecked()
        )

    def reset_to_defaults(self, parent_widget: QWidget) -> bool:
        """Delete the config directory after user confirmation. Returns True if reset was performed."""
        config_dir = os.path.expanduser("~/.config/cable")

        reply = QMessageBox.question(
            parent_widget,
            "Confirm Reset",
            f"This will delete the entire Cable configuration directory:\n{config_dir}\n\n"
            "All settings will be reset to defaults. Application restart required.\n\nContinue?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if reply != QMessageBox.StandardButton.Ok:
            return False

        if os.path.exists(config_dir):
            try:
                shutil.rmtree(config_dir)
                logger.info(f"Deleted configuration directory: {config_dir}")
                QMessageBox.information(
                    parent_widget,
                    "Reset Complete",
                    "Configuration has been reset. Please restart the application.",
                )
                return True
            except Exception as e:
                logger.error(f"Error: Could not delete configuration directory: {e}")
                QMessageBox.critical(
                    parent_widget,
                    "Error",
                    f"Failed to delete configuration directory:\n{e}",
                )
        return False

    def show_restart_warning(self, parent_widget: QWidget) -> None:
        """Show a modal restart-required warning."""
        msg_box = QMessageBox(parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("Restart Required")
        msg_box.setText(
            "Application restart might be required for new settings to take effect."
        )
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setModal(True)
        msg_box.exec()

    def _compute_label_width(self) -> int:
        max_width = 0
        all_labels = [info["label"] for info in SETTINGS_MAP.values()] + [
            "Graph Untangle configuration\n(clients in a row and cycle order)",
            "Enable MIDI Matrix - EXPERIMENTAL",
        ]
        for text in all_labels:
            label = QLabel(text)
            label.adjustSize()
            if label.width() > max_width:
                max_width = label.width()
            label.deleteLater()
        return max_width + 60

    def _mark_settings_modified(self) -> None:
        """Mark settings as modified and enable the apply button if it exists."""
        self._settings_modified = True
        if self._apply_button is not None:
            self._apply_button.setEnabled(True)

    def _reset_modified_flag(self) -> None:
        """Reset the modified flag and disable the apply button."""
        self._settings_modified = False
        if self._apply_button is not None:
            self._apply_button.setEnabled(False)

    @staticmethod
    def _make_separator() -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator
