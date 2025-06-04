# gui_scene.py
import jack
import traceback
from collections import defaultdict
import copy

from PyQt6.QtWidgets import QGraphicsScene, QGraphicsPathItem
from PyQt6.QtGui import QColor, QPen, QPainterPath
from PyQt6.QtCore import Qt, QPointF, pyqtSlot, pyqtSignal, QRectF, QLineF, QObject, QTimer

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
    scene_fully_loaded = pyqtSignal() # Signal emitted when the scene is fully loaded initially

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
        """
        Perform a full refresh of the graph based on current JACK state.
        This includes updating visibility based on NodeVisibilityManager settings.
        """
        print("Performing full graph refresh...")

        try:
            # Get all ports from JACK
            all_ports = []
            midi_ports = jack_utils.get_all_jack_ports(self.jack_client, is_midi=True)
            audio_ports = jack_utils.get_all_jack_ports(self.jack_client, is_audio=True)
            
            if midi_ports:
                all_ports.extend(midi_ports)
            if audio_ports:
                all_ports.extend(audio_ports)
            
            # Synchronize nodes and connections
            self._synchronize_nodes_with_jack(all_ports)
            self._synchronize_connections_with_jack(all_ports)
            
            # Refresh connection visibility for all connections
            self._refresh_all_connection_visibility()

            # Emit signal that connections may have changed
            self.scene_connections_changed.emit()
            
            # Emit scene_fully_loaded signal if this is the first refresh
            # We use a static variable to track if this is the first refresh
            if not hasattr(self, '_first_refresh_done'):
                self._first_refresh_done = True
                self.scene_fully_loaded.emit()
                print("Scene fully loaded signal emitted")

        except Exception as e:
            print(f"Error during full graph refresh: {e}")
            import traceback
            traceback.print_exc()

    def _synchronize_nodes_with_jack(self, all_ports: list):
        """Adds new nodes from JACK and removes nodes not in JACK. Updates ports on existing nodes."""
        print("Synchronizing nodes with JACK...")
        
        # Create a lookup of client_name -> list of ports
        clients_ports = {}
        current_client_names = set()
        
        for port in all_ports:
            client_name, port_short_name = port.name.split(':', 1)
            current_client_names.add(client_name)
            
            if client_name not in clients_ports:
                clients_ports[client_name] = {}
            
            clients_ports[client_name][port.name] = port
        
        # Get the list of nodes we currently have
        existing_client_names = set(self.nodes.keys())
        
        if not hasattr(self, 'node_visibility_manager') or not self.node_visibility_manager:
            # If we don't have a node visibility manager, just show everything
            pass
        else:
            # Check each client for visibility and process it accordingly
            clients_to_remove = []
            clients_to_split = []
            
            for client_name in existing_client_names.intersection(current_client_names):
                # Determine if this is a MIDI client
                is_midi = False
                if client_name in clients_ports:
                    # Check if any port is a MIDI port
                    for port_name, port_obj in clients_ports[client_name].items():
                        if hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                            is_midi = True
                            break
                
                # Check input and output visibility
                input_visible = self.node_visibility_manager.is_input_visible(client_name, is_midi=is_midi)
                output_visible = self.node_visibility_manager.is_output_visible(client_name, is_midi=is_midi)
                
                # Determine what to do with this node
                if not input_visible and not output_visible:
                    # If both input and output are hidden, remove the node completely
                    clients_to_remove.append(client_name)
                elif input_visible and output_visible:
                    # Both visible - if the node is split, we should unsplit it
                    node = self.nodes.get(client_name)
                    if node and node.is_split_origin:
                        # Check if this was a manual split (don't unsplit manual splits)
                        is_manual_split = False
                        if hasattr(node, 'config') and node.config:
                            is_manual_split = node.config.get('manual_split', False)
                        
                        # For manually split nodes, make sure both parts are visible
                        if is_manual_split:
                            if node.split_input_node:
                                node.split_input_node.show()
                                # Also show connections to this part
                                self._update_node_connections_visibility(node.split_input_node, True)
                            if node.split_output_node:
                                node.split_output_node.show()
                                # Also show connections to this part
                                self._update_node_connections_visibility(node.split_output_node, True)
                        # Only unsplit if it wasn't a manual split
                        else:
                            # Node should be unsplit as both parts are visible
                            node.split_handler.unsplit_node(save_state=True)
                            
                            # Make sure both parts are visible as well 
                            # (this helps with the case where one part was previously hidden)
                            if node.split_input_node:
                                node.split_input_node.show()
                            if node.split_output_node:
                                node.split_output_node.show()
                                
                            # Also make sure the main node is visible
                            node.show()
                elif (input_visible and not output_visible) or (not input_visible and output_visible):
                    # Only one side is visible - node should be split if it has both inputs and outputs
                    node = self.nodes.get(client_name)
                    
                    # Check if node has both input and output ports
                    has_inputs = False
                    has_outputs = False
                    
                    if client_name in clients_ports:
                        for port_name, port_obj in clients_ports[client_name].items():
                            if hasattr(port_obj, 'is_input'):
                                if port_obj.is_input:
                                    has_inputs = True
                                else:
                                    has_outputs = True
                            
                            if has_inputs and has_outputs:
                                break
                    
                    if has_inputs and has_outputs:
                        # Node has both inputs and outputs, check if it should be split
                        if node and not node.is_split_origin:
                            # Add to list of nodes to split
                            clients_to_split.append(client_name)
                        elif node and node.is_split_origin:
                            # Node is already split, make sure the appropriate parts are shown/hidden
                            # based on current visibility settings
                            
                            # For input part
                            if node.split_input_node:
                                if input_visible:
                                    node.split_input_node.show()
                                    # Also show connections to this part
                                    self._update_node_connections_visibility(node.split_input_node, True)
                                else:
                                    node.split_input_node.hide()
                                    # Also hide connections to this part
                                    self._update_node_connections_visibility(node.split_input_node, False)
                            
                            # For output part
                            if node.split_output_node:
                                if output_visible:
                                    node.split_output_node.show()
                                    # Also show connections to this part
                                    self._update_node_connections_visibility(node.split_output_node, True)
                                else:
                                    node.split_output_node.hide()
                                    # Also hide connections to this part
                                    self._update_node_connections_visibility(node.split_output_node, False)
                            
                            # Do a full refresh of connection visibility to ensure consistency
                            self._refresh_all_connection_visibility()

            # Remove hidden nodes
            for client_name in clients_to_remove:
                self.remove_node(client_name)
                # Also remove it from the set of existing names to avoid processing it further
                existing_client_names.discard(client_name)
            
            # Split nodes as needed
            for client_name in clients_to_split:
                node = self.nodes.get(client_name)
                if node and not node.is_split_origin:
                    # Split the node
                    node.split_handler.split_node(save_state=True)
                    
                    # Now hide the appropriate part based on visibility
                    is_midi = False
                    for port_name, port_obj in clients_ports[client_name].items():
                        if hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                            is_midi = True
                            break
                    
                    input_visible = self.node_visibility_manager.is_input_visible(client_name, is_midi=is_midi)
                    output_visible = self.node_visibility_manager.is_output_visible(client_name, is_midi=is_midi)
                    
                    # For input part
                    if node.split_input_node:
                        if input_visible:
                            node.split_input_node.show()
                            # Also show connections to this part
                            self._update_node_connections_visibility(node.split_input_node, True)
                        else:
                            node.split_input_node.hide()
                            # Also hide connections to this part
                            self._update_node_connections_visibility(node.split_input_node, False)
                    
                    # For output part  
                    if node.split_output_node:
                        if output_visible:
                            node.split_output_node.show()
                            # Also show connections to this part
                            self._update_node_connections_visibility(node.split_output_node, True)
                        else:
                            node.split_output_node.hide()
                            # Also hide connections to this part
                            self._update_node_connections_visibility(node.split_output_node, False)
                        
                    # Do a full refresh of all connection visibility to ensure consistency
                    self._refresh_all_connection_visibility()

        # Update existing nodes and add new ones
        new_node_y_offset = 0
        for client_name in sorted(current_client_names):
            if client_name in existing_client_names:
                self._update_node_ports(client_name, clients_ports[client_name])
            else:
                # Check if the node should be visible according to visibility settings
                if hasattr(self, 'node_visibility_manager') and self.node_visibility_manager:
                    is_midi = False
                    for port_name, port_obj in clients_ports[client_name].items():
                        if hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                            is_midi = True
                            break
                    
                    input_visible = self.node_visibility_manager.is_input_visible(client_name, is_midi=is_midi)
                    output_visible = self.node_visibility_manager.is_output_visible(client_name, is_midi=is_midi)
                    
                    if not input_visible and not output_visible:
                        # Node should not be visible at all
                        continue
                
                # Add the node
                node = self.add_node(client_name, clients_ports[client_name])
                
                # Get the loaded config or create an empty one
                config = self.node_configs.get(client_name, {})
                
                # We pass the config directly. NodeItem will interpret it.
                node.apply_configuration(config) # This is the new method in NodeItem

                # Check if we need to split the node based on visibility settings
                if hasattr(self, 'node_visibility_manager') and self.node_visibility_manager:
                    is_midi = False
                    for port_name, port_obj in clients_ports[client_name].items():
                        if hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                            is_midi = True
                            break
                    
                    input_visible = self.node_visibility_manager.is_input_visible(client_name, is_midi=is_midi)
                    output_visible = self.node_visibility_manager.is_output_visible(client_name, is_midi=is_midi)
                    
                    # Check if node has both input and output ports
                    has_inputs = False
                    has_outputs = False
                    
                    for port_name, port_obj in clients_ports[client_name].items():
                        if hasattr(port_obj, 'is_input'):
                            if port_obj.is_input:
                                has_inputs = True
                            else:
                                has_outputs = True
                        
                        if has_inputs and has_outputs:
                            break
                    
                    if has_inputs and has_outputs and ((input_visible and not output_visible) or (not input_visible and output_visible)):
                        # Node should be split with one part hidden
                        node.split_handler.split_node(save_state=True)
                        
                        # For input part
                        if node.split_input_node:
                            if input_visible:
                                node.split_input_node.show()
                                # Also show connections to this part
                                self._update_node_connections_visibility(node.split_input_node, True)
                            else:
                                node.split_input_node.hide()
                                # Also hide connections to this part
                                self._update_node_connections_visibility(node.split_input_node, False)
                        
                        # For output part
                        if node.split_output_node:
                            if output_visible:
                                node.split_output_node.show()
                                # Also show connections to this part
                                self._update_node_connections_visibility(node.split_output_node, True)
                            else:
                                node.split_output_node.hide()
                                # Also hide connections to this part
                                self._update_node_connections_visibility(node.split_output_node, False)
                        
                        # Do a full refresh of all connection visibility to ensure consistency
                        self._refresh_all_connection_visibility()

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

        # Finally, refresh all connection visibility to ensure consistency
        self._refresh_all_connection_visibility()

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


    def add_node(self, client_name, client_ports=None):
        """
        Add a node representing a JACK client to the scene.
        
        Args:
            client_name: The name of the JACK client
            client_ports: Optional dictionary of ports to add to the node
            
        Returns:
            NodeItem: The created node, or None if creation failed
        """
        # Check if we should show this node based on visibility settings
        if hasattr(self, 'node_visibility_manager') and self.node_visibility_manager:
            # Determine if this is a MIDI client
            is_midi = False
            if client_ports:
                # Check if any port is a MIDI port
                for port_name, port_obj in client_ports.items():
                    if hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                        is_midi = True
                        break
            
            # Check if the node should be visible
            if not self.node_visibility_manager.is_node_visible(client_name, is_midi=is_midi):
                return None
        
        # Proceed with existing code
        if client_name in self.nodes:
            print(f"Node {client_name} already exists")
            return self.nodes[client_name]
        
        try:
            # Pass the required jack_handler and config_manager to the NodeItem constructor
            node = NodeItem(client_name, self.graph_jack_handler, self.config_manager, ports_to_add=client_ports)
            self.addItem(node)
            
            # Position the node intelligently if not loading from config
            if client_name not in self.node_configs:
                # Try to find a good position for the new node
                # This is a simple grid layout, but could be improved
                x = 50 + (len(self.nodes) % 5) * 200
                y = 50 + (len(self.nodes) // 5) * 200
                node.setPos(x, y)
            
            self.nodes[client_name] = node
            return node
        except Exception as e:
            print(f"Error creating node for {client_name}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def remove_node(self, client_name):
        node = self.nodes.pop(client_name, None)
        if node:
            print(f"Removing node: {client_name}")
            
            # Check if this is a split origin node - if so, also remove its split parts
            if node.is_split_origin:
                # Save references to split parts before handling the origin
                input_part = node.split_input_node
                output_part = node.split_output_node
                
                # Clean up the origin node first
                ports_to_clean = list(node.input_ports.values()) + list(node.output_ports.values())
                for port in ports_to_clean:
                    node.remove_port(port.port_name)
                self.removeItem(node)
                
                # Now clean up the split parts if they exist
                if input_part:
                    # Clean up connections from the input part
                    input_ports_to_clean = list(input_part.input_ports.values()) + list(input_part.output_ports.values())
                    for port in input_ports_to_clean:
                        input_part.remove_port(port.port_name)
                    # Remove the input part from the scene
                    if input_part.scene():
                        self.removeItem(input_part)
                
                if output_part:
                    # Clean up connections from the output part
                    output_ports_to_clean = list(output_part.input_ports.values()) + list(output_part.output_ports.values())
                    for port in output_ports_to_clean:
                        output_part.remove_port(port.port_name)
                    # Remove the output part from the scene
                    if output_part.scene():
                        self.removeItem(output_part)
            else:
                # Original behavior for non-split nodes
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
            
            # Fetch all ports for this client to ensure we get a complete picture
            try:
                client_ports = {}
                all_ports = jack_utils.get_all_jack_ports(self.jack_client, name_pattern=f"{client_name}:*")
                
                for port in all_ports:
                    client_ports[port.name] = port
                
                node = self.add_node(client_name, client_ports)
                
                # Apply any stored configuration for this new node
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)
                    if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                        # Basic default positioning if no config, similar to full_graph_refresh
                        node.setPos(QPointF(20, 20 + len(self.nodes) * 50))
                
                return  # Since we've added all ports, no need to add the individual port
            except Exception as e:
                print(f"Error fetching all ports for client {client_name}: {e}")
                # Continue with single port addition as fallback
        
        if node:
            # Fetch the port object from JACK
            port_obj = self.graph_jack_handler.get_port_by_name(port_name)
            if port_obj:
                node.add_port(port_name, port_obj)
            else:
                print(f"GraphScene: Could not fetch jack.Port object for '{port_name}'. Port item might be incomplete.")
                # We could try to create a mock port object here if absolutely necessary
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
            # Fetch all ports for this client
            try:
                client_ports = {}
                # Get all audio and MIDI ports for this client
                all_ports = jack_utils.get_all_jack_ports(self.jack_client, name_pattern=f"{client_name}:*")
                
                # Organize ports by name
                for port in all_ports:
                    client_ports[port.name] = port
                
                # Add the node with the fetched ports
                node = self.add_node(client_name, client_ports)
                
                # Apply configuration and default position
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)
                    if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                        node.setPos(QPointF(20, 20 + len(self.nodes) * 50)) # Simple default
            except Exception as e:
                print(f"Error fetching ports for new client {client_name}: {e}")
                # Fall back to just adding the node without ports
                node = self.add_node(client_name)
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)
                    if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                        node.setPos(QPointF(20, 20 + len(self.nodes) * 50))
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
        
    def untangle_graph(self, max_nodes_per_row=6):
        """
        Automatically organizes the graph nodes to reduce visual clutter.
        This method arranges nodes in a logical flow based on their connections:
        1. Starts with nodes that only have output ports (source nodes)
        2. Places connected nodes in a pattern that reduces connection crossing
        3. Groups disconnected nodes separately
        
        Args:
            max_nodes_per_row (int): Maximum number of nodes to place in a row before
                                     starting a new row. Default is 6.
        """
        if not self.nodes:
            return  # No nodes to untangle
            
        # Identify original nodes and their split parts, exclude origins from direct layout
        layout_nodes = {}
        original_node_parts = defaultdict(lambda: {'input': None, 'output': None})
        for client_name, node in self.nodes.items():
            if node.is_split_origin:
                if node.split_input_node:
                    original_node_parts[node.client_name]['input'] = node.split_input_node
                if node.split_output_node:
                    original_node_parts[node.client_name]['output'] = node.split_output_node
                # Exclude split origins from direct layout, their parts will be handled
                continue
            layout_nodes[client_name] = node

        if not layout_nodes:
            return # No visible nodes to untangle
            
        # Initialize tracking variables
        placed_nodes = set()
        row = 0
        col = 0
        node_count = 0
        
        # Find all nodes with only output ports (sources) or no connections at all
        source_nodes = []
        connected_nodes = set()
        
        # First, identify all nodes that participate in connections
        for connection_key in self.connections:
            out_port, in_port = connection_key
            out_node_candidate_name = out_port.split(':')[0]
            in_node_candidate_name = in_port.split(':')[0]

            # Resolve to original client name if dealing with a split part's port
            out_node_item = self.nodes.get(out_node_candidate_name)
            in_node_item = self.nodes.get(in_node_candidate_name)

            if out_node_item:
                actual_out_client = out_node_item.original_client_name if out_node_item.is_split_part else out_node_item.client_name
                if actual_out_client:
                    connected_nodes.add(actual_out_client)
            
            if in_node_item:
                actual_in_client = in_node_item.original_client_name if in_node_item.is_split_part else in_node_item.client_name
                if actual_in_client:
                    connected_nodes.add(actual_in_client)
        
        # Find nodes with only output ports or ones that are starting points
        for client_name, node in layout_nodes.items(): # Use layout_nodes
            # Consider the original client for connection checks if it's a split part
            effective_client_name = node.original_client_name if node.is_split_part else client_name

            has_inputs = False
            if node.is_split_part:
                # A split input part inherently has inputs. An output part has no inputs.
                if node.client_name.endswith(constants.SPLIT_INPUT_SUFFIX) or (not node.output_ports and node.input_ports): # it's an input part
                    has_inputs = any(port for port in node.input_ports.values() if port.connections)
                # else it's an output part, so has_inputs remains False
            else: # Normal node
                has_inputs = any(port for port in node.input_ports.values() if port.connections)

            has_outputs = False
            if node.is_split_part:
                # A split output part inherently has outputs. An input part has no outputs.
                if node.client_name.endswith(constants.SPLIT_OUTPUT_SUFFIX) or (not node.input_ports and node.output_ports): # it's an output part
                    has_outputs = any(port for port in node.output_ports.values() if port.connections)
                # else it's an input part, so has_outputs remains False
            else: # Normal node
                has_outputs = any(port for port in node.output_ports.values() if port.connections)
            
            if (has_outputs and not has_inputs) or (not has_inputs and not has_outputs and effective_client_name in connected_nodes):
                source_nodes.append(node)
                
        # If no source nodes found, just use any connected node as starting point
        if not source_nodes and connected_nodes:
            for client_name in connected_nodes: # Iterate over original names
                # Find corresponding visible node (could be a part or a full node)
                found_node_for_source = None
                if client_name in layout_nodes: # It's a non-split node
                    found_node_for_source = layout_nodes[client_name]
                elif client_name in original_node_parts: # It's a split node, prefer output part as source
                    if original_node_parts[client_name]['output']:
                        found_node_for_source = original_node_parts[client_name]['output']
                    elif original_node_parts[client_name]['input']:
                         found_node_for_source = original_node_parts[client_name]['input'] # Fallback
                
                if found_node_for_source and found_node_for_source.client_name not in [sn.client_name for sn in source_nodes]:
                    source_nodes.append(found_node_for_source)
                    break
        
        # Define a minimum spacing based on node bounding rectangles
        min_horizontal_spacing = 30  # Minimum gap between nodes horizontally
        min_vertical_spacing = 30    # Minimum gap between nodes vertically
        
        # Function to get node size including margins
        def get_node_size(node):
            rect = node.boundingRect()
            return rect.width(), rect.height()
            
        # Function to check if a position would cause overlap
        def position_causes_overlap(node, x, y, existing_positions):
            node_width, node_height = get_node_size(node)
            # Create a rectangle for this node at the proposed position
            node_rect = (x, y, x + node_width, y + node_height)
            
            # Check against all existing node positions
            for pos_node, pos_rect in existing_positions:
                # Skip checking against itself
                if pos_node == node:
                    continue
                    
                # Check if the rectangles overlap
                if (node_rect[0] < pos_rect[2] and node_rect[2] > pos_rect[0] and
                    node_rect[1] < pos_rect[3] and node_rect[3] > pos_rect[1]):
                    return True
                    
            return False
            
        # Track positions and sizes of placed nodes
        node_positions = []  # List of (node, rect) tuples
        
        # Calculate a reasonable starting point
        start_x = 50
        start_y = 50
        current_row_height = 0
        
        # Place source nodes first
        x = start_x
        y = start_y
        row_nodes = []
        
        for node in source_nodes:
            if node.client_name in placed_nodes:
                continue
            # If node is a split part, try to place its sibling if not already placed and it's a better source
            if node.is_split_part and node.split_origin_node:
                origin = node.split_origin_node
                is_current_node_input_part = (node == origin.split_input_node) or node.client_name.endswith(constants.SPLIT_INPUT_SUFFIX)
                is_current_node_output_part = (node == origin.split_output_node) or node.client_name.endswith(constants.SPLIT_OUTPUT_SUFFIX)

                sibling_part = None
                if is_current_node_input_part and origin.split_output_node:
                    sibling_part = origin.split_output_node
                elif is_current_node_output_part and origin.split_input_node:
                    sibling_part = origin.split_input_node

                # If the current node is an input part, but its output sibling is a better source (has outputs, no inputs)
                # and hasn't been placed, prioritize the output sibling.
                if is_current_node_input_part and sibling_part and sibling_part.client_name not in placed_nodes:
                    # Check if sibling is a "truer" source
                    sib_has_inputs = any(p for p in sibling_part.input_ports.values() if p.connections)
                    sib_has_outputs = any(p for p in sibling_part.output_ports.values() if p.connections)
                    if sib_has_outputs and not sib_has_inputs:
                        # This sibling is a better source, skip current node for now, it will be picked up via connections
                        if sibling_part not in source_nodes: # Add if not already (e.g. if initial scan missed it)
                             source_nodes.insert(0, sibling_part) # Process it soon
                        # continue # This might skip the input part entirely if it has no connections later.
                        # Instead of skipping, we just ensure the output part is prioritized in source_nodes.

            # Get node dimensions
            node_width, node_height = get_node_size(node)
            current_row_height = max(current_row_height, node_height)
            
            # If this would exceed max_nodes_per_row or cause horizontal overflow, move to next row
            if len(row_nodes) >= max_nodes_per_row:
                # Move to next row
                x = start_x
                y += current_row_height + min_vertical_spacing
                row_nodes = []
                current_row_height = node_height
            
            # Check if the node would overlap with any placed node
            attempt_count = 0
            original_x, original_y = x, y
            
            while position_causes_overlap(node, x, y, node_positions) and attempt_count < 10:
                # Try adjusting position slightly
                x += min_horizontal_spacing
                attempt_count += 1
                
                # If we've tried several times horizontally, try moving vertically
                if attempt_count >= 5:
                    x = original_x
                    y += min_vertical_spacing
            
            # Set node position
            node.setPos(x, y)
            placed_nodes.add(node.client_name)
            node_positions.append((node, (x, y, x + node_width, y + node_height)))
            row_nodes.append(node)
            
            # Update position for next node
            x += node_width + min_horizontal_spacing
            
            # Update node configuration for persistence
            if node.client_name in self.node_configs:
                self.node_configs[node.client_name]['pos'] = (x, y)
                
            node_count += 1
        
        # Function to get connected nodes that haven't been placed yet
        def get_next_nodes(current_node_obj): # Takes NodeItem object
            next_nodes_list = []
            current_client_name = current_node_obj.client_name # Name of the part or full node
            
            # Look for nodes that receive input from this node
            for connection_key in self.connections:
                out_port, in_port = connection_key
                out_client_part_name = out_port.split(':')[0]
                in_client_part_name = in_port.split(':')[0]
                
                if out_client_part_name == current_client_name and in_client_part_name not in placed_nodes:
                    # in_client_part_name is the name of the node item in self.nodes (which is layout_nodes + origins)
                    # We need to fetch from layout_nodes as those are the ones we are placing
                    if in_client_part_name in layout_nodes:
                        node_to_add = layout_nodes[in_client_part_name]
                        if node_to_add not in next_nodes_list:
                            next_nodes_list.append(node_to_add)
            
            # If current_node_obj is an input part of a split node, its "next" nodes could also be its output sibling
            if current_node_obj.is_split_part and current_node_obj.split_origin_node:
                origin = current_node_obj.split_origin_node
                is_input_part = (current_node_obj == origin.split_input_node) or current_node_obj.client_name.endswith(constants.SPLIT_INPUT_SUFFIX)
                if is_input_part and origin.split_output_node:
                    output_sibling = origin.split_output_node
                    if output_sibling.client_name not in placed_nodes and output_sibling not in next_nodes_list:
                        # Add sibling to be processed, typically right after the input part.
                        # This helps keep them together if there are no direct connections from input part to external nodes.
                        next_nodes_list.insert(0, output_sibling) # Prioritize sibling
                        
            return next_nodes_list
        
        # Now place connected nodes in sequence
        wave_direction = 1  # Always left to right now
        
        # Process all already placed nodes to find their connections
        processed = set()
        to_process = list(placed_nodes)
        
        # Move to next row for connected nodes
        y += current_row_height + min_vertical_spacing * 2
        x = start_x  # Always start from the left
        row_nodes = []
        current_row_height = 0
        
        while to_process:
            current_client_name_in_placed = to_process.pop(0)
            if current_client_name_in_placed in processed:
                continue
            processed.add(current_client_name_in_placed)

            # current_client_name_in_placed is the name of the NodeItem (part or full)
            current_node_object = layout_nodes.get(current_client_name_in_placed)
            if not current_node_object: # Should not happen if placed_nodes used client_name from layout_nodes
                print(f"Warning: Untangle could not find node object for {current_client_name_in_placed}")
                continue
            
            # Get nodes connected to this one
            next_nodes_to_place = get_next_nodes(current_node_object)
            
            # Try to place sibling part next if it hasn't been placed
            if current_node_object.is_split_part and current_node_object.split_origin_node:
                origin = current_node_object.split_origin_node
                sibling_to_place_next = None
                is_current_input = origin.split_input_node == current_node_object
                
                if is_current_input and origin.split_output_node and origin.split_output_node.client_name not in placed_nodes:
                    sibling_to_place_next = origin.split_output_node
                elif not is_current_input and origin.split_input_node and origin.split_input_node.client_name not in placed_nodes: # current is output
                    sibling_to_place_next = origin.split_input_node
                
                if sibling_to_place_next and sibling_to_place_next not in next_nodes_to_place:
                    is_sibling_pending = any(item == sibling_to_place_next.client_name for item in to_process)
                    if not is_sibling_pending:
                         next_nodes_to_place.insert(0, sibling_to_place_next) # Prioritize sibling

            for node in next_nodes_to_place:
                if node.client_name in placed_nodes:
                    continue
                    
                # Get node dimensions
                node_width, node_height = get_node_size(node)
                current_row_height = max(current_row_height, node_height)
                
                # If this would exceed max_nodes_per_row or cause overflow, move to next row
                if len(row_nodes) >= max_nodes_per_row:
                    # No longer changing direction for snake pattern
                    
                    # Move to next row
                    y += current_row_height + min_vertical_spacing
                    # Reset x to align with the start of the row above
                    x = start_x
                    
                    row_nodes = []
                    current_row_height = node_height # Reset for new row with current node
                
                # Check if the node would overlap with any placed node
                attempt_count = 0
                original_x_attempt, original_y_attempt = x, y # Save before overlap adjustment
                
                temp_x, temp_y = x, y # Use temporary for overlap checks

                while position_causes_overlap(node, temp_x, temp_y, node_positions) and attempt_count < 10:
                    # Try adjusting position slightly - always move right now
                    temp_x += min_horizontal_spacing
                    attempt_count += 1
                    
                    if attempt_count >= 5: # If we've tried several times horizontally
                        temp_x = original_x_attempt # Reset x for this attempt
                        temp_y += min_vertical_spacing # Try moving vertically

                # Update main x, y with the non-overlapping position
                x, y = temp_x, temp_y
                
                # Set node position
                node.setPos(x, y)
                placed_nodes.add(node.client_name)
                if node.client_name not in processed and node.client_name not in to_process:
                    to_process.append(node.client_name)
                node_positions.append((node, (x, y, x + node_width, y + node_height)))
                row_nodes.append(node)
                
                # Update position for next node in the current row - always left to right
                x += node_width + min_horizontal_spacing
                
                # Update node configuration
                if node.client_name in self.node_configs: # Should be original_client_name if part? No, config saves part pos.
                    # Config keys are 'pos' for unsplit, 'split_input_pos', 'split_output_pos' for split parts
                    # The node.client_name is the key for layout_nodes, which are parts or unsplit nodes.
                    # The save_node_states will handle mapping this to the correct config structure.
                    # So direct self.node_configs update might be tricky here if it expects original names.
                    # Let's assume node.client_name is what's expected for the 'pos' of a visible item.
                    # The main self.save_node_states() at the end should reconcile everything.
                     if node.is_split_part and node.split_origin_node:
                         origin_name = node.split_origin_node.client_name
                         if origin_name not in self.node_configs: self.node_configs[origin_name] = {}
                         pos_key = "split_input_pos" if (node == node.split_origin_node.split_input_node or node.client_name.endswith(constants.SPLIT_INPUT_SUFFIX)) else "split_output_pos"
                         self.node_configs[origin_name][pos_key] = (x,y) # Store tuple
                     elif not node.is_split_origin : # Normal non-split node (is_split_origin is already filtered)
                         if node.client_name not in self.node_configs: self.node_configs[node.client_name] = {}
                         self.node_configs[node.client_name]['pos'] = (x,y) # Store tuple

                node_count += 1
        
        # Finally, place any remaining unconnected nodes
        # Move to next row with extra spacing
        y += current_row_height + min_vertical_spacing * 3
        x = start_x
        row_nodes = []
        current_row_height = 0
        
        for client_name, node in layout_nodes.items(): # Use layout_nodes
            if client_name in placed_nodes:
                continue
                
            # Get node dimensions
            node_width, node_height = get_node_size(node)
            current_row_height = max(current_row_height, node_height)
            
            # If this would exceed max_nodes_per_row or cause overflow, move to next row
            if len(row_nodes) >= max_nodes_per_row:
                # Move to next row
                x = start_x
                y += current_row_height + min_vertical_spacing
                row_nodes = []
                current_row_height = node_height
            
            # Check if the node would overlap with any placed node
            attempt_count = 0
            original_x, original_y = x, y
            
            while position_causes_overlap(node, x, y, node_positions) and attempt_count < 10:
                # Try adjusting position slightly
                x += min_horizontal_spacing
                attempt_count += 1
                
                # If we've tried several times horizontally, try moving vertically
                if attempt_count >= 5:
                    x = original_x
                    y += min_vertical_spacing
            
            # Set node position
            node.setPos(x, y)
            node_positions.append((node, (x, y, x + node_width, y + node_height)))
            row_nodes.append(node)
            
            # Update position for next node
            x += node_width + min_horizontal_spacing
            
            # Update node configuration
            if client_name in self.node_configs:
                self.node_configs[client_name]['pos'] = (x, y)
        
        # Update all connection paths
        self.update_all_connection_paths()
        
        # Save the new node positions to config
        self.save_node_states()

    def set_node_visibility_manager(self, node_visibility_manager):
        """Set the NodeVisibilityManager instance for this scene."""
        self.node_visibility_manager = node_visibility_manager
        print("Node visibility manager set for graph scene")

    def _update_node_ports(self, client_name, port_dict):
        """Update ports within an existing node"""
        if client_name not in self.nodes:
            return
            
        node = self.nodes[client_name]
        
        # Get existing port names in the node
        existing_port_names = set()
        existing_port_names.update(node.input_ports.keys())
        existing_port_names.update(node.output_ports.keys())
        
        # Get current port names from JACK
        current_port_names = set(port_dict.keys())
        
        # Remove ports that don't exist anymore
        for port_name in existing_port_names - current_port_names:
            node.remove_port(port_name)
        
        # Add new ports
        for port_name in current_port_names - existing_port_names:
            port_obj = port_dict[port_name]
            node.add_port(port_name, port_obj)

    def _update_node_connections_visibility(self, node: 'NodeItem', visible: bool):
        """
        Update the visibility of all connections for a node.
        
        Args:
            node: The node whose connections should be updated
            visible: Whether the connections should be visible
        """
        if not node:
            return
            
        # For all ports of this node
        for port_list in [node.input_ports, node.output_ports]:
            for port_item in port_list.values():
                # For all connections of this port
                for conn in list(port_item.connections):
                    if conn:
                        conn.setVisible(visible)

    def _refresh_all_connection_visibility(self):
        """
        Ensure all connections have proper visibility based on their connected ports.
        A connection should only be visible if BOTH its source and destination ports 
        are visible.
        """
        for conn_key, conn in list(self.connections.items()):
            if not conn or not conn.source_port or not conn.dest_port:
                continue
                
            # Get the parent node items for both ports
            source_node = conn.source_port.parentItem()
            dest_node = conn.dest_port.parentItem()
            
            # A connection is visible only if both its connected nodes are visible
            should_be_visible = (source_node and dest_node and 
                                source_node.isVisible() and 
                                dest_node.isVisible())
            
            # Update the connection visibility
            conn.setVisible(should_be_visible)

    def get_node_states(self):
        """
        Gets the current node states (positions, split states, fold states) for all nodes.
        Returns a deep copy of the node_configs dictionary.
        
        Returns:
            dict: A dictionary of node configurations
        """
        # Ensure the node_configs dictionary is up to date
        current_configs = {}
        
        # For each node, get its current configuration
        for client_name, node in self.nodes.items():
            if node.is_split_origin:
                # For split nodes, store configuration for all parts
                current_configs[client_name] = {
                    'is_split': True,
                    'manual_split': True  # Assume it's a manual split
                }
                
                # Store positions for input and output parts if they exist
                if node.split_input_node:
                    current_configs[client_name]['split_input_pos'] = node.split_input_node.scenePos()
                
                if node.split_output_node:
                    current_configs[client_name]['split_output_pos'] = node.split_output_node.scenePos()
            else:
                # For non-split nodes, store position and other attributes
                current_configs[client_name] = {
                    'pos': node.scenePos(),
                    'is_split': False
                }
                
                # Store fold state if available
                if hasattr(node, 'is_folded'):
                    current_configs[client_name]['is_folded'] = node.is_folded
                if hasattr(node, 'input_part_folded'):
                    current_configs[client_name]['input_part_folded'] = node.input_part_folded
                if hasattr(node, 'output_part_folded'):
                    current_configs[client_name]['output_part_folded'] = node.output_part_folded
        
        return copy.deepcopy(current_configs)
    
    def restore_node_states(self, node_states):
        """
        Restores node positions and states from the provided configuration.
        
        Args:
            node_states (dict): A dictionary of node configurations
        """
        if not node_states:
            return
            
        # For each node in the configuration
        for client_name, config in node_states.items():
            node = self.get_node_item_by_name(client_name)
            if not node:
                continue
                
            # If the node should be split
            if config.get('is_split', False):
                # If the node is not already split, split it
                if not node.is_split_origin:
                    node.split_handler.split_node(save_state=False)
                
                # Set positions for input and output parts
                if 'split_input_pos' in config and node.split_input_node:
                    node.split_input_node.setPos(config['split_input_pos'])
                
                if 'split_output_pos' in config and node.split_output_node:
                    node.split_output_node.setPos(config['split_output_pos'])
            else:
                # If the node is split but shouldn't be, unsplit it
                if node.is_split_origin:
                    node.split_handler.unsplit_node(save_state=False)
                
                # Set position for non-split node
                if 'pos' in config:
                    node.setPos(config['pos'])
                
                # Set fold state if available - using the correct methods
                if 'is_folded' in config and hasattr(node, 'is_folded'):
                    # Check if current state is different from desired state
                    if node.is_folded != config['is_folded']:
                        # Toggle the state directly or use toggle_main_fold_state
                        node.fold_handler.toggle_main_fold_state()
                
                if 'input_part_folded' in config and hasattr(node, 'input_part_folded'):
                    # Use toggle_input_part_fold with explicit fold state
                    node.fold_handler.toggle_input_part_fold(fold_state=config['input_part_folded'])
                
                if 'output_part_folded' in config and hasattr(node, 'output_part_folded'):
                    # Use toggle_output_part_fold with explicit fold state
                    node.fold_handler.toggle_output_part_fold(fold_state=config['output_part_folded'])
        
        # Update all connection paths to reflect the new node positions
        self.update_all_connection_paths()
        
        # Force a scene update
        self.update()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for graph operations."""
        key = event.key()
        
        # Get selected nodes
        selected_nodes = [item for item in self.selectedItems() if isinstance(item, NodeItem)]
        
        if selected_nodes:
            if key == Qt.Key.Key_H:  # Hide selected nodes
                for node in selected_nodes:
                    node._hide_node()
                event.accept()
                return
            elif key == Qt.Key.Key_S:  # Split selected nodes
                for node in selected_nodes:
                    # Only split if node is not already split and has both inputs and outputs
                    if not node.is_split_origin and not node.is_split_part and node.input_ports and node.output_ports:
                        node.split_handler.split_node(save_state=True)
                event.accept()
                return
            elif key == Qt.Key.Key_U:  # Unsplit selected nodes
                for node in selected_nodes:
                    # For split parts, unsplit their origin node
                    if node.is_split_part and node.split_origin_node:
                        node.split_origin_node.split_handler.unsplit_node(save_state=True)
                    # For split origins, unsplit directly
                    elif node.is_split_origin:
                        node.split_handler.unsplit_node(save_state=True)
                event.accept()
                return
        
        # If we get here, we didn't handle the key
        super().keyPressEvent(event)
