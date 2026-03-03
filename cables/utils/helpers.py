"""
Helper functions for the Cables application
"""

from PyQt6.QtWidgets import QMessageBox, QWidget
from PyQt6.QtCore import QTimer


def show_timed_messagebox(parent: QWidget, icon: QMessageBox.Icon, title: str, text: str, duration: int = 1000) -> None:
    """
    Shows a message box that automatically closes after a specified duration.
    
    Args:
        parent: The parent widget
        icon: The message box icon (e.g., QMessageBox.Icon.Information)
        title: The title of the message box
        text: The text to display in the message box
        duration: The duration in milliseconds before the message box closes (default: 1000ms)
    """
    msgBox = QMessageBox(parent)
    msgBox.setIcon(icon)
    msgBox.setWindowTitle(title)
    msgBox.setText(text)
    msgBox.setStandardButtons(QMessageBox.StandardButton.NoButton)  # No buttons needed
    QTimer.singleShot(duration, msgBox.accept)  # Close after duration
    msgBox.exec()
