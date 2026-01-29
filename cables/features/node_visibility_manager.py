"""
NodeVisibilityManager - Manages node visibility preferences
"""

import os
import json
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, 
                            QPushButton, QScrollArea, QWidget, QLineEdit)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from cables import jack_utils

class NodeVisibilityManager:
    """
    Manages node visibility preferences for the Cables application.
    
    This class handles saving and loading node visibility settings,
    and provides a dialog for configuring which nodes should be visible.
    """
    
    def __init__(self, connection_manager, config_manager):
        """
        Initialize the NodeVisibilityManager.
        
        Args:
            connection_manager: The main JackConnectionManager instance
            config_manager: The ConfigManager instance
        """
        self.connection_manager = connection_manager
        self.config_manager = config_manager
        self.config_path = os.path.expanduser('~/.config/cable/node_visibility.json')
        self.load_visibility_settings()
    
    def load_visibility_settings(self):
        """Load node visibility settings from the config file."""
        # Initialize with empty dictionaries
        self.audio_input_visibility = {}
        self.audio_output_visibility = {}
        self.midi_input_visibility = {}
        self.midi_output_visibility = {}
        self.midi_matrix_input_visibility = {}
        self.midi_matrix_output_visibility = {}

        # For backward compatibility
        self.audio_node_visibility = {}
        self.midi_node_visibility = {}
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    
                    # Load legacy format if present (for backward compatibility)
                    if 'audio' in data:
                        self.audio_node_visibility = data.get('audio', {})
                    if 'midi' in data:
                        self.midi_node_visibility = data.get('midi', {})
                    
                    # Load new format
                    self.audio_input_visibility = data.get('audio_input', {})
                    self.audio_output_visibility = data.get('audio_output', {})
                    self.midi_input_visibility = data.get('midi_input', {})
                    self.midi_output_visibility = data.get('midi_output', {})
                    self.midi_matrix_input_visibility = data.get('midi_matrix_input', {})
                    self.midi_matrix_output_visibility = data.get('midi_matrix_output', {})
                    
                    # If using legacy format, convert to new format
                    if (self.audio_node_visibility or self.midi_node_visibility) and not (
                        self.audio_input_visibility or self.audio_output_visibility or 
                        self.midi_input_visibility or self.midi_output_visibility):
                        self._convert_legacy_settings()
            except Exception as e:
                print(f"Error loading node visibility settings: {e}")
    
    def _convert_legacy_settings(self):
        """Convert legacy node visibility settings to input/output format."""
        # Convert audio settings
        for node, visible in self.audio_node_visibility.items():
            self.audio_input_visibility[node] = visible
            self.audio_output_visibility[node] = visible
        
        # Convert MIDI settings
        for node, visible in self.midi_node_visibility.items():
            self.midi_input_visibility[node] = visible
            self.midi_output_visibility[node] = visible
    
    def save_visibility_settings(self):
        """Save node visibility settings to the config file."""
        config_dir = os.path.dirname(self.config_path)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        data = {
            # New format
            'audio_input': self.audio_input_visibility,
            'audio_output': self.audio_output_visibility,
            'midi_input': self.midi_input_visibility,
            'midi_output': self.midi_output_visibility,
            'midi_matrix_input': self.midi_matrix_input_visibility,
            'midi_matrix_output': self.midi_matrix_output_visibility
        }
        
        try:
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving node visibility settings: {e}")
    
    def _extract_client_name(self, node_name):
        """
        Extract the base client name from a node name.
        Handles both port names (with ':') and split audio/midi nodes (with ' (Audio)' or ' (MIDI)').
        
        Args:
            node_name: The name of the node (e.g., "Client:port", "Client (Audio)", "Client (MIDI)")
            
        Returns:
            str: The base client name
        """
        # First, get the client name part (before the colon for port names)
        parts = node_name.split(':')
        client_name = parts[0] if parts else node_name
        
        # Then, strip the (Audio) or (MIDI) suffix if present (for split audio/midi clients)
        if client_name.endswith(' (Audio)'):
            client_name = client_name[:-8]  # Remove ' (Audio)'
        elif client_name.endswith(' (MIDI)'):
            client_name = client_name[:-7]  # Remove ' (MIDI)'
        
        return client_name
    
    def is_node_visible(self, node_name, is_midi=False):
        """
        Check if a node should be visible (for backward compatibility).
        
        Args:
            node_name: The name of the node to check
            is_midi: Whether this is a MIDI node
            
        Returns:
            bool: True if the node should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)
        
        if is_midi:
            # For MIDI nodes, check if EITHER inputs or outputs are explicitly set to visible
            # If neither is in the dictionary, default to True (visible)
            input_visible = self.midi_input_visibility.get(client_name)
            output_visible = self.midi_output_visibility.get(client_name)
            
            # If both are explicitly set, use OR logic
            if input_visible is not None and output_visible is not None:
                return input_visible or output_visible
            # If only one is set, use that value
            elif input_visible is not None:
                return input_visible
            elif output_visible is not None:
                return output_visible
            # If neither is set, default to visible
            else:
                return True
        else:
            # For audio nodes, same logic
            input_visible = self.audio_input_visibility.get(client_name)
            output_visible = self.audio_output_visibility.get(client_name)
            
            # If both are explicitly set, use OR logic
            if input_visible is not None and output_visible is not None:
                return input_visible or output_visible
            # If only one is set, use that value
            elif input_visible is not None:
                return input_visible
            elif output_visible is not None:
                return output_visible
            # If neither is set, default to visible
            else:
                return True
    
    def is_input_visible(self, node_name, is_midi=False):
        """
        Check if a node's input should be visible.
        
        Args:
            node_name: The name of the node to check
            is_midi: Whether this is a MIDI node
            
        Returns:
            bool: True if the node's input should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)
        
        # Check the visibility setting
        visibility_dict = self.midi_input_visibility if is_midi else self.audio_input_visibility
        # If the node is not in the dictionary, it's visible by default
        return visibility_dict.get(client_name, True)
    
    def is_output_visible(self, node_name, is_midi=False):
        """
        Check if a node's output should be visible.

        Args:
            node_name: The name of the node to check
            is_midi: Whether this is a MIDI node

        Returns:
            bool: True if the node's output should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # Check the visibility setting
        visibility_dict = self.midi_output_visibility if is_midi else self.audio_output_visibility
        # If the node is not in the dictionary, it's visible by default
        return visibility_dict.get(client_name, True)

    def is_midi_matrix_input_visible(self, node_name):
        """
        Check if a node's input should be visible in the MIDI Matrix.

        Args:
            node_name: The name of the node to check

        Returns:
            bool: True if the node's input should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # If the node is not in the dictionary, it's visible by default
        return self.midi_matrix_input_visibility.get(client_name, True)

    def is_midi_matrix_output_visible(self, node_name):
        """
        Check if a node's output should be visible in the MIDI Matrix.

        Args:
            node_name: The name of the node to check

        Returns:
            bool: True if the node's output should be visible, False otherwise
        """
        # Get the base client name
        client_name = self._extract_client_name(node_name)

        # If the node is not in the dictionary, it's visible by default
        return self.midi_matrix_output_visibility.get(client_name, True)
    
    def show_configuration_dialog(self, parent=None, tab_type='graph'):
        """
        Show the node visibility configuration dialog.

        Args:
            parent: The parent widget
            tab_type: The type of tab ('audio', 'midi', 'midi_matrix', or 'graph')
        """
        if tab_type == 'midi_matrix':
            dialog = NodeVisibilityDialog(
                self.connection_manager,
                {},  # No audio for MIDI matrix
                {},  # No audio for MIDI matrix
                self.midi_matrix_input_visibility,
                self.midi_matrix_output_visibility,
                parent,
                tab_type
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Settings are already modified directly since dialog works with references
                self.save_visibility_settings()

                # Apply new visibility settings
                self.apply_visibility_settings()
        else:
            dialog = NodeVisibilityDialog(
                self.connection_manager,
                self.audio_input_visibility,
                self.audio_output_visibility,
                self.midi_input_visibility,
                self.midi_output_visibility,
                parent,
                tab_type
            )

            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Update settings from dialog
                self.audio_input_visibility = dialog.audio_input_visibility
                self.audio_output_visibility = dialog.audio_output_visibility
                self.midi_input_visibility = dialog.midi_input_visibility
                self.midi_output_visibility = dialog.midi_output_visibility
                self.save_visibility_settings()

                # Apply new visibility settings
                self.apply_visibility_settings()
    
    def apply_visibility_settings(self):
        """Apply current visibility settings to the port trees."""
        # Update audio tab
        self._update_tree_visibility(
            self.connection_manager.input_tree,
            self.connection_manager.output_tree,
            is_midi=False
        )
        
        # Update MIDI tab
        self._update_tree_visibility(
            self.connection_manager.midi_input_tree,
            self.connection_manager.midi_output_tree,
            is_midi=True
        )
        
        # Update MIDI matrix
        if hasattr(self.connection_manager, 'midi_matrix_widget') and self.connection_manager.midi_matrix_widget:
            self.connection_manager.midi_matrix_widget.refresh_matrix()

        # Update graph view
        if hasattr(self.connection_manager, 'graph_main_window') and self.connection_manager.graph_main_window:
            if hasattr(self.connection_manager.graph_main_window, 'scene') and self.connection_manager.graph_main_window.scene:
                # Make sure the scene has a reference to this node visibility manager
                if not hasattr(self.connection_manager.graph_main_window.scene, 'node_visibility_manager') or \
                   self.connection_manager.graph_main_window.scene.node_visibility_manager is None:
                    self.connection_manager.graph_main_window.scene.set_node_visibility_manager(self)

                # Log changes from dialog to help with debugging
                print("Applying visibility settings to graph. Current settings:")
                for client_name in set(list(self.audio_input_visibility.keys()) +
                                      list(self.audio_output_visibility.keys()) +
                                      list(self.midi_input_visibility.keys()) +
                                      list(self.midi_output_visibility.keys())):
                    audio_in_visible = self.audio_input_visibility.get(client_name, True)
                    audio_out_visible = self.audio_output_visibility.get(client_name, True)
                    midi_in_visible = self.midi_input_visibility.get(client_name, True)
                    midi_out_visible = self.midi_output_visibility.get(client_name, True)

                    # Check for partial visibility (one part hidden, one visible)
                    if ((audio_in_visible != audio_out_visible) or
                        (midi_in_visible != midi_out_visible)):
                        print(f"Node {client_name} has partial visibility - should be split")
                        print(f"  Audio in: {audio_in_visible}, Audio out: {audio_out_visible}")
                        print(f"  MIDI in: {midi_in_visible}, MIDI out: {midi_out_visible}")

                # Perform a full refresh to apply visibility settings
                self.connection_manager.graph_main_window.scene.full_graph_refresh()
    
    def _update_tree_visibility(self, input_tree, output_tree, is_midi=False):
        """
        Update the visibility of nodes in the specified trees.
        
        Args:
            input_tree: The input port tree widget
            output_tree: The output port tree widget
            is_midi: Whether these are MIDI trees
        """
        # For the port trees, we don't need to do anything special here
        # as the port trees are rebuilt by _refresh_single_port_type which
        # uses PortManager._get_ports, which we've updated to handle
        # partial visibility (showing only input or only output)
        
        # Get the current tab's port type for the refresh
        port_type = 'midi' if is_midi else 'audio'
        
        # Store current selections to restore after refresh
        input_selection = None
        output_selection = None
        
        if input_tree and hasattr(self.connection_manager, '_get_selected_item_info'):
            input_selection = self.connection_manager._get_selected_item_info(input_tree)
        
        if output_tree and hasattr(self.connection_manager, '_get_selected_item_info'):
            output_selection = self.connection_manager._get_selected_item_info(output_tree)
        
        # Refresh the port trees - this will use our updated _get_ports method
        # to show only the appropriate ports
        self.connection_manager._refresh_single_port_type(port_type)
        
        # Restore selections if possible
        if input_tree and input_selection and hasattr(self.connection_manager, '_restore_selection'):
            self.connection_manager._restore_selection(input_tree, input_selection)
        
        if output_tree and output_selection and hasattr(self.connection_manager, '_restore_selection'):
            self.connection_manager._restore_selection(output_tree, output_selection)
        
        # Refresh connections visualization
        self.connection_manager.refresh_visualizations()


class NodeVisibilityDialog(QDialog):
    """Dialog for configuring node visibility settings."""
    
    def __init__(self, connection_manager, audio_input_visibility, audio_output_visibility,
                 midi_input_visibility, midi_output_visibility, parent=None, tab_type='graph'):
        """
        Initialize the dialog.

        Args:
            connection_manager: The main JackConnectionManager instance
            audio_input_visibility: Dictionary of audio input visibility settings
            audio_output_visibility: Dictionary of audio output visibility settings
            midi_input_visibility: Dictionary of MIDI input visibility settings
            midi_output_visibility: Dictionary of MIDI output visibility settings
            parent: The parent widget
            tab_type: The type of tab ('audio', 'midi', or 'graph')
        """
        super().__init__(parent)
        self.connection_manager = connection_manager
        # For MIDI Matrix, work with references to allow direct modification
        if tab_type == 'midi_matrix':
            self.audio_input_visibility = audio_input_visibility
            self.audio_output_visibility = audio_output_visibility
            self.midi_input_visibility = midi_input_visibility
            self.midi_output_visibility = midi_output_visibility
        else:
            # For other tabs, work with copies for cancel functionality
            self.audio_input_visibility = dict(audio_input_visibility)
            self.audio_output_visibility = dict(audio_output_visibility)
            self.midi_input_visibility = dict(midi_input_visibility)
            self.midi_output_visibility = dict(midi_output_visibility)
        self.tab_type = tab_type
        
        if self.tab_type == 'midi_matrix':
            self.setWindowTitle("MIDI Matrix Clients Visibility Configuration")
        else:
            self.setWindowTitle("Clients Visibility Configuration")
        self.resize(600, 600)
        
        # Track node checkboxes and their children
        self.audio_nodes = {}  # Maps node name to: {'node': node_checkbox, 'input': input_checkbox, 'output': output_checkbox}
        self.midi_nodes = {}   # Same structure for MIDI nodes
        
        self._setup_ui()
        self._populate_nodes()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Add filter input
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter clients...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_edit)
        layout.addLayout(filter_layout)
        
        # Tabs label
        if self.tab_type == 'midi_matrix':
            self.tabs_label = QLabel("Note: Changes will apply to the MIDI Matrix tab")
        else:
            self.tabs_label = QLabel("Note: Changes will apply to Audio, MIDI, and Graph tabs")
        layout.addWidget(self.tabs_label)
        
        # Create scroll area for node checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.node_container = QWidget()
        self.node_layout = QVBoxLayout(self.node_container)
        
        # Audio nodes section
        self.audio_label = QLabel("Audio Clients")
        font = self.audio_label.font()
        font.setBold(True)
        self.audio_label.setFont(font)
        self.node_layout.addWidget(self.audio_label)
        
        # MIDI nodes section
        self.midi_label = QLabel("MIDI Clients")
        font = self.midi_label.font()
        font.setBold(True)
        self.midi_label.setFont(font)
        self.node_layout.addWidget(self.midi_label)
        
        scroll.setWidget(self.node_container)
        layout.addWidget(scroll)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Select/deselect all buttons
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._populate_nodes)
        
        # OK/Cancel buttons
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(select_all_btn)
        button_layout.addWidget(deselect_all_btn)
        button_layout.addWidget(refresh_btn)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _populate_nodes(self):
        """Populate the dialog with node checkboxes."""
        self._clear_node_layout()

        self.audio_nodes = {}
        self.midi_nodes = {}

        # Get clients based on tab type
        if self.tab_type in ['audio', 'graph']:
            # Get all audio nodes (clients)
            audio_nodes = self._get_unique_client_names(is_midi=False)
            for node in sorted(audio_nodes):
                self._add_node_hierarchy(node, is_midi=False)

        if self.tab_type in ['midi', 'midi_matrix', 'graph']:
            # Get all MIDI nodes (clients)
            midi_nodes = self._get_unique_client_names(is_midi=True)
            for node in sorted(midi_nodes):
                self._add_node_hierarchy(node, is_midi=True)

        # Apply any active filter
        self._apply_filter(self.filter_edit.text())

        # Add stretch to prevent spacing issues when there are few clients
        self.node_layout.addStretch()
    
    def _clear_node_layout(self):
        """Clear all widgets and items from node layout except section labels."""
        if not self.node_layout:
            return
            
        # Iterate backwards to safely remove items
        for i in reversed(range(self.node_layout.count())):
            item = self.node_layout.itemAt(i)
            widget = item.widget()
            
            # Skip the section labels
            if widget and (widget == self.audio_label or widget == self.midi_label):
                continue
            
            # Remove the item from layout
            self.node_layout.takeAt(i)
            
            # If it's a widget, delete it
            if widget:
                widget.deleteLater()
    
    def _add_node_hierarchy(self, node_name, is_midi=False):
        """
        Create a hierarchical layout for a node with indented input/output checkboxes.
        
        Args:
            node_name: The name of the node
            is_midi: Whether this is a MIDI node
        """
        # Determine which directions this client actually exposes
        has_input = False
        has_output = False
        
        # Handle split node names for querying ports
        query_name = node_name
        is_audio_split = False
        is_midi_split = False
        
        if node_name.endswith(" (Audio)"):
            query_name = node_name[:-8]
            is_audio_split = True
        elif node_name.endswith(" (MIDI)"):
            query_name = node_name[:-7]
            is_midi_split = True
            
        try:
            # If it's a split node, we must enforce the type matching the suffix
            # regardless of the is_midi argument passed to this function (though they should match)
            check_midi = is_midi
            check_audio = not is_midi
            
            if is_audio_split:
                check_midi = False
                check_audio = True
            elif is_midi_split:
                check_midi = True
                check_audio = False
                
            ports = jack_utils.get_all_jack_ports(
                self.connection_manager.client,
                name_pattern=f"{query_name}:",
                is_midi=check_midi,
                is_audio=check_audio
            )
            for port in ports:
                if port.is_input:
                    has_input = True
                if port.is_output:
                    has_output = True
                if has_input and has_output:
                    break
        except Exception as e:
            print(f"Error checking port directions for {node_name}: {e}")
        
        # If no ports are found, assume the node has both input and output
        # This can happen for nodes that exist in the graph but don't have active JACK ports
        # at the moment of querying (e.g., Easy Effects internal filters)
        if not has_input and not has_output:
            # Default to having both directions so the node appears in the dialog
            has_input = True
            has_output = True
        
        # Create node container and checkbox
        node_widget = QWidget()
        node_layout = QVBoxLayout(node_widget)
        node_layout.setContentsMargins(0, 5, 0, 5)
        
        # Main node checkbox with name
        node_checkbox = QCheckBox(node_name)
        font = node_checkbox.font()
        font.setBold(True)
        node_checkbox.setFont(font)
        node_layout.addWidget(node_checkbox)
        
        # Add indented container for input/output checkboxes
        io_widget = QWidget()
        io_layout = QHBoxLayout(io_widget)
        io_layout.setContentsMargins(20, 0, 0, 0)
        
        # Create input checkbox if the client has input ports
        input_checkbox = None
        if has_input:
            input_checkbox = QCheckBox("Input")
            # Use query_name (base client name) for visibility lookup
            if is_midi:
                input_checkbox.setChecked(self.midi_input_visibility.get(query_name, True))
                input_checkbox.stateChanged.connect(lambda state, n=query_name: self._on_midi_input_checkbox_changed(n, state))
            else:
                input_checkbox.setChecked(self.audio_input_visibility.get(query_name, True))
                input_checkbox.stateChanged.connect(lambda state, n=query_name: self._on_audio_input_checkbox_changed(n, state))
            io_layout.addWidget(input_checkbox)
        
        # Create output checkbox if the client has output ports
        output_checkbox = None
        if has_output:
            output_checkbox = QCheckBox("Output")
            # Use query_name (base client name) for visibility lookup
            if is_midi:
                output_checkbox.setChecked(self.midi_output_visibility.get(query_name, True))
                output_checkbox.stateChanged.connect(lambda state, n=query_name: self._on_midi_output_checkbox_changed(n, state))
            else:
                output_checkbox.setChecked(self.audio_output_visibility.get(query_name, True))
                output_checkbox.stateChanged.connect(lambda state, n=query_name: self._on_audio_output_checkbox_changed(n, state))
            io_layout.addWidget(output_checkbox)
        
        io_layout.addStretch()
        node_layout.addWidget(io_widget)
        
        # Connect node checkbox to control existing child checkboxes
        node_checkbox.stateChanged.connect(
            lambda state, i=input_checkbox, o=output_checkbox: self._on_node_checkbox_changed(state, i, o)
        )
        
        # Update node checkbox initial state
        self._update_node_checkbox_state(node_checkbox, input_checkbox, output_checkbox)
        
        # Connect child checkbox state changes to update the parent node checkbox
        if input_checkbox:
            input_checkbox.stateChanged.connect(
                lambda _state, n=node_checkbox, i=input_checkbox, o=output_checkbox: self._update_node_checkbox_state(n, i, o)
            )
        if output_checkbox:
            output_checkbox.stateChanged.connect(
                lambda _state, n=node_checkbox, i=input_checkbox, o=output_checkbox: self._update_node_checkbox_state(n, i, o)
            )
        
        # Add to appropriate section and tracking dictionaries
        if is_midi:
            self.node_layout.insertWidget(self.node_layout.count(), node_widget)
            self.midi_nodes[node_name] = {
                'node': node_checkbox,
                'input': input_checkbox,
                'output': output_checkbox,
                'widget': node_widget
            }
        else:
            self.node_layout.insertWidget(self.node_layout.indexOf(self.midi_label), node_widget)
            self.audio_nodes[node_name] = {
                'node': node_checkbox,
                'input': input_checkbox,
                'output': output_checkbox,
                'widget': node_widget
            }
    

    def _on_node_checkbox_changed(self, state, input_checkbox, output_checkbox):
        """Handle changes to the node checkbox by updating child checkboxes."""
        checked = (state == Qt.CheckState.Checked.value)

        if input_checkbox:
            input_checkbox.blockSignals(True)
            input_checkbox.setChecked(checked)
            input_checkbox.blockSignals(False)
            if not input_checkbox.signalsBlocked():
                input_checkbox.stateChanged.emit(Qt.CheckState.Checked.value if checked else Qt.CheckState.Unchecked.value)

        if output_checkbox:
            output_checkbox.blockSignals(True)
            output_checkbox.setChecked(checked)
            output_checkbox.blockSignals(False)
            if not output_checkbox.signalsBlocked():
                output_checkbox.stateChanged.emit(Qt.CheckState.Checked.value if checked else Qt.CheckState.Unchecked.value)

    def _update_node_checkbox_state(self, node_checkbox, input_checkbox, output_checkbox):
        """Synchronize node checkbox state with its existing child checkboxes."""
        node_checkbox.blockSignals(True)
        
        # Gather child states that actually exist
        child_states = []
        if input_checkbox:
            child_states.append(input_checkbox.isChecked())
        if output_checkbox:
            child_states.append(output_checkbox.isChecked())
        
        if not child_states:
            node_checkbox.setCheckState(Qt.CheckState.Unchecked)
        elif all(child_states):
            node_checkbox.setCheckState(Qt.CheckState.Checked)
        elif any(child_states):
            node_checkbox.setCheckState(Qt.CheckState.Checked)  # Set to checked if any child is checked
        else:
            node_checkbox.setCheckState(Qt.CheckState.Unchecked)
        
        node_checkbox.blockSignals(False)
    
    def _get_unique_client_names(self, is_midi=False):
        """
        Get a list of unique client names.
        
        Args:
            is_midi: Whether to get MIDI clients
            
        Returns:
            set: A set of unique client names
        """
        unique_clients = set()
        
        try:
            # Check if we should split audio/midi clients
            # We need to access the main config manager, which is passed to NodeVisibilityManager
            # but not directly to NodeVisibilityDialog. However, NodeVisibilityDialog has connection_manager
            # which has config_manager.
            split_audio_midi = False
            if hasattr(self.connection_manager, 'config_manager'):
                split_audio_midi = self.connection_manager.config_manager.get_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', False)
            
            # If we are in the graph tab and splitting is enabled, we need special handling
            if self.tab_type == 'graph' and split_audio_midi:
                # Get all ports to determine which clients have what
                all_audio_ports = jack_utils.get_all_jack_ports(self.connection_manager.client, is_audio=True)
                all_midi_ports = jack_utils.get_all_jack_ports(self.connection_manager.client, is_midi=True)
                
                client_capabilities = {} # client_name -> {'audio': bool, 'midi': bool}
                
                for port in all_audio_ports:
                    parts = port.name.split(':')
                    if parts:
                        client = parts[0]
                        if client not in client_capabilities:
                            client_capabilities[client] = {'audio': False, 'midi': False}
                        client_capabilities[client]['audio'] = True
                        
                for port in all_midi_ports:
                    parts = port.name.split(':')
                    if parts:
                        client = parts[0]
                        if client not in client_capabilities:
                            client_capabilities[client] = {'audio': False, 'midi': False}
                        client_capabilities[client]['midi'] = True
                
                # Now generate the list based on requested type
                for client, caps in client_capabilities.items():
                    if caps['audio'] and caps['midi']:
                        # Mixed client - split it
                        if is_midi:
                            unique_clients.add(f"{client} (MIDI)")
                        else:
                            unique_clients.add(f"{client} (Audio)")
                    else:
                        # Not mixed, add as is if it matches the requested type
                        if is_midi and caps['midi']:
                            unique_clients.add(client)
                        elif not is_midi and caps['audio']:
                            unique_clients.add(client)
                            
            else:
                # Standard behavior for other tabs or when split is disabled
                if is_midi:
                    ports = jack_utils.get_all_jack_ports(self.connection_manager.client, is_midi=True)
                else:
                    ports = jack_utils.get_all_jack_ports(self.connection_manager.client, is_audio=True)
                
                # Extract client names (part before the colon)
                for port in ports:
                    parts = port.name.split(':')
                    if parts:
                        unique_clients.add(parts[0])
                        
        except Exception as e:
            print(f"Error getting client names: {e}")
        
        return unique_clients
    
    def _on_audio_input_checkbox_changed(self, node_name, state):
        """
        Handle checkbox state change for audio inputs.
        
        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.audio_input_visibility[node_name] = (state == Qt.CheckState.Checked.value)
    
    def _on_audio_output_checkbox_changed(self, node_name, state):
        """
        Handle checkbox state change for audio outputs.
        
        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.audio_output_visibility[node_name] = (state == Qt.CheckState.Checked.value)
    
    def _on_midi_input_checkbox_changed(self, node_name, state):
        """
        Handle checkbox state change for MIDI inputs.
        
        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.midi_input_visibility[node_name] = (state == Qt.CheckState.Checked.value)
    
    def _on_midi_output_checkbox_changed(self, node_name, state):
        """
        Handle checkbox state change for MIDI outputs.
        
        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.midi_output_visibility[node_name] = (state == Qt.CheckState.Checked.value)
    
    def _select_all(self):
        """Select all visible checkboxes."""
        for node_dict in [self.audio_nodes, self.midi_nodes]:
            for checkboxes in node_dict.values():
                if not checkboxes['widget'].isHidden():
                    node_cb = checkboxes['node']
                    input_cb = checkboxes.get('input')
                    output_cb = checkboxes.get('output')
                    
                    if input_cb:
                        input_cb.setChecked(True)
                    if output_cb:
                        output_cb.setChecked(True)
                    
                    # Update node checkbox state to reflect children
                    self._update_node_checkbox_state(node_cb, input_cb, output_cb)
    
    def _deselect_all(self):
        """Deselect all visible checkboxes and hide all nodes."""
        # First, uncheck all visible checkboxes in the dialog
        for node_dict in [self.audio_nodes, self.midi_nodes]:
            for checkboxes in node_dict.values():
                if not checkboxes['widget'].isHidden():
                    node_cb = checkboxes['node']
                    input_cb = checkboxes.get('input')
                    output_cb = checkboxes.get('output')
                    
                    if input_cb:
                        input_cb.setChecked(False)
                    if output_cb:
                        output_cb.setChecked(False)
                    
                    # Update node checkbox state to reflect children
                    self._update_node_checkbox_state(node_cb, input_cb, output_cb)
        
        # Also explicitly set all nodes in visibility dictionaries to False
        # This ensures nodes that don't appear in the current dialog (due to tab type)
        # are also hidden
        for client_name in list(self.audio_input_visibility.keys()):
            self.audio_input_visibility[client_name] = False
        for client_name in list(self.audio_output_visibility.keys()):
            self.audio_output_visibility[client_name] = False
        for client_name in list(self.midi_input_visibility.keys()):
            self.midi_input_visibility[client_name] = False
        for client_name in list(self.midi_output_visibility.keys()):
            self.midi_output_visibility[client_name] = False
    
    def _apply_filter(self, filter_text):
        """
        Apply filter to checkboxes.
        
        Args:
            filter_text: The filter text
        """
        filter_text = filter_text.lower()
        
        audio_visible = False
        midi_visible = False
        
        # Apply filter to audio nodes
        for node_name, checkboxes in self.audio_nodes.items():
            should_hide = bool(filter_text and filter_text not in node_name.lower())
            checkboxes['widget'].setHidden(should_hide)
            if not should_hide:
                audio_visible = True
        
        # Apply filter to MIDI nodes
        for node_name, checkboxes in self.midi_nodes.items():
            should_hide = bool(filter_text and filter_text not in node_name.lower())
            checkboxes['widget'].setHidden(should_hide)
            if not should_hide:
                midi_visible = True
        
        # Show/hide section labels based on if any items are visible
        self.audio_label.setHidden(not audio_visible)
        self.midi_label.setHidden(not midi_visible)
