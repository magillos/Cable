from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QDialogButtonBox, QMessageBox, QFrame, QLineEdit
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
            "CONNECTION_VIEW_INITIAL_WIDTH": {
                "label": "Connection area width\n"
                "in Audio and MIDI tab",
                "range": (100, 300),
                "default_key": "CONNECTION_VIEW_INITIAL_WIDTH"
            },
            "PWTOP_FONT_SIZE_PT": {
                "label": "pw-top font size",
                "range": (8, 20), # Reasonable range for font size
                "default_key": "PWTOP_FONT_SIZE_PT"
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
        for setting_info in self.settings_map.values():
            label = QLabel(setting_info["label"])
            # Ensure proper size calculation
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
            if key in ["MAIN_WINDOW_INITIAL_HEIGHT", "CONN_MANAGER_INITIAL_HEIGHT", "CONNECTION_VIEW_INITIAL_WIDTH"]:
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
        untangle_field.setToolTip("Enter comma-separated values (e.g., 4,5,6,7,2,3)")
        untangle_layout.addWidget(untangle_field)
        self.text_fields["GRAPH_UNTANGLE_VALUES"] = untangle_field

        main_layout.addLayout(untangle_layout)

        # Add separator after untangle values
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults |
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.clicked.connect(self._handle_button_click)
        main_layout.addWidget(button_box)

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
        # The warning is now shown by _handle_button_click for Apply/Default

    def _reset_to_defaults(self):
        keys_to_clear = list(self.settings_map.keys())
        keys_to_clear.append("GRAPH_UNTANGLE_VALUES")  # Add the untangle values key
        self.config_manager.clear_settings(keys_to_clear)

        # Also reset "don't show again" confirmation dialog settings to show dialogs by default
        # These settings are stored in the cables config, not cable_core config
        try:
            from cables.config.config_manager import ConfigManager as CablesConfigManager
            cables_config = CablesConfigManager()
            # Reset to show dialogs by default (True for show_hide and show_unload, False for preset_skip)
            cables_config.set_bool('show_hide_node_confirmation', True)  # True = show confirmation
            cables_config.set_bool('show_unload_all_sinks_confirmation', True)  # True = show confirmation
            cables_config.set_bool('default_preset_skip_confirmation', False)  # False = show confirmation
            print("Reset confirmation dialog preferences to show dialogs by default")
        except Exception as e:
            print(f"Warning: Could not reset confirmation dialog preferences: {e}")

        self._load_settings_from_config() # Reload from app_config defaults

    def _handle_button_click(self, button):
        if self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.ApplyRole:
            self._save_settings_to_config()
            self._show_restart_warning() # Show warning on Apply
        elif self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.AcceptRole: # OK button
            self._save_settings_to_config()  # Save settings on OK
            self.accept()  # Close dialog with accept
        elif self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.ResetRole: # RestoreDefaults button
            self._reset_to_defaults()
            self._show_restart_warning() # Show warning on Default
        elif self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.RejectRole: # Cancel button
            self.reject()
