# cables/highlight_manager.py

import jack
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QTreeWidgetItem, QTreeWidget
from PyQt6.QtCore import Qt

class HighlightManager:
    """Manages highlighting of ports and groups in the tree widgets."""

    def __init__(self, input_tree, output_tree, midi_input_tree, midi_output_tree, client, colors):
        """
        Initialize the HighlightManager.

        Args:
            input_tree: The input port tree widget (PortTreeWidget).
            output_tree: The output port tree widget (PortTreeWidget).
            midi_input_tree: The MIDI input port tree widget (PortTreeWidget).
            midi_output_tree: The MIDI output port tree widget (PortTreeWidget).
            client: The jack.Client instance.
            colors: A dictionary containing color definitions.
        """
        self.input_tree = input_tree
        self.output_tree = output_tree
        self.midi_input_tree = midi_input_tree
        self.midi_output_tree = midi_output_tree
        self.client = client
        self.colors = colors # Expecting keys like 'highlight', 'auto_highlight', 'drag_highlight', 'text', 'background'

        # Store colors for easy access
        self.default_text_color = self.colors.get('text', QColor("black"))
        self.default_background_color = self.colors.get('background', QColor("white"))
        self.highlight_color = self.colors.get('highlight', QColor(173, 216, 230)) # Default light mode highlight
        self.auto_highlight_color = self.colors.get('auto_highlight', QColor(255, 140, 0)) # Default light mode auto-highlight
        self.drag_highlight_color = self.colors.get('drag_highlight', QColor(200, 200, 200)) # Default light mode drag highlight

    def set_trees(self, input_tree, output_tree, midi_input_tree, midi_output_tree):
        """
        Update tree references after they are created.

        Args:
            input_tree: The input port tree widget (PortTreeWidget).
            output_tree: The output port tree widget (PortTreeWidget).
            midi_input_tree: The MIDI input port tree widget (PortTreeWidget).
            midi_output_tree: The MIDI output port tree widget (PortTreeWidget).
        """
        self.input_tree = input_tree
        self.output_tree = output_tree
        self.midi_input_tree = midi_input_tree
        self.midi_output_tree = midi_output_tree

    # --- Highlighting Methods Moved from JackConnectionManager ---

    def _highlight_connected_outputs_for_input(self, input_name, is_midi):
        """
        Highlight output ports connected to the given input port.

        Args:
            input_name: The name of the input port
            is_midi: Whether the port is a MIDI port
        """
        try:
            # Get only relevant output ports
            output_ports = self.client.get_ports(is_output=True, is_midi=is_midi)
            for output_port in output_ports:
                try:
                    # Check if output port exists before querying connections
                    if not any(p.name == output_port.name for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    connections = self.client.get_all_connections(output_port)
                    if input_name in [conn.name for conn in connections]:
                        if is_midi:
                            self.highlight_midi_output(output_port.name, auto_highlight=True)
                        else:
                            self.highlight_output(output_port.name, auto_highlight=True)
                except jack.JackError:
                    continue # Ignore errors for individual ports
        except jack.JackError as e:
            print(f"Error highlighting connected outputs: {e}")

    def _highlight_connected_inputs_for_output(self, output_name, is_midi):
        """
        Highlight input ports connected to the given output port.

        Args:
            output_name: The name of the output port
            is_midi: Whether the port is a MIDI port
        """
        try:
            # Get only relevant input ports
            input_ports = self.client.get_ports(is_input=True, is_midi=is_midi)
            for input_port in input_ports:
                try:
                    # Check if input port exists before querying connections
                    if not any(p.name == input_port.name for p in self.client.get_ports(is_input=True, is_midi=is_midi)):
                        continue
                    connections = self.client.get_all_connections(input_port)
                    if output_name in [c.name for c in connections]:
                        if is_midi:
                            self.highlight_midi_input(input_port.name, auto_highlight=True)
                        else:
                            self.highlight_input(input_port.name, auto_highlight=True)
                except jack.JackError:
                    continue # Ignore errors for individual ports
        except jack.JackError as e:
            print(f"Error highlighting connected inputs: {e}")

    def _highlight_connected_output_groups_for_input_group(self, input_group_item, is_midi):
        """
        Finds and highlights output groups connected to the selected input group.

        Args:
            input_group_item: The input group item
            is_midi: Whether the port is a MIDI port
        """
        input_ports = self._get_ports_in_group(input_group_item)
        if not input_ports:
            return

        output_tree = self.midi_output_tree if is_midi else self.output_tree

        try:
            # Iterate through all output ports to find connections to any port in the input group
            output_port_objects = self.client.get_ports(is_output=True, is_midi=is_midi)
            connected_output_groups = set()  # Store names of groups to highlight

            for output_port in output_port_objects:
                try:
                    # Check if output port exists before querying
                    if not any(p.name == output_port.name for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    connections = self.client.get_all_connections(output_port)
                    # Check if this output port connects to *any* port in the selected input group
                    if any(conn.name in input_ports for conn in connections):
                        # Find the group this output port belongs to
                        output_item = output_tree.port_items.get(output_port.name)
                        if output_item and output_item.parent():
                            connected_output_groups.add(output_item.parent().text(0))
                except jack.JackError:
                    continue  # Ignore errors for individual ports

            # Highlight the identified groups
            for group_name in connected_output_groups:
                self._highlight_group_item(output_tree, group_name)

        except jack.JackError as e:
            print(f"Error highlighting connected output groups: {e}")

    def _highlight_connected_input_groups_for_output_group(self, output_group_item, is_midi):
        """
        Finds and highlights input groups connected to the selected output group.

        Args:
            output_group_item: The output group item
            is_midi: Whether the port is a MIDI port
        """
        output_ports = self._get_ports_in_group(output_group_item)
        if not output_ports:
            return

        input_tree = self.midi_input_tree if is_midi else self.input_tree

        try:
            connected_input_groups = set()  # Store names of groups to highlight

            # Iterate through all ports in the selected output group
            for output_name in output_ports:
                try:
                    # Check if output port exists before querying
                    if not any(p.name == output_name for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    # Get all connections *from* this specific output port
                    connections = self.client.get_all_connections(output_name)
                    for input_port in connections:
                        # Find the group this connected input port belongs to
                        input_item = input_tree.port_items.get(input_port.name)
                        if input_item and input_item.parent():
                            connected_input_groups.add(input_item.parent().text(0))
                except jack.JackError:
                    continue  # Ignore errors for individual ports

            # Highlight the identified groups
            for group_name in connected_input_groups:
                self._highlight_group_item(input_tree, group_name)

        except jack.JackError as e:
            print(f"Error highlighting connected input groups: {e}")

    def _get_ports_in_group(self, item):
        """
        Get all ports in a group or just the single port if it's a port item.

        Args:
            item: The tree item

        Returns:
            list: The ports in the group
        """
        if not item:
            return []
        if item.childCount() == 0:  # It's a port item
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            return [port_name] if port_name else []
        else:  # It's a group item
            ports = []
            for i in range(item.childCount()):
                child = item.child(i)
                port_name = child.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    ports.append(port_name)
            return ports

    def highlight_input(self, input_name, auto_highlight=False):
        """Highlight an input port."""
        self._highlight_tree_item_by_name(self.input_tree, input_name, auto_highlight)

    def highlight_output(self, output_name, auto_highlight=False):
        """Highlight an output port."""
        self._highlight_tree_item_by_name(self.output_tree, output_name, auto_highlight)

    def highlight_midi_input(self, input_name, auto_highlight=False):
        """Highlight a MIDI input port."""
        self._highlight_tree_item_by_name(self.midi_input_tree, input_name, auto_highlight)

    def highlight_midi_output(self, output_name, auto_highlight=False):
        """Highlight a MIDI output port."""
        self._highlight_tree_item_by_name(self.midi_output_tree, output_name, auto_highlight)

    def _highlight_tree_item_by_name(self, tree_widget, port_name, auto_highlight=False):
        """
        Highlight a specific port item in a tree widget by port name.

        Args:
            tree_widget: The tree widget (PortTreeWidget).
            port_name: The name of the port.
            auto_highlight: Whether to use the auto highlight color.
        """
        port_item = tree_widget.port_items.get(port_name)
        if port_item:
            color = self.auto_highlight_color if auto_highlight else self.highlight_color
            # Use setForeground for text color highlighting as before
            port_item.setForeground(0, QBrush(color))
            # Optionally, use setBackground for background highlighting:
            # port_item.setBackground(0, QBrush(color))

    def _highlight_group_item(self, tree_widget, group_name):
        """
        Highlight a specific group item in a tree widget.

        Args:
            tree_widget: The tree widget (PortTreeWidget).
            group_name: The name of the group.
        """
        group_item = tree_widget.port_groups.get(group_name)
        if group_item:
            # Use the auto_highlight_color for connected groups (foreground)
            group_item.setForeground(0, QBrush(self.auto_highlight_color))
            # Optionally, use setBackground for background highlighting:
            # group_item.setBackground(0, QBrush(self.auto_highlight_color))

    def clear_highlights(self):
        """Clear highlights from audio port trees."""
        self._clear_tree_highlights(self.input_tree)
        self._clear_tree_highlights(self.output_tree)

    def clear_midi_highlights(self):
        """Clear highlights from MIDI port trees."""
        self._clear_tree_highlights(self.midi_input_tree)
        self._clear_tree_highlights(self.midi_output_tree)

    def _clear_tree_highlights(self, tree_widget):
        """
        Clear highlights (foreground/background) from all group and port items in a tree widget.

        Args:
            tree_widget: The tree widget (PortTreeWidget).
        """
        if not hasattr(tree_widget, 'topLevelItemCount'):
            return  # Safety check

        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            # Reset group item highlight (foreground and background)
            group_item.setForeground(0, QBrush(self.default_text_color))
            group_item.setBackground(0, QBrush(self.default_background_color))
            # Reset child item highlights
            for j in range(group_item.childCount()):
                child_item = group_item.child(j)
                child_item.setForeground(0, QBrush(self.default_text_color))
                child_item.setBackground(0, QBrush(self.default_background_color))

    def highlight_drop_target_item(self, item: QTreeWidgetItem):
        """
        Highlight an item when being dragged over (background).

        Args:
            item: The item to highlight.
        """
        if item:
            item.setBackground(0, QBrush(self.drag_highlight_color))

    def clear_drop_target_highlight(self, tree_widget: QTreeWidget):
        """
        Clear drop target highlighting (background) from all items in a tree.

        Args:
            tree_widget: The tree widget.
        """
        if isinstance(tree_widget, QTreeWidget):
            for i in range(tree_widget.topLevelItemCount()):
                group_item = tree_widget.topLevelItem(i)
                group_item.setBackground(0, QBrush(self.default_background_color))
                for j in range(group_item.childCount()):
                    child_item = group_item.child(j)
                    child_item.setBackground(0, QBrush(self.default_background_color))

    # --- Helper to apply highlights based on selection ---

    def apply_highlights_for_selection(self, clicked_item, clicked_tree, is_midi):
        """
        Applies appropriate highlights based on the selected item (port or group).
        This combines the logic previously in _on_port_clicked and refresh_ports.

        Args:
            clicked_item: The currently selected/clicked item.
            clicked_tree: The tree widget where the selection occurred.
            is_midi: Boolean indicating if it's the MIDI tab.
        """
        if not clicked_item:
            return

        # 1. Clear previous highlights for the correct type
        if is_midi:
            self.clear_midi_highlights()
        else:
            self.clear_highlights()

        # 2. Highlight the selected item itself
        is_group_item = clicked_item.childCount() > 0
        if is_group_item:
            group_name = clicked_item.text(0)
            self._highlight_group_item(clicked_tree, group_name) # Use standard highlight for selected group
        else: # Port item
            port_name = clicked_item.data(0, Qt.ItemDataRole.UserRole)
            if port_name:
                if is_midi:
                    if clicked_tree == self.midi_input_tree:
                        self.highlight_midi_input(port_name)
                    else:
                        self.highlight_midi_output(port_name)
                else:
                    if clicked_tree == self.input_tree:
                        self.highlight_input(port_name)
                    else:
                        self.highlight_output(port_name)

        # 3. Highlight connected items/groups (using auto-highlight color)
        if is_group_item:
            if is_midi:
                if clicked_tree == self.midi_input_tree:
                    self._highlight_connected_output_groups_for_input_group(clicked_item, is_midi)
                else: # Clicked on midi_output_tree
                    self._highlight_connected_input_groups_for_output_group(clicked_item, is_midi)
            else: # Audio
                if clicked_tree == self.input_tree:
                    self._highlight_connected_output_groups_for_input_group(clicked_item, is_midi)
                else: # Clicked on output_tree
                    self._highlight_connected_input_groups_for_output_group(clicked_item, is_midi)
        else: # Port item
            port_name = clicked_item.data(0, Qt.ItemDataRole.UserRole)
            if port_name:
                if is_midi:
                    if clicked_tree == self.midi_input_tree:
                        self._highlight_connected_outputs_for_input(port_name, is_midi)
                    else: # Clicked on midi_output_tree
                        self._highlight_connected_inputs_for_output(port_name, is_midi)
                else: # Audio
                    if clicked_tree == self.input_tree:
                        self._highlight_connected_outputs_for_input(port_name, is_midi)
                    else: # Clicked on output_tree
                        self._highlight_connected_inputs_for_output(port_name, is_midi)
