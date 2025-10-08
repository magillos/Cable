import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QScrollArea, QWidget,
                              QCheckBox, QDialogButtonBox, QLineEdit, QLabel,
                              QPushButton, QFileDialog, QHBoxLayout, QRadioButton,
                              QButtonGroup)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent

# --- New Dialog for Value Selection ---
class ValueSelectorDialog(QDialog):
    """Dialog to select active values from a list using checkboxes."""
    def __init__(self, title, all_values, active_values, parent=None):
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

    def get_selected_values(self):
        """Returns a list of integer values corresponding to checked boxes."""
        selected = []
        for checkbox in self.checkboxes:
            if checkbox.isChecked():
                try:
                    selected.append(int(checkbox.text()))
                except ValueError:
                    print(f"Warning: Could not convert checkbox text '{checkbox.text()}' to int.")
        return selected

# --- AppImage Path Dialog ---
class AppImagePathDialog(QDialog):
    """Dialog to configure AppImage path for autostart functionality."""
    def __init__(self, current_path=None, parent=None):
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

    def browse_appimage(self):
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

    def get_appimage_path(self):
        """Returns the entered AppImage path."""
        return self.path_input.text().strip()
# ------------------------------------

# --- Combined Virtual Sink/Source Dialog ---
class CombinedSinkSourceDialog(QDialog):
    """Dialog to configure and create a combined virtual sink/source."""
    def __init__(self, parent=None):
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

        # Mono radio button (top option, default)
        self.mono_radio = QRadioButton("Mono")
        self.mono_radio.setChecked(True)
        self.channel_group.addButton(self.mono_radio, 0)
        layout.addWidget(self.mono_radio)

        # Stereo radio button
        self.stereo_radio = QRadioButton("Stereo")
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

    def get_values(self):
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

    def showEvent(self, event: QShowEvent):
        """Override show event to select the default sink name text."""
        super().showEvent(event)
        self.name_input.selectAll()
# ------------------------------------
