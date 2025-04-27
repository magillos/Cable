"""
PortTreeWidget - Tree widget for displaying ports with collapsible groups
"""

import re
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu, QSizePolicy, QApplication
from PyQt6.QtCore import Qt, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QBrush, QDrag, QPixmap, QPainter, QFontMetrics, QAction, QPalette, QFont
from PyQt6.QtCore import QMimeData

class PortTreeWidget(QTreeWidget):
    """
    A tree widget for displaying ports with collapsible groups.
    
    This class provides a hierarchical view of ports organized into groups,
    with support for drag and drop operations.
    """
    
    itemDragged = pyqtSignal(QTreeWidgetItem)
    
    def __init__(self, port_role, parent=None):
        """
        Initialize the PortTreeWidget.
        
        Args:
            port_role: The role of the ports ('input' or 'output')
            parent: The parent widget
        """
        super().__init__(parent)
        self.port_role = port_role  # Store the role ('input' or 'output')
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(100)
        self._width = 150
        self.current_drag_highlight_item = None
        self.setHeaderHidden(True)
        self.setIndentation(15)
        self.port_groups = {}  # Maps group names to group items
        self.port_items = {}   # Maps port names to port items
        self.group_order = []  # Stores the *current visual* order of top-level group names
        self.manual_group_order = None # Stores the user-defined or initial natural order
        self.setDragEnabled(True)
        # Allow selecting multiple items with Ctrl/Shift
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        # Add tracking to improve drag behavior
        self.setMouseTracking(True)
        # Remember initially selected item to improve selection during drag operations
        self.initialSelection = None
        # Add storage for mouse press position
        self.mousePressPos = None
    
    def sizeHint(self):
        """
        Get the recommended size for the widget.
        
        Returns:
            QSize: The recommended size
        """
        return QSize(self._width, 300)  # Default height
    
    def get_current_group_order(self):
        """
        Returns a list of the current top-level group item names in their visual order.
        
        Returns:
            list: The current group order
        """
        order = []
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item:  # Basic check
                order.append(item.text(0))
        return order
    
    def _sort_items_naturally(self, items):
        """
        Sorts a list of strings using natural sorting (handles numbers).
        
        Args:
            items: The list of strings to sort
            
        Returns:
            list: The sorted list
        """
        def get_sort_key(item_name):
            # Treat None or non-string items gracefully if they somehow appear
            if not isinstance(item_name, str):
                return []  # Or handle as appropriate
            parts = re.split(r'(\d+)', item_name)
            key = []
            for part in parts:
                if part.isdigit():
                    key.append(int(part))
                else:
                    key.append(part.lower())
            return key
        # Filter out None before sorting if necessary, though item_name should always be str here
        return sorted([item for item in items if isinstance(item, str)], key=get_sort_key)

    def _calculate_untangled_order(self, all_ports, current_groups, ports_by_group, untangle_mode):
        """Calculates the group order based on connections.
        untangle_mode: 0=off, 1=normal (outputs drive inputs), 2=reversed (inputs drive outputs)
        """
        if untangle_mode == 0: # Should not be called if mode is 0, but handle defensively
             return self._sort_items_naturally(list(current_groups))

        # Access main window and client through self.window()
        main_window = self.window()
        if not main_window or not hasattr(main_window, 'client'):
            print("Error: Cannot access main window or JACK client from PortTreeWidget.")
            return self._sort_items_naturally(list(current_groups)) # Fallback

        connections = main_window._get_current_connections() # Use main window method
        is_input_tree = isinstance(self, DropPortTreeWidget) # Check if this is the input tree
        is_midi = main_window.port_type == 'midi' # Determine if we are dealing with MIDI ports

        connected_output_groups = set()
        connected_input_groups = set()
        output_to_inputs = {} # {output_port: {input_port1, input_port2}}
        input_to_outputs = {} # {input_port: {output_port1, output_port2}}
        group_to_group_connections = {} # {input_group: {output_group1, output_group2}}

        for conn_dict in connections:
            out_port = conn_dict.get('output')
            in_port = conn_dict.get('input')
            if not out_port or not in_port: # Skip if keys are missing or values are None/empty
                continue
            # Ensure we only process connections relevant to the current port type (audio/midi)
            conn_type = conn_dict.get("type", "audio") # Default to audio if type missing
            if (is_midi and conn_type != 'midi') or (not is_midi and conn_type != 'audio'):
                continue

            out_group = out_port.split(':', 1)[0] if ':' in out_port else out_port
            in_group = in_port.split(':', 1)[0] if ':' in in_port else in_port

            connected_output_groups.add(out_group)
            connected_input_groups.add(in_group)

            if out_port not in output_to_inputs: output_to_inputs[out_port] = set()
            output_to_inputs[out_port].add(in_port)

            if in_port not in input_to_outputs: input_to_outputs[in_port] = set()
            input_to_outputs[in_port].add(out_port)

            # Track group-to-group connections
            if in_group not in group_to_group_connections:
                group_to_group_connections[in_group] = set()
            group_to_group_connections[in_group].add(out_group)

        # --- Determine Primary and Secondary Groups based on mode ---
        primary_is_output = (untangle_mode == 1) # Normal mode: Outputs are primary

        # --- Get ALL primary groups for consistent numbering ---
        all_system_primary_ports = []
        try:
             # Fetch ports matching the current type (audio/midi) based on primary role
             all_system_primary_ports = main_window.client.get_ports(
                 is_output=primary_is_output,
                 is_input=not primary_is_output,
                 is_midi=is_midi,
                 is_audio=not is_midi
             )
        except main_window.client.JackError as e: # Use main_window.client.JackError
             print(f"Warning: Error fetching all system primary ports: {e}")

        all_primary_group_names = set()
        for port in all_system_primary_ports:
            if port and hasattr(port, 'name') and port.name: # Basic validation
                group_name = port.name.split(':', 1)[0] if ':' in port.name else port.name
                all_primary_group_names.add(group_name)

        # --- Primary Group Numbering (Based on ALL primary groups) ---
        naturally_sorted_all_primary_groups = self._sort_items_naturally(list(all_primary_group_names))

        # Create a consistent set of primary group numbers that will be used for both trees
        primary_group_numbers = {}
        number_counter = 1
        connected_primary_groups = connected_output_groups if primary_is_output else connected_input_groups
        for group_name in naturally_sorted_all_primary_groups:
            # Assign number only if the primary group is actually connected to something
            if group_name in connected_primary_groups:
                primary_group_numbers[group_name] = number_counter
                number_counter += 1

        # --- Secondary Group Numbering (Based on connections to numbered primary groups) ---
        secondary_group_numbers = {}
        connected_secondary_groups = connected_input_groups if primary_is_output else connected_output_groups
        # Iterate over the groups present in the *current* tree that are connected secondary groups
        for group_name in current_groups:
            if group_name in connected_secondary_groups: # Check if this secondary group has connections
                min_primary_group_number = None

                # Find the minimum number of the primary group(s) it connects to
                if primary_is_output: # Normal: Secondary=Input, Primary=Output
                    # Find minimum numbered output group this input group connects TO
                    if group_name in group_to_group_connections: # group_to_group_connections maps input -> {outputs}
                        for connected_primary_group in group_to_group_connections[group_name]:
                            if connected_primary_group in primary_group_numbers:
                                primary_number = primary_group_numbers[connected_primary_group]
                                if min_primary_group_number is None or primary_number < min_primary_group_number:
                                    min_primary_group_number = primary_number
                else: # Reversed: Secondary=Output, Primary=Input
                    # Find minimum numbered input group this output group connects FROM
                    min_primary_group_number = None
                    for conn_dict in connections:
                         out_port = conn_dict.get('output')
                         in_port = conn_dict.get('input')
                         if not out_port or not in_port: continue
                         conn_type = conn_dict.get("type", "audio")
                         if (is_midi and conn_type != 'midi') or (not is_midi and conn_type != 'audio'): continue

                         out_group = out_port.split(':', 1)[0] if ':' in out_port else out_port
                         in_group = in_port.split(':', 1)[0] if ':' in in_port else in_port

                         if out_group == group_name: # If this output group is the one we're processing
                             if in_group in primary_group_numbers: # And it connects to a numbered primary (input) group
                                 primary_number = primary_group_numbers[in_group]
                                 if min_primary_group_number is None or primary_number < min_primary_group_number:
                                     min_primary_group_number = primary_number

                if min_primary_group_number is not None:
                    secondary_group_numbers[group_name] = min_primary_group_number

        # --- Create final orders for the CURRENT tree ---
        # Determine which numbers to use based on tree type and mode
        if is_input_tree: # Sorting the INPUT tree
            if primary_is_output: # Normal mode: Input tree uses secondary numbers
                group_numbers_to_use = secondary_group_numbers
            else: # Reversed mode: Input tree uses primary numbers
                group_numbers_to_use = primary_group_numbers
        else: # Sorting the OUTPUT tree
            if primary_is_output: # Normal mode: Output tree uses primary numbers
                group_numbers_to_use = primary_group_numbers
            else: # Reversed mode: Output tree uses secondary numbers
                group_numbers_to_use = secondary_group_numbers

        # Generic sorting logic using the determined numbers
        numbered_groups_for_current_tree = sorted(
            [gn for gn in current_groups if gn in group_numbers_to_use], # Groups in current tree AND numbered
            key=lambda gn: group_numbers_to_use[gn]
        )
        unconnected_groups_for_current_tree = self._sort_items_naturally(
            [gn for gn in current_groups if gn not in group_numbers_to_use] # Groups in current tree but NOT numbered
        )
        final_order = numbered_groups_for_current_tree + unconnected_groups_for_current_tree

        return final_order

    def populate_tree(self, all_ports, previous_group_order=None): # Keep previous_group_order for non-untangle modes
        """
        Clears and repopulates the tree, preserving group order or using untangle sort.

        Args:
            all_ports: List of port names to populate the tree with
            previous_group_order: Optional list of group names in the desired order (used if untangle is off)
        """
        # 1. Determine current groups and ports per group (remains the same)
        current_groups = set()
        ports_by_group = {}
        for port_name in all_ports:
            group_name = port_name.split(':', 1)[0] if ':' in port_name else "Ungrouped"
            current_groups.add(group_name)
            if group_name not in ports_by_group:
                ports_by_group[group_name] = []
            ports_by_group[group_name].append(port_name)

        # 2. Determine final group order based on untangle mode
        main_window = self.window()
        untangle_mode = main_window.untangle_mode if main_window else 0 # Get current mode from main window

        if untangle_mode > 0:
            # Use the untangle logic with the current mode
            final_ordered_group_names = self._calculate_untangled_order(all_ports, current_groups, ports_by_group, untangle_mode)
        else:
            # Use previous order if provided and untangle is off
            if previous_group_order:
                final_ordered_group_names = [g for g in previous_group_order if g in current_groups]
                new_groups = [g for g in current_groups if g not in previous_group_order]
                final_ordered_group_names.extend(self._sort_items_naturally(new_groups))
            else:
                # Apply natural sorting to all groups when untangle is disabled and no previous order
                final_ordered_group_names = self._sort_items_naturally(list(current_groups))

        # 3. Clear internal state
        self.port_groups = {}
        self.port_items = {}
        self.clear()

        # 4. Create and add groups in the determined order
        for group_name in final_ordered_group_names:
            group_item = QTreeWidgetItem(self)
            group_item.setText(0, group_name)
            # Set bold font for group items
            font = group_item.font(0) # Get default font
            font.setBold(True)
            group_item.setFont(0, font)
            group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            group_item.setExpanded(True)  # Default to expanded
            self.port_groups[group_name] = group_item

            # Sort ports within each group naturally
            sorted_ports = self._sort_items_naturally(ports_by_group.get(group_name, [])) # Use .get for safety
            for port_name in sorted_ports:
                port_item = QTreeWidgetItem(group_item)
                # Display only the part after the colon, or the full name if no colon
                display_name = port_name.split(':', 1)[-1]
                port_item.setText(0, display_name)
                port_item.setData(0, Qt.ItemDataRole.UserRole, port_name)  # Store full port name
                self.port_items[port_name] = port_item

        # 5. Update the internal group order state
        self.group_order = final_ordered_group_names

    def expandCollapseGroup(self, group_name, expand):
        """
        Expand or collapse a specific group by name.
        
        Args:
            group_name: The name of the group to expand or collapse
            expand: True to expand, False to collapse
        """
        group_item = self.port_groups.get(group_name)
        if group_item:
            group_item.setExpanded(expand)
    
    def expandAllGroups(self):
        """Expand all port groups."""
        for group_item in self.port_groups.values():
            group_item.setExpanded(True)
    
    def collapseAllGroups(self):
        """Collapse all port groups."""
        for group_item in self.port_groups.values():
            group_item.setExpanded(False)
    
    def show_context_menu(self, position):
        """
        Show the context menu for the item at the given position.
        
        Args:
            position: The position to show the menu at
        """
        item = self.itemAt(position)
        if not item:
            return
            
        # Check if it's a port item (leaf node) or group item
        if item.childCount() == 0:  # Port item
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            menu = QMenu(self)
            disconnect_action = QAction("Disconnect all from this port", self)
            disconnect_action.triggered.connect(lambda checked, name=port_name:
                                              self.window().disconnect_node(name))
            menu.addAction(disconnect_action)
            menu.exec(self.mapToGlobal(position))
        else:  # Group item
            group_name = item.text(0)
            is_expanded = item.isExpanded()
            selected_items = self.selectedItems()  # Get all selected items
            
            # Determine if the right-clicked item is part of the current selection
            is_current_item_selected = item in selected_items
            
            # If the right-clicked item wasn't selected, treat it as the only selection for the context menu
            target_items = selected_items if is_current_item_selected and len(selected_items) > 1 else [item]
            
            # Filter to only include group items from the target items
            target_group_items = [i for i in target_items if i.childCount() > 0]
            
            menu = QMenu(self)
            
            # Toggle expand/collapse for this specific group
            toggle_action = QAction("Collapse group" if is_expanded else "Expand group", self)
            toggle_action.triggered.connect(lambda: item.setExpanded(not is_expanded))
            
            # Actions for all groups
            expand_all_action = QAction("Expand all", self)
            collapse_all_action = QAction("Collapse all", self)
            expand_all_action.triggered.connect(self.expandAllGroups)
            collapse_all_action.triggered.connect(self.collapseAllGroups)
            
            # Action to disconnect all ports within the selected group(s)
            disconnect_group_action = QAction(f"Disconnect group{'s' if len(target_group_items) > 1 else ''}", self)
            # Disable if no actual group items are targeted (shouldn't happen with current logic, but safe)
            disconnect_group_action.setEnabled(bool(target_group_items))
            disconnect_group_action.triggered.connect(lambda: self.window().disconnect_selected_groups(target_group_items))
            
            menu.addAction(toggle_action)
            menu.addSeparator()
            menu.addAction(expand_all_action)
            menu.addAction(collapse_all_action)
            menu.addSeparator()
            menu.addAction(disconnect_group_action)
            
            # Add Move Up/Down Actions
            menu.addSeparator()
            # Use the global actions from the main window
            move_up_action = self.window().move_group_up_action
            move_down_action = self.window().move_group_down_action
            
            # Update their enabled state based on the context item
            current_index = self.indexOfTopLevelItem(item)
            move_up_action.setEnabled(current_index > 0)
            move_down_action.setEnabled(current_index < self.topLevelItemCount() - 1)
            
            # Add the global actions to the menu
            menu.addAction(move_up_action)
            menu.addAction(move_down_action)
            
            menu.exec(self.mapToGlobal(position))
    
    def getSelectedPortNames(self):
        """
        Returns a list of port names for the currently selected port items.
        
        Returns:
            list: The selected port names
        """
        selected_ports = []
        for item in self.selectedItems():
            # Only include actual port items (leaves), not groups
            if item and item.childCount() == 0:
                port_name = item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    selected_ports.append(port_name)
        return selected_ports
    
    def getPortItemByName(self, port_name):
        """
        Returns the tree item for a given port name.
        
        Args:
            port_name: The name of the port to find
            
        Returns:
            QTreeWidgetItem: The port item, or None if not found
        """
        return self.port_items.get(port_name)
    
    def dragEnterEvent(self, event):
        """Accept drops only if the source role is the opposite of this tree's role."""
        mime_data = event.mimeData()
        has_role = mime_data.hasFormat("application/x-port-role")
        has_list = mime_data.hasFormat("application/x-port-list")
        has_group = mime_data.hasFormat("application/x-port-group")

        if has_role and (has_list or has_group or mime_data.hasText()): # Check text for single port drag
            source_role_bytes = mime_data.data("application/x-port-role")
            # Determine the expected opposite role
            expected_source_role = b"input" if self.port_role == 'output' else b"output"

            # Accept if the source role is the expected opposite role
            if source_role_bytes == expected_source_role:
                event.acceptProposedAction()
                return

        event.ignore()

    def dragMoveEvent(self, event):
        """Provide visual feedback during drag, accepting if roles are compatible."""
        mime_data = event.mimeData()
        has_role = mime_data.hasFormat("application/x-port-role")
        has_list = mime_data.hasFormat("application/x-port-list")
        has_group = mime_data.hasFormat("application/x-port-group")

        # Check if it's a valid drag type with the correct opposite role
        valid_drag = False
        if has_role and (has_list or has_group or mime_data.hasText()): # Check text for single port drag
            source_role_bytes = mime_data.data("application/x-port-role")
            expected_source_role = b"input" if self.port_role == 'output' else b"output"
            if source_role_bytes == expected_source_role: # Opposite role check
                valid_drag = True

        target_item = self.itemAt(event.position().toPoint())

        if valid_drag and target_item:
            # Valid drag over a potential target item
            if target_item != self.current_drag_highlight_item:
                self.window().clear_drop_target_highlight(self)
                self.window().highlight_drop_target_item(self, target_item)
                self.current_drag_highlight_item = target_item
            event.acceptProposedAction()
        else:
            # Invalid drag type, wrong role, or not over an item
            if self.current_drag_highlight_item:
                self.window().clear_drop_target_highlight(self)
                self.current_drag_highlight_item = None
            event.ignore()

# Escaped marker from original code (part of the replacement content)
    def dragLeaveEvent(self, event):
        """
        Handle drag leave events.
        
        Args:
            event: The drag leave event
        """
        self.window().clear_drop_target_highlight(self)
        self.current_drag_highlight_item = None
        super().dragLeaveEvent(event)
    
    def mousePressEvent(self, event):
        """
        Handle mouse press events.
        
        Args:
            event: The mouse press event
        """
        # Store the current mouse press position regardless of button
        self.mousePressPos = event.pos()
        item_at_pos = self.itemAt(event.pos())
        
        if event.button() == Qt.MouseButton.LeftButton:
            self.initialSelection = item_at_pos  # Remember item for potential drag start
            # Always call the superclass method for left clicks.
            # ExtendedSelection mode will interpret the Ctrl modifier correctly.
            super().mousePressEvent(event)
        else:
            # Handle other mouse buttons (e.g., right-click for context menu)
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """
        Handle mouse move events.
        
        Args:
            event: The mouse move event
        """
        if event.buttons() & Qt.MouseButton.LeftButton and self.initialSelection and self.mousePressPos:
            # Only start drag if we've moved a minimum distance and have a valid selection
            if self.initialSelection and (event.pos() - self.mousePressPos).manhattanLength() >= QApplication.startDragDistance():
                self.startDrag()  # Call the potentially overridden startDrag
        super().mouseMoveEvent(event)
    
    def move_group_up(self, item):
        """
        Moves the specified group item one position up in the tree.
        
        Args:
            item: The group item to move up
        """
        current_index = self.indexOfTopLevelItem(item)
        if current_index > 0:
            # Store expansion state
            is_expanded = item.isExpanded()
            # Take item out and insert it one position higher
            taken_item = self.takeTopLevelItem(current_index)
            self.insertTopLevelItem(current_index - 1, taken_item)
            # Restore expansion state
            taken_item.setExpanded(is_expanded)
            self.setCurrentItem(taken_item)  # Keep the moved item selected
            self.group_order = self.get_current_group_order()  # Update stored order
    
    def move_group_down(self, item):
        """
        Moves the specified group item one position down in the tree.
        
        Args:
            item: The group item to move down
        """
        current_index = self.indexOfTopLevelItem(item)
        if current_index < self.topLevelItemCount() - 1:
            # Store expansion state
            is_expanded = item.isExpanded()
            # Take item out and insert it one position lower
            taken_item = self.takeTopLevelItem(current_index)
            self.insertTopLevelItem(current_index + 1, taken_item)
            # Restore expansion state
            taken_item.setExpanded(is_expanded)
            self.setCurrentItem(taken_item)  # Keep the moved item selected
            self.group_order = self.get_current_group_order()  # Update stored order
    
    def startDrag(self, supportedActions=None):
        """
        Start drag operation, setting the correct port role based on self.port_role.
        
        Args:
            supportedActions: The supported drag actions
        """
        # --- Create Mime Data ---
        selected_items = self.selectedItems()
        if not selected_items or not self.initialSelection:  # Ensure drag was initiated properly
            return
        
        port_items = [item for item in selected_items if item.childCount() == 0]
        group_items = [item for item in selected_items if item.childCount() > 0]
        
        mime_data = QMimeData()
        drag_text = ""
        port_role_bytes = self.port_role.encode('utf-8')  # Use self.port_role
        
        if len(port_items) > 1:
            port_names = [item.data(0, Qt.ItemDataRole.UserRole) for item in port_items if item.data(0, Qt.ItemDataRole.UserRole)]
            if not port_names:
                return
            mime_data.setData("application/x-port-list", b"true")
            mime_data.setData("application/x-port-role", port_role_bytes)
            mime_data.setText('\n'.join(port_names))
            drag_text = f"{len(port_names)} {self.port_role.capitalize()} Ports"
        
        elif len(port_items) == 1 and not group_items:
            item = port_items[0]
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            if not port_name:
                return
            mime_data.setData("application/x-port-role", port_role_bytes)
            mime_data.setText(port_name)
            drag_text = item.text(0)
        
        elif len(group_items) == 1 and not port_items:
            item = group_items[0]
            group_name = item.text(0)
            port_list = self.window()._get_ports_in_group(item)
            if not port_list:
                return
            mime_data.setData("application/x-port-group", b"true")
            mime_data.setData("application/x-port-role", port_role_bytes)
            mime_data.setText('\n'.join(port_list))
            drag_text = group_name
        else:
            # If multiple groups or mix of groups/ports selected, maybe just return?
            print("Drag cancelled: Invalid selection (mix of groups/ports or multiple groups).")
            return  # Invalid selection
        
        # --- Perform Drag ---
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        
        # Create pixmap (same as before)
        font_metrics = QFontMetrics(self.font())
        text_width = font_metrics.horizontalAdvance(drag_text) + 10
        pixmap_width = max(70, text_width)
        pixmap = QPixmap(pixmap_width, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        elided_text = font_metrics.elidedText(drag_text, Qt.TextElideMode.ElideRight, pixmap_width)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, elided_text)
        painter.end()
        
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        
        result = drag.exec(Qt.DropAction.CopyAction)
        self.initialSelection = None  # Clear selection after drag finishes
    
    def dropEvent(self, event):
        """
        Handle drop events.
        
        Args:
            event: The drop event
        """
        mime_data = event.mimeData()
        has_role = mime_data.hasFormat("application/x-port-role")
        has_list = mime_data.hasFormat("application/x-port-list")
        has_group = mime_data.hasFormat("application/x-port-group")
        
        # 1. Check validity (Source role must be opposite of target role)
        expected_source_role = b"input" if self.port_role == 'output' else b"output"
        if not (has_role and (has_list or has_group or mime_data.hasText()) and mime_data.data("application/x-port-role") == expected_source_role):
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return
        
        # 2. Get target item and ports (This tree)
        target_item = self.itemAt(event.position().toPoint())
        if not target_item:
            event.ignore()  # Dropped outside an item
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return
        
        target_ports = self.window()._get_ports_in_group(target_item)  # Handles both port and group items
        if not target_ports:
            event.ignore()  # Target item has no associated ports
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return
        
        # Store target identifier *before* connection/refresh
        target_is_group = target_item.childCount() > 0
        target_identifier = target_item.text(0) if target_is_group else target_item.data(0, Qt.ItemDataRole.UserRole)
        
        # 3. Get source ports (From mime data)
        source_ports = [port for port in mime_data.text().split('\n') if port]
        if not source_ports:
            event.ignore()  # No source ports in mime data
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return
        
        # 4. Perform connection based on target tree role
        if self.port_role == 'output':
            # Target is Output tree, Source is Input
            print(f"Drop Event (Output Tree): Connecting Outputs(Target)={target_ports}, Inputs(Source)={source_ports}")
            self.window().make_multiple_connections(target_ports, source_ports)
        elif self.port_role == 'input':
            # Target is Input tree, Source is Output
            print(f"Drop Event (Input Tree): Connecting Outputs(Source)={source_ports}, Inputs(Target)={target_ports}")
            self.window().make_multiple_connections(source_ports, target_ports)
        else:
            # Should not happen
            print(f"Error: Unknown port_role '{self.port_role}' in dropEvent")
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return
        
        event.acceptProposedAction()
        
        # Find the target item again *after* potential refresh and set selection
        new_target_item = None
        if target_identifier:
            if target_is_group:
                for i in range(self.topLevelItemCount()):
                    item = self.topLevelItem(i)
                    if item and item.text(0) == target_identifier:
                        new_target_item = item
                        break
            else:  # It was a port item
                new_target_item = self.port_items.get(target_identifier)
        if new_target_item:
            self.setCurrentItem(new_target_item)
        # 5. Finalize
        self.window().clear_drop_target_highlight(self)
        self.current_drag_highlight_item = None


class DragPortTreeWidget(PortTreeWidget):
    """
    A PortTreeWidget for output ports (source role: output).
    """
    
    def __init__(self, parent=None):
        """
        Initialize the DragPortTreeWidget.
        
        Args:
            parent: The parent widget
        """
        super().__init__(port_role='output', parent=parent)  # Set role


class DropPortTreeWidget(PortTreeWidget):
    """
    A PortTreeWidget for input ports (source role: input).
    """
    
    def __init__(self, parent=None):
        """
        Initialize the DropPortTreeWidget.
        
        Args:
            parent: The parent widget
        """
        super().__init__(port_role='input', parent=parent)  # Set role
