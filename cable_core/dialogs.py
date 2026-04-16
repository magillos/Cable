"""
Reusable PyQt6 dialog classes: ValueSelectorDialog, AppImagePathDialog, CombinedSinkSourceDialog, QuickSettingsDialog.
"""

import os
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QScrollArea, QWidget,
    QCheckBox, QDialogButtonBox, QLineEdit, QLabel,
    QPushButton, QFileDialog, QHBoxLayout, QRadioButton,
    QButtonGroup, QComboBox, QGroupBox, QListWidget,
    QListWidgetItem, QFormLayout, QAbstractItemView)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QShowEvent, QIcon

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

# --- Quantum/Sample Rate Confirmation Dialog ---
class QuantumSampleRateConfirmationDialog(QDialog):
    """Auto-closing confirmation dialog for quantum/sample rate changes."""
    
    def __init__(self, message: str, duration_ms: int = 2000, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Setting Applied")
        self.setModal(False)  # Non-modal so it doesn't block interaction
        
        layout = QVBoxLayout(self)
        
        # Message label
        message_label = QLabel(message)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message_label)
        
        # Set reasonable size
        self.resize(250, 80)
        
        # Auto-close timer
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(duration_ms, self.accept)
    
    def showEvent(self, event: QShowEvent) -> None:
        """Override show event to center the dialog on parent or screen."""
        super().showEvent(event)
        parent_widget = self.parent()
        if parent_widget and parent_widget.isVisible():
            # Center on visible parent
            parent_rect = parent_widget.geometry()
            dialog_rect = self.geometry()
            x = parent_rect.x() + (parent_rect.width() - dialog_rect.width()) // 2
            y = parent_rect.y() + (parent_rect.height() - dialog_rect.height()) // 2
            self.move(x, y)
        else:
            # Parent is hidden or None: center on primary screen
            from PyQt6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            if screen:
                screen_geometry = screen.availableGeometry()
                x = screen_geometry.x() + (screen_geometry.width() - self.width()) // 2
                y = screen_geometry.y() + (screen_geometry.height() - self.height()) // 2
                self.move(x, y)
# ------------------------------------


# --- Quick Settings Dialog ---
class QuickSettingsDialog(QDialog):
    """Dialog to configure quick quantum and sample rate settings for the system tray.

    Displays all available quantum and sample rate values plus a "Default" option.
    The "Default" option triggers a reset (same as the Reset button in Cable).
    Existing quick settings are shown with trash icon buttons for removal.
    Use "Add to quick settings" to add the current dropdown selection to the list.
    Click OK to save the current list state.
    """

    _DEFAULT_LABEL = "Default"

    def __init__(
        self,
        existing_settings: List[dict],
        quantum_values: List[int],
        sample_rate_values: List[int],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Settings")
        self.setMinimumWidth(350)
        self.setToolTip("Configure quick quantum and sample rate settings")

        self._settings: List[dict] = list(existing_settings)
        self._quantum_values = quantum_values
        self._sample_rate_values = sample_rate_values

        layout = QVBoxLayout(self)

        # --- Existing quick settings ---
        existing_group = QGroupBox("Existing Quick Settings")
        existing_layout = QVBoxLayout(existing_group)

        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._populate_list()
        existing_layout.addWidget(self._list_widget)

        layout.addWidget(existing_group)

        # --- New quick setting ---
        new_group = QGroupBox("Add New Quick Setting")
        form_layout = QFormLayout(new_group)

        # Quantum combo - Default first, then values
        self._quantum_combo = QComboBox()
        self._quantum_combo.addItem(self._DEFAULT_LABEL)
        for val in quantum_values:
            self._quantum_combo.addItem(str(val))
        form_layout.addRow("Quantum:", self._quantum_combo)

        # Sample rate combo - Default first, then values
        self._sample_rate_combo = QComboBox()
        self._sample_rate_combo.addItem(self._DEFAULT_LABEL)
        for val in sample_rate_values:
            self._sample_rate_combo.addItem(str(val))
        form_layout.addRow("Sample Rate:", self._sample_rate_combo)

        # Add button below dropdowns
        self._add_button = QPushButton("Add to quick settings")
        self._add_button.clicked.connect(self._add_current_to_list)
        form_layout.addRow(self._add_button)

        layout.addWidget(new_group)

        # --- OK / Cancel ---
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _populate_list(self) -> None:
        """Populate the list widget with existing settings, each with a trash button."""
        self._list_widget.clear()
        for i, entry in enumerate(self._settings):
            self._add_list_item(entry, i)

    def _add_list_item(self, entry: dict, index: int) -> None:
        """Add a single item with trash button to the list."""
        # Create a widget to hold the label and trash button
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(4, 2, 4, 2)
        item_layout.setSpacing(8)

        # Label on the left
        label = self._make_label(entry)
        label_widget = QLabel(label)
        item_layout.addWidget(label_widget)

        item_layout.addStretch()

        # Trash button on the right
        trash_button = QPushButton()
        trash_button.setFixedSize(24, 24)
        trash_button.setFlat(True)
        trash_button.setToolTip("Remove this quick setting")
        trash_icon = QIcon.fromTheme("user-trash")
        if trash_icon.isNull():
            # Fallback: use edit-clear or edit-delete
            trash_icon = QIcon.fromTheme("edit-clear")
        if not trash_icon.isNull():
            trash_button.setIcon(trash_icon)
            trash_button.setIconSize(QSize(16, 16))
        else:
            # Final fallback: use text
            trash_button.setText("🗑")
        trash_button.clicked.connect(lambda checked, idx=index: self._remove_at_index(idx))
        item_layout.addWidget(trash_button)

        # Create list item and set the widget
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, index)
        self._list_widget.addItem(item)
        self._list_widget.setItemWidget(item, item_widget)

    @classmethod
    def _make_label(cls, entry: dict) -> str:
        """Create a display label like '128/48000' or '128/default'."""
        q = entry.get("quantum", cls._DEFAULT_LABEL)
        sr = entry.get("sample_rate", cls._DEFAULT_LABEL)
        return f"{q}/{sr}"

    def _remove_at_index(self, index: int) -> None:
        """Remove the quick setting entry at the given index."""
        if 0 <= index < len(self._settings):
            self._settings.pop(index)
            # Rebuild the entire list to update indices
            self._populate_list()

    def _add_current_to_list(self) -> None:
        """Add the currently selected quantum/sample rate to the quick settings list."""
        q_text = self._quantum_combo.currentText()
        sr_text = self._sample_rate_combo.currentText()
        quantum = "default" if q_text == self._DEFAULT_LABEL else q_text
        sample_rate = "default" if sr_text == self._DEFAULT_LABEL else sr_text
        entry = {"quantum": quantum, "sample_rate": sample_rate}

        self._settings.append(entry)
        self._populate_list()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_quick_settings(self) -> List[dict]:
        """Return the current quick settings list (including additions and removals)."""
        return list(self._settings)
    # ------------------------------------
