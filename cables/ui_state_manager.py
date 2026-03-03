# cables/ui_state_manager.py
"""
Manages UI state persistence and restoration (auto-refresh, collapse, font size, splitter positions).
"""

import logging
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QCheckBox, QPushButton, QTreeWidget, QToolButton
from PyQt6.QtGui import QFont

from cable_core import config_keys as keys

from typing import TYPE_CHECKING, Optional, Any, Union, List

if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager
    from cable_core.config import ConfigManager
    from cables.ui.connection_view import ConnectionView
    from cables.ui.port_tree_widget import PortTreeWidget

logger = logging.getLogger(__name__)

class UIStateManager(QObject):
    """Manages UI states like collapse, untangle, and font size.
    
    This class uses callbacks instead of main_window reference to reduce coupling.
    All operations that would require accessing the main window are provided as
    callback functions during initialization.
    """
    
    # Signals for external notification
    refresh_visualizations_requested = pyqtSignal()
    refresh_ports_requested = pyqtSignal()
    untangle_mode_changed = pyqtSignal(int)

    def __init__(self, 
                 parent: Optional[QObject] = None, 
                 config_manager: Optional['ConfigManager'] = None,
                 collapse_checkbox: Optional[Union[QCheckBox, QToolButton]] = None,
                 untangle_button: Optional[QPushButton] = None,
                 increase_font_button: Optional[QPushButton] = None,
                 decrease_font_button: Optional[QPushButton] = None,
                 input_tree: Optional['PortTreeWidget'] = None,
                 output_tree: Optional['PortTreeWidget'] = None,
                 midi_input_tree: Optional['PortTreeWidget'] = None,
                 midi_output_tree: Optional['PortTreeWidget'] = None,
                 connection_view: Optional['ConnectionView'] = None,
                 midi_connection_view: Optional['ConnectionView'] = None,
                 refresh_visualizations_callback: Optional[callable] = None,
                 refresh_ports_callback: Optional[callable] = None,
                 animate_button_callback: Optional[callable] = None,
                 get_port_type: Optional[callable] = None) -> None:
        """
        Initializes the UIStateManager.

        Args:
            parent: The parent QObject, typically JackConnectionManager.
            config_manager: Instance of ConfigManager for loading/saving settings.
            collapse_checkbox: The 'Collapse All' checkbox widget.
            untangle_button: The 'Untangle' button widget.
            increase_font_button: The 'Increase Font Size' button widget.
            decrease_font_button: The 'Decrease Font Size' button widget.
            input_tree: The audio input ports QTreeWidget.
            output_tree: The audio output ports QTreeWidget.
            midi_input_tree: The MIDI input ports QTreeWidget.
            midi_output_tree: The MIDI output ports QTreeWidget.
            connection_view: The audio ConnectionView instance.
            midi_connection_view: The MIDI ConnectionView instance.
            refresh_visualizations_callback: Callback to refresh visualizations.
            refresh_ports_callback: Callback to refresh ports.
            animate_button_callback: Callback to animate button press.
            get_port_type: Callback to get current port type ('audio' or 'midi').
        """
        super().__init__(parent)

        if not config_manager:
            logger.warning("UIStateManager: ConfigManager not provided.")

        self.config_manager = config_manager
        self.collapse_checkbox = collapse_checkbox
        self.untangle_button = untangle_button
        self.increase_font_button = increase_font_button
        self.decrease_font_button = decrease_font_button
        self.input_tree = input_tree
        self.output_tree = output_tree
        self.midi_input_tree = midi_input_tree
        self.midi_output_tree = midi_output_tree
        self.connection_view = connection_view
        self.midi_connection_view = midi_connection_view
        
        # Callbacks instead of main_window reference
        self._refresh_visualizations_callback = refresh_visualizations_callback
        self._refresh_ports_callback = refresh_ports_callback
        self._animate_button_callback = animate_button_callback
        self._get_port_type = get_port_type

        # --- State Attributes ---
        self._callbacks_enabled = True # Always enabled now
        self._untangle_mode = 0 # 0: Off, 1: >>, 2: <<
        self._port_list_font_size = 10 # Default, load from config
        self._is_focused = True # Track main window focus

        # Load initial states from config
        self._load_initial_states()

        # Note: UI element signals (stateChanged, clicked) will be connected
        # in JackConnectionManager after this instance is created.

    def _load_initial_states(self) -> None:
        """Load initial UI states from the configuration."""
        if not self.config_manager:
            return

        # Auto-refresh is now always enabled - set up event-driven refresh
        self._callbacks_enabled = True

        # Load Collapse state
        collapse_all_enabled = self.config_manager.get_bool(keys.COLLAPSE_ALL_ENABLED, False)
        if self.collapse_checkbox:
            self.collapse_checkbox.setChecked(collapse_all_enabled)
        # Apply initial collapse state after trees are populated (likely in main_window init or startup refresh)

        # Load Untangle state
        self._untangle_mode = self.config_manager.get_int(keys.UNTANGLE_MODE, 0)
        self._update_untangle_button_text()
        # Applying untangle sort happens during refresh_ports in main_window

        # Load Font Size state
        try:
            self._port_list_font_size = int(self.config_manager.get_str(keys.PORT_LIST_FONT_SIZE, '10'))
        except ValueError:
            logger.warning("Invalid font size in config, using default 10.")
            self._port_list_font_size = 10
        self._apply_port_list_font_size() # Apply loaded font size

        # Set initial focus state (assuming window starts focused)
        self._is_focused = True  # Assume focused on init

        # Always enable event-driven refresh
        self._setup_connection_views()


    def _setup_connection_views(self) -> None:
        """Sets up event-driven refresh for connection views (always enabled)."""
        if self.connection_view and self._refresh_visualizations_callback:
            self.connection_view.set_refresh_callback(self._refresh_visualizations_callback)
            # Do an initial refresh
            self.connection_view.request_refresh()
        else:
            logger.warning("Audio ConnectionView or refresh callback missing.")

        if self.midi_connection_view and self._refresh_visualizations_callback:
            self.midi_connection_view.set_refresh_callback(self._refresh_visualizations_callback)
            # Do an initial refresh
            self.midi_connection_view.request_refresh()
        else:
            logger.warning("MIDI ConnectionView or refresh callback missing.")
        logger.debug("Event-driven refresh enabled for connection views")

    def handle_focus_change(self, focused: bool) -> None:
        """Handles the main window gaining or losing focus."""
        if self._is_focused == focused:
            return
        self._is_focused = focused
        logger.debug(f"Focus Changed: {self._is_focused}")

    # --- Collapse All Logic ---
    def toggle_collapse_all(self, state: Union[int, bool]) -> None:
        """Handles the state change of the Collapse All checkbox/toolbutton.
        
        Args:
            state: Either an int (from QCheckBox.stateChanged) or bool (from QToolButton.toggled)
        """
        # Handle both int (QCheckBox stateChanged) and bool (QToolButton toggled)
        if isinstance(state, bool):
            is_checked = state
        else:
            is_checked = state == Qt.CheckState.Checked.value
        
        logger.debug(f"Collapse All Toggled: {is_checked}")

        if self.config_manager:
            self.config_manager.set_bool(keys.COLLAPSE_ALL_ENABLED, is_checked)

        # Apply the state to all trees immediately
        self.apply_collapse_state_to_all_trees(collapse=is_checked)

    def apply_collapse_state_to_all_trees(self, collapse: bool) -> None:
        """Applies a specific collapse state (True=collapse, False=expand) to all trees."""
        logger.debug(f"Applying Collapse State to All: {'Collapse' if collapse else 'Expand'}")
        action = 'collapse_all_groups' if collapse else 'expand_all_groups'
        trees = [self.input_tree, self.output_tree, self.midi_input_tree, self.midi_output_tree]
        for tree in trees:
            if tree and hasattr(tree, action):
                getattr(tree, action)()
            elif tree:
                 logger.warning(f"Tree widget missing method: {action}")

        # Refresh visualizations as item visibility changes affect layout
        if self._refresh_visualizations_callback:
            # Use singleShot to ensure collapse happens before refresh attempts to draw
            QTimer.singleShot(0, self._refresh_visualizations_callback)
        else:
            logger.warning("Cannot refresh visualizations after collapse: callback missing.")


    def apply_collapse_state_to_current_trees(self) -> None:
        """Applies the collapse state based on the checkbox/toolbutton to the currently relevant trees."""
        if not self.collapse_checkbox:
            logger.warning("Cannot apply collapse state to current trees: missing checkbox/toolbutton.")
            return

        # Get port type via callback
        port_type = self._get_port_type() if self._get_port_type else keys.TAB_AUDIO
        
        # isChecked() works for both QCheckBox and QToolButton
        collapse = self.collapse_checkbox.isChecked()
        logger.debug(f"Applying Collapse State to Current ({port_type}): {'Collapse' if collapse else 'Expand'}")
        action = 'collapse_all_groups' if collapse else 'expand_all_groups'

        if port_type == keys.TAB_AUDIO:
            trees_to_modify = [self.input_tree, self.output_tree]
        elif port_type == keys.TAB_MIDI:
            trees_to_modify = [self.midi_input_tree, self.midi_output_tree]
        else:
            trees_to_modify = []

        for tree in trees_to_modify:
            if tree and hasattr(tree, action):
                getattr(tree, action)()
            elif tree:
                 logger.warning(f"Tree widget missing method: {action}")

        # Refresh visualizations
        if self._refresh_visualizations_callback:
             QTimer.singleShot(0, self._refresh_visualizations_callback)


    # --- Untangle Logic ---
    def toggle_untangle_sort(self) -> None:
        """Cycles the untangle sort mode."""
        if not self._callbacks_enabled: return # Respect auto-refresh toggle
        self._untangle_mode = (self._untangle_mode + 1) % 3  # Cycle 0 -> 1 -> 2 -> 0
        logger.debug(f"Untangle Mode Cycled To: {self._untangle_mode}")

        if self.config_manager:
            self.config_manager.set_int(keys.UNTANGLE_MODE, self._untangle_mode)

        self._update_untangle_button_text()

        # Emit signal for external listeners
        self.untangle_mode_changed.emit(self._untangle_mode)
        
        # Trigger refresh via callback
        if self._refresh_ports_callback:
            self._refresh_ports_callback(refresh_all=True)
        else:
            logger.warning("Cannot refresh ports after untangle toggle: callback missing.")


    def _update_untangle_button_text(self) -> None:
        """Updates the text of the untangle button based on the mode."""
        modes = {
            0: "Untangle: Off",
            1: "Untangle: >>",
            2: "Untangle: <<"
        }
        tooltips = {
            0: "Sort clients alphabetically (Default)",
            1: "Sort clients to minimize cable crossing (Layout A)",
            2: "Sort clients to minimize cable crossing (Layout B)"
        }
        if self.untangle_button:
            self.untangle_button.setText(modes.get(self._untangle_mode, "Untangle: ???"))
            tooltip_base = tooltips.get(self._untangle_mode, "Toggle untangle sort mode")
            tooltip = f"{tooltip_base} <span style='color:grey'>Alt+U</span>"
            self.untangle_button.setToolTip(tooltip)

    def _handle_untangle_shortcut(self) -> None:
        """Handles the keyboard shortcut for toggling untangle mode."""
        logger.debug("Untangle Shortcut Triggered")
        if self._animate_button_callback and self.untangle_button:
            self._animate_button_callback(self.untangle_button)
        self.toggle_untangle_sort()


    # --- Font Size Logic ---
    def increase_font_size(self) -> None:
        """Increases the font size for the port lists."""
        if not self._callbacks_enabled: return

        max_font_size = self.config_manager.get_int(keys.MAX_FONT_SIZE, 24) if self.config_manager else 24
        if self._port_list_font_size < max_font_size:
            self._port_list_font_size += 1
            logger.debug(f"Increasing Font Size to: {self._port_list_font_size}")
            self._apply_port_list_font_size()
            if self.config_manager:
                self.config_manager.set_str(keys.PORT_LIST_FONT_SIZE, str(self._port_list_font_size))

    def decrease_font_size(self) -> None:
        """Decreases the font size for the port lists."""
        if not self._callbacks_enabled: return

        min_font_size = self.config_manager.get_int(keys.MIN_FONT_SIZE, 6) if self.config_manager else 6
        if self._port_list_font_size > min_font_size:
            self._port_list_font_size -= 1
            logger.debug(f"Decreasing Font Size to: {self._port_list_font_size}")
            self._apply_port_list_font_size()
            if self.config_manager:
                self.config_manager.set_str(keys.PORT_LIST_FONT_SIZE, str(self._port_list_font_size))

    def _apply_port_list_font_size(self) -> None:
        """Applies the current font size to the port list tree widgets."""
        font = QFont()
        font.setPointSize(self._port_list_font_size)
        logger.debug(f"Applying Font Size: {self._port_list_font_size}")

        trees_to_update = [
            self.input_tree, self.output_tree,
            self.midi_input_tree, self.midi_output_tree
        ]

        for tree in trees_to_update:
            if tree:
                tree.setFont(font)
                # Optionally adjust row height or other style aspects here if needed
                # e.g., tree.setStyleSheet(f"QTreeView::item {{ height: {self._port_list_font_size + 6}px; }}")

        # Refresh visualizations as item sizes might change layout
        if self._refresh_visualizations_callback:
             # Use singleShot to ensure font is applied before refresh
             QTimer.singleShot(0, self._refresh_visualizations_callback)
        else:
             logger.warning("Cannot refresh visualizations after font size change.")


    # --- Callback Control ---
    def are_callbacks_enabled(self) -> bool:
        """Check if UI callbacks are currently enabled (always True now)."""
        return self._callbacks_enabled

    # --- Getters for State (if needed externally) ---
    def get_untangle_mode(self) -> int:
        return self._untangle_mode

    def get_port_list_font_size(self) -> int:
        return self._port_list_font_size

    # --- Cleanup ---
    def cleanup(self) -> None:
        """Perform cleanup actions, e.g., stop timers."""
        logger.info("UIStateManager Cleanup: Stopping timers.")
        # Timers are managed by ConnectionView, letting JackConnectionManager.closeEvent
        # handle ConnectionView cleanup is sufficient.
