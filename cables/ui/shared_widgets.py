from PyQt6.QtWidgets import QToolButton, QApplication
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QSize

def create_action_button(parent_widget, action: QAction, icon_path: str = None, tooltip: str = "", fixed_size: QSize = None, min_width: int = None) -> QToolButton:
    button = QToolButton(parent_widget)
    if icon_path:
        button.setIcon(QIcon.fromTheme(icon_path, QIcon(icon_path))) # Fallback to path if not in theme
    from PyQt6.QtCore import Qt
    # Set tooltip on both button and action to ensure consistency
    if tooltip:  # Only set if tooltip is provided
        action.setToolTip(tooltip)
        button.setToolTip(tooltip)
        if "<" in tooltip and ">" in tooltip:  # Simple check for HTML tags
            button.setToolTipDuration(3000)  # Show tooltip for 3 seconds
    button.setDefaultAction(action) # Connects the button to the QAction
    
    if fixed_size:
        button.setFixedSize(fixed_size)
    if min_width is not None: # Check for None explicitly as 0 could be a valid (though unlikely) min_width
        button.setMinimumWidth(min_width)
        
    # Add any other common styling or properties
    return button

# You might have more specialized factories if needed