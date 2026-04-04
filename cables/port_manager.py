# cables/port_manager.py
"""
Manages port discovery, filtering, and population of Audio/MIDI tree widgets.
"""
import jack
from PyQt6.QtCore import Qt
from cables.jack_service import get_jack_service
from cables.utils.sort_utils import natural_sort_key_for_full_port_name

import logging
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Tuple, Set

if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager
    from cables.features.node_visibility_manager import NodeVisibilityManager
    from cables.ui.port_tree_widget import PortTreeWidget
    from PyQt6.QtWidgets import QLineEdit, QTreeWidget

logger = logging.getLogger(__name__)

class PortManager:
    """Manages fetching, sorting, and filtering of JACK ports."""

    def __init__(self, connection_manager: 'JackConnectionManager', jack_client: Optional[jack.Client], input_filter_edit: Optional['QLineEdit'], output_filter_edit: Optional['QLineEdit']) -> None:
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
        self._jack_service = get_jack_service()
        
        # Node visibility manager will be set by JackConnectionManager
        self.node_visibility_manager: Optional['NodeVisibilityManager'] = None

        # Initialize trees as None, they will be set by set_trees()
        self.input_tree: Optional['PortTreeWidget'] = None
        self.output_tree: Optional['PortTreeWidget'] = None
        self.midi_input_tree: Optional['PortTreeWidget'] = None
        self.midi_output_tree: Optional['PortTreeWidget'] = None

        # Do NOT connect filter signals here yet

    def set_trees(self, input_tree: 'PortTreeWidget', output_tree: 'PortTreeWidget', midi_input_tree: 'PortTreeWidget', midi_output_tree: 'PortTreeWidget') -> None:
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

    def set_node_visibility_manager(self, node_visibility_manager: 'NodeVisibilityManager') -> None:
        """
        Set the node visibility manager.
        
        Args:
            node_visibility_manager: The NodeVisibilityManager instance
        """
        self.node_visibility_manager = node_visibility_manager

    def _get_ports(self, is_midi_tab: bool) -> Tuple[List[str], List[str]]:
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
                input_port_objects = self._jack_service.get_ports(is_input=True, is_midi=True)
                output_port_objects = self._jack_service.get_ports(is_output=True, is_midi=True)
            else:
                # For Audio tab, get Audio ports (explicitly not MIDI)
                input_port_objects = self._jack_service.get_ports(is_input=True, is_audio=True)
                output_port_objects = self._jack_service.get_ports(is_output=True, is_audio=True)

            # Filter ports by visibility if node_visibility_manager is available
            if self.node_visibility_manager:
                # Determine tab type based on is_midi_tab parameter
                tab_type = "midi" if is_midi_tab else "audio"
                
                # For input ports, only check input visibility
                input_port_names = []
                for p in input_port_objects:
                    client_name = p.name.split(':', 1)[0] if ':' in p.name else p.name
                    if self.node_visibility_manager.is_input_visible(client_name, is_midi=is_midi_tab, tab_type=tab_type):
                        input_port_names.append(p.name)
                
                # For output ports, only check output visibility
                output_port_names = []
                for p in output_port_objects:
                    client_name = p.name.split(':', 1)[0] if ':' in p.name else p.name
                    if self.node_visibility_manager.is_output_visible(client_name, is_midi=is_midi_tab, tab_type=tab_type):
                        output_port_names.append(p.name)
            else:
                input_port_names = [p.name for p in input_port_objects]
                output_port_names = [p.name for p in output_port_objects]

            input_port_names = self._sort_ports(input_port_names)
            output_port_names = self._sort_ports(output_port_names)

        except jack.JackError as e: # This might be redundant if jack_utils handles it, but good for safety.
            logger.error(f"Error getting ports via jack_utils: {e}")
            # jack_utils functions return [] on JackError, so lists will be empty.
            pass
        
        return input_port_names, output_port_names

    def _sort_ports(self, port_names: List[str]) -> List[str]:
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
        return sorted(port_names, key=natural_sort_key_for_full_port_name)

    def filter_ports(self, tree_widget: Optional['QTreeWidget'], filter_text: str) -> None:
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

    def _handle_filter_change(self) -> None:
        """Handles text changes in the shared filter boxes."""
        # Access tab_widget through ui_manager
        tab_widget = self.connection_manager.ui_manager.tab_widget
        current_index = tab_widget.currentIndex()
        current_tab_text = tab_widget.tabText(current_index)
        input_text = self.input_filter_edit.text()
        output_text = self.output_filter_edit.text()

        # Use tab name to determine which trees to filter (handles integrated mode)
        if current_tab_text == "Audio":
            self.filter_ports(self.input_tree, input_text)
            self.filter_ports(self.output_tree, output_text)
        elif current_tab_text == "MIDI":
            self.filter_ports(self.midi_input_tree, input_text)
            self.filter_ports(self.midi_output_tree, output_text)
