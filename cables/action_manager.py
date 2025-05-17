# cables/action_manager.py

import random
import jack
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtGui import QKeySequence, QColor, QPainterPath, QPen, QAction
from PyQt6.QtCore import Qt, QTimer, QPointF
from cables.features.mixer import AlsMixerApp # Import AlsMixerApp

class ActionManager:
    """Manages QActions and QShortcuts for the application."""

    def __init__(self, main_window, connection_handler, preset_handler, ui):
        """
        Initialize the ActionManager and define QAction objects.
        Signal connections and shortcut registration will be done in complete_setup.

        Args:
            main_window: The main application window (JackConnectionManager instance).
            connection_handler: The JackConnectionHandler instance.
            preset_handler: The PresetHandler instance.
            ui: Dictionary-like object containing relevant UI elements from main_window.
        """
        self.main_window = main_window
        self.connection_handler = connection_handler
        self.preset_handler = preset_handler
        self.ui = ui # Store the UI elements reference
        self.state_manager = None # Will be set in complete_setup

        # --- Action Attributes ---
        # Define all action attributes first
        # Generic global shortcuts
        self.global_connect_action = None # Renamed from connect_action
        self.global_disconnect_action = None # Renamed from disconnect_action
        self.global_undo_action = None # Renamed from undo_shortcut_action
        self.global_redo_action = None # Renamed from redo_shortcut_action
        
        # Port Tab Actions (Audio/MIDI)
        self.audio_connect_action = None
        self.audio_disconnect_action = None
        self.midi_connect_action = None
        self.midi_disconnect_action = None
        self.refresh_ports_action = None # Renamed from refresh_shortcut_action
        self.presets_action = None # For Audio/MIDI tabs

        # Graph Tab Actions
        self.graph_connect_action = None
        self.graph_disconnect_action = None
        self.graph_undo_action = None
        self.graph_redo_action = None
        self.presets_graph_action = None # For Graph tab
        
        # Zoom Actions (used by Graph and Port List Font Size)
        self.zoom_in_action = None # Renamed from increase_font_action
        self.zoom_out_action = None # Renamed from decrease_font_action

        # Other existing actions
        self.collapse_all_shortcut_action = None
        self.auto_refresh_shortcut_action = None
        self.untangle_shortcut_action = None
        self.tab_switch_action = None
        self.tab_switch_back_action = None
        self.save_preset_action = None
        self.default_preset_action = None
        self.move_group_up_action = None
        self.move_group_down_action = None

        self._define_all_actions()

    def _define_all_actions(self):
        """Define all QAction objects and their basic properties (text, shortcuts)."""
        # --- Global Shortcut Actions ---
        self.global_connect_action = QAction("Connect Shortcut", self.main_window)
        self.global_connect_action.setShortcut(QKeySequence(Qt.Key.Key_C))

        self.global_disconnect_action = QAction("Disconnect Shortcut", self.main_window)
        self.global_disconnect_action.setShortcuts([QKeySequence(Qt.Key.Key_D), QKeySequence(Qt.Key.Key_Delete)])

        self.global_undo_action = QAction("Undo Shortcut", self.main_window)
        self.global_undo_action.setShortcut(QKeySequence.StandardKey.Undo)

        self.global_redo_action = QAction("Redo Shortcut", self.main_window)
        self.global_redo_action.setShortcuts([QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Y")])

        # --- Port Tab Specific Actions (Audio/MIDI) ---
        self.audio_connect_action = QAction("Connect", self.main_window)
        self.audio_disconnect_action = QAction("Disconnect", self.main_window)
        self.midi_connect_action = QAction("Connect", self.main_window)
        self.midi_disconnect_action = QAction("Disconnect", self.main_window)

        self.refresh_ports_action = QAction("Refresh", self.main_window)
        self.refresh_ports_action.setShortcut(QKeySequence(Qt.Key.Key_R))

        self.presets_action = QAction("Presets", self.main_window)
        self.presets_menu = QMenu(self.main_window)
        self.presets_action.setMenu(self.presets_menu)
        if not self.preset_handler: # Check if preset_handler is None
            self.presets_action.setEnabled(False)
        else:
            self.presets_action.setEnabled(True)


        # --- Graph Tab Specific Actions ---
        self.graph_connect_action = QAction("Connect", self.main_window)
        self.graph_disconnect_action = QAction("Disconnect", self.main_window)
        self.graph_undo_action = QAction("       Undo       ", self.main_window) # Added padding
        self.graph_redo_action = QAction("       Redo       ", self.main_window) # Added padding
        
        self.presets_graph_action = QAction("Presets", self.main_window)
        self.presets_graph_menu = QMenu(self.main_window)
        self.presets_graph_action.setMenu(self.presets_graph_menu)
        if not self.preset_handler: # Check if preset_handler is None
            self.presets_graph_action.setEnabled(False)
        else:
            self.presets_graph_action.setEnabled(True)


        # --- Zoom Actions (used by Graph and Port List Font Size) ---
        self.zoom_in_action = QAction("+", self.main_window)
        self.zoom_in_action.setShortcuts([
            QKeySequence.StandardKey.ZoomIn, QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")
        ])

        self.zoom_out_action = QAction("-", self.main_window)
        self.zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)

        # --- Other Existing Actions ---
        self.collapse_all_shortcut_action = QAction("Collapse All Shortcut", self.main_window)
        self.collapse_all_shortcut_action.setShortcut(QKeySequence("Alt+C"))

        self.auto_refresh_shortcut_action = QAction("Auto Refresh Shortcut", self.main_window)
        self.auto_refresh_shortcut_action.setShortcut(QKeySequence("Alt+R"))

        self.untangle_shortcut_action = QAction("Untangle Shortcut", self.main_window)
        self.untangle_shortcut_action.setShortcut(QKeySequence("Alt+U"))

        self.tab_switch_action = QAction("Switch Focus Forwards", self.main_window)
        self.tab_switch_action.setShortcut(QKeySequence(Qt.Key.Key_Tab))

        self.tab_switch_back_action = QAction("Switch Focus Backwards", self.main_window)
        self.tab_switch_back_action.setShortcut(QKeySequence(Qt.Key.Key_Backtab))

        self.save_preset_action = QAction("Save Preset Shortcut", self.main_window)
        self.save_preset_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_preset_action.setEnabled(False)

        self.default_preset_action = QAction("Default", self.main_window)
        self.default_preset_action.setShortcut(QKeySequence("Ctrl+Shift+R"))

        self.move_group_up_action = QAction("Move Up", self.main_window)
        self.move_group_up_action.setShortcut(QKeySequence("Alt+Up"))
        self.move_group_up_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.move_group_down_action = QAction("Move Down", self.main_window)
        self.move_group_down_action.setShortcut(QKeySequence("Alt+Down"))
        self.move_group_down_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def complete_setup(self, state_manager):
        """Connects action signals and adds shortcuts to the window."""
        self.state_manager = state_manager # Now state_manager is available
        self._connect_all_signals()
        self._add_actions_to_window()

    def _connect_all_signals(self):
        """Connect all QAction signals to their handlers."""
        # --- Global Shortcut Actions ---
        self.global_connect_action.triggered.connect(self._handle_global_connect_shortcut)
        self.global_disconnect_action.triggered.connect(self._handle_global_disconnect_shortcut)
        self.global_undo_action.triggered.connect(self._handle_global_undo_shortcut)
        self.global_redo_action.triggered.connect(self._handle_global_redo_shortcut)

        # --- Port Tab Specific Actions (Audio/MIDI) ---
        self.audio_connect_action.triggered.connect(self.main_window.make_connection_selected)
        self.audio_disconnect_action.triggered.connect(self.main_window.break_connection_selected)
        self.midi_connect_action.triggered.connect(self.main_window.make_midi_connection_selected)
        self.midi_disconnect_action.triggered.connect(self.main_window.break_midi_connection_selected)
        self.refresh_ports_action.triggered.connect(lambda: self.main_window.refresh_ports(from_shortcut=True))
        
        if self.preset_handler: # Connect menu signal only if handler exists
            self.presets_menu.aboutToShow.connect(self.preset_handler._show_preset_menu)

        # --- Graph Tab Specific Actions ---
        self.graph_connect_action.triggered.connect(self._handle_graph_connect)
        self.graph_disconnect_action.triggered.connect(self._handle_graph_disconnect)
        self.graph_undo_action.triggered.connect(self._handle_graph_undo)
        self.graph_redo_action.triggered.connect(self._handle_graph_redo)
        
        if self.preset_handler: # Connect menu signal only if handler exists
            self.presets_graph_menu.aboutToShow.connect(self.preset_handler._show_preset_menu)

        # --- Zoom Actions ---
        self.zoom_in_action.triggered.connect(self._handle_increase_font_size)
        self.zoom_out_action.triggered.connect(self._handle_decrease_font_size)

        # --- Other Existing Actions ---
        self.collapse_all_shortcut_action.triggered.connect(lambda: self.ui['collapse_all_checkbox'].toggle() if 'collapse_all_checkbox' in self.ui and self.ui['collapse_all_checkbox'] else None)
        self.auto_refresh_shortcut_action.triggered.connect(lambda: self.ui['auto_refresh_checkbox'].toggle() if 'auto_refresh_checkbox' in self.ui and self.ui['auto_refresh_checkbox'] else None)
        
        # Ensure state_manager is available before connecting signals that use it
        if self.state_manager:
            self.untangle_shortcut_action.triggered.connect(self.state_manager._handle_untangle_shortcut)
        else:
            print("ActionManager: state_manager not available for untangle_shortcut_action connection.")


        self.tab_switch_action.triggered.connect(lambda: self._handle_tab_switch(forwards=True))
        self.tab_switch_back_action.triggered.connect(lambda: self._handle_tab_switch(forwards=False))
        self.save_preset_action.triggered.connect(self.preset_handler._save_current_loaded_preset)
        self.default_preset_action.triggered.connect(self.preset_handler._handle_default_preset_action)
        self.move_group_up_action.triggered.connect(self._handle_move_group_up)
        self.move_group_down_action.triggered.connect(self._handle_move_group_down)

    def _add_actions_to_window(self):
        """Add QAction objects with shortcuts to the main window."""
        actions_with_shortcuts = [
            self.global_connect_action, self.global_disconnect_action,
            self.global_undo_action, self.global_redo_action,
            self.refresh_ports_action, self.collapse_all_shortcut_action,
            self.auto_refresh_shortcut_action, self.untangle_shortcut_action,
            self.zoom_in_action, self.zoom_out_action,
            self.tab_switch_action, self.tab_switch_back_action,
            self.save_preset_action, self.default_preset_action,
            self.move_group_up_action, self.move_group_down_action
        ]
        for action in actions_with_shortcuts:
            if action: # Ensure action is defined
                self.main_window.addAction(action)

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

    def _handle_global_connect_shortcut(self):
        """Handles the global 'C' key shortcut for connect."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return
        current_index = tab_widget.currentIndex()

        if current_index == 0:  # Audio Tab
            if self.audio_connect_action: self.audio_connect_action.trigger()
            audio_button = self.ui.get('connect_button') # This is manager.connect_button
            if audio_button: self._animate_button_press(audio_button)
        elif current_index == 1:  # MIDI Tab
            if self.midi_connect_action: self.midi_connect_action.trigger()
            midi_button = self.ui.get('midi_connect_button') # This is manager.midi_connect_button
            if midi_button: self._animate_button_press(midi_button)
        elif current_index == 2:  # Graph Tab
            if self.graph_connect_action: self.graph_connect_action.trigger()
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'connect_button'): # graph_mw.connect_button is the QToolButton
                 self._animate_button_press(graph_mw.connect_button)
        # Ignore if on other tabs

    def _handle_global_disconnect_shortcut(self):
        """Handles the global 'D'/Delete key shortcut for disconnect."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return
        current_index = tab_widget.currentIndex()

        if current_index == 0:  # Audio Tab
            if self.audio_disconnect_action: self.audio_disconnect_action.trigger()
            audio_button = self.ui.get('disconnect_button')
            if audio_button: self._animate_button_press(audio_button)
        elif current_index == 1:  # MIDI Tab
            if self.midi_disconnect_action: self.midi_disconnect_action.trigger()
            midi_button = self.ui.get('midi_disconnect_button')
            if midi_button: self._animate_button_press(midi_button)
        elif current_index == 2:  # Graph Tab
            if self.graph_disconnect_action: self.graph_disconnect_action.trigger()
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'disconnect_button'):
                 self._animate_button_press(graph_mw.disconnect_button)
        # Ignore if on other tabs

    def _handle_global_undo_shortcut(self):
        """Handles the global Ctrl+Z shortcut for undo."""
        tab_widget = self.ui.get('tab_widget')
        current_index = tab_widget.currentIndex() if tab_widget else -1

        if current_index == 2: # Graph Tab
            if self.graph_undo_action: self.graph_undo_action.trigger()
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'undo_button'):
                self._animate_button_press(graph_mw.undo_button)
            return # Graph action handles its own logic
        
        # Audio/MIDI or other tabs (use main window's undo logic)
        # This part remains for non-graph undo, assuming main_window has undo_button for these.
        # The refactor primarily affected button creation, not necessarily the core undo logic for audio/midi.
        # However, if audio/midi tabs also get dedicated undo buttons via shared_widgets,
        # this global handler might need to animate those too.
        # For now, assume existing global undo logic for non-graph tabs is okay.
        undo_button = self.ui.get('undo_button') # Main undo button for Audio/MIDI if it exists
        if undo_button: self._animate_button_press(undo_button)
        
        # Original global undo logic (for Audio/MIDI tabs)
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


    def _handle_global_redo_shortcut(self):
        """Handles the global Ctrl+Y/Ctrl+Shift+Z shortcut for redo."""
        tab_widget = self.ui.get('tab_widget')
        current_index = tab_widget.currentIndex() if tab_widget else -1

        if current_index == 2: # Graph Tab
            if self.graph_redo_action: self.graph_redo_action.trigger()
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'redo_button'):
                self._animate_button_press(graph_mw.redo_button)
            return # Graph action handles its own logic

        # Audio/MIDI or other tabs
        redo_button = self.ui.get('redo_button') # Main redo button for Audio/MIDI
        if redo_button: self._animate_button_press(redo_button)

        # Original global redo logic (for Audio/MIDI tabs)
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

        current_widget = tab_widget.currentWidget()
        if isinstance(current_widget, AlsMixerApp):
            # Let AlsMixerApp handle its own zoom shortcuts
            return

        current_index = tab_widget.currentIndex()

        if current_index == 0 or current_index == 1:  # Audio Tab (0) or MIDI Tab (1)
            self.state_manager.increase_font_size()
        elif current_index == 2: # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'view') and hasattr(graph_mw.view, 'zoom_in'):
                graph_mw.view.zoom_in()
        # If other tabs are active (and not AlsMixerApp), the action does nothing for these specific tabs,
        # allowing Ctrl++ to be potentially used by other functionalities on those other tabs.

    def _handle_decrease_font_size(self):
        """Handles the decrease font size action, only applying if Audio or MIDI tab is active."""
        tab_widget = self.ui.get('tab_widget')
        if not tab_widget: return

        current_widget = tab_widget.currentWidget()
        if isinstance(current_widget, AlsMixerApp):
            # Let AlsMixerApp handle its own zoom shortcuts
            return

        current_index = tab_widget.currentIndex()

        if current_index == 0 or current_index == 1:  # Audio Tab (0) or MIDI Tab (1)
            self.state_manager.decrease_font_size()
        elif current_index == 2: # Graph Tab
            graph_mw = self.ui.get('graph_main_window')
            if graph_mw and hasattr(graph_mw, 'view') and hasattr(graph_mw.view, 'zoom_out'):
                graph_mw.view.zoom_out()
        # If other tabs are active (and not AlsMixerApp), the action does nothing for these specific tabs,
        # allowing Ctrl+- to be potentially used by other functionalities on those other tabs.

    # --- New Handler Methods for Graph Actions ---
    def _handle_graph_connect(self):
        graph_mw = self.ui.get('graph_main_window')
        if graph_mw and hasattr(graph_mw, 'handle_connect_action'):
            graph_mw.handle_connect_action()

    def _handle_graph_disconnect(self):
        graph_mw = self.ui.get('graph_main_window')
        if graph_mw and hasattr(graph_mw, 'handle_disconnect_action'):
            graph_mw.handle_disconnect_action()

    def _handle_graph_undo(self):
        graph_mw = self.ui.get('graph_main_window')
        if graph_mw and hasattr(graph_mw, '_handle_graph_undo'):
            graph_mw._handle_graph_undo()

    def _handle_graph_redo(self):
        graph_mw = self.ui.get('graph_main_window')
        if graph_mw and hasattr(graph_mw, '_handle_graph_redo'):
            graph_mw._handle_graph_redo()