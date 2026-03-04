"""
Embedded Settings Panel - Inline settings display for Cable integrated mode.
Combines the Settings menu content and Other Settings dialog content into a single panel.
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QFrame, QCheckBox, QScrollArea, QGroupBox,
    QDialogButtonBox, QAbstractButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from cable_core import app_config
from cable_core.settings_builder import SettingsWidgetBuilder


class EmbeddedSettingsPanel(QWidget):
    """Panel that displays settings inline when Cable is embedded in Cables."""
    
    settings_changed = pyqtSignal()
    
    def __init__(self, app: QWidget, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.app = app
        self.config_manager = app.config_manager
        
        self.builder = SettingsWidgetBuilder(self.config_manager)
        
        self._init_ui()
        self._load_settings()
    
    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 5, 0)
        main_layout.setSpacing(8)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)
        
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        
        # --- Basic Settings Group ---
        basic_group = QGroupBox("Settings")
        basic_group.setFont(title_font)
        basic_layout = QVBoxLayout(basic_group)
        basic_layout.setSpacing(6)
        
        self.tray_checkbox = QCheckBox("Enable tray icon")
        self.tray_checkbox.stateChanged.connect(self._on_tray_changed)
        basic_layout.addWidget(self.tray_checkbox)
        
        self.autostart_checkbox = QCheckBox("Autostart")
        self.autostart_checkbox.stateChanged.connect(self._on_autostart_changed)
        basic_layout.addWidget(self.autostart_checkbox)
        
        self.remember_checkbox = QCheckBox("Save quantum and sample rate")
        self.remember_checkbox.stateChanged.connect(self._on_remember_changed)
        basic_layout.addWidget(self.remember_checkbox)
        
        self.restore_minimized_checkbox = QCheckBox("Restore above only when auto-started")
        self.restore_minimized_checkbox.stateChanged.connect(self._on_restore_minimized_changed)
        basic_layout.addWidget(self.restore_minimized_checkbox)
        
        self.check_updates_checkbox = QCheckBox("Check for updates at start")
        self.check_updates_checkbox.stateChanged.connect(self._on_check_updates_changed)
        basic_layout.addWidget(self.check_updates_checkbox)
        
        scroll_layout.addWidget(basic_group)
        
        # --- Other Settings Group ---
        other_group = QGroupBox("Other Settings")
        other_group.setFont(title_font)
        other_layout = QVBoxLayout(other_group)
        other_layout.setSpacing(6)
        
        self.builder.build_widgets(other_layout, label_width=180)
        
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
        
        self.version_label = QLabel()
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setTextFormat(Qt.TextFormat.RichText)
        self.version_label.setOpenExternalLinks(True)
        version_layout.addWidget(self.version_label)
        
        check_updates_btn = QPushButton("Check for Updates")
        check_updates_btn.clicked.connect(self._check_for_updates)
        version_layout.addWidget(check_updates_btn)
        
        download_btn = QPushButton("Download from GitHub")
        download_btn.clicked.connect(self.app.update_manager.open_download_page)
        version_layout.addWidget(download_btn)
        
        coffee_label = QLabel()
        coffee_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        coffee_label.setText('<a href="https://buymeacoffee.com/magillos" style="color: #FF813F; text-decoration: none; font-weight: bold;">☕ Buy me a coffee</a>')
        coffee_label.setOpenExternalLinks(True)
        coffee_label.setTextFormat(Qt.TextFormat.RichText)
        version_layout.addWidget(coffee_label)
        
        scroll_layout.addWidget(version_group)
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        self.setMinimumWidth(320)
    
    def _load_settings(self) -> None:
        """Load all settings from config."""
        self.tray_checkbox.blockSignals(True)
        self.tray_checkbox.setChecked(self.app.tray_enabled)
        self.tray_checkbox.setEnabled(not self.app.autostart_enabled)
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
        
        self.builder.load_settings()
        
        self._update_version_label()
    
    def refresh_settings(self) -> None:
        """Refresh settings from current app state."""
        self._load_settings()
    
    def _on_tray_changed(self, state: int) -> None:
        self.app.tray_toggle_checkbox.setChecked(state == Qt.CheckState.Checked.value)
    
    def _on_autostart_changed(self, state: int) -> None:
        self.app.tray_manager.toggle_autostart(state == Qt.CheckState.Checked.value)
        self.tray_checkbox.setEnabled(not self.app.autostart_enabled)
        # Ensure tray checkbox is checked when autostart is enabled
        if state == Qt.CheckState.Checked.value:
            self.tray_checkbox.setChecked(True)
    
    def _on_remember_changed(self, state: int) -> None:
        self.app.remember_settings_checkbox.setChecked(state == Qt.CheckState.Checked.value)
        self.restore_minimized_checkbox.setEnabled(state == Qt.CheckState.Checked.value)
    
    def _on_restore_minimized_changed(self, state: int) -> None:
        self.app.restore_only_minimized_checkbox.setChecked(state == Qt.CheckState.Checked.value)
    
    def _on_check_updates_changed(self, state: int) -> None:
        checked = state == Qt.CheckState.Checked.value
        self.app.check_updates_at_start = checked
        self.app.config_manager.toggle_startup_check(checked)
    
    def _handle_other_button_click(self, button: QAbstractButton) -> None:
        role = self.other_button_box.buttonRole(button)
        
        if role == QDialogButtonBox.ButtonRole.ApplyRole:
            self.builder.save_settings()
            self.builder.show_restart_warning(self)
        elif role == QDialogButtonBox.ButtonRole.ResetRole:
            self.builder.reset_to_defaults(self)
        elif role == QDialogButtonBox.ButtonRole.RejectRole:
            self._load_settings()
    
    def _check_for_updates(self) -> None:
        self.app.update_manager.check_for_updates(manual_check=True)
    
    def _update_version_label(self) -> None:
        curr_version = app_config.APP_VERSION
        if self.app.update_manager.update_available:
            latest = self.app.update_manager.latest_version
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: orange; text-decoration: none;">Version: {curr_version} (Update: {latest})</a>')
        else:
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">Version: {curr_version}</a>')
