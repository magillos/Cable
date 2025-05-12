# cables/port_manager.py
import jack
import re
from PyQt6.QtCore import Qt

class PortManager:
    """Manages fetching, sorting, and filtering of JACK ports."""

    def __init__(self, connection_manager, jack_client, input_filter_edit, output_filter_edit):
        """
        Initialize the PortManager. Trees are set later via set_trees().

        Args:
            connection_manager: The main JackConnectionManager instance.
            jack_client: The jack.Client instance.
            input_filter_edit: The QLineEdit for input filtering.
            output_filter_edit: The QLineEdit for output filtering.
        """
        self.connection_manager = connection_manager
        self.jack_client = jack_client
        self.input_filter_edit = input_filter_edit
        self.output_filter_edit = output_filter_edit

        # Initialize trees as None, they will be set by set_trees()
        self.input_tree = None
        self.output_tree = None
        self.midi_input_tree = None
        self.midi_output_tree = None

        # Do NOT connect filter signals here yet

    def set_trees(self, input_tree, output_tree, midi_input_tree, midi_output_tree):
        """
        Set the tree widgets and connect filter signals. Called after trees are created.

        Args:
            input_tree: The QTreeWidget for audio input ports.
            output_tree: The QTreeWidget for audio output ports.
            midi_input_tree: The QTreeWidget for MIDI input ports.
            midi_output_tree: The QTreeWidget for MIDI output ports.
        """
        self.input_tree = input_tree
        self.output_tree = output_tree
        self.midi_input_tree = midi_input_tree
        self.midi_output_tree = midi_output_tree

        # Connect filter signals now that trees and filters exist
        if self.input_filter_edit:
            # Ensure no duplicate connections if called multiple times (though it shouldn't be)
            try: self.input_filter_edit.textChanged.disconnect(self._handle_filter_change)
            except TypeError: pass
            self.input_filter_edit.textChanged.connect(self._handle_filter_change)

        if self.output_filter_edit:
            try: self.output_filter_edit.textChanged.disconnect(self._handle_filter_change)
            except TypeError: pass
            self.output_filter_edit.textChanged.connect(self._handle_filter_change)


    def _get_ports(self, is_midi):
        """
        Get the input and output ports.

        Args:
            is_midi: Whether to get MIDI ports

        Returns:
            tuple: A tuple containing the input and output ports
        """
        input_ports = []
        output_ports = []
        try:
            # Get input port objects
            input_port_objects = self.jack_client.get_ports(is_input=True, is_midi=is_midi)

            # Get output port objects
            output_port_objects = self.jack_client.get_ports(is_output=True, is_midi=is_midi)

            # Explicitly filter for the Audio tab (is_midi=False)
            # Ensure only ports reported as non-MIDI by the port object itself are included.
            if not is_midi:
                input_port_objects = [p for p in input_port_objects if p is not None and not p.is_midi]
                output_port_objects = [p for p in output_port_objects if p is not None and not p.is_midi]
            else:
                # For MIDI tab, just ensure ports are not None
                input_port_objects = [p for p in input_port_objects if p is not None]
                output_port_objects = [p for p in output_port_objects if p is not None]

            # Extract names from the filtered objects
            input_ports = [p.name for p in input_port_objects]
            output_ports = [p.name for p in output_port_objects]

            # Sort the names
            input_ports = self._sort_ports(input_ports)
            output_ports = self._sort_ports(output_ports)
        except jack.JackError as e:
            print(f"Error getting ports: {e}")
            # Return current lists even if incomplete
            pass

        return input_ports, output_ports

    def _sort_ports(self, port_names):
        """
        Sort port names in a natural order.

        Args:
            port_names: The port names to sort

        Returns:
            list: The sorted port names
        """
        def get_sort_key(port_name):
            parts = re.split(r'(\d+)', port_name)
            key = []
            for part in parts:
                if part.isdigit():
                    key.append(int(part))
                else:
                    key.append(part.lower())
            return key

        return sorted(port_names, key=get_sort_key)

    def filter_ports(self, tree_widget, filter_text):
        """
        Filters the items in the specified tree widget based on the filter text.

        Args:
            tree_widget: The tree widget to filter
            filter_text: The filter text
        """
        if not tree_widget: # Guard against None tree during initialization phases
             return

        filter_text_lower = filter_text.lower()
        terms = filter_text_lower.split()
        include_terms = [term for term in terms if not term.startswith('-')]
        exclude_terms = [term[1:] for term in terms if term.startswith('-') and len(term) > 1]  # Remove '-'

        # Iterate through all top-level items (groups)
        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            group_visible = False  # Assume group is hidden unless a child matches

            # Iterate through children (ports) of the group
            for j in range(group_item.childCount()):
                port_item = group_item.child(j)
                port_name = port_item.data(0, Qt.ItemDataRole.UserRole)  # Get full port name
                if not port_name:  # Skip if port name is invalid
                    port_item.setHidden(True)
                    continue

                port_name_lower = port_name.lower()

                # 1. Check exclusion terms
                excluded = False
                for term in exclude_terms:
                    if term in port_name_lower:
                        excluded = True
                        break
                if excluded:
                    port_item.setHidden(True)
                    continue  # Skip to next port if excluded

                # 2. Check inclusion terms (all must match)
                included = True
                if include_terms:  # Only check if there are inclusion terms
                    for term in include_terms:
                        if term not in port_name_lower:
                            included = False
                            break

                if included:
                    port_item.setHidden(False)
                    group_visible = True  # Make group visible if this port is visible
                else:
                    port_item.setHidden(True)

            # Set the visibility of the group item
            group_item.setHidden(not group_visible)

        # After filtering, we need to refresh the connection visualization
        # because hidden items might affect line drawing positions.
        # Call the method on the connection_manager instance
        self.connection_manager.refresh_visualizations()

    def _handle_filter_change(self):
        """Handles text changes in the shared filter boxes."""
        # Access tab_widget through connection_manager
        current_index = self.connection_manager.tab_widget.currentIndex()
        input_text = self.input_filter_edit.text()
        output_text = self.output_filter_edit.text()

        # Use the tree references stored in self
        if current_index == 0:  # Audio tab
            self.filter_ports(self.input_tree, input_text)
            self.filter_ports(self.output_tree, output_text)
        elif current_index == 1:  # MIDI tab
            self.filter_ports(self.midi_input_tree, input_text)
            self.filter_ports(self.midi_output_tree, output_text)