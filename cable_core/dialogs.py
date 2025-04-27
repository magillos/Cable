from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QScrollArea, QWidget,
                             QCheckBox, QDialogButtonBox)

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
# ------------------------------------