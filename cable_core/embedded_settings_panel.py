"""
Embedded Settings Panel - Inline settings display for Cable integrated mode.
Combines the Settings menu content and Other Settings dialog content into a single panel.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QFrame, QLineEdit, QCheckBox, QScrollArea, QGroupBox, QSizePolicy,
    QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from cable_core import app_config


class EmbeddedSettingsPanel(QWidget):
    """Panel that displays settings inline when Cable is embedded in Cables."""
    
    settings_changed = pyqtSignal()
    
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.config_manager = app.config_manager
        
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
        self.text_fields = {}
        
        self._init_ui()
        self._load_settings()
    
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 5, 0)  # Match left column: no top margin, small right margin
        main_layout.setSpacing(8)
        
        # Create scroll area for all content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)
        
        # Create bold font for group titles (matching Cable's Quantum label style)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        
        # --- Basic Settings Group ---
        basic_group = QGroupBox("Settings")
        basic_group.setFont(title_font)
        basic_layout = QVBoxLayout(basic_group)
        basic_layout.setSpacing(6)
        
        # Tray icon toggle
        self.tray_checkbox = QCheckBox("Enable tray icon")
        self.tray_checkbox.stateChanged.connect(self._on_tray_changed)
        basic_layout.addWidget(self.tray_checkbox)
        
        # Autostart toggle
        self.autostart_checkbox = QCheckBox("Autostart")
        self.autostart_checkbox.stateChanged.connect(self._on_autostart_changed)
        basic_layout.addWidget(self.autostart_checkbox)
        
        # Save quantum/sample rate
        self.remember_checkbox = QCheckBox("Save quantum and sample rate")
        self.remember_checkbox.stateChanged.connect(self._on_remember_changed)
        basic_layout.addWidget(self.remember_checkbox)
        
        # Restore only when auto-started
        self.restore_minimized_checkbox = QCheckBox("Restore above only when auto-started")
        self.restore_minimized_checkbox.stateChanged.connect(self._on_restore_minimized_changed)
        basic_layout.addWidget(self.restore_minimized_checkbox)
        
        # Check for updates at start
        self.check_updates_checkbox = QCheckBox("Check for updates at start")
        self.check_updates_checkbox.stateChanged.connect(self._on_check_updates_changed)
        basic_layout.addWidget(self.check_updates_checkbox)
        
        scroll_layout.addWidget(basic_group)
        
        # --- Other Settings Group ---
        other_group = QGroupBox("Other Settings")
        other_group.setFont(title_font)
        other_layout = QVBoxLayout(other_group)
        other_layout.setSpacing(6)
        
        # Calculate max label width
        max_label_width = 180
        
        # Add sliders for numeric settings
        for key, setting_info in self.settings_map.items():
            h_layout = QHBoxLayout()
            h_layout.setSpacing(8)
            
            label = QLabel(setting_info["label"])
            label.setMinimumWidth(max_label_width)
            h_layout.addWidget(label)
            
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(setting_info["range"][0])
            slider.setMaximum(setting_info["range"][1])
            slider.setSingleStep(1)
            slider.valueChanged.connect(self._create_slider_handler(key))
            h_layout.addWidget(slider)
            self.sliders[key] = slider
            
            value_label = QLabel()
            value_label.setFixedWidth(40)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h_layout.addWidget(value_label)
            self.value_labels[key] = value_label
            
            other_layout.addLayout(h_layout)
            
            # Add separators after certain settings
            if key in ["MAIN_WINDOW_INITIAL_HEIGHT", "CONN_MANAGER_INITIAL_HEIGHT", "PWTOP_FONT_SIZE_PT"]:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFrameShadow(QFrame.Shadow.Sunken)
                other_layout.addWidget(separator)
        
        # Add separator after sliders
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        other_layout.addWidget(separator)
        
        # Untangle configuration
        untangle_layout = QHBoxLayout()
        untangle_label = QLabel("Graph Untangle config")
        untangle_label.setMinimumWidth(max_label_width)
        untangle_layout.addWidget(untangle_label)
        
        self.untangle_field = QLineEdit()
        self.untangle_field.setToolTip("Comma-separated values (e.g., 4,5,6,7,2,3)\n'0' for dynamic arrangement")
        untangle_layout.addWidget(self.untangle_field)
        self.text_fields["GRAPH_UNTANGLE_VALUES"] = self.untangle_field
        other_layout.addLayout(untangle_layout)
        
        # MIDI Matrix checkbox
        self.midi_matrix_checkbox = QCheckBox("Enable MIDI Matrix (experimental)")
        self.midi_matrix_checkbox.setToolTip("May require Pipewire 1.5.81 (1.6 RC1) or later")
        other_layout.addWidget(self.midi_matrix_checkbox)
        
        # Straight lines checkbox
        self.straight_lines_checkbox = QCheckBox("Use straight connection lines")
        self.straight_lines_checkbox.setToolTip("Use straight lines instead of curves")
        other_layout.addWidget(self.straight_lines_checkbox)
        
        # Split audio/midi checkbox
        self.split_audio_midi_checkbox = QCheckBox("Split Audio/MIDI clients in Graph")
        self.split_audio_midi_checkbox.setToolTip("Show clients with both Audio and MIDI ports as separate nodes")
        other_layout.addWidget(self.split_audio_midi_checkbox)
        
        # Separator before integrate option
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        other_layout.addWidget(separator)
        
        # Integrate Cable and Cables checkbox
        self.integrate_checkbox = QCheckBox("Integrate Cable and Cables")
        self.integrate_checkbox.setToolTip("Show Cable as the first tab in Cables window.\nRequires application restart.")
        other_layout.addWidget(self.integrate_checkbox)
        
        # Separator before buttons
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        other_layout.addWidget(separator)
        
        # Action buttons for Other Settings (matching OtherSettingsDialog, without OK)
        self.other_button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults |
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel
        )
        self.other_button_box.clicked.connect(self._handle_other_button_click)
        other_layout.addWidget(self.other_button_box)
        
        scroll_layout.addWidget(other_group)
        
        # --- Version and Links ---
        version_group = QGroupBox("About")
        version_group.setFont(title_font)
        version_layout = QVBoxLayout(version_group)
        version_layout.setSpacing(6)
        
        # Version label
        self.version_label = QLabel()
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setTextFormat(Qt.TextFormat.RichText)
        self.version_label.setOpenExternalLinks(True)
        version_layout.addWidget(self.version_label)
        
        # Check for updates button
        check_updates_btn = QPushButton("Check for Updates")
        check_updates_btn.clicked.connect(self._check_for_updates)
        version_layout.addWidget(check_updates_btn)
        
        # Download link
        download_btn = QPushButton("Download from GitHub")
        download_btn.clicked.connect(self.app.update_manager.open_download_page)
        version_layout.addWidget(download_btn)
        
        # Buy me a coffee link
        coffee_label = QLabel()
        coffee_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        coffee_label.setText('<a href="https://buymeacoffee.com/magillos" style="color: #FF813F; text-decoration: none; font-weight: bold;">☕ Buy me a coffee</a>')
        coffee_label.setOpenExternalLinks(True)
        coffee_label.setTextFormat(Qt.TextFormat.RichText)
        version_layout.addWidget(coffee_label)
        
        scroll_layout.addWidget(version_group)
        
        # Add stretch at bottom
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # Set minimum width
        self.setMinimumWidth(320)
    
    def _create_slider_handler(self, key):
        def handler(value):
            self.value_labels[key].setText(str(value))
        return handler
    
    def _load_settings(self):
        """Load all settings from config."""
        # Basic settings
        self.tray_checkbox.blockSignals(True)
        self.tray_checkbox.setChecked(self.app.tray_enabled)
        self.tray_checkbox.blockSignals(False)
        
        self.autostart_checkbox.blockSignals(True)
        self.autostart_checkbox.setChecked(self.app.autostart_enabled)
        self.autostart_checkbox.blockSignals(False)
        
        self.remember_checkbox.blockSignals(True)
        self.remember_checkbox.setChecked(self.app.remember_settings)
        self.remember_checkbox.blockSignals(False)
        
        self.restore_minimized_checkbox.blockSignals(True)
        self.restore_minimized_checkbox.setChecked(self.app.restore_only_minimized)
        self.restore_minimized_checkbox.setEnabled(self.app.remember_settings)
        self.restore_minimized_checkbox.blockSignals(False)
        
        self.check_updates_checkbox.blockSignals(True)
        self.check_updates_checkbox.setChecked(self.app.check_updates_at_start)
        self.check_updates_checkbox.blockSignals(False)
        
        # Other settings - sliders
        for key, setting_info in self.settings_map.items():
            default_value = getattr(app_config, setting_info["default_key"])
            current_value = self.config_manager.get_int_setting(key, default_value)
            self.sliders[key].blockSignals(True)
            self.sliders[key].setValue(current_value)
            self.sliders[key].blockSignals(False)
            self.value_labels[key].setText(str(current_value))
        
        # Untangle values
        default_untangle = app_config.DEFAULT_UNTANGLE_VALUES
        config = self.config_manager._get_config_parser()
        if 'DEFAULT' in config and 'GRAPH_UNTANGLE_VALUES' in config['DEFAULT']:
            untangle_str = config['DEFAULT']['GRAPH_UNTANGLE_VALUES']
        else:
            untangle_str = ','.join(map(str, default_untangle))
        self.untangle_field.setText(untangle_str)
        
        # Checkboxes
        self.midi_matrix_checkbox.blockSignals(True)
        self.midi_matrix_checkbox.setChecked(self.config_manager.get_bool('enable_midi_matrix', False))
        self.midi_matrix_checkbox.blockSignals(False)
        
        self.straight_lines_checkbox.blockSignals(True)
        self.straight_lines_checkbox.setChecked(self.config_manager.get_bool('use_straight_lines', False))
        self.straight_lines_checkbox.blockSignals(False)
        
        self.split_audio_midi_checkbox.blockSignals(True)
        self.split_audio_midi_checkbox.setChecked(self.config_manager.get_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', False))
        self.split_audio_midi_checkbox.blockSignals(False)
        
        self.integrate_checkbox.blockSignals(True)
        self.integrate_checkbox.setChecked(self.config_manager.get_bool('integrate_cable_and_cables', False))
        self.integrate_checkbox.blockSignals(False)
        
        # Version label
        curr_version = app_config.APP_VERSION
        if self.app.update_manager.update_available:
            latest = self.app.update_manager.latest_version
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: orange; text-decoration: none;">Version: {curr_version} (Update: {latest})</a>')
        else:
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">Version: {curr_version}</a>')
    
    def refresh_settings(self):
        """Refresh settings from current app state."""
        self._load_settings()
    
    def _on_tray_changed(self, state):
        self.app.tray_toggle_checkbox.setChecked(state == Qt.CheckState.Checked.value)
    
    def _on_autostart_changed(self, state):
        self.app.tray_manager.toggle_autostart(state == Qt.CheckState.Checked.value)
        # Update tray checkbox enabled state
        self.tray_checkbox.setEnabled(not self.app.autostart_enabled)
    
    def _on_remember_changed(self, state):
        self.app.remember_settings_checkbox.setChecked(state == Qt.CheckState.Checked.value)
        self.restore_minimized_checkbox.setEnabled(state == Qt.CheckState.Checked.value)
    
    def _on_restore_minimized_changed(self, state):
        self.app.restore_only_minimized_checkbox.setChecked(state == Qt.CheckState.Checked.value)
    
    def _on_check_updates_changed(self, state):
        self.app.config_manager.toggle_startup_check(state == Qt.CheckState.Checked.value)
    
    def _handle_other_button_click(self, button):
        """Handle button clicks from the Other Settings button box."""
        role = self.other_button_box.buttonRole(button)
        
        if role == QDialogButtonBox.ButtonRole.ApplyRole:
            self._apply_other_settings()
        elif role == QDialogButtonBox.ButtonRole.ResetRole:  # RestoreDefaults
            self._reset_to_defaults()
        elif role == QDialogButtonBox.ButtonRole.RejectRole:  # Cancel
            self._cancel_other_settings()
    
    def _check_for_updates(self):
        """Check for updates and refresh version label."""
        self.app.update_manager.check_for_updates(manual_check=True)
        self._update_version_label()
    
    def _update_version_label(self):
        """Update the version label with current update status."""
        curr_version = app_config.APP_VERSION
        if self.app.update_manager.update_available:
            latest = self.app.update_manager.latest_version
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: orange; text-decoration: none;">Version: {curr_version} (Update: {latest})</a>')
        else:
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">Version: {curr_version}</a>')
    
    def _apply_other_settings(self):
        """Apply other settings and show restart warning."""
        # Save slider values
        for key in self.settings_map.keys():
            self.config_manager.set_int_setting(key, self.sliders[key].value())
        
        # Save untangle values
        untangle_str = self.untangle_field.text().strip()
        self.config_manager.set_str_setting("GRAPH_UNTANGLE_VALUES", untangle_str)
        
        # Save checkbox values
        self.config_manager.set_bool('enable_midi_matrix', self.midi_matrix_checkbox.isChecked())
        self.config_manager.set_bool('use_straight_lines', self.straight_lines_checkbox.isChecked())
        self.config_manager.set_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', self.split_audio_midi_checkbox.isChecked())
        self.config_manager.set_bool('integrate_cable_and_cables', self.integrate_checkbox.isChecked())
        
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(
            self, "Restart Required",
            "Application restart might be required for new settings to take effect."
        )
    
    def _reset_to_defaults(self):
        """Reset all settings to defaults by deleting config directory."""
        import os
        import shutil
        from PyQt6.QtWidgets import QMessageBox
        
        config_dir = os.path.expanduser("~/.config/cable")
        
        reply = QMessageBox.question(
            self, "Confirm Reset",
            f"This will delete the entire Cable configuration directory:\n{config_dir}\n\n"
            "All settings will be reset to defaults. Application restart required.\n\nContinue?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        
        if reply != QMessageBox.StandardButton.Ok:
            return
        
        if os.path.exists(config_dir):
            try:
                shutil.rmtree(config_dir)
                QMessageBox.information(
                    self, "Reset Complete",
                    "Configuration has been reset. Please restart the application."
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Error",
                    f"Failed to delete configuration directory:\n{e}"
                )
    
    def _cancel_other_settings(self):
        """Discard changes and reload settings from config."""
        self._load_settings()
