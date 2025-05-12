# cables/action_manager.py

import random
import jack
from PyQt6.QtWidgets import QApplication # QAction removed
from PyQt6.QtGui import QKeySequence, QColor, QPainterPath, QPen, QAction # QAction added
from PyQt6.QtCore import Qt, QTimer, QPointF

class ActionManager:
    """Manages QActions and QShortcuts for the application."""

    def __init__(self, main_window, state_manager, connection_handler, preset_handler, ui):
        """
        Initialize the ActionManager.

        Args:
            main_window: The main application window (JackConnectionManager instance).
            state_manager: The UIStateManager instance.
            connection_handler: The JackConnectionHandler instance.
            preset_handler: The PresetHandler instance.
            ui: Dictionary-like object containing relevant UI elements from main_window
                (e.g., ui.tab_widget, ui.connect_button, ui.disconnect_button, etc.).
        """
        self.main_window = main_window
        self.state_manager = state_manager
        self.connection_handler = connection_handler
        self.preset_handler = preset_handler
        self.ui = ui # Store the UI elements reference

        # --- Action Attributes ---
        self.connect_action = None
        self.disconnect_action = None
        self.undo_shortcut_action = None
        self.redo_shortcut_action = None
        self.refresh_shortcut_action = None
        self.collapse_all_shortcut_action = None
        self.auto_refresh_shortcut_action = None
        self.untangle_shortcut_action = None
        self.increase_font_action = None
        self.decrease_font_action = None
        self.tab_switch_action = None
        self.tab_switch_back_action = None
        self.save_preset_action = None
        self.default_preset_action = None
        self.move_group_up_action = None
        self.move_group_down_action = None

    def setup_actions_and_shortcuts(self):
        """Sets up all QActions and QShortcuts and adds them to the main window."""
        self._setup_actions()
        self._add_actions_to_window()

    def _setup_actions(self):
        """Define all QAction objects for shortcuts and context menus."""
        # Connect Shortcut (c)
        self.connect_action = QAction("Connect Shortcut", self.main_window)
        self.connect_action.setShortcut(QKeySequence(Qt.Key.Key_C))
        self.connect_action.triggered.connect(self._handle_connect)

        # Disconnect Shortcut (d/Delete)
        self.disconnect_action = QAction("Disconnect Shortcut", self.main_window)
        self.disconnect_action.setShortcuts([QKeySequence(Qt.Key.Key_D), QKeySequence(Qt.Key.Key_Delete)])
        self.disconnect_action.triggered.connect(self._handle_disconnect)

        # Undo Shortcut (Ctrl+Z)
        self.undo_shortcut_action = QAction("Undo Shortcut", self.main_window)
        self.undo_shortcut_action.setShortcut(QKeySequence.StandardKey.Undo)  # Standard Ctrl+Z
        self.undo_shortcut_action.triggered.connect(self._handle_undo) # Connect to internal handler

        # Redo Shortcut (Ctrl+Y / Ctrl+Shift+Z)
        self.redo_shortcut_action = QAction("Redo Shortcut", self.main_window)
        self.redo_shortcut_action.setShortcuts([QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Y")])
        self.redo_shortcut_action.triggered.connect(self._handle_redo) # Connect to internal handler

        # Refresh Shortcut (r)
        self.refresh_shortcut_action = QAction("Refresh Shortcut", self.main_window)
        self.refresh_shortcut_action.setShortcut(QKeySequence(Qt.Key.Key_R))
        # Connect directly to main_window's refresh method
        self.refresh_shortcut_action.triggered.connect(lambda: self.main_window.refresh_ports(from_shortcut=True))

        # Collapse All Shortcut (Alt+C)
        self.collapse_all_shortcut_action = QAction("Collapse All Shortcut", self.main_window)
        self.collapse_all_shortcut_action.setShortcut(QKeySequence("Alt+C"))
        # Connect shortcut to toggle the checkbox, which triggers UIStateManager via stateChanged signal
        self.collapse_all_shortcut_action.triggered.connect(lambda: self.ui['collapse_all_checkbox'].toggle() if 'collapse_all_checkbox' in self.ui and self.ui['collapse_all_checkbox'] else None)

        # Auto Refresh Shortcut (Alt+R)
        self.auto_refresh_shortcut_action = QAction("Auto Refresh Shortcut", self.main_window)
        self.auto_refresh_shortcut_action.setShortcut(QKeySequence("Alt+R"))
        # Connect shortcut to toggle the checkbox, which triggers UIStateManager via stateChanged signal
        self.auto_refresh_shortcut_action.triggered.connect(lambda: self.ui['auto_refresh_checkbox'].toggle() if 'auto_refresh_checkbox' in self.ui and self.ui['auto_refresh_checkbox'] else None)

        # Untangle Shortcut (Alt+U)
        self.untangle_shortcut_action = QAction("Untangle Shortcut", self.main_window)
        self.untangle_shortcut_action.setShortcut(QKeySequence("Alt+U"))
        # Connect directly to UIStateManager's handler
        self.untangle_shortcut_action.triggered.connect(self.state_manager._handle_untangle_shortcut)

        # Font Size Increase Shortcut (Ctrl++/Ctrl+=)
        self.increase_font_action = QAction("Increase Font Size", self.main_window)
        self.increase_font_action.setShortcuts([
            QKeySequence.StandardKey.ZoomIn,  # Standard Ctrl++
            QKeySequence("Ctrl++"),
            QKeySequence("Ctrl+=")
        ])
        # Connect to a new handler method
        self.increase_font_action.triggered.connect(self._handle_increase_font_size)

        # Font Size Decrease Shortcut (Ctrl+-)
        self.decrease_font_action = QAction("Decrease Font Size", self.main_window)
        self.decrease_font_action.setShortcut(QKeySequence.StandardKey.ZoomOut)  # Standard Ctrl+-
        # Connect to a new handler method
        self.decrease_font_action.triggered.connect(self._handle_decrease_font_size)

        # Tab key for switching focus between trees
        self.tab_switch_action = QAction("Switch Focus Forwards", self.main_window)
        self.tab_switch_action.setShortcut(QKeySequence(Qt.Key.Key_Tab))
        self.tab_switch_action.triggered.connect(lambda: self._handle_tab_switch(forwards=True)) # Connect to internal handler

        # Shift+Tab for switching focus in reverse
        self.tab_switch_back_action = QAction("Switch Focus Backwards", self.main_window)
        self.tab_switch_back_action.setShortcut(QKeySequence(Qt.Key.Key_Backtab))  # Backtab is Shift+Tab
        self.tab_switch_back_action.triggered.connect(lambda: self._handle_tab_switch(forwards=False)) # Connect to internal handler

        # --- Preset Shortcuts (Global) ---
        # Save Preset Shortcut (Ctrl+S)
        self.save_preset_action = QAction("Save Preset Shortcut", self.main_window)
        self.save_preset_action.setShortcut(QKeySequence("Ctrl+S"))
        # Connect directly to PresetHandler's method
        self.save_preset_action.triggered.connect(self.preset_handler._save_current_loaded_preset)
        self.save_preset_action.setEnabled(False)  # Initially disabled (state managed by main_window/preset_handler)

        # Default Preset Shortcut (Ctrl+Shift+R)
        self.default_preset_action = QAction("Default", self.main_window) # MODIFIED TEXT
        self.default_preset_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        # Connect directly to PresetHandler's method
        self.default_preset_action.triggered.connect(self.preset_handler._handle_default_preset_action)

        # --- PortTreeWidget Actions (Move Up/Down) ---
        self.move_group_up_action = QAction("Move Up", self.main_window)
        self.move_group_up_action.setShortcut(QKeySequence("Alt+Up"))
        self.move_group_up_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # Context needed
        self.move_group_up_action.triggered.connect(self._handle_move_group_up) # Connect to internal handler

        self.move_group_down_action = QAction("Move Down", self.main_window)
        self.move_group_down_action.setShortcut(QKeySequence("Alt+Down"))
        self.move_group_down_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # Context needed
        self.move_group_down_action.triggered.connect(self._handle_move_group_down) # Connect to internal handler

    def _add_actions_to_window(self):
        """Add the pre-defined QAction objects (with shortcuts) to the main window."""
        # Actions are defined in _setup_actions
        self.main_window.addAction(self.connect_action)
        self.main_window.addAction(self.disconnect_action)
        self.main_window.addAction(self.undo_shortcut_action)
        self.main_window.addAction(self.redo_shortcut_action)
        self.main_window.addAction(self.refresh_shortcut_action)
        self.main_window.addAction(self.collapse_all_shortcut_action)
        self.main_window.addAction(self.auto_refresh_shortcut_action)
        self.main_window.addAction(self.untangle_shortcut_action)
        self.main_window.addAction(self.increase_font_action)
        self.main_window.addAction(self.decrease_font_action)
        self.main_window.addAction(self.tab_switch_action)
        self.main_window.addAction(self.tab_switch_back_action)
        self.main_window.addAction(self.save_preset_action)
        self.main_window.addAction(self.default_preset_action)
        self.main_window.addAction(self.move_group_up_action)
        self.main_window.addAction(self.move_group_down_action)

    # --- Handler Methods ---

    def _animate_button_press(self, button):
        """
        Animates a button press by briefly changing its style and then restoring it.

        Args:
            button: The button to animate
        """
        if not button:
            return

        # Store original style
        original_style = button.styleSheet()

        # Skip if already in pressed state
        if "inset" in original_style:
            return

        # Apply pressed style (uses colors from main_window)
        pressed_style = f"""
            QPushButton {{
                background-color: {self.main_window.highlight_color.name()};
                color: {self.main_window.text_color.name()};
                border: 2px inset {self.main_window.highlight_color.darker(120).name()};
            }}
        """
        button.setStyleSheet(pressed_style)

        # Restore original style after a short delay
        QTimer.singleShot(150, lambda: button.setStyleSheet(original_style))

    def _handle_connect(self):
        """Calls the appropriate connect method based on the current tab."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return
        current_index = tab_widget.currentIndex()

        if current_index == 0:  # Audio Tab
            connect_button = self.ui.get('connect_button')
            if connect_button: self._animate_button_press(connect_button)
            self.main_window.make_connection_selected()
        elif current_index == 1:  # MIDI Tab
            midi_connect_button = self.ui.get('midi_connect_button')
            if midi_connect_button: self._animate_button_press(midi_connect_button)
            self.main_window.make_midi_connection_selected()
        elif current_index == 2:  # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw:
                if hasattr(graph_mw, 'connect_button'):
                    self._animate_button_press(graph_mw.connect_button)
                if hasattr(graph_mw, 'handle_connect_action'):
                    graph_mw.handle_connect_action()
        # Ignore if on other tabs

    def _handle_disconnect(self):
        """Calls the appropriate disconnect method based on the current tab."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return
        current_index = tab_widget.currentIndex()

        if current_index == 0:  # Audio Tab
            disconnect_button = self.ui.get('disconnect_button')
            if disconnect_button: self._animate_button_press(disconnect_button)
            self.main_window.break_connection_selected()
        elif current_index == 1:  # MIDI Tab
            midi_disconnect_button = self.ui.get('midi_disconnect_button')
            if midi_disconnect_button: self._animate_button_press(midi_disconnect_button)
            self.main_window.break_midi_connection_selected()
        elif current_index == 2:  # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw:
                if hasattr(graph_mw, 'disconnect_button'):
                    self._animate_button_press(graph_mw.disconnect_button)
                if hasattr(graph_mw, 'handle_disconnect_action'):
                    graph_mw.handle_disconnect_action()
        # Ignore if on other tabs

    def _handle_undo(self):
        """Undo the last connection action using the handler."""
        tab_widget = self.ui.get('tab_widget')
        current_index = tab_widget.currentIndex() if tab_widget else -1

        if current_index == 2: # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'undo_button'):
                self._animate_button_press(graph_mw.undo_button)
            # The graph tab's undo button click calls graph_mw._handle_graph_undo directly.
            # If the shortcut is global, we might need to call that handler if on graph tab.
            if graph_mw and hasattr(graph_mw, '_handle_graph_undo'):
                graph_mw._handle_graph_undo() # Call graph's own undo handler
                return # Prevent further processing by global undo
        else: # Audio/MIDI or other tabs
            undo_button = self.ui.get('undo_button') # Main undo button for Audio/MIDI
            if undo_button: self._animate_button_press(undo_button)

        # Global undo logic (for Audio/MIDI tabs or if Graph tab doesn't handle it)
        action = self.main_window.connection_history.undo() # Access history via main_window
        if action:
            action_type, output_name, input_name, is_midi = action # Unpack is_midi
            # is_midi is now directly from history, heuristic no longer needed.
            # is_midi = ':midi_' in output_name or ':midi_' in input_name or output_name.startswith('midi_') or input_name.startswith('midi_')

            try:
                # Perform the action returned by undo() (which is the inverse of the original)
                if action_type == 'disconnect': # Inverse action is disconnect (original was connect)
                    if is_midi:
                        self.connection_handler.break_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.break_connection(output_name, input_name, is_undo_redo=True)
                elif action_type == 'connect': # Inverse action is connect (original was disconnect)
                    if is_midi:
                        self.connection_handler.make_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.make_connection(output_name, input_name, is_undo_redo=True)
                # Note: UI updates (buttons, visuals, ports) are handled within the handler's _port_operation
                if hasattr(self.main_window, 'notify_connection_history_changed'):
                    self.main_window.notify_connection_history_changed()

            except jack.JackError as e: # Should be caught by handler, but keep for safety
                print(f"Undo error during handler call: {e}")
            # History is managed by the handler, button updates are triggered by handler
            if hasattr(self.main_window, 'notify_connection_history_changed'): # Also notify on error to update buttons
                self.main_window.notify_connection_history_changed()


    def _handle_redo(self):
        """Redo the last undone connection action using the handler."""
        tab_widget = self.ui.get('tab_widget')
        current_index = tab_widget.currentIndex() if tab_widget else -1

        if current_index == 2: # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'redo_button'):
                self._animate_button_press(graph_mw.redo_button)
            # Similar to undo, call graph's specific redo handler if shortcut is global.
            if graph_mw and hasattr(graph_mw, '_handle_graph_redo'):
                graph_mw._handle_graph_redo() # Call graph's own redo handler
                return # Prevent further processing by global redo
        else: # Audio/MIDI or other tabs
            redo_button = self.ui.get('redo_button') # Main redo button for Audio/MIDI
            if redo_button: self._animate_button_press(redo_button)

        # Global redo logic (for Audio/MIDI tabs or if Graph tab doesn't handle it)
        action = self.main_window.connection_history.redo() # Access history via main_window
        if action:
            action_type, output_name, input_name, is_midi = action # Unpack is_midi
            # is_midi is now directly from history, heuristic no longer needed.
            # is_midi = ':midi_' in output_name or ':midi_' in input_name or output_name.startswith('midi_') or input_name.startswith('midi_')

            try:
                # Perform the *original* action using the connection_handler
                if action_type == 'connect':
                    if is_midi:
                        self.connection_handler.make_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.make_connection(output_name, input_name, is_undo_redo=True)
                else: # Action was disconnect
                    if is_midi:
                        self.connection_handler.break_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.break_connection(output_name, input_name, is_undo_redo=True)
                # UI updates handled within handler's _port_operation
                if hasattr(self.main_window, 'notify_connection_history_changed'):
                    self.main_window.notify_connection_history_changed()

            except jack.JackError as e: # Should be caught by handler
                print(f"Redo error during handler call: {e}")
            # History managed by handler, button updates triggered by handler
            if hasattr(self.main_window, 'notify_connection_history_changed'): # Also notify on error
                self.main_window.notify_connection_history_changed()

    def _get_focused_tree_widget(self):
        """Finds which PortTreeWidget currently has focus."""
        focused_widget = QApplication.focusWidget()
        # Check if the focused widget itself is a PortTreeWidget (has 'port_items')
        if hasattr(focused_widget, 'port_items'):
            return focused_widget
        # Check parents if focus is on a child widget within the tree
        while focused_widget is not None:
            if hasattr(focused_widget, 'port_items'):
                return focused_widget
            focused_widget = focused_widget.parent()
        return None

    def _handle_move_group_up(self):
        """Handles the global 'Move Up' action trigger."""
        focused_tree = self._get_focused_tree_widget()
        if focused_tree:
            item = focused_tree.currentItem()
            if item and item.parent() is None:  # Only move top-level items (groups)
                focused_tree.move_group_up(item) # Call method on the tree widget itself

    def _handle_move_group_down(self):
        """Handles the global 'Move Down' action trigger."""
        focused_tree = self._get_focused_tree_widget()
        if focused_tree:
            item = focused_tree.currentItem()
            if item and item.parent() is None:  # Only move top-level items (groups)
                focused_tree.move_group_down(item) # Call method on the tree widget itself

    def _handle_tab_switch(self, forwards=True):
        """Switch focus between output and input trees in the current tab."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return
        current_tab = tab_widget.currentIndex()
        is_midi = current_tab == 1

        output_tree = self.ui.get('output_tree')
        input_tree = self.ui.get('input_tree')
        midi_output_tree = self.ui.get('midi_output_tree')
        midi_input_tree = self.ui.get('midi_input_tree')

        if current_tab == 0:  # Audio tab
            trees = [output_tree, input_tree] if forwards else [input_tree, output_tree]
        elif current_tab == 1:  # MIDI tab
            trees = [midi_output_tree, midi_input_tree] if forwards else [midi_input_tree, midi_output_tree]
        else:
            return  # Do nothing on other tabs

        # Filter out None trees in case some UI elements weren't passed
        trees = [tree for tree in trees if tree]
        if not trees: return # No valid trees for this tab

        # Find which tree currently has focus
        current_tree = None
        for tree in trees:
            if tree and tree.hasFocus(): # Check if tree exists
                current_tree = tree
                break

        # Switch focus to the other tree
        if current_tree:
            other_tree = trees[1] if current_tree == trees[0] else trees[0]
            if not other_tree: return # Check if other tree exists

            # Get selected ports from current tree (using main_window method)
            selected_ports = self.main_window._get_ports_from_selected_items(current_tree)

            # Find connected ports in the other tree
            if selected_ports:
                # Determine direction based on which tree we're moving from
                is_input_to_output = current_tree in (input_tree, midi_input_tree)
                connected_ports = self._get_connected_ports(selected_ports, is_input_to_output, is_midi)

                # Clear current selection in destination tree
                other_tree.clearSelection()

                # Select connected ports in destination tree
                for port_name in connected_ports:
                    port_item = other_tree.port_items.get(port_name)
                    if port_item:
                        port_item.setSelected(True)

            # Set focus to destination tree
            other_tree.setFocus()

            # Update button states after selection and focus change (using main_window methods)
            if is_midi:
                self.main_window.update_midi_connection_buttons()
            else:
                self.main_window.update_connection_buttons()
        elif trees[0]: # If no tree has focus, focus the first one if it exists
            trees[0].setFocus()

    def _get_connected_ports(self, port_names, is_input_to_output=True, is_midi=False):
        """
        Get connected ports for the given port names.
        Uses the main_window's JACK client.

        Args:
            port_names: List of port names to check connections for.
            is_input_to_output: True if checking connections *from* the given input ports *to* output ports.
                                False if checking connections *from* the given output ports *to* input ports.
            is_midi: Boolean indicating if these are MIDI ports.

        Returns:
            list: A list of connected port names.
        """
        connected_ports = set()
        client = self.main_window.client # Use client from main_window
        try:
            if is_input_to_output:
                # From input to output - look at all output ports
                output_ports = client.get_ports(is_output=True, is_midi=is_midi)
                for output_port in output_ports:
                    try:
                        # Get ports connected *to this output*
                        connections = client.get_all_connections(output_port)
                        # Check if any of the *source* ports (the ones connected *to* this output)
                        # are in our original list of input ports.
                        # Note: JACK API get_all_connections(output_port) returns the *input* ports it's connected to.
                        # This logic seems reversed. Let's rethink.

                        # We have a list of INPUT ports (port_names).
                        # We want to find the OUTPUT ports connected TO these input ports.
                        # Iterate through all OUTPUT ports.
                        # For each OUTPUT port, get its connections (which are INPUT ports).
                        # If any of those connected INPUT ports are in our port_names list,
                        # then this OUTPUT port is one we're looking for.
                        connected_inputs = client.get_all_connections(output_port)
                        if any(conn.name in port_names for conn in connected_inputs):
                             connected_ports.add(output_port.name)

                    except jack.JackError:
                        continue # Skip this output port if error
            else:
                # From output to input - get direct connections for each output port
                for port_name in port_names:
                    try:
                        # Get the input ports connected *to this output port*
                        connections = client.get_all_connections(port_name)
                        connected_ports.update(conn.name for conn in connections)
                    except jack.JackError:
                        continue # Skip this output port if error
        except jack.JackError as e:
            print(f"Error getting connected ports: {e}")
        return list(connected_ports)

    def _handle_increase_font_size(self):
        """Handles the increase font size action, only applying if Audio or MIDI tab is active."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return
        current_index = tab_widget.currentIndex()

        if current_index == 0 or current_index == 1:  # Audio Tab (0) or MIDI Tab (1)
            self.state_manager.increase_font_size()
        elif current_index == 2: # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'view') and hasattr(graph_mw.view, 'zoom_in'):
                graph_mw.view.zoom_in()
        # If other tabs are active, the action does nothing for these specific tabs,
        # allowing Ctrl++ to be potentially used by other functionalities on those other tabs.

    def _handle_decrease_font_size(self):
        """Handles the decrease font size action, only applying if Audio or MIDI tab is active."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return
        current_index = tab_widget.currentIndex()

        if current_index == 0 or current_index == 1:  # Audio Tab (0) or MIDI Tab (1)
            self.state_manager.decrease_font_size()
        elif current_index == 2: # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'view') and hasattr(graph_mw.view, 'zoom_out'):
                graph_mw.view.zoom_out()
        # If other tabs are active, the action does nothing for these specific tabs,
        # allowing Ctrl+- to be potentially used by other functionalities on those other tabs.