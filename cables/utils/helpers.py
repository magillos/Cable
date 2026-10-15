"""
Helper functions for the Cables application
"""

from PyQt6.QtWidgets import QDialog, QWidget
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QShowEvent

from cable_core.dialogs import _center_dialog_on_parent_or_screen, _setup_frameless_message


class FramelessNotification(QDialog):
    """Frameless auto-closing notification dialog.

    Matches the style of SettingConfirmationDialog from cable_core/dialogs.py.
    Displays a centered message and disappears automatically after a duration.
    No buttons, no title bar, non-modal.
    """

    def __init__(
        self, text: str, title: str = "", duration_ms: int = 1000, parent: QWidget = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        _setup_frameless_message(self, text, word_wrap=True)

        # Auto-size based on text content
        line_count = text.count("\n") + 1
        max_line_len = max((len(line) for line in text.split("\n")), default=40)
        # Width: at least 300, more for long lines, cap at 450
        width = min(max(300, max_line_len * 8), 450)
        # Height: at least 100, more for multi-line content, cap at 250
        height = min(max(100, line_count * 30), 250)
        self.resize(width, height)

        # Auto-close timer
        QTimer.singleShot(duration_ms, self.accept)

    def showEvent(self, event: QShowEvent) -> None:
        """Center the dialog on parent or screen."""
        super().showEvent(event)
        _center_dialog_on_parent_or_screen(self)


def show_timed_messagebox(
    parent: QWidget,
    icon: object,
    title: str,
    text: str,
    duration: int = 1500,
) -> None:
    """
    Shows a frameless auto-closing notification that disappears after a duration.

    This replaces the old QMessageBox-based implementation with a frameless
    pop-up matching the style of SettingConfirmationDialog.

    Args:
        parent: The parent widget
        icon: Ignored (kept for backward compatibility)
        title: The title of the notification
        text: The text to display in the notification
        duration: The duration in milliseconds before it closes (default: 1500ms)
    """
    dialog = FramelessNotification(
        text=text, title=title, duration_ms=duration, parent=parent
    )
    dialog.exec()