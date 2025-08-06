from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLineEdit, QSpacerItem, QSizePolicy, QMessageBox, QToolButton, QMenu)
from PyQt6.QtCore import pyqtSlot, QSize # Added QSize
from PyQt6.QtGui import QAction, QKeySequence, QIcon # Added for shortcuts and icons

from cables.ui.shared_widgets import create_action_button
import jack # For jack.Client type hint
# from cables.connection_manager import JackConnectionManager # For type hint - REMOVED to break cycle
from .jack_handler import GraphJackHandler # Updated import
from .gui_scene import JackGraphScene
from .gui_view import JackGraphView
from .port_item import PortItem
from .connection_item import ConnectionItem
from .constants import GRAPH_TOOLBAR_UNDO_REDO_OFFSET
from cable_core import app_config
import os
import configparser
import copy

# Special value to represent the original layout in the untangle cycle
ORIGINAL_LAYOUT = -1

class MainWindow(QMainWindow):
    def __init__(self, jack_client: jack.Client, connection_manager: 'JackConnectionManager', preset_handler_ref, connection_history_ref):
        super().__init__()
        self.jack_client = jack_client # Store the shared jack.Client instance
        self.connection_manager = connection_manager # Store the JackConnectionManager instance
        self.preset_handler = preset_handler_ref # Store the reference
        self.connection_history = connection_history_ref # Store the reference
        # self.jack_handler is removed, GraphJackHandler is now part of JackGraphScene
        
        # Load untangle values from config or use defaults
        self.untangle_values = self._load_untangle_values()
        
        # Add the special value for original layout to the untangle values
        if ORIGINAL_LAYOUT not in self.untangle_values:
            self.untangle_values.append(ORIGINAL_LAYOUT)
        
        # Current max_nodes_per_row value for untangle
        self.current_untangle_setting = self.untangle_values[0] if self.untangle_values else 6  # Default value
        # Track if untangle has been used at least once
        self.untangle_button_clicked = False
        
        # Will store the initial node positions
        self.initial_node_positions = None

        self.setWindowTitle("PyQt JACK Graph")
        self.setGeometry(100, 100, 1000, 700)

        # JackGraphScene now takes jack_client, connection_manager, connection_history, and parent (self)
        self.scene = JackGraphScene(
            jack_client=self.jack_client,
            connection_manager=self.connection_manager,
            connection_history=self.connection_history,
            parent=self # Pass self as parent, which JackGraphScene uses as main_window_ref for its GraphJackHandler
        )
        self.view = JackGraphView(self.scene)
        
        # Store initial node positions after the scene is fully loaded
        self.scene.scene_fully_loaded.connect(self._store_initial_node_positions)

        # Main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5) # Small margins
        main_layout.setSpacing(5)

        # Create buttons using shared_widgets factory
        # Assumes self.connection_manager.action_manager provides the necessary QAction instances
        action_manager = self.connection_manager.action_manager

        self.graph_connect_action = action_manager.graph_connect_action
        self.connect_button = create_action_button(self, self.graph_connect_action, tooltip="Connect selected items <span style='color:grey'>C</span>")

        self.graph_disconnect_action = action_manager.graph_disconnect_action
        self.disconnect_button = create_action_button(self, self.graph_disconnect_action, tooltip="Disconnect selected items <span style='color:grey'>D/Del</span>")

        self.presets_graph_action = action_manager.presets_graph_action # This action should have text "Presets" and its menu configured
        self.preset_button = create_action_button(self, self.presets_graph_action, tooltip="Manage Presets")
        self.preset_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup) # Ensure popup mode for menu

        self.graph_undo_action = action_manager.graph_undo_action
        self.undo_button = create_action_button(
            self,
            self.graph_undo_action,
            tooltip="Undo last connection <span style='color:grey'>Ctrl+Z</span>",
            min_width=90
        )

        self.graph_redo_action = action_manager.graph_redo_action
        self.redo_button = create_action_button(
            self,
            self.graph_redo_action,
            tooltip="Redo last connection <span style='color:grey'>Shift+Ctrl+Z/Ctrl+Y</span>",
            min_width=90
        )
        
        # Create Untangle button and action
        self.untangle_action = QAction("Untangle", self)
        next_value = self._get_next_untangle_value()
        # At startup, only show the next value in the tooltip
        self.untangle_action.setToolTip(f"Automatically organize nodes to reduce visual clutter (next: {next_value})")
        self.untangle_action.triggered.connect(self._handle_untangle)
        self.untangle_button = create_action_button(
            self,
            self.untangle_action,
            tooltip=f"Reorganize graph (next: {next_value})",
            min_width=100
        )

        self.zoom_in_action = action_manager.zoom_in_action # Assuming generic zoom actions
        self.zoom_in_button = create_action_button(
            self,
            self.zoom_in_action,
            tooltip="Zoom In <span style='color:grey'>Ctrl++/Ctrl+Scroll</span>",
            fixed_size=QSize(25, 25)
        )

        self.zoom_out_action = action_manager.zoom_out_action
        self.zoom_out_button = create_action_button(
            self,
            self.zoom_out_action,
            tooltip="Zoom Out <span style='color:grey'>Ctrl+-/Ctrl+Scroll</span>",
            fixed_size=QSize(25, 25)
        )

        # Create filter boxes
        self.node_filter_box = QLineEdit()
        self.node_filter_box.setPlaceholderText("Filter Clients...")
        self.node_filter_box.setFixedWidth(150)
        self.node_filter_box.setToolTip("Use \"-\" prefix for exclusive filtering")
        self.node_filter_box.textChanged.connect(self._handle_node_filter_change)

        # Top toolbar layout (Connect, Disconnect, Preset) - Centered
        top_toolbar_layout = QHBoxLayout()
        top_toolbar_layout.addStretch(1)
        top_toolbar_layout.addWidget(self.connect_button)
        top_toolbar_layout.addWidget(self.disconnect_button)
        top_toolbar_layout.addWidget(self.preset_button)
        top_toolbar_layout.addStretch(1)
        
        # Store a reference to the top toolbar layout for external access
        self._top_toolbar_layout = top_toolbar_layout

        # Bottom toolbar layout (Filters, Undo, Redo, Zoom) - Mimicking Audio tab structure
        bottom_toolbar_layout = QHBoxLayout()
        
        bottom_toolbar_layout.addWidget(self.node_filter_box)
        
        bottom_toolbar_layout.addStretch(1) # This stretch will now be at the beginning of the layout
        
        # bottom_toolbar_layout.addStretch(1) # Add another stretch to push undo/redo buttons to the center # Removed to re-center Undo/Redo buttons
        
        # Apply offset for buttons
        if GRAPH_TOOLBAR_UNDO_REDO_OFFSET > 0:
            bottom_toolbar_layout.addSpacerItem(QSpacerItem(GRAPH_TOOLBAR_UNDO_REDO_OFFSET, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        
        # Add Untangle button to the left of Undo/Redo
        bottom_toolbar_layout.addWidget(self.untangle_button)
        
        bottom_toolbar_layout.addWidget(self.undo_button)
        bottom_toolbar_layout.addWidget(self.redo_button)

        if GRAPH_TOOLBAR_UNDO_REDO_OFFSET < 0:
            bottom_toolbar_layout.addSpacerItem(QSpacerItem(abs(GRAPH_TOOLBAR_UNDO_REDO_OFFSET), 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        
        bottom_toolbar_layout.addStretch(1)
        
        bottom_toolbar_layout.addWidget(self.zoom_out_button) # Zoom out first
        bottom_toolbar_layout.addWidget(self.zoom_in_button)
        
        bottom_toolbar_layout.addSpacerItem(QSpacerItem(10, 10, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)) # Small spacer
        
        
        # Add top toolbar and graph view to main layout
        main_layout.addLayout(top_toolbar_layout)
        main_layout.addWidget(self.view) # Graph view now before bottom toolbar

        # Add bottom toolbar to main layout
        main_layout.addLayout(bottom_toolbar_layout) # Bottom toolbar now after graph view

        self.setCentralWidget(main_widget)

        # Handle JACK shutdown - connect to the signal from JackConnectionManager
        self.connection_manager.jack_shutdown_signal.connect(self.handle_jack_shutdown)

        # Button signals are connected via QAction.triggered by button.setDefaultAction() in the factory.
        # Tooltips are set by the factory or should be on the QAction.
        # The presets_graph_action should have its menu and aboutToShow signal connected
        # within ActionManager, and its enabled state managed based on self.preset_handler.

        # Connect scene selection change to update button states
        self.scene.selectionChanged.connect(self.update_graph_connection_buttons_state)
        # Connect scene connection changes to update button states
        # Also update undo/redo buttons when connections change in the scene
        self.scene.scene_connections_changed.connect(self.update_graph_connection_buttons_state)
        self.scene.scene_connections_changed.connect(self._update_graph_undo_redo_buttons_state)
 
        # Connect view's zoom_changed signal to handle saving zoom state
        self.view.zoom_changed.connect(self.handle_zoom_changed)
 
        # Set initial button states
        self.update_graph_connection_buttons_state()
        self._update_graph_undo_redo_buttons_state() # Initial state for undo/redo
        
        # self._setup_zoom_actions() # Commented out to let global ActionManager handle zoom shortcuts

        # Apply loaded zoom level
        if self.scene.initial_zoom_level is not None:
            print(f"Applying loaded zoom level: {self.scene.initial_zoom_level}")
            self.view.set_zoom_level(self.scene.initial_zoom_level)

        # Store references to controls that can be hidden in fullscreen
        self._internal_controls = [
            self.connect_button, self.disconnect_button, self.preset_button,
            self.untangle_button, self.undo_button, self.redo_button, 
            self.zoom_in_button, self.zoom_out_button,
            self.node_filter_box  # Add the node filter box to be hidden in fullscreen
        ]
        # Also need to hide the layouts containing them if possible, or their container widgets.
        # Since layouts are added directly, we hide the widgets themselves.

    def _load_untangle_values(self):
        """Load untangle values from config or use defaults."""
        config_path = os.path.expanduser("~/.config/cable/config.ini")
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            try:
                config.read(config_path)
                if 'DEFAULT' in config and 'GRAPH_UNTANGLE_VALUES' in config['DEFAULT']:
                    values_str = config['DEFAULT']['GRAPH_UNTANGLE_VALUES']
                    try:
                        # Parse comma-separated values
                        values = [int(v.strip()) for v in values_str.split(',') if v.strip().isdigit()]
                        if values:  # Only return if we have valid values
                            return values
                    except ValueError:
                        print(f"Error parsing untangle values from config: {values_str}")
            except Exception as e:
                print(f"Error reading untangle values from config: {e}")
        
        # Return default values if config doesn't exist or has invalid values
        return app_config.DEFAULT_UNTANGLE_VALUES

    def _store_initial_node_positions(self):
        """Store the initial node positions when the scene is first loaded."""
        if not self.initial_node_positions:
            # Get current node positions from the scene
            node_states = self.scene.get_node_states()
            if node_states:
                self.initial_node_positions = copy.deepcopy(node_states)
                print("Initial node positions stored")

    def _get_next_untangle_value(self):
        """Get the next untangle value in the cycle."""
        if not self.untangle_values:
            return 6  # Default if no values
        
        try:
            current_index = self.untangle_values.index(self.current_untangle_setting)
            next_index = (current_index + 1) % len(self.untangle_values)
            next_value = self.untangle_values[next_index]
            
            # Format the value for display
            if next_value == ORIGINAL_LAYOUT:
                # Indicate if the original layout was saved by the user
                return "original layout (saved)" if hasattr(self, 'initial_node_positions') and self.initial_node_positions else "original layout"
            return next_value
        except (ValueError, IndexError):
            # If current value not in the list or list is empty
            return self.untangle_values[0] if self.untangle_values else 6

    def toggle_internal_controls(self, visible: bool):
        """Shows or hides the internal toolbar/control widgets."""
        print(f"Graph MainWindow: Setting internal controls visibility to {visible}")
        for control in self._internal_controls:
            if control: # Check if widget exists
                control.setVisible(visible)
        # Force layout update within the graph tab's main widget
        if self.centralWidget() and self.centralWidget().layout():
             self.centralWidget().layout().activate()


    @pyqtSlot()
    def _update_graph_undo_redo_buttons_state(self):
        """Updates the enabled state of Undo and Redo buttons for the graph tab."""
        if self.connection_history and hasattr(self, 'graph_undo_action') and hasattr(self, 'graph_redo_action'):
            self.graph_undo_action.setEnabled(self.connection_history.can_undo())
            self.graph_redo_action.setEnabled(self.connection_history.can_redo())
        else:
            if hasattr(self, 'graph_undo_action'): self.graph_undo_action.setEnabled(False)
            if hasattr(self, 'graph_redo_action'): self.graph_redo_action.setEnabled(False)

    @pyqtSlot()
    def _handle_graph_undo(self):
        if self.connection_history and self.connection_history.can_undo():
            action = self.connection_history.undo()
            if action:
                action_type, output_name, input_name, is_midi_op = action # Unpack is_midi_op
                print(f"Graph Undo: {action_type} {output_name} -> {input_name} (MIDI: {is_midi_op})")

                # action_type is the INVERSE action.
                # If action_type is 'disconnect', it means the original action was 'connect', so we need to break the connection.
                # If action_type is 'connect', it means the original action was 'disconnect', so we need to make the connection.
                if action_type == 'disconnect':
                    if is_midi_op:
                        self.scene.jack_connection_handler.break_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.scene.jack_connection_handler.break_connection(output_name, input_name, is_undo_redo=True)
                elif action_type == 'connect':
                    if is_midi_op:
                        self.scene.jack_connection_handler.make_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.scene.jack_connection_handler.make_connection(output_name, input_name, is_undo_redo=True)
            self._update_graph_undo_redo_buttons_state()

    @pyqtSlot()
    def _handle_graph_redo(self):
        if self.connection_history and self.connection_history.can_redo():
            action = self.connection_history.redo()
            if action:
                action_type, output_name, input_name, is_midi_op = action # Unpack is_midi_op
                print(f"Graph Redo: {action_type} {output_name} -> {input_name} (MIDI: {is_midi_op})")
                
                if action_type == 'connect': # Redoing a connect means making a connection
                    if is_midi_op:
                        self.scene.jack_connection_handler.make_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.scene.jack_connection_handler.make_connection(output_name, input_name, is_undo_redo=True)
                elif action_type == 'disconnect': # Redoing a disconnect means breaking a connection
                    if is_midi_op:
                        self.scene.jack_connection_handler.break_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.scene.jack_connection_handler.break_connection(output_name, input_name, is_undo_redo=True)
            self._update_graph_undo_redo_buttons_state()

    @pyqtSlot()
    def _zoom_in_view(self):
        if self.view:
            self.view.zoom_in()

    @pyqtSlot()
    def _zoom_out_view(self):
        if self.view:
            self.view.zoom_out()

    @pyqtSlot(float)
    def handle_zoom_changed(self, zoom_level: float):
        """Handles the zoom_changed signal from the view and saves the state."""
        # print(f"Handling zoom change event in MainWindow: {zoom_level}") # Silenced
        # Save node positions and zoom level
        self.scene.save_node_states(graph_zoom_level=zoom_level)
        
    def _handle_untangle(self):
        """Handles the untangle button action and cycles through max_nodes_per_row values."""
        # Use the loaded untangle values from config
        if not self.untangle_values:
            # If no values are available, use defaults
            self.untangle_values = app_config.DEFAULT_UNTANGLE_VALUES
            # Make sure the original layout option is included
            if ORIGINAL_LAYOUT not in self.untangle_values:
                self.untangle_values.append(ORIGINAL_LAYOUT)
        
        # Get the index of the current setting in the cycle
        try:
            current_index = self.untangle_values.index(self.current_untangle_setting)
            # Move to the next value in the cycle
            next_index = (current_index + 1) % len(self.untangle_values)
            self.current_untangle_setting = self.untangle_values[next_index]
        except ValueError:
            # If current value not in the list, start with the first value
            self.current_untangle_setting = self.untangle_values[0]
        
        # If the current setting is the special value for original layout
        if self.current_untangle_setting == ORIGINAL_LAYOUT:
            # Restore the original node positions (preserves split state from original layout)
            if self.initial_node_positions:
                self.scene.restore_node_states(self.initial_node_positions)
                # Display a status message
                if hasattr(self, 'statusBar') and self.statusBar():
                    self.statusBar().showMessage("Restored original layout.", 3000)
            else:
                # If no initial positions are stored, use a default untangle
                print("No initial node positions stored, using default untangle")
                self.scene.untangle_graph(max_nodes_per_row=6)
                if hasattr(self, 'statusBar') and self.statusBar():
                    self.statusBar().showMessage("Original layout not available, using default untangle.", 3000)
        else:
            # For untangle layouts, unsplit all nodes first to improve organization
            print(f"Untangling with {self.current_untangle_setting} nodes per row - unsplitting all nodes first")
            self.scene.unsplit_all_nodes(save_state=False)
            
            # Then apply the regular untangle with the current setting
            self.scene.untangle_graph(max_nodes_per_row=self.current_untangle_setting)
            # Display a status message with the current setting
            if hasattr(self, 'statusBar') and self.statusBar():
                self.statusBar().showMessage(f"Graph untangled with {self.current_untangle_setting} nodes per row.", 3000)
        
        # Update the button tooltip to show both current and next values after first click
        next_value = self._get_next_untangle_value()
        self.untangle_button_clicked = True
        
        # Format the current setting for display
        if self.current_untangle_setting == ORIGINAL_LAYOUT:
            # Indicate if the original layout was saved by the user
            original_label = "original layout (saved)" if hasattr(self, 'initial_node_positions') and self.initial_node_positions else "original layout"
            current_display = original_label
        else:
            current_display = f"{self.current_untangle_setting} nodes per row"
        
        self.untangle_button.setToolTip(f"Reorganize graph ({current_display}, next: {next_value})")

    @pyqtSlot()
    def update_graph_connection_buttons_state(self):
        selected_items = self.scene.selectedItems()
        
        selected_input_ports = []
        selected_output_ports = []
        selected_connection_items = []
        selected_input_bulk_areas = []
        selected_output_bulk_areas = []

        for item in selected_items:
            if isinstance(item, PortItem):
                if item.is_input:
                    selected_input_ports.append(item)
                else:
                    selected_output_ports.append(item)
            elif isinstance(item, ConnectionItem):
                selected_connection_items.append(item)
            # Check for BulkAreaItem selections
            elif hasattr(item, 'is_input') and hasattr(item, 'parent_node'):
                # This is likely a BulkAreaItem
                if item.is_input:
                    selected_input_bulk_areas.append(item)
                else:
                    selected_output_bulk_areas.append(item)

        # Connect button state
        can_connect = False
        potential_connections_to_make = []
        all_potential_connections_exist = True # Assume true until a non-existing one is found

        # Check for port-to-port connections
        if len(selected_output_ports) == 1 and len(selected_input_ports) >= 1:
            single_out = selected_output_ports[0]
            if single_out in selected_input_ports: # Self-connection attempt with the same item selected as both
                 pass # can_connect remains false
            else:
                for in_port in selected_input_ports:
                    if single_out == in_port: continue # Should not happen if selection logic is strict
                    potential_connections_to_make.append((single_out.port_name, in_port.port_name))
                    # Check if this specific connection doesn't exist
                    if (single_out.port_name, in_port.port_name) not in self.scene.connections:
                        all_potential_connections_exist = False
                if not potential_connections_to_make: # e.g. output selected, and the same port (if it were also input capable) selected as input
                    pass
                else:
                    can_connect = not all_potential_connections_exist # Only enable if at least one connection doesn't exist

        elif len(selected_input_ports) == 1 and len(selected_output_ports) >= 1:
            single_in = selected_input_ports[0]
            if single_in in selected_output_ports: # Self-connection attempt
                pass # can_connect remains false
            else:
                for out_port in selected_output_ports:
                    if single_in == out_port: continue
                    potential_connections_to_make.append((out_port.port_name, single_in.port_name))
                    # Check if this specific connection doesn't exist
                    if (out_port.port_name, single_in.port_name) not in self.scene.connections:
                        all_potential_connections_exist = False
                if not potential_connections_to_make:
                    pass
                else:
                    can_connect = not all_potential_connections_exist # Only enable if at least one connection doesn't exist
        
        # Check for bulk area connections (IN/OUT bulk areas selected)
        elif (len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1):
            # Check if any ports between the bulk areas are not connected
            all_connected = True
            for input_bulk in selected_input_bulk_areas:
                for output_bulk in selected_output_bulk_areas:
                    input_node = input_bulk.parent_node
                    output_node = output_bulk.parent_node
                    if input_node == output_node:
                        continue
                    input_ports = list(input_node.input_ports.values())
                    output_ports = list(output_node.output_ports.values())
                    input_ports.sort(key=lambda p: p.scenePos().y())
                    output_ports.sort(key=lambda p: p.scenePos().y())
                    for i in range(min(len(input_ports), len(output_ports))):
                        output_port = output_ports[i]
                        input_port = input_ports[i]
                        if (output_port.port_name, input_port.port_name) not in self.scene.connections:
                            all_connected = False
                            break
                    if not all_connected:
                        break
                if not all_connected:
                    break
            can_connect = not all_connected # Enable if any potential connections are missing

        if hasattr(self, 'graph_connect_action'):
            self.graph_connect_action.setEnabled(can_connect)

        # Disconnect button state
        can_disconnect = False
        if selected_connection_items: # Can always disconnect selected connection items
            can_disconnect = True
        elif selected_input_ports and selected_output_ports: # Only check port-based disconnect if no direct connections selected
            # Check if any selected input port is connected to any selected output port
            for out_port in selected_output_ports:
                for in_port in selected_input_ports:
                    if (out_port.port_name, in_port.port_name) in self.scene.connections:
                        can_disconnect = True
                        break
                if can_disconnect:
                    break
        # Check for bulk area disconnections
        elif len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1:
            # For each pair of input and output bulk areas
            for input_bulk in selected_input_bulk_areas:
                for output_bulk in selected_output_bulk_areas:
                    # Get the parent nodes
                    input_node = input_bulk.parent_node
                    output_node = output_bulk.parent_node
                    
                    # Skip if same node
                    if input_node == output_node:
                        continue
                    
                    # Get all input ports from the input node
                    input_ports = list(input_node.input_ports.values())
                    # Get all output ports from the output node
                    output_ports = list(output_node.output_ports.values())
                    
                    # Sort ports by their vertical position
                    input_ports.sort(key=lambda p: p.scenePos().y())
                    output_ports.sort(key=lambda p: p.scenePos().y())
                    
                    # Check for position-based connections (left to left, right to right)
                    for i in range(min(len(input_ports), len(output_ports))):
                        output_port = output_ports[i]
                        input_port = input_ports[i]
                        if (output_port.port_name, input_port.port_name) in self.scene.connections:
                            can_disconnect = True
                            break
                    if can_disconnect:
                        break
                if can_disconnect:
                    break
        
        if hasattr(self, 'graph_disconnect_action'):
            self.graph_disconnect_action.setEnabled(can_disconnect)


    @pyqtSlot()
    def handle_connect_action(self):
        selected_items = self.scene.selectedItems()
        
        selected_input_ports = []
        selected_output_ports = []
        selected_input_bulk_areas = []
        selected_output_bulk_areas = []

        for item in selected_items:
            if isinstance(item, PortItem):
                if item.is_input:
                    selected_input_ports.append(item)
                else:
                    selected_output_ports.append(item)
            # Check for BulkAreaItem selections
            elif hasattr(item, 'is_input') and hasattr(item, 'parent_node'):
                # This is likely a BulkAreaItem
                if item.is_input:
                    selected_input_bulk_areas.append(item)
                else:
                    selected_output_bulk_areas.append(item)
        
        # Button should be disabled if selection is invalid, so no need for QMessageBox here.
        # if not selected_input_ports and not selected_output_ports:
        #     QMessageBox.warning(self, "Connection Error", "No ports selected. Please select one output and one or more input ports, or vice-versa.")
        #     return

        connections_made = 0
        
        # Handle port-to-port connections
        if len(selected_output_ports) == 1 and len(selected_input_ports) >= 1:
            output_port_item = selected_output_ports[0]
            for input_port_item in selected_input_ports:
                # Prevent connecting a port to itself
                if output_port_item == input_port_item:
                    print(f"Skipping self-connection for port: {output_port_item.port_name}")
                    continue
                print(f"Attempting to connect: {output_port_item.port_name} -> {input_port_item.port_name}")
                # Use JackConnectionHandler
                if output_port_item.is_midi: # Assuming PortItem has is_midi
                    if self.scene.jack_connection_handler.make_midi_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made +=1
                else:
                    if self.scene.jack_connection_handler.make_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made +=1
        elif len(selected_input_ports) == 1 and len(selected_output_ports) >= 1:
            input_port_item = selected_input_ports[0]
            for output_port_item in selected_output_ports:
                 # Prevent connecting a port to itself
                if output_port_item == input_port_item:
                    print(f"Skipping self-connection for port: {output_port_item.port_name}")
                    continue
                print(f"Attempting to connect: {output_port_item.port_name} -> {input_port_item.port_name}")
                # Use JackConnectionHandler
                if output_port_item.is_midi: # Assuming PortItem has is_midi
                    if self.scene.jack_connection_handler.make_midi_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made += 1
                else:
                    if self.scene.jack_connection_handler.make_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made += 1
        
        # Handle bulk area connections
        elif len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1:
            # For each pair of input and output bulk areas
            for input_bulk_area_item in selected_input_bulk_areas: # Renamed for clarity
                for output_bulk_area_item in selected_output_bulk_areas: # Renamed for clarity
                    # Get the parent nodes
                    input_node = input_bulk_area_item.parent_node
                    output_node = output_bulk_area_item.parent_node
                    
                    # Skip if same node
                    if input_node == output_node:
                        continue
                    
                    # Get all input ports from the input node
                    input_port_items = list(input_node.input_ports.values()) # Renamed for clarity
                    # Get all output ports from the output node
                    output_port_items = list(output_node.output_ports.values()) # Renamed for clarity
                    
                    # Convert to lists of port names for JackConnectionHandler
                    input_port_names = [p.port_name for p in input_port_items]
                    output_port_names = [p.port_name for p in output_port_items]

                    if output_port_names and input_port_names:
                        print(f"Attempting bulk connection between {output_node.client_name} (OUT) and {input_node.client_name} (IN)")
                        # JackConnectionHandler.make_multiple_connections determines MIDI type based on active tab.
                        # This might need refinement if graph tab handles mixed types or has its own context.
                        self.scene.jack_connection_handler.make_multiple_connections(output_port_names, input_port_names)
                        # We assume make_multiple_connections handles history and UI updates.
                        # Counting 'connections_made' here might be tricky as make_multiple_connections does many.
                        # For simplicity, we'll consider this one "attempt".
                        connections_made += 1 # Increment for the bulk attempt
                    else:
                        print(f"Skipping bulk connection between {output_node.client_name} and {input_node.client_name} due to empty port lists.")
        
        if connections_made > 0:
            if hasattr(self, 'statusBar') and self.statusBar():
                self.statusBar().showMessage(f"{connections_made} connection(s) attempted.", 3000)
        else:
            # Only show this if an attempt was actually possible (action was enabled)
            if hasattr(self, 'graph_connect_action') and self.graph_connect_action.isEnabled(): # Check if action was enabled
                 if hasattr(self, 'statusBar') and self.statusBar():
                     self.statusBar().showMessage("No new connections were made (possibly already connected or error).", 3000)
        # self.update_graph_connection_buttons_state() # No longer needed here, scene signal will trigger it
        self._update_graph_undo_redo_buttons_state() # Update undo/redo buttons


    @pyqtSlot()
    def handle_disconnect_action(self):
        selected_items = self.scene.selectedItems()
        disconnections_made = 0

        selected_connection_items = [item for item in selected_items if isinstance(item, ConnectionItem)]
        selected_port_items = [item for item in selected_items if isinstance(item, PortItem)]
        selected_input_bulk_areas = []
        selected_output_bulk_areas = []

        # Check for BulkAreaItem selections
        for item in selected_items:
            if hasattr(item, 'is_input') and hasattr(item, 'parent_node'):
                # This is likely a BulkAreaItem
                if item.is_input:
                    selected_input_bulk_areas.append(item)
                else:
                    selected_output_bulk_areas.append(item)

        if selected_connection_items:
            for conn_item in selected_connection_items:
                if conn_item.source_port and conn_item.dest_port:
                    print(f"Attempting to disconnect via ConnectionItem: {conn_item.source_port.port_name} -> {conn_item.dest_port.port_name}")
                    # Use JackConnectionHandler
                    if conn_item.source_port.is_midi: # Assuming PortItem has is_midi
                        if self.scene.jack_connection_handler.break_midi_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name):
                            disconnections_made += 1
                    else:
                        if self.scene.jack_connection_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name):
                            disconnections_made += 1
                else:
                    print(f"Warning: A selected ConnectionItem has missing source or destination port. Skipping.")
        
        elif selected_port_items:
            selected_input_ports = []
            selected_output_ports = []
            for item in selected_port_items:
                if item.is_input:
                    selected_input_ports.append(item)
                else:
                    selected_output_ports.append(item)

            # Button should be disabled if selection is invalid
            # if not selected_input_ports or not selected_output_ports:
            #     QMessageBox.warning(self, "Disconnection Error",
            #                         "To disconnect ports, please select at least one input and one output port that are connected, or select the connection line(s) directly.")
            #     return

            if selected_input_ports and selected_output_ports: # Ensure both lists have items
                for output_port_item in selected_output_ports:
                    for input_port_item in selected_input_ports:
                        connection_key = (output_port_item.port_name, input_port_item.port_name)
                        if connection_key in self.scene.connections:
                            print(f"Attempting to disconnect via PortItems: {output_port_item.port_name} -> {input_port_item.port_name}")
                            # Use JackConnectionHandler
                            if output_port_item.is_midi: # Assuming PortItem has is_midi
                                if self.scene.jack_connection_handler.break_midi_connection(output_port_item.port_name, input_port_item.port_name):
                                    disconnections_made += 1
                            else:
                                if self.scene.jack_connection_handler.break_connection(output_port_item.port_name, input_port_item.port_name):
                                    disconnections_made += 1
                        # else:
                        #     print(f"Ports {output_port_item.port_name} and {input_port_item.port_name} are not directly connected in the scene's view.")
        
        # Handle bulk area disconnections
        elif len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1:
            # For each pair of input and output bulk areas
            for input_bulk in selected_input_bulk_areas:
                for output_bulk in selected_output_bulk_areas:
                    # Get the parent nodes
                    input_node = input_bulk.parent_node
                    output_node = output_bulk.parent_node
                    
                    # Skip if same node
                    if input_node == output_node:
                        continue
                    
                    # Get all input ports from the input node
                    input_ports = list(input_node.input_ports.values())
                    # Get all output ports from the output node
                    output_ports = list(output_node.output_ports.values())
                    
                    # Sort ports by their vertical position
                    input_ports.sort(key=lambda p: p.scenePos().y())
                    output_ports.sort(key=lambda p: p.scenePos().y())
                    
                    # Check for position-based connections (left to left, right to right)
                    for i in range(min(len(input_ports), len(output_ports))):
                        output_port = output_ports[i]
                        input_port = input_ports[i]
                        connection_key = (output_port_item.port_name, input_port_item.port_name) # Corrected variable names
                        if connection_key in self.scene.connections:
                            print(f"Attempting bulk disconnection (position-based): {output_port_item.port_name} -> {input_port_item.port_name}")
                             # Use JackConnectionHandler
                            if output_port_item.is_midi: # Assuming PortItem has is_midi
                                if self.scene.jack_connection_handler.break_midi_connection(output_port_item.port_name, input_port_item.port_name):
                                    disconnections_made += 1
                            else:
                                if self.scene.jack_connection_handler.break_connection(output_port_item.port_name, input_port_item.port_name):
                                    disconnections_made += 1

        if disconnections_made > 0:
            if hasattr(self, 'statusBar') and self.statusBar():
                self.statusBar().showMessage(f"{disconnections_made} disconnection(s) attempted.", 3000)
        else:
            # Only show this if an attempt was actually possible (action was enabled)
            if hasattr(self, 'graph_disconnect_action') and self.graph_disconnect_action.isEnabled(): # Check if action was enabled
                if hasattr(self, 'statusBar') and self.statusBar():
                    self.statusBar().showMessage("No connections were broken (possibly not connected or error).", 3000)
        # self.update_graph_connection_buttons_state() # No longer needed here, scene signal will trigger it
        self._update_graph_undo_redo_buttons_state() # Update undo/redo buttons

    @pyqtSlot()
    @pyqtSlot()
    def _handle_node_filter_change(self):
        """Handles text changes in the node filter box."""
        filter_text = self.node_filter_box.text()
        self.scene.filter_nodes(filter_text)

    def handle_jack_shutdown(self):
        print("JACK has shut down. Disabling graph interaction.")
        # Disable further interaction, maybe show a message
        self.scene.clear_graph()
        self.view.setEnabled(False)
        # Check if statusBar exists before using it
        if hasattr(self, 'statusBar') and self.statusBar():
             self.statusBar().showMessage("JACK connection lost.", 5000)
        # Optionally try to reconnect or close the app

    def closeEvent(self, event):
        """Ensure JACK client is cleaned up when closing the window."""
        print("Closing application...")
        # Disconnect signals that might try to access the scene after it's deleted
        try:
            self.scene.selectionChanged.disconnect(self.scene.interaction_handler.handle_selection_changed)
        except TypeError: # Signal might already be disconnected or handler doesn't exist
            pass # Ignore if disconnection fails
        # Save node positions and zoom level before shutting down
        # REMOVED: Saving on exit is no longer desired. States are saved immediately on change.
        # current_zoom_level = self.view.get_zoom_level()
        # print(f"MainWindow closeEvent: current_zoom_level from view = {current_zoom_level}") # DEBUG
        # self.scene.save_node_states(graph_zoom_level=current_zoom_level) # Also ensure this uses save_node_states if kept
        # self.jack_handler.stop() # Removed, main client lifecycle managed by JackConnectionManager
        event.accept()

    def get_top_toolbar_layout(self):
        """Returns the top toolbar layout for external modification.
        
        Returns:
            QHBoxLayout: The top toolbar layout containing Connect, Disconnect, and Preset buttons
        """
        # Store a reference to the top_toolbar_layout as a class member
        if hasattr(self, '_top_toolbar_layout'):
            return self._top_toolbar_layout
            
        if self.centralWidget() and isinstance(self.centralWidget().layout(), QVBoxLayout):
            main_layout = self.centralWidget().layout()
            if main_layout.count() > 0:
                # The first item should be the top_toolbar_layout
                item = main_layout.itemAt(0)
                if item and item.layout() and isinstance(item.layout(), QHBoxLayout):
                    # Cache the reference for future use
                    self._top_toolbar_layout = item.layout()
                    return self._top_toolbar_layout
        
        return None

    def save_current_layout(self):
        """Save the current node layout to the node_positions.json file.
        This is called when the user selects "Save current layout" from the context menu.
        """
        # Get the current node states from the scene
        current_states = self.scene.get_node_states()
        
        # Save the node states to the config file
        self.scene.config_manager.save_node_states_as_default(current_states)
        
        # Update the in-memory initial_node_positions variable
        # This ensures that when cycling back to the original layout with the Untangle button,
        # the saved layout will be used
        self.initial_node_positions = copy.deepcopy(current_states)
        
        # Show a status message
        if hasattr(self, 'statusBar') and self.statusBar():
            self.statusBar().showMessage("Current layout saved as default and will be used as 'original layout' in Untangle cycle", 5000)
        
        # Update the Untangle button tooltip to reflect that the original layout has been changed
        next_value = self._get_next_untangle_value()
        current_display = "original layout (saved)" if self.current_untangle_setting == ORIGINAL_LAYOUT else f"{self.current_untangle_setting} nodes per row"
        self.untangle_button.setToolTip(f"Reorganize graph ({current_display}, next: {next_value})")
