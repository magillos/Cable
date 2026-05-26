"""
"Other Settings" dialog for advanced application preferences.
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QWidget, QAbstractButton
)
from PyQt6.QtCore import Qt

import logging
logger = logging.getLogger(__name__)

from cable_core import app_config
from cable_core.config import ConfigManager
from cable_core.settings_builder import SettingsWidgetBuilder


class OtherSettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, config_manager: Optional[ConfigManager] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Other Settings")
        self.config_manager = config_manager or ConfigManager()

        self.builder = SettingsWidgetBuilder(self.config_manager)

        self._init_ui()
        self.builder.load_settings()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults |
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel
        )
        apply_button = button_box.button(QDialogButtonBox.StandardButton.Apply)
        self.builder.build_widgets(main_layout, apply_button=apply_button)
        button_box.clicked.connect(self._handle_button_click)
        main_layout.addWidget(button_box)

        # Version label at the bottom
        self.version_label = QLabel()
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setTextFormat(Qt.TextFormat.RichText)
        self.version_label.setOpenExternalLinks(True)

        curr_version = app_config.APP_VERSION
        update_available = False
        latest_version = None

        if self.parent() and getattr(self.parent(), 'update_manager', None) is not None:
            update_manager = self.parent().update_manager
            update_available = update_manager.update_available
            latest_version = update_manager.latest_version

        if update_available:
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: orange; text-decoration: none;">Version: {curr_version} (Update available: {latest_version})</a>')
        else:
            self.version_label.setText(f'<a href="https://github.com/magillos/Cable/releases" style="color: grey; text-decoration: none;">Version: {curr_version}</a>')

        main_layout.addWidget(self.version_label)

    def _handle_button_click(self, button: QAbstractButton) -> None:
        if self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.ApplyRole:
            self.builder.save_settings()
            needs_restart = self.builder.requires_restart_warning()
            self.builder._reset_modified_flag()
            if needs_restart:
                self.builder.show_restart_warning(self)
            # Live-apply tray icon (monochrome / invert) changes immediately
            parent = self.parent()
            if parent is not None and hasattr(parent, "tray_manager"):
                tm = getattr(parent, "tray_manager", None)
                if tm is not None:
                    tm.update_tray_icon()
        elif self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.ResetRole:
            if self.builder.reset_to_defaults(self):
                self.accept()
        elif self.sender().buttonRole(button) == QDialogButtonBox.ButtonRole.RejectRole:
            self.builder.load_settings()
            self.builder._reset_modified_flag()
            self.reject()
