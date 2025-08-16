# cables/port_manager.py
import jack
import re
from PyQt6.QtCore import Qt
from cables import jack_utils # Import the new jack_utils module

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
        
        # Node visibility manager will be set by JackConnectionManager
        self.node_visibility_manager = None

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
            # Style to match Graph tab's filter
            self.input_filter_edit.setFrame(False)
            self.input_filter_edit.setStyleSheet("""
                QLineEdit {
                    border: 1px solid rgba(0, 0, 0, 0.1);
                    border-radius: 3px;
                    padding: 2px 5px;
                }
                QLineEdit:focus {
                    border: 1px solid rgba(0, 85, 255, 0.3);
                }
            """)
            # Ensure no duplicate connections if called multiple times
            try: self.input_filter_edit.textChanged.disconnect(self._handle_filter_change)
            except TypeError: pass
            self.input_filter_edit.textChanged.connect(self._handle_filter_change)

        if self.output_filter_edit:
            # Style to match Graph tab's filter
            self.output_filter_edit.setFrame(False)
            self.output_filter_edit.setStyleSheet("""
                QLineEdit {
                    border: 1px solid rgba(0, 0, 0, 0.1);
                    border-radius: 3px;
                    padding: 2px 5px;
                }
                QLineEdit:focus {
                    border: 1px solid rgba(0, 85, 255, 0.3);
                }
            """)
            try: self.output_filter_edit.textChanged.disconnect(self._handle_filter_change)
            except TypeError: pass
            self.output_filter_edit.textChanged.connect(self._handle_filter_change)

    def set_node_visibility_manager(self, node_visibility_manager):
        """
        Set the node visibility manager.
        
        Args:
            node_visibility_manager: The NodeVisibilityManager instance
        """
        self.node_visibility_manager = node_visibility_manager

    def _get_ports(self, is_midi_tab: bool):
        """
        Get the input and output ports using jack_utils.

        Args:
            is_midi_tab: Whether to get MIDI ports (for MIDI tab) or Audio ports (for Audio tab)

        Returns:
            tuple: A tuple containing the sorted input and output port names
        """
        input_port_names = []
        output_port_names = []

        if not self.jack_client:
            return input_port_names, output_port_names

        try:
            if is_midi_tab:
                # For MIDI tab, get MIDI ports
                input_port_objects = jack_utils.get_all_jack_ports(self.jack_client, is_input=True, is_midi=True)
                output_port_objects = jack_utils.get_all_jack_ports(self.jack_client, is_output=True, is_midi=True)
            else:
                # For Audio tab, get Audio ports (explicitly not MIDI)
                # jack.Client.get_ports(is_audio=True) is the most direct way.
                input_port_objects = jack_utils.get_all_jack_ports(self.jack_client, is_input=True, is_audio=True)
                output_port_objects = jack_utils.get_all_jack_ports(self.jack_client, is_output=True, is_audio=True)

            # Filter ports by visibility if node_visibility_manager is available
            if self.node_visibility_manager:
                # For input ports, only check input visibility
                input_port_names = []
                for p in input_port_objects:
                    client_name = p.name.split(':', 1)[0] if ':' in p.name else p.name
                    if self.node_visibility_manager.is_input_visible(client_name, is_midi=is_midi_tab):
                        input_port_names.append(p.name)
                
                # For output ports, only check output visibility
                output_port_names = []
                for p in output_port_objects:
                    client_name = p.name.split(':', 1)[0] if ':' in p.name else p.name
                    if self.node_visibility_manager.is_output_visible(client_name, is_midi=is_midi_tab):
                        output_port_names.append(p.name)
            else:
                input_port_names = [p.name for p in input_port_objects]
                output_port_names = [p.name for p in output_port_objects]

            input_port_names = self._sort_ports(input_port_names)
            output_port_names = self._sort_ports(output_port_names)

        except jack.JackError as e: # This might be redundant if jack_utils handles it, but good for safety.
            print(f"Error getting ports via jack_utils: {e}")
            # jack_utils functions return [] on JackError, so lists will be empty.
            pass
        
        return input_port_names, output_port_names

    def _sort_ports(self, port_names):
        """
        Sort port names in a logical order, grouping by base name.
        
        For example, ports like:
        - Equalizer:input_FL
        - Equalizer:input_FL-448
        - Equalizer:input_FL-458
        - Equalizer:input_FR
        - Equalizer:input_FR-449
        - Equalizer:input_FR-459
        
        Will be sorted as:
        - Equalizer:input_FL
        - Equalizer:input_FR
        - Equalizer:input_FL-448
        - Equalizer:input_FR-449
        - Equalizer:input_FL-458
        - Equalizer:input_FR-459

        Args:
            port_names: The port names to sort

        Returns:
            list: The sorted port names
        """
        def get_enhanced_sort_key(port_name):
            """Enhanced sort key that groups ports logically"""
            def tryint(text):
                try:
                    return int(text)
                except ValueError:
                    return text.lower()

            # Split the port name into client and port parts
            if ':' in port_name:
                client_part, port_part = port_name.split(':', 1)
            else:
                client_part, port_part = '', port_name
            
            # Extract base name and suffix from port part
            # Look for patterns like "input_FL-448" or "output_1-mono"
            base_name = port_part
            suffix = ''
            
            # Try to find a suffix pattern (dash followed by numbers/text)
            suffix_match = re.search(r'[-_](\d+.*?)$', port_part)
            if suffix_match:
                suffix = suffix_match.group(1)
                base_name = port_part[:suffix_match.start()]
            
            # Create sort key components
            client_key = [tryint(part) for part in re.split(r'(\d+)', client_part.lower())]
            base_name_key = [tryint(part) for part in re.split(r'(\d+)', base_name.lower())]
            
            # For the desired sorting behavior:
            # 1. First show all base ports (no suffix) sorted by base name
            # 2. Then show suffixed ports, grouped by suffix value, with base names sorted within each suffix group
            if suffix:
                suffix_key = [tryint(part) for part in re.split(r'(\d+)', suffix.lower())]
                # For suffixed ports: sort by (client, suffix, base_name)
                return (client_key, [1], suffix_key, base_name_key)  # [1] puts suffixed ports after base ports
            else:
                # For base ports: sort by (client, base_name)
                return (client_key, [0], base_name_key, [])  # [0] puts base ports first

        return sorted(port_names, key=get_enhanced_sort_key)

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