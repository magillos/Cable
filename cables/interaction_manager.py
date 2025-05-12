#!/usr/bin/env python3
"""
Manages user interactions with port tree widgets.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication

class InteractionManager:
    """Handles clicks and selection logic for port tree widgets."""

    def __init__(self, highlight_manager, update_connection_buttons_func, update_midi_connection_buttons_func):
        """
        Initialize the InteractionManager.

        Args:
            highlight_manager: Instance of HighlightManager.
            update_connection_buttons_func: Callable to update audio connection buttons.
            update_midi_connection_buttons_func: Callable to update MIDI connection buttons.
        """
        self.highlight_manager = highlight_manager
        self.update_connection_buttons = update_connection_buttons_func
        self.update_midi_connection_buttons = update_midi_connection_buttons_func

    def handle_port_click(self, item, clicked_tree, is_midi):
        """
        Handle selection in tree widgets for ports and groups, respecting Ctrl modifier.
        This method is intended to be called directly via signal connections (e.g., lambdas).

        Args:
            item: The clicked item.
            clicked_tree: The tree that was clicked.
            is_midi: Whether the port is a MIDI port.
        """
        if not item: # Ignore clicks on empty areas
             return

        # Check if Ctrl key is pressed during the click that triggered this handler
        ctrl_pressed = QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier

        if not ctrl_pressed:
            # Clear previous highlights if not holding Ctrl
            # We need to clear highlights on *both* trees in the pair
            if is_midi:
                self.highlight_manager.clear_midi_highlights()
            else:
                self.highlight_manager.clear_highlights()

        # Apply highlights for the clicked item and its connections
        self.highlight_manager.apply_highlights_for_selection(item, clicked_tree, is_midi)

        # Update connection buttons based on the new selection state
        if is_midi:
            self.update_midi_connection_buttons()
        else:
            self.update_connection_buttons()