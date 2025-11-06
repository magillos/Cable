# cables/ui_state_manager.py

import logging
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QCheckBox, QPushButton, QTreeWidget
from PyQt6.QtGui import QFont

# Import constants for refresh rates
from cable_core import app_config

# Import necessary types for hinting (adjust paths if needed)
# from .config.config_manager import ConfigManager
# from .ui.connection_view import ConnectionView
# from .connection_manager import JackConnectionManager # Avoid circular import if possible

logger = logging.getLogger(__name__)

class UIStateManager(QObject):
    """Manages UI states like auto-refresh, collapse, untangle, and font size."""

    # Signals (optional, if other components need to react directly)
    # auto_refresh_state_changed = pyqtSignal(bool)
    # collapse_state_changed = pyqtSignal(bool) # Note: Collapse state is now managed via checkbox state
    # untangle_mode_changed = pyqtSignal(int) # JackConnectionManager already has this
    # font_size_changed = pyqtSignal(int)

    def __init__(self, parent=None, config_manager=None, main_window=None,
                 auto_refresh_checkbox: QCheckBox = None,
                 collapse_checkbox: QCheckBox = None, # Changed from button
                 untangle_button: QPushButton = None,
                 increase_font_button: QPushButton = None,
                 decrease_font_button: QPushButton = None,
                 input_tree: QTreeWidget = None,
                 output_tree: QTreeWidget = None,
                 midi_input_tree: QTreeWidget = None,
                 midi_output_tree: QTreeWidget = None,
                 connection_view=None, # Audio ConnectionView
                 midi_connection_view=None): # MIDI ConnectionView
        """
        Initializes the UIStateManager.

        Args:
            parent: The parent QObject, typically JackConnectionManager.
            config_manager: Instance of ConfigManager for loading/saving settings.
            main_window: The main application window (JackConnectionManager instance).
            auto_refresh_checkbox: The 'Auto Refresh' checkbox widget.
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
        """
        super().__init__(parent)

        if not config_manager:
            logger.warning("UIStateManager: ConfigManager not provided.")
        if not main_window:
            logger.warning("UIStateManager: Main window (JackConnectionManager) not provided.")

        self.config_manager = config_manager
        self.main_window = main_window
        self.auto_refresh_checkbox = auto_refresh_checkbox
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

        # --- State Attributes ---
        self._callbacks_enabled = True # Internal flag, controlled by auto-refresh checkbox state
        self._untangle_mode = 0 # 0: Off, 1: >>, 2: <<
        self._port_list_font_size = 10 # Default, load from config
        self._is_focused = True # Track main window focus

        # Load initial states from config
        self._load_initial_states()

        # Note: UI element signals (stateChanged, clicked) will be connected
        # in JackConnectionManager after this instance is created.

    def _load_initial_states(self):
        """Load initial UI states from the configuration."""
        if not self.config_manager:
            return

        # Load Auto Refresh state (controls callbacks and timers)
        auto_refresh_enabled = self.config_manager.get_bool('auto_refresh_enabled', True)
        self._callbacks_enabled = auto_refresh_enabled # Link internal flag
        if self.auto_refresh_checkbox:
            self.auto_refresh_checkbox.setChecked(auto_refresh_enabled)
        # Initial timer setup is handled by toggle_auto_refresh logic below

        # Load Collapse state
        collapse_all_enabled = self.config_manager.get_bool('collapse_all_enabled', False)
        if self.collapse_checkbox:
            self.collapse_checkbox.setChecked(collapse_all_enabled)
        # Apply initial collapse state after trees are populated (likely in main_window init or startup refresh)

        # Load Untangle state
        self._untangle_mode = self.config_manager.get_int('untangle_mode', 0)
        self._update_untangle_button_text()
        # Applying untangle sort happens during refresh_ports in main_window

        # Load Font Size state
        try:
            self._port_list_font_size = int(self.config_manager.get_str('port_list_font_size', '10'))
        except ValueError:
            logger.warning("Invalid font size in config, using default 10.")
            self._port_list_font_size = 10
        self._apply_port_list_font_size() # Apply loaded font size

        # Set initial focus state (assuming window starts focused)
        self._is_focused = self.main_window.isActiveWindow() if self.main_window else True

        # Apply initial timer state based on loaded auto-refresh pref
        self._update_timer_state(auto_refresh_enabled)


    # --- Auto Refresh Logic ---
    def toggle_auto_refresh(self, state):
        """Handles the state change of the Auto Refresh checkbox."""
        is_checked = state == Qt.CheckState.Checked.value # Use enum value for comparison
        logger.debug(f"Auto Refresh Toggled: {is_checked}")
        self._callbacks_enabled = is_checked # Update internal flag

        if self.config_manager:
            self.config_manager.set_bool('auto_refresh_enabled', is_checked)

        self._update_timer_state(is_checked)

    def _update_timer_state(self, enabled: bool):
        """Starts/stops visualization timers and sets the correct interval."""
        if enabled:
            if self.connection_view and hasattr(self.main_window, 'refresh_visualizations'):
                # Start timer with a placeholder interval (1ms), will be adjusted immediately
                self.connection_view.start_refresh_timer(self.main_window.refresh_visualizations, interval=1)
            else:
                 logger.warning("Audio ConnectionView or refresh_visualizations method missing.")

            if self.midi_connection_view and hasattr(self.main_window, 'refresh_visualizations'):
                 self.midi_connection_view.start_refresh_timer(self.main_window.refresh_visualizations, interval=1)
            else:
                 logger.warning("MIDI ConnectionView or refresh_visualizations method missing.")

            # Set the correct interval based on current focus and tab
            self._update_refresh_timer_interval()
        else:
            # Stop timers
            if self.connection_view and hasattr(self.connection_view, 'refresh_timer'):
                self.connection_view.refresh_timer.stop()
            if self.midi_connection_view and hasattr(self.midi_connection_view, 'refresh_timer'):
                self.midi_connection_view.refresh_timer.stop()
            logger.debug("Auto Refresh Timers Stopped")

    def _update_refresh_timer_interval(self):
        """Adjusts the visualization refresh timer interval based on focus and active tab."""
        if not self._callbacks_enabled: # Only adjust if auto-refresh is on
             return

        if not self.main_window or not hasattr(self.main_window.ui_manager, 'tab_widget'):
            logger.warning("Cannot update timer interval: main window or ui_manager.tab_widget missing.")
            return

        # Determine interval based on focus and tab using constants from app_config
        interval = app_config.REFRESH_RATE_UNFOCUSED_MS # Default unfocused
        if self._is_focused:
            current_index = self.main_window.ui_manager.tab_widget.currentIndex()
            # Indices for tabs that should use the slower refresh rate when focused
            special_tabs_indices = [2, 3, 4, 5] # Graph, Alsa Mixer, pw-top, Latency Test
            if current_index in [0, 1]: # Audio or MIDI tab
                interval = app_config.REFRESH_RATE_FOCUSED_MS
            elif current_index in special_tabs_indices:
                 interval = app_config.REFRESH_RATE_SPECIAL_TABS_MS
            else: # Fallback for any other tabs (shouldn't happen with current tabs, but good practice)
                 interval = app_config.REFRESH_RATE_FOCUSED_MS
        # else: # Not focused - already set as default above

        logger.debug(f"Setting refresh interval to: {interval} ms (Focused: {self._is_focused})")

        # Apply interval to active timers
        try:
            if self.connection_view and hasattr(self.connection_view, 'refresh_timer') and self.connection_view.refresh_timer.isActive():
                self.connection_view.refresh_timer.setInterval(interval)
            if self.midi_connection_view and hasattr(self.midi_connection_view, 'refresh_timer') and self.midi_connection_view.refresh_timer.isActive():
                self.midi_connection_view.refresh_timer.setInterval(interval)
        except AttributeError as e:
            logger.warning(f"Could not access refresh_timer to set interval: {e}")


    def handle_focus_change(self, focused: bool):
        """Handles the main window gaining or losing focus."""
        if self._is_focused == focused:
             return # No change
        self._is_focused = focused
        logger.debug(f"Focus Changed: {self._is_focused}")
        # Update timer interval if auto-refresh is enabled
        self._update_refresh_timer_interval()

    # --- Collapse All Logic ---
    def toggle_collapse_all(self, state):
        """Handles the state change of the Collapse All checkbox."""
        is_checked = state == Qt.CheckState.Checked.value
        logger.debug(f"Collapse All Toggled: {is_checked}")

        if self.config_manager:
            self.config_manager.set_bool('collapse_all_enabled', is_checked)

        # Apply the state to all trees immediately
        self.apply_collapse_state_to_all_trees(collapse=is_checked)

    def apply_collapse_state_to_all_trees(self, collapse: bool):
        """Applies a specific collapse state (True=collapse, False=expand) to all trees."""
        logger.debug(f"Applying Collapse State to All: {'Collapse' if collapse else 'Expand'}")
        action = 'collapseAllGroups' if collapse else 'expandAllGroups'
        trees = [self.input_tree, self.output_tree, self.midi_input_tree, self.midi_output_tree]
        for tree in trees:
            if tree and hasattr(tree, action):
                getattr(tree, action)()
            elif tree:
                 logger.warning(f"Tree widget missing method: {action}")

        # Refresh visualizations as item visibility changes affect layout
        if self.main_window and hasattr(self.main_window, 'refresh_visualizations'):
            # Use singleShot to ensure collapse happens before refresh attempts to draw
            QTimer.singleShot(0, self.main_window.refresh_visualizations)
        else:
            logger.warning("Cannot refresh visualizations after collapse: main window or method missing.")


    def apply_collapse_state_to_current_trees(self):
        """Applies the collapse state based on the checkbox to the currently relevant trees."""
        if not self.collapse_checkbox or not self.main_window or not hasattr(self.main_window, 'port_type'):
            logger.warning("Cannot apply collapse state to current trees: missing components.")
            return

        collapse = self.collapse_checkbox.isChecked()
        logger.debug(f"Applying Collapse State to Current ({self.main_window.port_type}): {'Collapse' if collapse else 'Expand'}")
        action = 'collapseAllGroups' if collapse else 'expandAllGroups'

        if self.main_window.port_type == 'audio':
            trees_to_modify = [self.input_tree, self.output_tree]
        elif self.main_window.port_type == 'midi':
            trees_to_modify = [self.midi_input_tree, self.midi_output_tree]
        else:
            trees_to_modify = []

        for tree in trees_to_modify:
            if tree and hasattr(tree, action):
                getattr(tree, action)()
            elif tree:
                 logger.warning(f"Tree widget missing method: {action}")

        # Refresh visualizations
        if self.main_window and hasattr(self.main_window, 'refresh_visualizations'):
             QTimer.singleShot(0, self.main_window.refresh_visualizations)


    # --- Untangle Logic ---
    def toggle_untangle_sort(self):
        """Cycles the untangle sort mode."""
        if not self._callbacks_enabled: return # Respect auto-refresh toggle
        self._untangle_mode = (self._untangle_mode + 1) % 3  # Cycle 0 -> 1 -> 2 -> 0
        logger.debug(f"Untangle Mode Cycled To: {self._untangle_mode}")

        if self.config_manager:
            self.config_manager.set_int('untangle_mode', self._untangle_mode)

        self._update_untangle_button_text()

        # Trigger refresh in main window, which applies the sort mode
        if self.main_window and hasattr(self.main_window, 'refresh_ports'):
            # Emit the signal JackConnectionManager listens to for applying sort
            if hasattr(self.main_window, 'untangle_mode_changed'):
                 self.main_window.untangle_mode_changed.emit(self._untangle_mode)
            # Refresh ports which will use the new mode
            self.main_window.refresh_ports(refresh_all=True)
        else:
            logger.warning("Cannot refresh ports after untangle toggle: main window or method missing.")


    def _update_untangle_button_text(self):
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

    def _handle_untangle_shortcut(self):
        """Handles the keyboard shortcut for toggling untangle mode."""
        logger.debug("Untangle Shortcut Triggered")
        if self.main_window and hasattr(self.main_window, '_animate_button_press'):
            self.main_window._animate_button_press(self.untangle_button)
        self.toggle_untangle_sort()


    # --- Font Size Logic ---
    def increase_font_size(self):
        """Increases the font size for the port lists."""
        if not self._callbacks_enabled: return

        max_font_size = self.config_manager.get_int('max_font_size', 24) if self.config_manager else 24
        if self._port_list_font_size < max_font_size:
            self._port_list_font_size += 1
            logger.debug(f"Increasing Font Size to: {self._port_list_font_size}")
            self._apply_port_list_font_size()
            if self.config_manager:
                self.config_manager.set_str('port_list_font_size', str(self._port_list_font_size))

    def decrease_font_size(self):
        """Decreases the font size for the port lists."""
        if not self._callbacks_enabled: return

        min_font_size = self.config_manager.get_int('min_font_size', 6) if self.config_manager else 6
        if self._port_list_font_size > min_font_size:
            self._port_list_font_size -= 1
            logger.debug(f"Decreasing Font Size to: {self._port_list_font_size}")
            self._apply_port_list_font_size()
            if self.config_manager:
                self.config_manager.set_str('port_list_font_size', str(self._port_list_font_size))

    def _apply_port_list_font_size(self):
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
        if self.main_window and hasattr(self.main_window, 'refresh_visualizations'):
             # Use singleShot to ensure font is applied before refresh
             QTimer.singleShot(0, self.main_window.refresh_visualizations)
        else:
             logger.warning("Cannot refresh visualizations after font size change.")


    # --- Callback Control ---
    # Callbacks are now implicitly controlled by _callbacks_enabled,
    # which is tied to the auto-refresh checkbox state.
    # No explicit enable/disable method needed externally for now.
    def are_callbacks_enabled(self) -> bool:
        """Check if UI callbacks are currently enabled (based on auto-refresh state)."""
        return self._callbacks_enabled

    # --- Getters for State (if needed externally) ---
    def get_untangle_mode(self) -> int:
        return self._untangle_mode

    def get_port_list_font_size(self) -> int:
        return self._port_list_font_size

    # --- Cleanup ---
    def cleanup(self):
        """Perform cleanup actions, e.g., stop timers."""
        logger.info("UIStateManager Cleanup: Stopping timers.")
        # Timers are managed by ConnectionView, stopping them via toggle_auto_refresh(False)
        # or letting JackConnectionManager.closeEvent handle ConnectionView cleanup might be sufficient.
        # Explicitly stop here just in case.
        self._update_timer_state(enabled=False)
