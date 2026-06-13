"""
Helper functions for the Cables application
"""

from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QShowEvent


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
        self.setModal(False)

        # Prevent focus stealing
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        layout = QVBoxLayout(self)

        # Styling for frameless window
        self.setStyleSheet("""
            QDialog {
                background-color: palette(window);
                border: 1px solid palette(mid);
                border-radius: 4px;
            }
            QLabel {
                padding: 10px;
            }
        """)

        message_label = QLabel(text)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

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
        parent_widget = self.parent()
        if parent_widget and parent_widget.isVisible():
            parent_rect = parent_widget.geometry()
            dialog_rect = self.geometry()
            x = parent_rect.x() + (parent_rect.width() - dialog_rect.width()) // 2
            y = parent_rect.y() + (parent_rect.height() - dialog_rect.height()) // 2
            self.move(x, y)
        else:
            from PyQt6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            if screen:
                screen_geometry = screen.availableGeometry()
                x = screen_geometry.x() + (screen_geometry.width() - self.width()) // 2
                y = (
                    screen_geometry.y()
                    + (screen_geometry.height() - self.height()) // 2
                )
                self.move(x, y)


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