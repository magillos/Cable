import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QDialogButtonBox, QMessageBox, QFrame, QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt

from cable_core import app_config
from cable_core.config import ConfigManager

class OtherSettingsDialog(QDialog):
    def __init__(self, parent=None, config_manager: ConfigManager = None):
        super().__init__(parent)
        self.setWindowTitle("Other Settings")
        self.config_manager = config_manager or ConfigManager()

        self.settings_map = {
            "MAIN_WINDOW_INITIAL_WIDTH": {
                "label": "Cable window width",
                "range": (300, 1500),
                "default_key": "MAIN_WINDOW_INITIAL_WIDTH"
            },
            "MAIN_WINDOW_INITIAL_HEIGHT": {
                "label": "Cable window height",
                "range": (600, 1500),
                "default_key": "MAIN_WINDOW_INITIAL_HEIGHT"
            },
            "CONN_MANAGER_INITIAL_WIDTH": {
                "label": "Cables window width",
                "range": (800, 2500),
                "default_key": "CONN_MANAGER_INITIAL_WIDTH"
            },
            "CONN_MANAGER_INITIAL_HEIGHT": {
                "label": "Cables window height",
                "range": (600, 2000),
                "default_key": "CONN_MANAGER_INITIAL_HEIGHT"
            },
            "PWTOP_FONT_SIZE_PT": {
                "label": "pw-top font size",
                "range": (8, 20),
                "default_key": "PWTOP_FONT_SIZE_PT"
            },
            "CONNECTION_LINE_THICKNESS": {
                "label": "Cables thickness",
                "range": (1, 6),
                "default_key": "CONNECTION_LINE_THICKNESS"
            },
        }

        self.sliders = {}
        self.value_labels = {}
        self.text_fields = {}  # New dictionary to store text fields

        self._init_ui()
        self._load_settings_from_config()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # Calculate maximum label width
        max_label_width = 0
        all_labels = [info["label"] for info in self.settings_map.values()] + [
            "Graph Untangle configuration\n(clients in a row and cycle order)",
            "Enable MIDI Matrix - EXPERIMENTAL"
        ]

        for label_text in all_labels:
            label = QLabel(label_text)
            label.adjustSize()
            if label.width() > max_label_width:
                max_label_width = label.width()
            label.deleteLater()

        # Add some padding
        max_label_width += 60

        for key, setting_info in self.settings_map.items():
            h_layout = QHBoxLayout()
            
            label = QLabel(setting_info["label"])
            label.setFixedWidth(max_label_width)
            h_layout.addWidget(label)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(setting_info["range"][0])
            slider.setMaximum(setting_info["range"][1])
            slider.setSingleStep(1)
            slider.valueChanged.connect(self._update_value_label(key))
            h_layout.addWidget(slider)
            self.sliders[key] = slider

            value_label = QLabel()
            value_label.setFixedWidth(50) # Adjust as needed
            h_layout.addWidget(value_label)
            self.value_labels[key] = value_label

            main_layout.addLayout(h_layout)

            # Add line separators after specific settings
            if key in ["MAIN_WINDOW_INITIAL_HEIGHT", "CONN_MANAGER_INITIAL_HEIGHT", "PWTOP_FONT_SIZE_PT"]:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFrameShadow(QFrame.Shadow.Sunken)
                main_layout.addWidget(separator)

        # Add separator after the last slider
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)

        # Add untangle values text field
        untangle_layout = QHBoxLayout()
        untangle_label = QLabel("Graph Untangle configuration\n(clients in a row and cycle order)")
        untangle_label.setFixedWidth(max_label_width)
        untangle_layout.addWidget(untangle_label)

        untangle_field = QLineEdit()
        untangle_field.setToolTip("Enter comma-separated values (e.g., 4,5,6,7,2,3)\n'0' dynamically arranges clients in columns according to their connections and type")
        untangle_layout.addWidget(untangle_field)
        self.text_fields["GRAPH_UNTANGLE_VALUES"] = untangle_field

        main_layout.addLayout(untangle_layout)

        # Add MIDI Matrix checkbox
        midi_matrix_layout = QHBoxLayout()
        midi_matrix_label = QLabel("Enable MIDI Matrix - EXPERIMENTAL")
        midi_matrix_label.setFixedWidth(max_label_width)
        midi_matrix_layout.addWidget(midi_matrix_label)

        self.midi_matrix_checkbox = QCheckBox()
        self.midi_matrix_checkbox.setToolTip("May require Pipewire 1.5.81 (1.6 RC1) or later")
        midi_matrix_layout.addStretch(1)
        midi_matrix_layout.addWidget(self.midi_matrix_checkbox)
        main_layout.addLayout(midi_matrix_layout)

        # Add straight lines checkbox
        straight_lines_layout = QHBoxLayout()
        straight_lines_label = QLabel("Use straight connection lines")
        straight_lines_label.setFixedWidth(max_label_width)
        straight_lines_layout.addWidget(straight_lines_label)

        self.straight_lines_checkbox = QCheckBox()
        self.straight_lines_checkbox.setToolTip("Use straight lines instead of curves in Audio/MIDI tabs")
        straight_lines_layout.addStretch(1)
        straight_lines_layout.addWidget(self.straight_lines_checkbox)
        main_layout.addLayout(straight_lines_layout)

        # Add split audio/midi checkbox
        self.split_audio_midi_layout = QHBoxLayout()
        self.split_audio_midi_label = QLabel("Split Audio/MIDI clients in Graph")
        self.split_audio_midi_label.setFixedWidth(max_label_width)
        self.split_audio_midi_layout.addWidget(self.split_audio_midi_label)

        self.split_audio_midi_checkbox = QCheckBox()
        self.split_audio_midi_checkbox.setToolTip("Show clients with both, Audio and MIDI ports as separate nodes in Graph")
        self.split_audio_midi_layout.addStretch(1)
        self.split_audio_midi_layout.addWidget(self.split_audio_midi_checkbox)
        main_layout.addLayout(self.split_audio_midi_layout)

        # Add separator before integrate option
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)

        # Add integrate Cable and Cables checkbox
        integrate_layout = QHBoxLayout()
        integrate_label = QLabel("Integrate Cable and Cables")
        integrate_label.setFixedWidth(max_label_width)
        integrate_layout.addWidget(integrate_label)

        self.integrate_checkbox = QCheckBox()
        self.integrate_checkbox.setToolTip("Show Cable as the first tab in Cables window.\nSimplifies tray menu to single 'Open' option.\nRequires application restart.")
        integrate_layout.addStretch(1)
        integrate_layout.addWidget(self.integrate_checkbox)
        main_layout.addLayout(integrate_layout)

        # Add separator after integrate option
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults |
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.clicked.connect(self._handle_button_click)
        main_layout.addWidget(button_box)

        # Add version label at the very bottom
        self.version_label = QLabel()
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setTextFormat(Qt.TextFormat.RichText)
        self.version_label.setOpenExternalLinks(True)
        
        # Get version info from parent if available
        curr_version = app_config.APP_VERSION
        update_available = False
        latest_version = None
        
        if self.parent() and hasattr(self.parent(), 'update_manager'):
            update_manager = self.parent().update_manager
            update_available = update_manager.update_available
            latest_version = update_manager.latest_version
            
        if update_available:
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: orange; text-decoration: none;">Version: {curr_version} (Update available: {latest_version})</a>')
        else:
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">Version: {curr_version}</a>')
            
        main_layout.addWidget(self.version_label)

    def _update_value_label(self, key):
        def update():
            self.value_labels[key].setText(str(self.sliders[key].value()))
        return update

    def _load_settings_from_config(self):
        for key, setting_info in self.settings_map.items():
            default_value = getattr(app_config, setting_info["default_key"])
            current_value = self.config_manager.get_int_setting(key, default_value)
            self.sliders[key].setValue(current_value)
            self.value_labels[key].setText(str(current_value))
        
        # Load untangle values
        default_untangle_values = app_config.DEFAULT_UNTANGLE_VALUES
        config = self.config_manager._get_config_parser()
        untangle_values_str = ""
        
        if 'DEFAULT' in config and 'GRAPH_UNTANGLE_VALUES' in config['DEFAULT']:
            untangle_values_str = config['DEFAULT']['GRAPH_UNTANGLE_VALUES']
        else:
            # Convert default list to comma-separated string
            untangle_values_str = ','.join(map(str, default_untangle_values))
        
        self.text_fields["GRAPH_UNTANGLE_VALUES"].setText(untangle_values_str)

        # Load MIDI Matrix setting
        enable_midi_matrix = self.config_manager.get_bool('enable_midi_matrix', False)
        self.midi_matrix_checkbox.setChecked(enable_midi_matrix)

        # Load straight lines setting
        straight_lines = self.config_manager.get_bool('use_straight_lines', False)
        self.straight_lines_checkbox.setChecked(straight_lines)

        # Load split audio/midi setting
        split_audio_midi = self.config_manager.get_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', False)
        self.split_audio_midi_checkbox.setChecked(split_audio_midi)

        # Load integrate Cable and Cables setting
        integrate = self.config_manager.get_bool('integrate_cable_and_cables', False)
        self.integrate_checkbox.setChecked(integrate)

    def _show_restart_warning(self):
        msg_box = QMessageBox(self) # Re-add parent
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("Restart Required")
        msg_box.setText("Application restart might be required for new settings to take effect.")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok) # Bring back OK button
        msg_box.setModal(True) # Make it modal again
        msg_box.exec() # Use exec() to show and wait for user interaction

    def _save_settings_to_config(self):
        for key in self.settings_map.keys():
            self.config_manager.set_int_setting(key, self.sliders[key].value())
        
        # Save untangle values
        untangle_values_str = self.text_fields["GRAPH_UNTANGLE_VALUES"].text().strip()
        self.config_manager.set_str_setting("GRAPH_UNTANGLE_VALUES", untangle_values_str)

        # Save MIDI Matrix setting
        self.config_manager.set_bool('enable_midi_matrix', self.midi_matrix_checkbox.isChecked())

        # Save straight lines setting
        self.config_manager.set_bool('use_straight_lines', self.straight_lines_checkbox.isChecked())

        # Save split audio/midi setting
        self.config_manager.set_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', self.split_audio_midi_checkbox.isChecked())

        # Save integrate Cable and Cables setting
        self.config_manager.set_bool('integrate_cable_and_cables', self.integrate_checkbox.isChecked())

    def _reset_to_defaults(self):
        import shutil
        config_dir = os.path.expanduser("~/.config/cable")
        
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            f"This will delete the entire Cable configuration directory:\n{config_dir}\n\nAll settings will be reset to defaults. Application restart required.\n\nContinue?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        
        if reply != QMessageBox.StandardButton.Ok:
            return
        
        if os.path.exists(config_dir):
            try:
                shutil.rmtree(config_dir)
                print(f"Deleted configuration directory: {config_dir}")
                QMessageBox.information(
                    self,
                    "Reset Complete",
                    "Configuration has been reset. Please restart the application."
                )
                self.accept()  # Close the dialog
            except Exception as e:
                print(f"Error: Could not delete configuration directory: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to delete configuration directory:\n{e}"
                )
                return

    def _handle_button_click(self, button):
        if self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.ApplyRole:
            self._save_settings_to_config()
            self._show_restart_warning()
        elif self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.ResetRole:
            self._reset_to_defaults()
        elif self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.RejectRole:
            self.reject()
