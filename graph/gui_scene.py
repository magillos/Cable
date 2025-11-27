# gui_scene.py
import jack
import traceback
from collections import defaultdict
import copy

from PyQt6.QtWidgets import QGraphicsScene, QGraphicsPathItem
from PyQt6.QtGui import QColor, QPen, QPainterPath
from PyQt6.QtCore import Qt, QPointF, pyqtSlot, pyqtSignal, QRectF, QLineF, QObject, QTimer, QVariantAnimation, QEasingCurve

from . import constants # Import the new constants module
from .jack_handler import GraphJackHandler # Import the refactored class
from .layout import GraphLayouter  # Import the graph layouter
from cables import jack_utils # Import the new jack_utils module
from .port_item import PortItem
from .node_item import NodeItem
# from cables.connection_manager import JackConnectionManager # For signals and client access - REMOVED to break cycle
from .connection_item import ConnectionItem
from .bulk_area_item import BulkAreaItem
from .config_utils import ConfigManager # Import the config managermanager
from .graph_interaction_handler import GraphInteractionHandler # Import the new handler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager

class JackGraphScene(QGraphicsScene):
    """Manages the nodes, ports, and connections. Delegates interactions to GraphInteractionHandler."""
    scene_connections_changed = pyqtSignal() # Signal for when connections are added/removed
    scene_fully_loaded = pyqtSignal() # Signal emitted when the scene is fully loaded initially
    node_states_changed = pyqtSignal() # Signal emitted when node positions/split/fold states change due to user action
    
    def __init__(self, jack_client: jack.Client, connection_manager: 'JackConnectionManager', connection_history, parent=None):
        super().__init__(parent)
        
        # Debounce timer for full_graph_refresh to batch rapid JACK events (e.g., desktop clients)
        self._refresh_debounce_timer = QTimer(self)
        self._refresh_debounce_timer.setSingleShot(True)
        self._refresh_debounce_timer.timeout.connect(self._deferred_full_refresh)

    def __init__(self, jack_client: jack.Client, connection_manager: 'JackConnectionManager', connection_history, parent=None):
        super().__init__(parent)
        
        # Debounce timer for full_graph_refresh to batch rapid JACK events (e.g., desktop clients)
        self._refresh_debounce_timer = QTimer(self)
        self._refresh_debounce_timer.setSingleShot(True)
        self._refresh_debounce_timer.timeout.connect(self._deferred_full_refresh)
        
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
        self.node_config_manager = ConfigManager()
        self.main_config_manager = self.connection_manager.config_manager
        self.initial_zoom_level = None # Initialize attribute
 
        # Load saved node configurations and zoom level
        self.node_configs, self.initial_zoom_level = self.node_config_manager.load_node_states()
        
        # Extract the untangle setting from the config dict if present
        self.initial_untangle_setting = self.node_configs.pop(self.node_config_manager.CURRENT_UNTANGLE_SETTING_KEY, None)
 
        # Instantiate the interaction handler (pass scene, graph_jack_handler, config manager, and jack_connection_handler)
        self.interaction_handler = GraphInteractionHandler(
            scene=self,
            jack_handler=self.graph_jack_handler,
            config_manager=self.node_config_manager,
            jack_connection_handler=self.jack_connection_handler # Pass the new handler
        )
        
        # Initialize the graph layouter
        self.layouter = GraphLayouter(self)

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
        
        self.connection_manager.graph_updated.connect(self._schedule_full_refresh) # Connect debounced full refresh

        # Selection linking is now handled by PortItem and BulkAreaItem's itemChange methods
        # self.selectionChanged.connect(self.interaction_handler.handle_selection_changed) # Removed
 
    def _schedule_full_refresh(self):
        """Schedule a debounced full graph refresh."""
        self._refresh_debounce_timer.start(100)  # 100ms debounce for rapid JACK events
    
    @pyqtSlot()
    def _deferred_full_refresh(self):
        """Deferred full graph refresh after debounce."""
        self.full_graph_refresh()
    
    @pyqtSlot()
    def full_graph_refresh(self):
        """
        Perform a full refresh of the graph based on current JACK state.
        This includes updating visibility based on NodeVisibilityManager settings.
        Only shows audio and MIDI clients, filtering out video clients and other non-audio/MIDI clients.
        """
        print("Performing full graph refresh...")

        try:
            # Set flag to indicate we're in a full refresh
            self._in_full_refresh = True
            
            # Get only audio and MIDI ports from JACK (filters out video clients, aj-snapshot, etc.)
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

            # Clear the flag before emitting signal
            self._in_full_refresh = False
            
            # Emit signal that connections may have changed
            self.scene_connections_changed.emit()

            # Check if this is the first refresh and emit scene_fully_loaded signal
            is_first_refresh = not hasattr(self, '_first_refresh_done')
            if is_first_refresh:
                self._first_refresh_done = True
                # Clean up orphaned unified sinks after synchronization, but only on first load
                self._cleanup_orphaned_unified_sinks(all_ports)
                self.scene_fully_loaded.emit()
                print("Scene fully loaded signal emitted")

        except Exception as e:
            print(f"Error during full graph refresh: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Always clear the flag, even if there was an error
            self._in_full_refresh = False

    def _synchronize_nodes_with_jack(self, all_ports: list):
        """Adds new nodes from JACK and removes nodes not in JACK. Updates ports on existing nodes."""
        print("Synchronizing nodes with JACK...")
        
        # Create a lookup of client_name -> list of ports
        clients_ports = {}
        for port in all_ports:
            client_name, port_short_name = port.name.split(':', 1)
            if client_name not in clients_ports:
                clients_ports[client_name] = {}
            clients_ports[client_name][port.name] = port

        # Check if we need to split audio/midi clients
        split_audio_midi = self.main_config_manager.get_bool('GRAPH_SPLIT_AUDIO_MIDI_CLIENTS', False)
        
        clients_to_process = {}
        if split_audio_midi:
            for client_name, ports in clients_ports.items():
                has_audio = any(p.is_audio for p in ports.values())
                has_midi = any(p.is_midi for p in ports.values())

                if has_audio and has_midi:
                    # Split into two virtual clients
                    audio_ports = {p_name: p for p_name, p in ports.items() if p.is_audio}
                    midi_ports = {p_name: p for p_name, p in ports.items() if p.is_midi}
                    
                    audio_client_name = f"{client_name} (Audio)"
                    clients_to_process[audio_client_name] = {
                        'ports': audio_ports,
                        'original_client_name': client_name
                    }
                    
                    midi_client_name = f"{client_name} (MIDI)"
                    clients_to_process[midi_client_name] = {
                        'ports': midi_ports,
                        'original_client_name': client_name
                    }
                else:
                    # Not a mixed client, add as is
                    clients_to_process[client_name] = {
                        'ports': ports,
                        'original_client_name': client_name
                    }
        else:
            # Not splitting, just format the dictionary as needed
            for client_name, ports in clients_ports.items():
                clients_to_process[client_name] = {
                    'ports': ports,
                    'original_client_name': client_name
                }

        # Filter clients based on visibility settings
        if hasattr(self, 'node_visibility_manager') and self.node_visibility_manager:
            visible_clients = {}
            for client_name, client_info in clients_to_process.items():
                # Determine if this is a MIDI client based on its ports
                is_midi = False
                ports = client_info['ports']
                if ports:
                    # Check if any port is a MIDI port
                    for port_obj in ports.values():
                        if hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                            is_midi = True
                            break
                
                # Check visibility
                if self.node_visibility_manager.is_node_visible(client_name, is_midi=is_midi):
                    visible_clients[client_name] = client_info
            clients_to_process = visible_clients

        current_client_names = set(clients_to_process.keys())
        
        # Get the list of nodes we currently have
        existing_client_names = set(self.nodes.keys())
        
        # Nodes to remove
        nodes_to_remove = existing_client_names - current_client_names
        for client_name in nodes_to_remove:
            self.remove_node(client_name)

        # Update existing nodes and add new ones
        new_node_y_offset = 0
        for client_name, client_info in sorted(clients_to_process.items()):
            ports_to_process = client_info['ports']
            original_client_name = client_info['original_client_name']

            if client_name in self.nodes:
                # Existing node, update its ports
                self._update_node_ports(client_name, ports_to_process)
            else:
                # New node
                node = self.add_node(client_name, ports_to_process, original_client_name)
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)
                    
                    # Defer push-away check until after node is fully laid out
                    # This handles cases where config has overlapping positions
                    if self.layouter and not node.is_split_origin:
                        QTimer.singleShot(0, lambda n=node: self._apply_push_away_for_node(n))
                    
                    if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                        node.setPos(QPointF(20, 20 + new_node_y_offset))
                        new_node_y_offset += 100
        
        # The rest of the original logic for visibility/splitting is complex and might conflict.
        # For now, focusing on the primary goal of splitting audio/midi.
        # The original visibility logic might need to be adapted to this new structure.
        # For simplicity, I'm omitting the complex visibility logic from the original function for now.

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

    def _apply_push_away_for_node(self, node: 'NodeItem', animate: bool = None):
        """Apply push-away behavior for a newly placed node if it overlaps with others.
        
        Args:
            node: The node that may be overlapping with others
            animate: If True, animate the victim nodes to their new positions.
                    If None, uses the value from constants.PUSH_AWAY_ANIMATION_ENABLED
        """
        if not self.layouter or not node:
            return
        
        # Use constant if animate not explicitly specified
        if animate is None:
            animate = constants.PUSH_AWAY_ANIMATION_ENABLED
            
        current_pos = node.scenePos()
        victims = self.layouter.get_overlapping_nodes(node, current_pos.x(), current_pos.y())
        
        moved_victims = set()
        for victim in victims:
            if victim in moved_victims:
                continue
                
            # Find a new spot for the victim
            v_pos = victim.scenePos()
            new_x, new_y = self.layouter.find_non_overlapping_position(victim, v_pos.x(), v_pos.y())
            
            if new_x != v_pos.x() or new_y != v_pos.y():
                if animate:
                    # Animate the victim to its new position
                    self._animate_node_to_position(victim, new_x, new_y)
                else:
                    # Instant move
                    victim.setPos(new_x, new_y)
                    
                moved_victims.add(victim)
                self._update_config_for_moved_node(victim)
    
    def _animate_node_to_position(self, node: 'NodeItem', target_x: float, target_y: float):
        """Animate a node smoothly to a target position.
        
        Args:
            node: The node to animate
            target_x: Target X coordinate
            target_y: Target Y coordinate
        """
        # Create animation using QVariantAnimation (works with QGraphicsItem)
        animation = QVariantAnimation(self)
        animation.setDuration(constants.PUSH_AWAY_ANIMATION_DURATION)
        animation.setStartValue(node.pos())
        animation.setEndValue(QPointF(target_x, target_y))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)  # Smooth deceleration
        
        # Update node position during animation
        animation.valueChanged.connect(lambda value: node.setPos(value))
        
        # Store animation reference to prevent garbage collection
        if not hasattr(self, '_active_animations'):
            self._active_animations = []
        
        # Clean up finished animations
        self._active_animations = [anim for anim in self._active_animations if anim.state() == QVariantAnimation.State.Running]
        
        # Add new animation
        self._active_animations.append(animation)
        
        # Start the animation
        animation.start()

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


    def add_node(self, client_name, client_ports=None, original_client_name=None):
        """
        Add a node representing a JACK client to the scene.
        
        Args:
            client_name: The name of the JACK client
            client_ports: Optional dictionary of ports to add to the node
            original_client_name: The original JACK client name if this is a virtual node
            
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
            node = NodeItem(client_name, self.graph_jack_handler, self.node_config_manager, ports_to_add=client_ports, original_client_name=original_client_name)
            self.addItem(node)
            
            # IMPORTANT: Layout ports AFTER the node has been added to the scene
            # This prevents "Cannot layout ports: Node is not in a scene" errors.
            node.layout_ports()
            
            # Force geometry update to ensure boundingRect is accurate
            node.prepareGeometryChange()
            node.update()

            # Position the node intelligently if not loading from config
            if client_name not in self.node_configs:
                # Try to find a good position for the new node
                # Start with a simple grid layout as a base
                x = 50.0 + (len(self.nodes) % 5) * 200.0
                y = 50.0 + (len(self.nodes) // 5) * 200.0
                
                # Use the layouter to find a non-overlapping position
                if self.layouter:
                    x, y = self.layouter.find_non_overlapping_position(node, x, y)
                    
                node.setPos(x, y)
                
                # Defer push-away check until after node is fully laid out
                # This is especially important for complex nodes (like Ardour) with many ports
                QTimer.singleShot(0, lambda: self._apply_push_away_for_node(node))
            
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

            # For unified nodes, unload the unified sink before removing the node
            # Handle split unification
            if hasattr(node, 'is_input_unified') and node.is_input_unified:
                print(f"Unloading input unified sink for node {client_name} before removal")
                try:
                    node._unload_unified_sink(is_input=True)
                except Exception as e:
                    print(f"Error unloading input unified sink: {e}")

            if hasattr(node, 'is_output_unified') and node.is_output_unified:
                print(f"Unloading output unified sink for node {client_name} before removal")
                try:
                    node._unload_unified_sink(is_input=False)
                except Exception as e:
                    print(f"Error unloading output unified sink: {e}")

            # Legacy check
            if hasattr(node, 'is_unified') and node.is_unified:
                print(f"Unloading legacy unified sink for node {client_name} before removal")
                try:
                    # Try to determine type or just pass False/True if specific legacy method exists
                    # Since we updated _unload_unified_sink to require is_input, we need to be careful.
                    # If is_unified is True but split flags are False, it might be an old state.
                    # We can try both or check unified_ports_type if it still exists.
                    if hasattr(node, 'unified_ports_type'):
                        if node.unified_ports_type == 'input':
                            node._unload_unified_sink(is_input=True)
                        elif node.unified_ports_type == 'output':
                            node._unload_unified_sink(is_input=False)
                        else:
                             # Fallback or generic
                             pass
                except Exception as e:
                    print(f"Error unloading legacy unified sink: {e}")

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
        
        # Only process audio and MIDI ports, skip video ports and others
        # Check if the port is actually audio or MIDI by querying JACK
        port_obj = self.graph_jack_handler.get_port_by_name(port_name)
        if port_obj:
            if not (port_obj.is_audio or port_obj.is_midi):
                print(f"GraphScene: Skipping non-audio/MIDI port '{port_name}' of type '{type_str}'")
                return
        else:
            # Fallback to type string check if we can't get the port object
            if type_str not in ['32 bit float mono audio', 'MIDI', '8 bit raw midi']:
                print(f"GraphScene: Skipping non-audio/MIDI port '{port_name}' of type '{type_str}'")
                return
            
        node = self.nodes.get(client_name)
        if not node:
            print(f"GraphScene: Node '{client_name}' not found for adding port '{port_name}'. Adding node first.")
            
            # Fetch only audio and MIDI ports for this client (filters out video ports, etc.)
            try:
                client_ports = {}
                # Get audio ports for this client
                audio_ports = jack_utils.get_all_jack_ports(self.jack_client, name_pattern=f"{client_name}:*", is_audio=True)
                # Get MIDI ports for this client  
                midi_ports = jack_utils.get_all_jack_ports(self.jack_client, name_pattern=f"{client_name}:*", is_midi=True)
                
                all_ports = []
                if audio_ports:
                    all_ports.extend(audio_ports)
                if midi_ports:
                    all_ports.extend(midi_ports)
                
                for port in all_ports:
                    client_ports[port.name] = port
                
                node = self.add_node(client_name, client_ports)
                
                # Apply any stored configuration for this new node
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)
                    if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                        # Basic default positioning if no config, similar to full_graph_refresh
                        x = 20.0
                        y = 20.0 + len(self.nodes) * 50.0
                        if self.layouter:
                            x, y = self.layouter.find_non_overlapping_position(node, x, y)
                        node.setPos(QPointF(x, y))
                        # Defer push-away check until after node is fully laid out
                        QTimer.singleShot(0, lambda n=node: self._apply_push_away_for_node(n))
                
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
            # Fetch only audio and MIDI ports for this client (filters out video ports, etc.)
            try:
                client_ports = {}
                # Get audio ports for this client
                audio_ports = jack_utils.get_all_jack_ports(self.jack_client, name_pattern=f"{client_name}:*", is_audio=True)
                # Get MIDI ports for this client
                midi_ports = jack_utils.get_all_jack_ports(self.jack_client, name_pattern=f"{client_name}:*", is_midi=True)
                
                all_ports = []
                if audio_ports:
                    all_ports.extend(audio_ports)
                if midi_ports:
                    all_ports.extend(midi_ports)
                
                # If this client has no audio or MIDI ports, don't add it to the graph
                if not all_ports:
                    print(f"GraphScene: Client '{client_name}' has no audio or MIDI ports, skipping.")
                    return
                
                # Organize ports by name
                for port in all_ports:
                    client_ports[port.name] = port
                
                # Add the node with the fetched ports
                node = self.add_node(client_name, client_ports)
                
                # Apply configuration and default position
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)
                    
                    # Check for overlaps even if we loaded a position from config
                    if self.layouter:
                        current_pos = node.scenePos()
                        new_x, new_y = self.layouter.find_non_overlapping_position(node, current_pos.x(), current_pos.y())
                        if new_x != current_pos.x() or new_y != current_pos.y():
                            node.setPos(new_x, new_y)
                        else:
                            # Apply push-away behavior if the node overlaps with others
                            self._apply_push_away_for_node(node)
                            
                    if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                        # node.setPos(QPointF(20, 20 + len(self.nodes) * 50)) # Simple default - REMOVED, add_node handles this
                        pass

                    # Check if the client should be unified
                    if hasattr(self.connection_manager, 'preset_handler') and self.connection_manager.preset_handler:
                        unified_clients = self.connection_manager.preset_handler.unified_clients
                        if client_name in unified_clients:
                            node.unify_from_preset(unified_clients[client_name])
            except Exception as e:
                print(f"Error fetching ports for new client {client_name}: {e}")
                # Fall back to just adding the node without ports
                node = self.add_node(client_name)
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)
                    
                    # Check for overlaps even if we loaded a position from config
                    if self.layouter:
                        current_pos = node.scenePos()
                        new_x, new_y = self.layouter.find_non_overlapping_position(node, current_pos.x(), current_pos.y())
                        if new_x != current_pos.x() or new_y != current_pos.y():
                            node.setPos(new_x, new_y)
                        else:
                            # Defer push-away check until after node is fully laid out
                            QTimer.singleShot(0, lambda n=node: self._apply_push_away_for_node(n))

                    if not config.get('pos') and not node.is_split_origin and not node.is_split_part:
                        # node.setPos(QPointF(20, 20 + len(self.nodes) * 50))
                        pass
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
           considering split nodes and audio/midi split nodes."""
        
        port_obj = self.graph_jack_handler.get_port_by_name(port_name)
        if not port_obj:
            print(f"find_port_item: Could not get port object for '{port_name}'.")
            return None

        client_name, short_port_name = port_name.split(':', 1)
        
        # Determine the node to search in
        node_to_search = None
        
        # Check for audio/midi split nodes first
        audio_node_name = f"{client_name} (Audio)"
        midi_node_name = f"{client_name} (MIDI)"
        
        if port_obj.is_audio and audio_node_name in self.nodes:
            node_to_search = self.nodes.get(audio_node_name)
        elif port_obj.is_midi and midi_node_name in self.nodes:
            node_to_search = self.nodes.get(midi_node_name)
        else:
            # Fallback to original client name
            node_to_search = self.nodes.get(client_name)

        if not node_to_search:
            print(f"find_port_item: Node for client '{client_name}' not found.")
            return None

        # Now, handle manually split nodes (input/output parts)
        target_node = node_to_search
        if node_to_search.is_split_origin:
            if port_obj.is_input and node_to_search.split_input_node:
                target_node = node_to_search.split_input_node
            elif not port_obj.is_input and node_to_search.split_output_node:
                target_node = node_to_search.split_output_node
            else:
                print(f"find_port_item: Port '{port_name}' not found on expected split part of '{node_to_search.client_name}'.")
                return None
        
        # Search for the port on the determined target node
        port_item = target_node.input_ports.get(port_name) or target_node.output_ports.get(port_name)
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
        if self.interaction_handler._is_double_click:
            self.interaction_handler._is_double_click = False
            return

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
            
            # Check for overlaps and push other nodes away
            if self.layouter:
                aggressor_nodes = set()
                if moved_node and isinstance(moved_node, NodeItem):
                    aggressor_nodes.add(moved_node)
                
                for item in self.selectedItems():
                    if isinstance(item, NodeItem):
                        aggressor_nodes.add(item)
                
                # We need to handle this carefully to avoid infinite loops or weird behavior
                # if multiple nodes are moved.
                # Strategy: For each aggressor, find victims. Move victims.
                # If a victim moves and hits another, that's a secondary collision.
                # For simplicity, we'll just move the immediate victims to a free spot.
                
                moved_victims = set()
                
                for aggressor in aggressor_nodes:
                    current_pos = aggressor.scenePos()
                    victims = self.layouter.get_overlapping_nodes(aggressor, current_pos.x(), current_pos.y())
                    
                    for victim in victims:
                        if victim in aggressor_nodes:
                            continue # Don't push other nodes being dragged
                            
                        if victim in moved_victims:
                            continue # Already moved this one
                            
                        # Find a new spot for the victim
                        # We start searching from the victim's current position
                        v_pos = victim.scenePos()
                        new_x, new_y = self.layouter.find_non_overlapping_position(victim, v_pos.x(), v_pos.y())
                        
                        if new_x != v_pos.x() or new_y != v_pos.y():
                            # Animate the victim to its new position
                            self._animate_node_to_position(victim, new_x, new_y)
                            moved_victims.add(victim)
                            
                # Update config for any victims that were moved
                for victim in moved_victims:
                    self._update_config_for_moved_node(victim)

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

        # Emit that node states changed (manual move complete)
        self.node_states_changed.emit()


    # --- Selection Linking Logic (Moved to Handler) ---
    # handle_selection_changed is now in GraphInteractionHandler

    # --- Other Methods ---
 
    def save_node_states(self, graph_zoom_level=None, current_untangle_setting=None):
        """Save the current node configurations (positions, split states, fold states, zoom level, and untangle setting)
           using the ConfigManager.
        Args:
            graph_zoom_level (float, optional): The current zoom level of the graph view.d
            current_untangle_setting (int, optional): The current untangle layout setting.
        """
        # print(f"JackGraphScene: Saving node states. Zoom: {graph_zoom_level}") # DEBUG
        # Pass the dictionary of original NodeItems, zoom level, and untangle setting to the config manager
        self.node_config_manager.save_node_states(self.nodes, graph_zoom_level=graph_zoom_level, current_untangle_setting=current_untangle_setting)

    def request_specific_node_save(self, node_item: 'NodeItem'):
        """Requests the ConfigManager to save the state of a specific node."""
        if not self.node_config_manager or not node_item:
            return
        
        client_name_key = node_item.original_client_name or node_item.client_name
        nodes_to_save = {client_name_key: node_item}
        
        current_zoom = None
        if hasattr(self, 'view') and self.view and hasattr(self.view, 'get_zoom_level'):
            current_zoom = self.view.get_zoom_level()
            
        # print(f"JackGraphScene: Requesting specific save for node '{client_name_key}'. Zoom: {current_zoom}") # DEBUG
        self.node_config_manager.save_node_states(nodes_to_save, graph_zoom_level=current_zoom)

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
        Delegates to the GraphLayouter class to perform the actual layout.
        
        Args:
            max_nodes_per_row (int): Maximum number of nodes to place in a row before
                                     starting a new row. Default is 6.
        """
        self.layouter.untangle_graph(max_nodes_per_row)

    def untangle_graph_by_io(self):
        """
        Triggers the I/O-based untangle layout.
        """
        self.layouter.untangle_graph_by_io()

    def unsplit_all_nodes(self, save_state=True):
        """
        Unsplits all currently split nodes in the scene.
        
        Args:
            save_state (bool): If True, saves the node states after unsplitting.
        """
        split_origins = []
        
        # Find all split origin nodes
        for client_name, node in self.nodes.items():
            if node.is_split_origin:
                split_origins.append(node)
        
        if not split_origins:
            return  # No split nodes to unsplit
        
        # Unsplit each split origin node
        unsplit_count = 0
        for node in split_origins:
            try:
                node.split_handler.unsplit_node(save_state=False)  # Don't save state for each individual unsplit
                unsplit_count += 1
            except Exception as e:
                print(f"Error unsplitting node {node.client_name}: {e}")
        
        # Save state once at the end if requested
        if save_state and unsplit_count > 0:
            self.save_node_states()
        
        if unsplit_count > 0:
            print(f"Unsplit {unsplit_count} nodes for untangle operation")

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

    def _cleanup_orphaned_unified_sinks(self, all_ports: list):
        """
        Clean up unified virtual sinks that no longer have corresponding JACK clients.
        This handles the edge case where the graph app is closed and reopened, but some
        JACK clients have disappeared while their unified sinks remain active.
        """
        if hasattr(self.connection_manager, 'unified_sink_manager'):
            try:
                return self.connection_manager.unified_sink_manager.cleanup_orphaned_unified_sinks(all_ports)
            except Exception as e:
                print(f"Error during unified sink cleanup: {e}")
                return 0
        else:
            print("UnifiedSinkManager not available for cleanup.")
            print(f"Available attributes on connection_manager: {[attr for attr in dir(self.connection_manager) if not attr.startswith('_')]}")
            return 0

    def get_unified_nodes(self):
        """Returns a list of all unified nodes in the scene."""
        unified_nodes = []
        for node in self.nodes.values():
            if hasattr(node, 'is_unified') and node.is_unified:
                unified_nodes.append(node)
        return unified_nodes

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
                    'pos': node.scenePos(),  # Store the original node position too
                    'manual_split': getattr(node, 'manual_split', True)  # Get actual manual_split flag
                }
                
                # Store positions for input and output parts if they exist
                if node.split_input_node:
                    current_configs[client_name]['split_input_pos'] = node.split_input_node.scenePos()
                    # Store fold state of input part
                    if hasattr(node.split_input_node, 'input_part_folded'):
                        current_configs[client_name]['input_part_folded'] = node.split_input_node.input_part_folded
                
                if node.split_output_node:
                    current_configs[client_name]['split_output_pos'] = node.split_output_node.scenePos()
                    # Store fold state of output part
                    if hasattr(node.split_output_node, 'output_part_folded'):
                        current_configs[client_name]['output_part_folded'] = node.split_output_node.output_part_folded
            else:
                # For non-split nodes, store position and other attributes
                current_configs[client_name] = {
                    'pos': node.scenePos(),
                    'is_split': False
                }
                
                # Store fold state if available
                if hasattr(node, 'is_folded'):
                    current_configs[client_name]['is_folded'] = node.is_folded
                
                # Store split position history if available (for nodes that were split before)
                if hasattr(node, 'split_input_node') and node.split_input_node:
                    current_configs[client_name]['split_input_pos'] = node.split_input_node.scenePos()
                elif hasattr(node, 'config') and node.config and 'split_input_pos' in node.config:
                    current_configs[client_name]['split_input_pos'] = node.config['split_input_pos']
                    
                if hasattr(node, 'split_output_node') and node.split_output_node:
                    current_configs[client_name]['split_output_pos'] = node.split_output_node.scenePos()
                elif hasattr(node, 'config') and node.config and 'split_output_pos' in node.config:
                    current_configs[client_name]['split_output_pos'] = node.config['split_output_pos']
                
                # Store part fold states if available (for nodes that were split before)
                if hasattr(node, 'input_part_folded'):
                    current_configs[client_name]['input_part_folded'] = node.input_part_folded
                if hasattr(node, 'output_part_folded'):
                    current_configs[client_name]['output_part_folded'] = node.output_part_folded
                
                # Store manual split flag if available
                if hasattr(node, 'config') and node.config and 'manual_split' in node.config:
                    current_configs[client_name]['manual_split'] = node.config['manual_split']

                # Store unified state if available
                if hasattr(node, 'is_unified') and node.is_unified:
                    current_configs[client_name]['is_unified'] = True
                    current_configs[client_name]['unified_virtual_sink_name'] = node.unified_virtual_sink_name
                    current_configs[client_name]['unified_module_id'] = node.unified_module_id
        
        return copy.deepcopy(current_configs)
    
    def apply_unified_states(self, unified_clients):
        """
        Applies unified states to nodes from a preset.

        Args:
            unified_clients (dict): A dictionary of unified clients from the preset.
        """
        if not unified_clients:
            return

        for client_name, unify_data in unified_clients.items():
            node = self.get_node_item_by_name(client_name)
            if node and hasattr(node, 'unify_from_preset'):
                node.unify_from_preset(unify_data)

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
                
                # Set the original node position if available
                if 'pos' in config:
                    node.setPos(config['pos'])
                
                # Set manual_split flag if available
                if 'manual_split' in config:
                    if hasattr(node, 'config'):
                        if not node.config:
                            node.config = {}
                        node.config['manual_split'] = config['manual_split']
                
                # Set positions for input and output parts
                if 'split_input_pos' in config and node.split_input_node:
                    node.split_input_node.setPos(config['split_input_pos'])
                
                if 'split_output_pos' in config and node.split_output_node:
                    node.split_output_node.setPos(config['split_output_pos'])
                
                # Set fold states for split parts
                if 'input_part_folded' in config and node.split_input_node:
                    # Set fold state for input part
                    if hasattr(node.split_input_node, 'input_part_folded'):
                        if node.split_input_node.input_part_folded != config['input_part_folded']:
                            node.split_input_node.fold_handler.toggle_input_part_fold(fold_state=config['input_part_folded'])
                
                if 'output_part_folded' in config and node.split_output_node:
                    # Set fold state for output part
                    if hasattr(node.split_output_node, 'output_part_folded'):
                        if node.split_output_node.output_part_folded != config['output_part_folded']:
                            node.split_output_node.fold_handler.toggle_output_part_fold(fold_state=config['output_part_folded'])
            else:
                # If the node is split but shouldn't be, unsplit it
                if node.is_split_origin:
                    node.split_handler.unsplit_node(save_state=False)
                
                # Set position for non-split node
                if 'pos' in config:
                    node.setPos(config['pos'])
                
                # Preserve split position history for potential future splits
                if hasattr(node, 'config'):
                    if not node.config:
                        node.config = {}
                    if 'split_input_pos' in config:
                        node.config['split_input_pos'] = config['split_input_pos']
                    if 'split_output_pos' in config:
                        node.config['split_output_pos'] = config['split_output_pos']
                    if 'manual_split' in config:
                        node.config['manual_split'] = config['manual_split']
                
                # Preserve part fold states for potential future splits
                if 'input_part_folded' in config:
                    node.input_part_folded = config['input_part_folded']
                if 'output_part_folded' in config:
                    node.output_part_folded = config['output_part_folded']
                
                # Set fold state if available - using the correct methods
                if 'is_folded' in config and hasattr(node, 'is_folded'):
                    # Check if current state is different from desired state
                    if node.is_folded != config['is_folded']:
                        # Toggle the state directly or use toggle_main_fold_state
                        node.fold_handler.toggle_main_fold_state()
        
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
