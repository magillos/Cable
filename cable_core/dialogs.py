"""
Reusable PyQt6 dialog classes: ValueSelectorDialog, AppImagePathDialog, CombinedSinkSourceDialog.
"""

import os
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QScrollArea, QWidget,
                              QCheckBox, QDialogButtonBox, QLineEdit, QLabel,
                              QPushButton, QFileDialog, QHBoxLayout, QRadioButton,
                              QButtonGroup)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent

import logging
logger = logging.getLogger(__name__)

# --- Default Reset Confirm Dialog ---
class DefaultResetConfirmDialog(QDialog):
    """Custom dialog for Default preset confirmation with 'Don't show again' option."""
    
    def __init__(self, parent: Optional['QWidget'] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm Reset")
        self.setModal(True)
        self.dont_show_again = False
        
        # Set up the dialog layout
        layout = QVBoxLayout(self)
        
        # Message label
        message = QLabel(
            "This will disconnect all current connections, unhide and unfold all nodes/clients, "
            "and then restart WirePlumber to restore default connections.\n\n"
            "Do you want to proceed?"
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        
        # Don't show again checkbox
        self.dont_show_checkbox = QCheckBox("Don't show this confirmation again")
        layout.addWidget(self.dont_show_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.yes_button = QPushButton("Yes")
        self.yes_button.clicked.connect(self.accept)
        
        self.no_button = QPushButton("No")
        self.no_button.clicked.connect(self.reject)
        self.no_button.setDefault(True)  # Make No the default button
        
        button_layout.addStretch()
        button_layout.addWidget(self.yes_button)
        button_layout.addWidget(self.no_button)
        
        layout.addLayout(button_layout)
        
        # Set reasonable size
        self.resize(400, 150)
    
    def accept(self) -> None:
        """Override accept to capture the checkbox state."""
        self.dont_show_again = self.dont_show_checkbox.isChecked()
        super().accept()
# ------------------------------------

# --- New Dialog for Value Selection ---
class ValueSelectorDialog(QDialog):
    """Dialog to select active values from a list using checkboxes."""
    def __init__(self, title: str, all_values: List[int], active_values: List[int], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300) # Set a minimum width

        self.checkboxes = []
        layout = QVBoxLayout(self)

        # Scroll Area for potentially long lists
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        for value in all_values:
            checkbox = QCheckBox(str(value))
            if value in active_values:
                checkbox.setChecked(True)
            self.checkboxes.append(checkbox)
            scroll_layout.addWidget(checkbox)

        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # OK and Cancel buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def get_selected_values(self) -> List[int]:
        """Returns a list of integer values corresponding to checked boxes."""
        selected = []
        for checkbox in self.checkboxes:
            if checkbox.isChecked():
                try:
                    selected.append(int(checkbox.text()))
                except ValueError:
                    logger.warning(f"Warning: Could not convert checkbox text '{checkbox.text()}' to int.")
        return selected

# --- AppImage Path Dialog ---
class AppImagePathDialog(QDialog):
    """Dialog to configure AppImage path for autostart functionality."""
    def __init__(self, current_path: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure AppImage Path")
        self.setMinimumWidth(400)
        self.current_path = current_path

        layout = QVBoxLayout(self)

        # Instructions
        instruction_label = QLabel(
            "To enable autostart with AppImage, please select your Cable AppImage file:\n\n"
            "This is the .AppImage file you downloaded and made executable."
        )
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        # Path input layout
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        if current_path:
            self.path_input.setText(current_path)
        self.path_input.setPlaceholderText("Select your Cable AppImage file...")
        path_layout.addWidget(self.path_input)

        # Browse button
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.browse_appimage)
        path_layout.addWidget(browse_button)

        layout.addLayout(path_layout)

        # OK and Cancel buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def browse_appimage(self) -> None:
        """Open file dialog to select AppImage file."""
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("AppImage files (*.AppImage);;All files (*)")
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)

        if self.current_path:
            file_dialog.setDirectory(os.path.dirname(self.current_path))

        if file_dialog.exec() == QDialog.DialogCode.Accepted:
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.path_input.setText(selected_files[0])

    def get_appimage_path(self) -> str:
        """Returns the entered AppImage path."""
        return self.path_input.text().strip()
# ------------------------------------

# --- Combined Virtual Sink/Source Dialog ---
class CombinedSinkSourceDialog(QDialog):
    """Dialog to configure and create a combined virtual sink/source."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Combined Virtual Sink/Source")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # Sink name label and input
        name_layout = QVBoxLayout()
        name_label = QLabel("Name:")
        self.name_input = QLineEdit()
        self.name_input.setText("my-combined-sink")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # Channel map label and radio buttons
        channel_label = QLabel("Channel Map:")
        layout.addWidget(channel_label)

        # Create radio button group for exclusive selection
        self.channel_group = QButtonGroup(self)
        self.channel_group.setExclusive(True)

        # Mono radio button
        self.mono_radio = QRadioButton("Mono")
        self.channel_group.addButton(self.mono_radio, 0)
        layout.addWidget(self.mono_radio)

        # Stereo radio button (default)
        self.stereo_radio = QRadioButton("Stereo")
        self.stereo_radio.setChecked(True)
        self.channel_group.addButton(self.stereo_radio, 1)
        layout.addWidget(self.stereo_radio)

        # 5.1 radio button
        self.surround51_radio = QRadioButton("5.1")
        self.channel_group.addButton(self.surround51_radio, 2)
        layout.addWidget(self.surround51_radio)

        # 7.1 radio button
        self.surround71_radio = QRadioButton("7.1")
        self.channel_group.addButton(self.surround71_radio, 3)
        layout.addWidget(self.surround71_radio)

        # Spacer
        layout.addStretch()

        # Create and Cancel buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def get_values(self) -> Tuple[str, str]:
        """Returns the entered sink name and selected channel map."""
        sink_name = self.name_input.text().strip()

        channel_map = "Mono"
        if self.stereo_radio.isChecked():
            channel_map = "Stereo"
        elif self.surround51_radio.isChecked():
            channel_map = "5.1"
        elif self.surround71_radio.isChecked():
            channel_map = "7.1"

        return sink_name, channel_map

    def showEvent(self, event: QShowEvent) -> None:
        """Override show event to select the default sink name text."""
        super().showEvent(event)
        self.name_input.selectAll()
# ------------------------------------


# --- Hide Node Confirmation Dialog ---
def show_hide_node_confirmation_dialog(
    parent: Optional[QWidget],
    node_name: str,
    message_type: str,
    config_manager: Optional[object] = None,
    custom_message: Optional[str] = None
) -> bool:
    """Show a confirmation dialog with 'don't show again' checkbox for hiding nodes.

    This is a shared utility used by both the graph view (NodeItem) and
    the port tree view (PortTreeWidget) when hiding nodes.

    Args:
        parent: Parent widget for the dialog.
        node_name: Name of the client/node to hide.
        message_type: Type of the node (e.g., 'audio', 'MIDI').
        config_manager: Optional ConfigManager instance for persisting the
                        'don't show again' preference.
        custom_message: Optional custom message body. If not provided, a
                        default message is constructed from node_name and message_type.

    Returns:
        True if user confirmed hiding, False otherwise.
    """
    from cable_core import config_keys as keys

    dialog = QDialog(parent)
    dialog.setWindowTitle("Hide Node")
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)

    if custom_message:
        message = f"{custom_message}\n\nYou can restore it later from the Node Visibility dialog."
    else:
        message = f"Hide {node_name} {message_type} node?\n\nYou can restore it later from the Node Visibility dialog."

    label = QLabel(message)
    layout.addWidget(label)

    checkbox = QCheckBox("Don't show this message again")
    layout.addWidget(checkbox)

    button_box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
    )
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    layout.addWidget(button_box)

    result = dialog.exec() == QDialog.DialogCode.Accepted

    if result and checkbox.isChecked() and config_manager is not None:
        if hasattr(config_manager, 'set_bool'):
            config_manager.set_bool(keys.SHOW_HIDE_NODE_CONFIRMATION, False)

    return result
# ------------------------------------
