# gui_scene.py
import jack
import traceback
from collections import defaultdict

from PyQt6.QtWidgets import QGraphicsScene, QGraphicsPathItem
from PyQt6.QtGui import QColor, QPen, QPainterPath
from PyQt6.QtCore import Qt, QPointF, pyqtSlot, pyqtSignal

from . import constants # Import the new constants module
from .jack_handler import GraphJackHandler # Import the refactored class
from cables import jack_utils # Import the new jack_utils module
from .port_item import PortItem
from .node_item import NodeItem
# from cables.connection_manager import JackConnectionManager # For signals and client access - REMOVED to break cycle
from .connection_item import ConnectionItem
from .bulk_area_item import BulkAreaItem
from .config_utils import ConfigManager # Import the config manager
from .graph_interaction_handler import GraphInteractionHandler # Import the new handler

class JackGraphScene(QGraphicsScene):
    """Manages the nodes, ports, and connections. Delegates interactions to GraphInteractionHandler."""
    scene_connections_changed = pyqtSignal() # Signal for when connections are added/removed

    def __init__(self, jack_client: jack.Client, connection_manager: 'JackConnectionManager', connection_history, parent=None):
        super().__init__(parent)
        self.jack_client = jack_client # The main jack.Client instance
        self.connection_manager = connection_manager # For JACK event signals
        # connection_history is used by GraphJackHandler for undo/redo
        # parent is assumed to be the graph's MainWindow, used as main_window_ref for GraphJackHandler
        
        # Get the JackConnectionHandler instance from the connection_manager
        self.jack_connection_handler = self.connection_manager.jack_handler

        self.graph_jack_handler = GraphJackHandler(
            jack_client=self.jack_client,
            connection_history_ref=connection_history,
            main_window_ref=parent, # Assuming parent is the graph's MainWindow
            jack_connection_handler_ref=self.jack_connection_handler # Pass the new handler
        )

        self.nodes = {} # client_name: NodeItem (Stores the *original* NodeItem, even if hidden when split)
        self.connections = {} # (out_port_name, in_port_name): ConnectionItem
        self.node_configs = {} # Store loaded node configurations: client_name -> {pos, is_split, split_input_pos, ...}
        # self.setBackgroundBrush(QColor(30, 30, 30)) # Allow theme to control background

        # Initialize config manager for saving/loading node configurations
        self.config_manager = ConfigManager()
        self.initial_zoom_level = None # Initialize attribute
 
        # Load saved node configurations and zoom level
        self.node_configs, self.initial_zoom_level = self.config_manager.load_node_states()
 
        # Instantiate the interaction handler (pass scene, graph_jack_handler, config manager, and jack_connection_handler)
        self.interaction_handler = GraphInteractionHandler(
            scene=self,
            jack_handler=self.graph_jack_handler,
            config_manager=self.config_manager,
            jack_connection_handler=self.jack_connection_handler # Pass the new handler
        )

        # Connect signals from JackConnectionManager
        # Old signals disconnected, new detailed signals connected below
        # self.connection_manager.port_registered.connect(self.handle_port_registered) # OLD
        # self.connection_manager.client_registered.connect(self.handle_client_registered) # OLD
        # self.connection_manager.ports_connected.connect(self.handle_ports_connected) # OLD

        self.connection_manager.port_added.connect(self._handle_port_added)
        self.connection_manager.port_removed.connect(self._handle_port_removed)
        self.connection_manager.client_added.connect(self._handle_client_added)
        self.connection_manager.client_removed.connect(self._handle_client_removed)
        self.connection_manager.connection_made.connect(self._handle_connection_made)
        self.connection_manager.connection_broken.connect(self._handle_connection_broken)
        self.connection_manager.jack_shutdown_signal.connect(self._handle_jack_shutdown)
        
        self.connection_manager.graph_updated.connect(self.full_graph_refresh) # Connect full refresh as fallback

        # Selection linking is now handled by PortItem and BulkAreaItem's itemChange methods
        # self.selectionChanged.connect(self.interaction_handler.handle_selection_changed) # Removed
 
    @pyqtSlot()
    def full_graph_refresh(self):
        """Completely rebuild the graph based on current JACK state by calling helper methods."""
        print("Performing full graph refresh...")
        if not self.jack_client: # Check if the jack.Client instance is available
            self.clear_graph()
            print("Full graph refresh aborted: JACK client not available.")
            return

        try:
            # Use the new utility function to get all ports
            all_ports = jack_utils.get_all_jack_ports(self.jack_client)
            if all_ports is None: # Should not happen if jack_utils returns [] on error
                all_ports = []

            self._synchronize_nodes_with_jack(all_ports)
            self._apply_node_configurations() # This will use the new NodeItem.apply_configuration
            self._synchronize_connections_with_jack(all_ports)

            print("Graph refresh complete.")

        except jack.JackError as e:
            print(f"JACK error during full graph refresh: {e}")
        except Exception as e:
            print(f"Unexpected error during full graph refresh: {e}")
            traceback.print_exc()

    def _synchronize_nodes_with_jack(self, all_ports: list):
        """Adds new nodes from JACK and removes nodes not in JACK. Updates ports on existing nodes."""
        print("Synchronizing nodes with JACK...")
        clients_ports = defaultdict(list)
        for port in all_ports:
            client_name = port.name.split(':')[0]
            clients_ports[client_name].append(port)

        current_client_names = set(clients_ports.keys())
        existing_client_names = set(self.nodes.keys())

        # Remove nodes for clients that no longer exist
        for client_name in existing_client_names - current_client_names:
            self.remove_node(client_name)

        # Add nodes for new clients (initial add, configuration applied separately)
        for client_name in current_client_names - existing_client_names:
            self.add_node(client_name) # Adds the original node item, position/split state handled later

        # Update ports within existing nodes
        for client_name in current_client_names.intersection(existing_client_names):
            if client_name in self.nodes:
                node = self.nodes[client_name]
                node.update_ports() # Update ports on the original node item

    def _apply_node_configurations(self):
        """Applies stored configurations (position, split state) to all current nodes."""
        # print("Applying node configurations...") # Silenced
        new_node_y_offset = 0 # For default positioning of new nodes without config

        for client_name, node in self.nodes.items():
            config = self.node_configs.get(client_name, {})
            
            # Call the new apply_configuration method on NodeItem
            # This method will handle splitting, unsplitting, and positioning
            # based on the config.
            # We pass the config directly. NodeItem will interpret it.
            node.apply_configuration(config) # This is the new method in NodeItem

            # Fallback default positioning for nodes that had no 'pos' in their config
            # and were not split (apply_configuration would handle split pos).
            # This is mainly for brand new nodes not in config yet.
            if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                 # Check if the node is visible (not a hidden original of a split node)
                 if node.isVisible():
                    # Check if it's truly a new node without any position set by apply_configuration
                    # A simple check could be if its pos is still (0,0) or if it's a new client
                    # For simplicity, let's assume apply_configuration handles existing configs.
                    # This part is for nodes that are genuinely new and had no config.
                    # A better check might be if client_name was not in self.node_configs initially.
                    # However, self.node_configs might have an empty dict for it.
                    # Let's rely on apply_configuration to set pos if 'pos' exists.
                    # If 'pos' doesn't exist and it's not split, it needs a default.
                    
                    # A simple way to check if it was newly added and not configured:
                    # If it's at (0,0) and not a split part (split parts are positioned by apply_config)
                    # This might conflict if (0,0) is a valid saved position.
                    # A robust way: if config was empty or lacked 'pos' and 'is_split'.
                    if not config or ('pos' not in config and not config.get('is_split')):
                        node.setPos(QPointF(20, 20 + new_node_y_offset))
                        # print(f"Applied default position to new/unconfigured node {client_name}") # Silenced
                        new_node_y_offset += 100


    def _synchronize_connections_with_jack(self, all_ports: list):
        """Adds new visual connections from JACK and removes those not in JACK."""
        print("Synchronizing connections with JACK...")
        # Clear existing visual connections first
        for conn in list(self.connections.values()):
            conn.destroy()
        self.connections.clear()

        # Rebuild connections by querying JACK
        all_connections_set = set()
        output_ports = [p for p in all_ports if p.is_output]

        if output_ports:
            for out_port in output_ports:
                try:
                    # Use GraphJackHandler for operations like get_all_connections
                    jack_connections = self.graph_jack_handler.get_all_connections(out_port.name)
                    for actual_out, actual_in in jack_connections:
                        all_connections_set.add((actual_out, actual_in))
                except Exception as e:
                    print(f"Error fetching connections for {out_port.name}: {e}")

        # Synchronize visual connections
        for conn_key in all_connections_set: # Add all connections found in JACK
            self.add_connection(*conn_key)
        # Note: Removal of old connections was handled by clearing all connections first.

    def filter_nodes(self, filter_text: str):
        """Filters nodes based on their client names.
        
        Args:
            filter_text: The filter text to match against node names.
                        Supports space-separated terms and exclusion with '-' prefix.
        """
        if not self.nodes:
            return
            
        filter_text_lower = filter_text.lower()
        terms = filter_text_lower.split()
        include_terms = [term for term in terms if not term.startswith('-')]
        exclude_terms = [term[1:] for term in terms if term.startswith('-') and len(term) > 1]

        for node in self.nodes.values():
            # Skip hidden split origin nodes
            if node.is_split_origin and not node.isVisible():
                continue
                
            node_name_lower = node.client_name.lower()
            
            # Check exclusion terms first
            excluded = any(term in node_name_lower for term in exclude_terms)
            if excluded:
                node.setVisible(False)
                # Hide connections for this node
                self._update_connections_visibility(node)
                continue
                
            # Check inclusion terms (all must match)
            included = True
            if include_terms:
                included = all(term in node_name_lower for term in include_terms)
                
            node.setVisible(included)
            self._update_connections_visibility(node)

    def _update_connections_visibility(self, node: 'NodeItem'):
        """Updates visibility of connections for a node based on its visibility."""
        if not node.isVisible():
            # Hide all connections for this node's ports
            for port in list(node.input_ports.values()) + list(node.output_ports.values()):
                for conn in port.connections:
                    conn.setVisible(False)
        else:
            # Show connections only if both nodes are visible
            for port in list(node.input_ports.values()) + list(node.output_ports.values()):
                for conn in port.connections:
                    other_port = conn.source_port if port.is_input else conn.dest_port
                    if other_port and other_port.parentItem().isVisible():
                        conn.setVisible(True)

    def clear_graph(self):
        """Remove all items from the scene."""
        print("Clearing graph visual.")
        # Destroy connections first to avoid issues when nodes/ports are removed
        for conn in list(self.connections.values()):
            conn.destroy()
        self.connections.clear()

        # Remove nodes (which should handle removing their ports)
        for node in list(self.nodes.values()):
            self.remove_node(node.client_name) # Use the method to ensure cleanup
        self.nodes.clear()

        self.clear() # Clears the underlying QGraphicsScene


    def add_node(self, client_name):
        if client_name not in self.nodes:
            print(f"Adding node: {client_name}")
            # Pass the GraphJackHandler instance and config_manager to the NodeItem constructor
            node = NodeItem(client_name, self.graph_jack_handler, self.config_manager)
            self.nodes[client_name] = node
            self.addItem(node)
            # Initial position will be set by auto_layout_nodes
            return node
        return self.nodes[client_name]

    def remove_node(self, client_name):
        node = self.nodes.pop(client_name, None)
        if node:
            print(f"Removing node: {client_name}")
            # Connections should be handled by port removal or graph refresh
            # Ensure ports are visually removed
            ports_to_clean = list(node.input_ports.values()) + list(node.output_ports.values())
            for port in ports_to_clean:
                node.remove_port(port.port_name) # Clean internal refs and visual item
            self.removeItem(node)

    # New handlers for detailed signals from JackConnectionManager

    @pyqtSlot(str, str, int, str, bool)
    def _handle_port_added(self, port_name: str, client_name: str, flags: int, type_str: str, is_input: bool):
        """Handles the port_added signal from JackConnectionManager."""
        print(f"GraphScene: Port added - Name: {port_name}, Client: {client_name}, Input: {is_input}, Type: {type_str}, Flags: {flags}")
        node = self.nodes.get(client_name)
        if not node:
            print(f"GraphScene: Node '{client_name}' not found for adding port '{port_name}'. Adding node first.")
            node = self.add_node(client_name)
            # Apply any stored configuration for this new node
            config = self.node_configs.get(client_name, {})
            node.apply_configuration(config)
            if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                # Basic default positioning if no config, similar to full_graph_refresh
                # This might need refinement to avoid overlaps if many nodes are added quickly
                node.setPos(QPointF(20, 20 + len(self.nodes) * 50))


        if node:
            # We can create a mock/partial jack.Port object if GraphJackHandler or NodeItem needs it,
            # or adapt NodeItem.add_port to accept these parameters directly.
            # For now, let's assume NodeItem.add_port can be adapted or we fetch the full port object.
            # Fetching the full port object is safer to ensure all attributes are correct.
            port_obj = self.graph_jack_handler.get_port_by_name(port_name)
            if port_obj:
                node.add_port(port_name, port_obj)
            else:
                # Fallback: Try to create a port item with available info if full object fetch fails
                # This would require NodeItem.add_port to handle potentially incomplete port objects
                # or direct parameters. For now, we log and rely on full_graph_refresh if this path is taken.
                print(f"GraphScene: Could not fetch full jack.Port object for '{port_name}'. Port item might be incomplete or a refresh might be needed.")
                # As a simple fallback, we could try to add with basic info, but NodeItem expects a jack.Port
                # node.add_port_basic(port_name, is_input, type_str, flags) # Hypothetical
                self.full_graph_refresh() # Safer to refresh if port object is missing
        else:
            print(f"GraphScene: Failed to add/find node '{client_name}' for port '{port_name}'.")


    @pyqtSlot(str, str)
    def _handle_port_removed(self, port_name: str, client_name: str):
        """Handles the port_removed signal from JackConnectionManager."""
        print(f"GraphScene: Port removed - Name: {port_name}, Client: {client_name}")
        node = self.nodes.get(client_name)
        if node:
            node.remove_port(port_name)
        else:
            print(f"GraphScene: Node '{client_name}' not found for removing port '{port_name}'.")

    @pyqtSlot(str)
    def _handle_client_added(self, client_name: str):
        """Handles the client_added signal from JackConnectionManager."""
        print(f"GraphScene: Client added - Name: {client_name}")
        if client_name not in self.nodes:
            node = self.add_node(client_name)
            # Apply configuration and default position
            config = self.node_configs.get(client_name, {})
            node.apply_configuration(config)
            if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                 node.setPos(QPointF(20, 20 + len(self.nodes) * 50)) # Simple default
            # Ports for this client will be added via subsequent _handle_port_added signals
            # or a full_graph_refresh if events are batched.
        else:
            print(f"GraphScene: Client '{client_name}' already exists.")


    @pyqtSlot(str)
    def _handle_client_removed(self, client_name: str):
        """Handles the client_removed signal from JackConnectionManager."""
        print(f"GraphScene: Client removed - Name: {client_name}")
        self.remove_node(client_name)

    @pyqtSlot(str, str)
    def _handle_connection_made(self, out_port_name: str, in_port_name: str):
        """Handles the connection_made signal from JackConnectionManager."""
        print(f"GraphScene: Connection made - From: {out_port_name}, To: {in_port_name}")
        self.add_connection(out_port_name, in_port_name)

    @pyqtSlot(str, str)
    def _handle_connection_broken(self, out_port_name: str, in_port_name: str):
        """Handles the connection_broken signal from JackConnectionManager."""
        print(f"GraphScene: Connection broken - From: {out_port_name}, To: {in_port_name}")
        self.remove_connection(out_port_name, in_port_name)

    @pyqtSlot()
    def _handle_jack_shutdown(self):
        """Handles the jack_shutdown_signal from JackConnectionManager."""
        print("GraphScene: JACK server shutdown detected. Clearing graph.")
        self.clear_graph()
        # Optionally, display a message to the user in the graph view
        # e.g., by adding a QGraphicsTextItem indicating JACK shutdown.

    # Old handlers (to be removed or verified if still needed by other parts, though unlikely for these specific ones)
    # @pyqtSlot(str, bool)
    # def handle_client_registered(self, client_name: str, is_registered: bool): ...
    # @pyqtSlot(str, bool)
    # def handle_port_registered(self, port_name: str, is_registered: bool): ...
    # @pyqtSlot(str, str, bool)
    # def handle_ports_connected(self, out_port_name: str, in_port_name: str, is_connected: bool): ...

    def find_port_item(self, port_name: str) -> PortItem | None:
        """Find the VISIBLE PortItem QGraphicsItem corresponding to a full port name,
           considering split nodes."""
        client_name, short_port_name = port_name.split(':', 1)
        original_node = self.nodes.get(client_name)
        if not original_node:
            print(f"find_port_item: Original node '{client_name}' not found.")
            return None

        # Determine which node item (original, input part, or output part) is currently visible/relevant
        target_node = original_node
        if original_node.is_split_origin:
            # If original is split, find port on the corresponding part
            port_obj = original_node.jack_handler.get_port_by_name(port_name) # Check if input/output
            if port_obj:
                if port_obj.is_input and original_node.split_input_node:
                    target_node = original_node.split_input_node
                elif not port_obj.is_input and original_node.split_output_node:
                    target_node = original_node.split_output_node
                else:
                    # This case shouldn't happen if split correctly
                    print(f"find_port_item: Port '{port_name}' not found on expected split part of '{client_name}'.")
                    return None
            else:
                 print(f"find_port_item: Could not get port object for '{port_name}' to determine split part.")
                 return None # Cannot determine which split part owns the port
        elif original_node.is_split_part:
            # This function should ideally be called with the *original* client name.
            # If called with a split part name, we might have issues.
            # Let's assume it's called correctly with the original name.
            print(f"Warning: find_port_item called for a node that is already a split part ('{client_name}'). This might indicate an issue.")
            # Attempt to find the port on the part itself
            target_node = original_node # Treat it as the node to search on

        # Now search for the port on the determined target node
        port_item = target_node.input_ports.get(port_name) or target_node.output_ports.get(port_name)
        # print(f"find_port_item: Searching on '{target_node.client_name}', found: {port_item}") # Debug
        return port_item

    def add_connection(self, out_port_name: str, in_port_name: str):
        conn_key = (out_port_name, in_port_name)
        if conn_key in self.connections:
            return # Already exists visually

        source_port_item = self.find_port_item(out_port_name)
        dest_port_item = self.find_port_item(in_port_name)

        if source_port_item and dest_port_item:
            # print(f"Adding visual connection: {out_port_name} -> {in_port_name}") # Commented out for less verbose logging
            conn = ConnectionItem(source_port_item, dest_port_item)
            self.addItem(conn)
            self.connections[conn_key] = conn
            self.scene_connections_changed.emit() # Emit signal
        else:
            print(f"Warning: Could not find port items for connection: {out_port_name} -> {in_port_name}")


    def remove_connection(self, out_port_name: str, in_port_name: str):
        conn_key = (out_port_name, in_port_name)
        conn = self.connections.pop(conn_key, None)
        if conn:
             print(f"Removing visual connection: {out_port_name} -> {in_port_name}")
             conn.destroy() # Removes from scene and port lists
             self.scene_connections_changed.emit() # Emit signal


    # --- Mouse Events (Delegated to Handler) ---

    def mousePressEvent(self, event):
        """Delegate press event to the interaction handler."""
        # Let handler process first (e.g., store potential drag item)
        self.interaction_handler.mousePressEvent(event)

        # Always call super() AFTER handler.
        # super() handles selection state changes based on modifiers and button clicks,
        # and initiates the move operation for movable items if appropriate.
        super().mousePressEvent(event)
        # print(f"Scene mousePress: Called super().") # Optional debug


    def mouseMoveEvent(self, event):
        """Delegate move event to the interaction handler."""
        # Let handler process first (e.g., initiate drag, update line)
        consumed = self.interaction_handler.mouseMoveEvent(event)

        # If the handler consumed the event (e.g., started/updated a drag), don't call super.
        if consumed:
            event.accept()
            # print("Scene mouseMove: Handler consumed event.") # Optional debug
            return

        # If handler didn't consume, call super() for default behavior (moving items, rubber band).
        # print("Scene mouseMove: Passing event to super.") # Optional debug
        super().mouseMoveEvent(event)


    def mouseReleaseEvent(self, event):
        """Delegate release event to the interaction handler."""
        # Let handler process first (e.g., end drag, handle node drop)
        moved_node, consumed = self.interaction_handler.mouseReleaseEvent(event)

        # If the handler consumed the event (e.g., finished a custom drag), accept it.
        if consumed:
            event.accept()
            # print("Scene mouseRelease: Handler consumed event.") # Silenced
            # We still might need to update node positions if a drag finished,
            # but the handler doesn't know about selection state after super() is called below.
            # Let the 'else' block handle position saving.

        # If handler didn't consume, pass to super for default release behavior
        # (finalizing moves, selection changes).
        else:
            # print("Scene mouseRelease: Passing event to super.") # Silenced
            super().mouseReleaseEvent(event)

        # --- Update Node Config on Move ---
        # Update the scene's node_configs dictionary immediately when a node
        # (or a split part) finishes moving. This ensures the latest position
        # is available for re-splitting and is saved on exit.


        # Check the node that was potentially moved by the interaction handler or super()
        # Note: moved_node comes from the handler's return value
        node_that_moved = moved_node

        # Update config for the node that was directly moved/dragged
        if node_that_moved and isinstance(node_that_moved, NodeItem):
            self._update_config_for_moved_node(node_that_moved)

        # Also update config for any *other* selected nodes that might have moved together
        for item in self.selectedItems():
             if isinstance(item, NodeItem) and item != node_that_moved: # Avoid double update
                 self._update_config_for_moved_node(item)


    # --- Selection Linking Logic (Moved to Handler) ---
    # handle_selection_changed is now in GraphInteractionHandler

    # --- Other Methods ---
 
    def save_node_states(self, graph_zoom_level=None):
        """Save the current node configurations (positions, split states, fold states, and zoom level)
           using the ConfigManager.
        Args:
            graph_zoom_level (float, optional): The current zoom level of the graph view.
        """
        # print(f"JackGraphScene: Saving node states. Zoom: {graph_zoom_level}") # DEBUG
        # Pass the dictionary of original NodeItems and zoom level to the config manager
        self.config_manager.save_node_states(self.nodes, graph_zoom_level=graph_zoom_level)

    def request_specific_node_save(self, node_item: 'NodeItem'):
        """Requests the ConfigManager to save the state of a specific node."""
        if not self.config_manager or not node_item:
            return
        
        client_name_key = node_item.original_client_name or node_item.client_name
        nodes_to_save = {client_name_key: node_item}
        
        current_zoom = None
        if hasattr(self, 'view') and self.view and hasattr(self.view, 'get_zoom_level'):
            current_zoom = self.view.get_zoom_level()
            
        # print(f"JackGraphScene: Requesting specific save for node '{client_name_key}'. Zoom: {current_zoom}") # DEBUG
        self.config_manager.save_node_states(nodes_to_save, graph_zoom_level=current_zoom)
 
    def _update_config_for_moved_node(self, node_item: 'NodeItem'):
        """Helper to update the scene's node_configs dict after a node moves.
        Ensures configuration is saved under the original client name for split parts."""
        if not isinstance(node_item, NodeItem):
            return

        new_pos = node_item.scenePos() # Get the final position after the move
        original_client_name = None
        config_key_to_update = None

        if node_item.is_split_part:
            # This item is a split part (e.g., "client_name (Inputs)" or "client_name (Outputs)")
            if node_item.split_origin_node:
                original_client_name = node_item.split_origin_node.client_name
                # Determine if it's the input or output part.
                # A more robust way might be to check its actual name or a property.
                # For now, using port presence:
                has_inputs_only = bool(node_item.input_ports) and not bool(node_item.output_ports)
                has_outputs_only = bool(node_item.output_ports) and not bool(node_item.input_ports)

                if node_item.client_name.endswith(constants.SPLIT_INPUT_SUFFIX):
                    config_key_to_update = "split_input_pos"
                elif node_item.client_name.endswith(constants.SPLIT_OUTPUT_SUFFIX):
                    config_key_to_update = "split_output_pos"
                elif has_inputs_only: # Fallback if suffix naming isn't strictly followed by client_name
                    config_key_to_update = "split_input_pos"
                    print(f"Warning: Split part '{node_item.client_name}' identified as input by ports, not suffix.")
                elif has_outputs_only: # Fallback
                    config_key_to_update = "split_output_pos"
                    print(f"Warning: Split part '{node_item.client_name}' identified as output by ports, not suffix.")
                else:
                    print(f"Warning: Moved split part '{node_item.client_name}' for original '{original_client_name}'"
                          f" could not be identified as input or output part for config saving.")
                    return # Don't save if we can't determine the key
            else:
                print(f"Warning: Moved split part '{node_item.client_name}' has no reference to its origin. Cannot save position.")
                return # Don't save if no origin

        elif not node_item.is_split_origin and not node_item.is_split_part:
            # This is an original, non-split, visible node.
            original_client_name = node_item.client_name
            config_key_to_update = "pos"
        # else: It's a hidden split origin node (node_item.is_split_origin is True).
        # Its position is not saved directly; its split parts' positions are.
        # Or it's an unhandled case.

        # Update the dictionary if we identified what to update
        if original_client_name and config_key_to_update:
            if original_client_name not in self.node_configs:
                self.node_configs[original_client_name] = {} # Ensure entry exists for the original client

            # Store the new position
            self.node_configs[original_client_name][config_key_to_update] = new_pos
            # print(f"Updated config for '{original_client_name}': {config_key_to_update} = {new_pos}") # Silenced
        # else:
            # print(f"Debug: No config update for {node_item.client_name} (is_split_part={node_item.is_split_part}, is_split_origin={node_item.is_split_origin})")

    def get_node_item_by_name(self, node_name: str) -> 'NodeItem | None':
        """
        Retrieves a NodeItem from the scene by its original client name.
        This primarily searches the self.nodes dictionary which stores original NodeItems.
        """
        return self.nodes.get(node_name)

    def update_all_connection_paths(self):
        """
        Iterates through all ConnectionItem instances in the scene
        and calls their update_path() method to refresh their visual representation.
        Useful after nodes have been moved, for example, when loading a preset.
        """
        # print("Updating all connection paths...") # Silenced
        for connection_item in self.connections.values():
            connection_item.update_path()
        self.update() # Request a general scene update
