# gui_scene.py
"""
QGraphicsScene managing visual graph nodes, ports, and connections.

JACK synchronization logic (querying, filtering, diffing) is handled by
GraphStateManager, which emits signals that this scene responds to for
adding/removing visual elements.
"""
import jack
import traceback
import copy

import logging
logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent
from PyQt6.QtCore import Qt, QPointF, pyqtSlot, pyqtSignal, QObject, QTimer, QEasingCurve

from . import constants
from .animations import NodeAnimator, GraphAnimationController
from .jack_handler import GraphJackHandler
from .layout import GraphLayouter  # Import the graph layouter
from cables.jack_service import get_jack_service
from .port_item import PortItem
from .node_item import NodeItem
from .connection_item import ConnectionItem
from .bulk_area_item import BulkAreaItem
from .config_utils import GraphConfigManager
from .graph_interaction_handler import GraphInteractionHandler # Import the new handler
from .scene_connection_manager import SceneConnectionManager
from .graph_state_manager import GraphStateManager
from typing import TYPE_CHECKING, List, Dict, Optional, Any, Set, Tuple, Union
if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager
    from cables.features.connection_history import ConnectionHistory
    from .node_item import NodeItem
    from cables.features.node_visibility_manager import NodeVisibilityManager

class JackGraphScene(QGraphicsScene):
    """Manages the nodes, ports, and connections. Delegates interactions to GraphInteractionHandler."""
    scene_connections_changed = pyqtSignal() # Signal for when connections are added/removed
    scene_fully_loaded = pyqtSignal() # Signal emitted when the scene is fully loaded initially
    node_states_changed = pyqtSignal() # Signal emitted when node positions/split/fold states change due to user action
    
    def __init__(self, jack_client: jack.Client, connection_manager: 'JackConnectionManager', connection_history: 'ConnectionHistory', parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        
        self.jack_client = jack_client
        self.connection_manager = connection_manager
        
        # Get the JackConnectionHandler instance from the connection_manager
        self.jack_connection_handler = self.connection_manager.jack_handler

        self.graph_jack_handler = GraphJackHandler(
            jack_client=self.jack_client,
            connection_history_ref=connection_history,
            main_window_ref=parent,
            jack_connection_handler_ref=self.jack_connection_handler
        )

        self.nodes: Dict[str, 'NodeItem'] = {}
        self.connections: Dict[tuple, 'ConnectionItem'] = {}
        self.node_configs: Dict[str, dict] = {}
        self._first_refresh_done = False
        self._in_full_refresh = False

        # Initialize config manager for saving/loading node configurations
        self.node_config_manager = GraphConfigManager()
        self.main_config_manager = self.connection_manager.config_manager
        self.initial_zoom_level = None
 
        # Load saved node configurations and zoom level
        self.node_configs, self.initial_zoom_level = self.node_config_manager.load_node_states()
        
        # Extract the untangle setting from the config dict if present
        self.initial_untangle_setting = self.node_configs.pop(self.node_config_manager.CURRENT_UNTANGLE_SETTING_KEY, None)
 
        # Instantiate the interaction handler
        self.interaction_handler = GraphInteractionHandler(
            scene=self,
            jack_handler=self.graph_jack_handler,
            config_manager=self.node_config_manager,
            jack_connection_handler=self.jack_connection_handler
        )
        
        # Initialize the scene connection manager
        self.connection_mgr = SceneConnectionManager(self)

        # Initialize the graph layouter
        self.layouter = GraphLayouter(self)

        # Centralized animation helper (push-away + layout transitions)
        self.node_animator = NodeAnimator(self)
        self.animations = GraphAnimationController(self, self.node_animator)

        # Pending node positions (e.g. virtual sinks created from the view context menu)
        self._pending_node_positions: dict[str, QPointF] = {}

        # Initialize the state manager (handles all JACK synchronization)
        self.state_manager = GraphStateManager(
            jack_client=self.jack_client,
            connection_manager=self.connection_manager,
            main_config_manager=self.main_config_manager,
            parent=self,
        )
        self.state_manager.full_sync_ready.connect(self._on_full_sync_ready)
        self.state_manager.jack_shutdown_detected.connect(self._on_jack_shutdown)

        # Connection signals go directly to SceneConnectionManager (visual-only, no processing needed)
        jack_service = get_jack_service()
        jack_service.connection_made.connect(self.connection_mgr.handle_connection_made)
        jack_service.connection_broken.connect(self.connection_mgr.handle_connection_broken)
 
    def register_pending_node_position(self, sink_name: str, scene_pos: QPointF) -> None:
        """Register a pending position for a node expected to appear soon.

        This is used to place newly-created virtual sinks/sources at the user's click position.
        """
        if not sink_name:
            return
        self._pending_node_positions[sink_name] = scene_pos

    def unregister_pending_node_position(self, sink_name: str) -> None:
        """Remove a pending position (e.g. if creation failed)."""
        if not sink_name:
            return
        self._pending_node_positions.pop(sink_name, None)

    def _pop_pending_position_for_client(self, client_name: str) -> QPointF | None:
        """Return and remove a pending position matching this JACK client name."""
        if not client_name or not self._pending_node_positions:
            return None

        # For virtual sinks created via pactl, the JACK/pipewire client name is typically
        # "<sink_name> Audio/Sink sink" or similar patterns. We match on prefix "<sink_name> ".
        # Also handle module-id suffixes like "<sink_name>-1" or "<sink_name>.1"
        logger.debug(f"Looking for pending position for client: {client_name}, pending: {list(self._pending_node_positions.keys())}")
        for sink_name, pos in list(self._pending_node_positions.items()):
            # Exact match
            if client_name == sink_name:
                logger.info(f"Found pending position for exact match: {sink_name} -> {pos}")
                self._pending_node_positions.pop(sink_name, None)
                return pos
            # Prefix match with space (e.g., "my_sink " matches "my_sink Audio/Sink")
            if client_name.startswith(sink_name + ' '):
                logger.info(f"Found pending position for prefix match with space: {sink_name} -> {pos}")
                self._pending_node_positions.pop(sink_name, None)
                return pos
            # Prefix match with module ID suffix (e.g., "my_sink-1" matches "my_sink-1")
            if client_name.startswith(sink_name):
                rest = client_name[len(sink_name):]
                if rest and (rest[0] == '-' or rest[0] == '.') and len(rest) > 1 and rest[1:].isdigit():
                    logger.info(f"Found pending position for module ID suffix match: {sink_name} -> {pos}")
                    self._pending_node_positions.pop(sink_name, None)
                    return pos
                # Also handle just "-" or "." followed by digit(s)
                if rest and (rest == '-' or rest == '.'):
                    # This is just the sink name with no suffix, might be a false positive
                    pass

        logger.debug(f"No pending position found for client: {client_name}")
        return None

    def _apply_pending_position_if_any(self, node: 'NodeItem') -> bool:
        """If a pending position exists for this node, apply it and return True."""
        if not node:
            return False

        pending_pos = self._pop_pending_position_for_client(node.client_name)
        if pending_pos is None:
            return False

        logger.info(f"Applying pending position {pending_pos} to node {node.client_name}")

        # Place node centered at the click position (after layout so size is accurate)
        br = node.boundingRect()
        x = pending_pos.x() - br.width() / 2.0
        y = pending_pos.y() - br.height() / 2.0

        if self.layouter:
            x, y = self.layouter.find_non_overlapping_position(node, x, y)

        node.setPos(QPointF(x, y))

        # Push away any nodes still overlapping (deferred so geometry is settled)
        QTimer.singleShot(0, lambda n=node: self._apply_push_away_for_node(n))
        return True
    
    @pyqtSlot()
    def full_graph_refresh(self) -> None:
        """Perform an immediate full refresh of the graph based on current JACK state.

        Delegates to :class:`GraphStateManager` which queries JACK, filters
        clients, and emits ``full_sync_ready`` — handled by
        :meth:`_on_full_sync_ready` to apply visual changes.
        """
        self.state_manager.perform_sync()

    @pyqtSlot(object, object, object)
    def _on_full_sync_ready(self, clients_to_process: dict, present_client_names: set, all_ports: list) -> None:
        """Apply sync data computed by GraphStateManager to the visual scene."""
        logger.info("Applying full graph sync...")
        try:
            self._in_full_refresh = True

            self._apply_node_sync(clients_to_process, present_client_names)
            self.connection_mgr.synchronize_connections_with_jack(all_ports)
            self.connection_mgr.refresh_all_connection_visibility()
            self._cleanup_orphaned_unified_sinks(all_ports)

            self._in_full_refresh = False
            self.scene_connections_changed.emit()

            if not self._first_refresh_done:
                self._first_refresh_done = True
                self.scene_fully_loaded.emit()
                logger.info("Scene fully loaded signal emitted")

        except Exception as e:
            logger.error(f"Error during full graph sync: {e}")
            traceback.print_exc()
        finally:
            self._in_full_refresh = False

    def _apply_node_sync(self, clients_to_process: dict, present_client_names: set) -> None:
        """Add/remove/update scene nodes to match the desired state from GraphStateManager."""
        current_client_names = set(clients_to_process.keys())
        existing_client_names = set(self.nodes.keys())

        # Remove nodes no longer present
        for client_name in existing_client_names - current_client_names:
            unload_unified_sinks = client_name not in present_client_names
            self.remove_node(client_name, unload_unified_sinks=unload_unified_sinks)

        # Update existing nodes and add new ones
        new_node_y_offset = 0
        for client_name, client_info in sorted(clients_to_process.items()):
            ports_to_process = client_info['ports']
            original_client_name = client_info['original_client_name']

            if client_name in self.nodes:
                self._update_node_ports(client_name, ports_to_process)

                if hasattr(self.nodes[client_name], 'check_if_virtual_sink'):
                    self.nodes[client_name].check_if_virtual_sink(client_name)
                    self.nodes[client_name].update()

                if hasattr(self.nodes[client_name], 'ensure_unified_sink_exists'):
                    self.nodes[client_name].ensure_unified_sink_exists()
            else:
                node = self.add_node(client_name, ports_to_process, original_client_name)
                if node:
                    config = self.node_configs.get(client_name, {})
                    node.apply_configuration(config)

                    # Try to apply pending position from context menu click
                    pending_applied = self._apply_pending_position_if_any(node)

                    if self.layouter and not node.is_split_origin:
                        QTimer.singleShot(0, lambda n=node: self._apply_push_away_for_node(n))

                    # Only apply default grid position if:
                    # 1. No saved config position exists
                    # 2. No pending position was applied (new virtual sink at click location)
                    if not config.get('pos') and not pending_applied and not node.is_split_origin and not node.is_split_part:
                        node.setPos(QPointF(20, 20 + new_node_y_offset))
                        new_node_y_offset += 100

                    # Apply preset unification for newly created nodes
                    if hasattr(self.connection_manager, 'preset_handler') and self.connection_manager.preset_handler:
                        unified_clients = self.connection_manager.preset_handler.unified_clients
                        if client_name in unified_clients:
                            node.unify_from_preset(unified_clients[client_name])

        self._apply_split_part_visibility()

    def _apply_node_configurations(self) -> None:
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


    def filter_nodes(self, filter_text: str) -> None:
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
                self.connection_mgr.update_connections_visibility(node)
                continue
                
            # Check inclusion terms (all must match)
            included = True
            if include_terms:
                included = all(term in node_name_lower for term in include_terms)
                
            node.setVisible(included)
            self.connection_mgr.update_connections_visibility(node)

    def _apply_push_away_for_node(self, node: 'NodeItem', animate: Optional[bool] = None) -> None:
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

    def _animate_node_to_position(self, node: 'NodeItem', target_x: float, target_y: float) -> None:
        """Animate a node smoothly to a target position.
        
        Args:
            node: The node to animate
            target_x: Target X coordinate
            target_y: Target Y coordinate
        """
        self.node_animator.animate_to(
            node,
            QPointF(target_x, target_y),
            duration_ms=constants.PUSH_AWAY_ANIMATION_DURATION,
            easing=QEasingCurve.Type.OutCubic,
        )

    def _animate_nodes_to_targets(self, targets: Dict['NodeItem', QPointF]) -> None:
        self.animations.animate_nodes_to_targets(
            targets,
            update_config_for_item=self._update_config_for_moved_node,
        )

    def clear_graph(self) -> None:
        """Remove all items from the scene."""
        logger.debug("Clearing graph visual.")
        # Destroy connections first to avoid issues when nodes/ports are removed
        self.connection_mgr.clear_all_connections()

        # Remove nodes (which should handle removing their ports)
        for node in list(self.nodes.values()):
            self.remove_node(node.client_name) # Use the method to ensure cleanup
        self.nodes.clear()

        self.clear() # Clears the underlying QGraphicsScene


    def add_node(self, client_name: str, client_ports: Optional[Dict[str, jack.Port]] = None, original_client_name: Optional[str] = None) -> Optional['NodeItem']:
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
            logger.debug(f"Node {client_name} already exists")
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
                    
                node.setPos(QPointF(x, y))
                
                # Defer push-away check until after node is fully laid out
                # This is especially important for complex nodes (like Ardour) with many ports
                QTimer.singleShot(0, lambda: self._apply_push_away_for_node(node))
            
            self.nodes[client_name] = node
            return node
        except Exception as e:
            logger.error(f"Error creating node for {client_name}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def remove_node(self, client_name: str, unload_unified_sinks: bool = False) -> None:
        node = self.nodes.pop(client_name, None)
        if node:
            logger.debug(f"Removing node: {client_name}")

            # Preserve unified state in node_configs so it is restored
            # when the client reappears (e.g. audio stream restarts).
            if node.is_input_unified or node.is_output_unified:
                config = self.node_configs.get(client_name, {})
                if node.is_input_unified:
                    config['is_input_unified'] = True
                    config['unified_input_sink_name'] = node.unified_input_sink_name
                if node.is_output_unified:
                    config['is_output_unified'] = True
                    config['unified_output_sink_name'] = node.unified_output_sink_name
                # Save current position so the node reappears in the same spot
                pos = node.scenePos()
                if pos and (pos.x() != 0 or pos.y() != 0):
                    config['pos'] = pos
                self.node_configs[client_name] = config
                logger.debug(f"Preserved unified state in node_configs for {client_name}")

            if unload_unified_sinks:
                if hasattr(node, 'is_input_unified') and node.is_input_unified:
                    logger.debug(f"Unloading input unified sink for node {client_name} before removal")
                    try:
                        node._unload_unified_sink(is_input=True)
                    except Exception as e:
                        logger.error(f"Error unloading input unified sink: {e}")

                if hasattr(node, 'is_output_unified') and node.is_output_unified:
                    logger.debug(f"Unloading output unified sink for node {client_name} before removal")
                    try:
                        node._unload_unified_sink(is_input=False)
                    except Exception as e:
                        logger.error(f"Error unloading output unified sink: {e}")



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

    @pyqtSlot()
    def _on_jack_shutdown(self) -> None:
        """Handle JACK server shutdown signal from GraphStateManager."""
        logger.debug("GraphScene: JACK server shutdown detected. Clearing graph.")
        self.clear_graph()

    def find_port_item(self, port_name: str) -> PortItem | None:
        """Find the VISIBLE PortItem QGraphicsItem corresponding to a full port name,
           considering split nodes and audio/midi split nodes."""
        
        port_obj = self.graph_jack_handler.get_port_by_name(port_name)
        if not port_obj:
            logger.debug(f"find_port_item: Could not get port object for '{port_name}'.")
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
            logger.debug(f"find_port_item: Node for client '{client_name}' not found.")
            return None

        # Now, handle manually split nodes (input/output parts)
        target_node = node_to_search
        if node_to_search.is_split_origin:
            if port_obj.is_input and node_to_search.split_input_node:
                target_node = node_to_search.split_input_node
            elif not port_obj.is_input and node_to_search.split_output_node:
                target_node = node_to_search.split_output_node
            else:
                logger.debug(f"find_port_item: Port '{port_name}' not found on expected split part of '{node_to_search.client_name}'.")
                return None
        
        # Search for the port on the determined target node
        port_item = target_node.input_ports.get(port_name) or target_node.output_ports.get(port_name)
        return port_item

    # --- Mouse Events (Delegated to Handler) ---

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """Delegate press event to the interaction handler."""
        # Let handler process first (e.g., store potential drag item)
        self.interaction_handler.mousePressEvent(event)

        # Always call super() AFTER handler.
        # super() handles selection state changes based on modifiers and button clicks,
        # and initiates the move operation for movable items if appropriate.
        super().mousePressEvent(event)
        # print(f"Scene mousePress: Called super().") # Optional debug


    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
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


    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
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
 
    def save_node_states(self, graph_zoom_level: Optional[float] = None, current_untangle_setting: Optional[int] = None) -> None:
        """Save the current node configurations (positions, split states, fold states, zoom level, and untangle setting)
           using the ConfigManager.
        Args:
            graph_zoom_level (float, optional): The current zoom level of the graph view.d
            current_untangle_setting (int, optional): The current untangle layout setting.
        """
        # print(f"JackGraphScene: Saving node states. Zoom: {graph_zoom_level}") # DEBUG
        # Pass the dictionary of original NodeItems, zoom level, and untangle setting to the config manager
        self.node_config_manager.save_node_states(self.nodes, graph_zoom_level=graph_zoom_level, current_untangle_setting=current_untangle_setting)

    def request_specific_node_save(self, node_item: 'NodeItem') -> None:
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

    def _update_config_for_moved_node(self, node_item: 'NodeItem') -> None:
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
                    logger.warning(f"Warning: Split part '{node_item.client_name}' identified as input by ports, not suffix.")
                elif has_outputs_only: # Fallback
                    config_key_to_update = "split_output_pos"
                    logger.warning(f"Warning: Split part '{node_item.client_name}' identified as output by ports, not suffix.")
                else:
                    logger.warning(f"Warning: Moved split part '{node_item.client_name}' for original '{original_client_name}'"
                          f" could not be identified as input or output part for config saving.")
                    return # Don't save if we can't determine the key
            else:
                logger.warning(f"Warning: Moved split part '{node_item.client_name}' has no reference to its origin. Cannot save position.")
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

    def get_node_item_by_name(self, node_name: str) -> 'NodeItem | None':
        """
        Retrieves a NodeItem from the scene by its original client name.
        This primarily searches the self.nodes dictionary which stores original NodeItems.
        """
        return self.nodes.get(node_name)

    def untangle_graph(self, max_nodes_per_row: int = 6) -> None:
        """
        Automatically organizes the graph nodes to reduce visual clutter.
        Delegates to the GraphLayouter class to perform the actual layout.
        
        Args:
            max_nodes_per_row (int): Maximum number of nodes to place in a row before
                                     starting a new row. Default is 6.
        """
        try:
            before = {n: n.pos() for n in self.nodes.values()}
            self.layouter.untangle_graph(max_nodes_per_row)
            after = {n: n.pos() for n in self.nodes.values()}
        except Exception as e:
            logger.error("Error in untangle_graph: %s", e)
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
            return

        targets: Dict[NodeItem, QPointF] = {}
        for node, after_pos in after.items():
            if before.get(node) != after_pos:
                targets[node] = after_pos

        for node, before_pos in before.items():
            node.setPos(before_pos)

        self._animate_nodes_to_targets(targets)

    def untangle_graph_by_io(self) -> None:
        """
        Triggers the I/O-based untangle layout.
        """
        from .node_item import NodeItem

        logger.debug("=== Starting untangle_graph_by_io ===")
        logger.debug("Current nodes in scene (self.nodes): %d", len(self.nodes))
        logger.debug("Current items in scene: %d", len(self.items()))

        try:
            logger.debug("Calling layouter.untangle_graph_by_io()")
            self.layouter.untangle_graph_by_io()
        except Exception as e:
            logger.error("Error in untangle_graph_by_io: %s", e)
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
            return

        # After layout is complete, ensure all node positions are properly updated
        self.connection_mgr.update_all_connection_paths()
        logger.debug("=== Finished untangle_graph_by_io ===")

    def untangle_graph_auto(self, auto_split: bool = True) -> bool:
        """Triggers the Graphviz-based auto layout.

        Args:
            auto_split: If True, automatically split nodes for optimal layout.
                If False, preserve the current split/unsplit state.

        Returns:
            True on success, False if graphviz is unavailable or layout fails.
        """
        from .node_item import NodeItem

        before_items = [
            item for item in self.items()
            if isinstance(item, NodeItem) and item.isVisible() and not item.is_split_origin
        ]
        before_pos = {n: n.pos() for n in before_items}

        try:
            ok = self.layouter.untangle_graph_auto(auto_split=auto_split)
        except Exception as e:
            logger.error("Error in untangle_graph_auto: %s", e)
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
            return False

        if not ok:
            return False

        after_items = [
            item for item in self.items()
            if isinstance(item, NodeItem) and item.isVisible() and not item.is_split_origin
        ]
        after_pos = {n: n.pos() for n in after_items}

        targets, start_pos = self.animations.compute_layout_transition_targets(
            before_items=before_items,
            before_pos=before_pos,
            after_pos=after_pos,
            origin_getter=lambda n: getattr(n, 'split_origin_node', None),
        )

        for node, pos in start_pos.items():
            node.setPos(pos)

        self._animate_nodes_to_targets(targets)
        return True

    def unsplit_all_nodes(self, save_state: bool = True) -> None:
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
                logger.error(f"Error unsplitting node {node.client_name}: {e}")
        
        # Save state once at the end if requested
        if save_state and unsplit_count > 0:
            self.save_node_states()
        
        if unsplit_count > 0:
            logger.debug(f"Unsplit {unsplit_count} nodes for untangle operation")

    def set_node_visibility_manager(self, node_visibility_manager: 'NodeVisibilityManager') -> None:
        """Set the NodeVisibilityManager instance for this scene and state manager."""
        self.node_visibility_manager = node_visibility_manager
        self.state_manager.set_node_visibility_manager(node_visibility_manager)
        logger.debug("Node visibility manager set for graph scene")

    def _update_node_ports(self, client_name: str, port_dict: Dict[str, jack.Port]) -> None:
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

    def _apply_split_part_visibility(self) -> None:
        """
        Apply individual visibility settings to split node parts.
        
        This method handles the case where only the input or only the output part
        of a split node should be visible. It checks the visibility settings and
        hides/shows the appropriate split parts.
        """
        if not hasattr(self, 'node_visibility_manager') or not self.node_visibility_manager:
            return
        
        for node in list(self.nodes.values()):
            # Only process split origin nodes
            if not node.is_split_origin:
                continue
            
            # Get the base client name
            client_name = node.client_name
            
            # Determine if this is a MIDI node
            is_midi = False
            if node.split_input_node:
                for port_item in node.split_input_node.input_ports.values():
                    if hasattr(port_item.port_obj, 'is_midi') and port_item.port_obj.is_midi:
                        is_midi = True
                        break
            if not is_midi and node.split_output_node:
                for port_item in node.split_output_node.output_ports.values():
                    if hasattr(port_item.port_obj, 'is_midi') and port_item.port_obj.is_midi:
                        is_midi = True
                        break
            
            # Check visibility settings for input and output parts
            input_visible = self.node_visibility_manager.is_input_visible(client_name, is_midi=is_midi)
            output_visible = self.node_visibility_manager.is_output_visible(client_name, is_midi=is_midi)
            
            logger.debug(f"Split part visibility for {client_name} (MIDI={is_midi}): input={input_visible}, output={output_visible}")
            
            # Apply visibility to split parts
            if node.split_input_node:
                should_hide = not input_visible
                is_currently_hidden = not node.split_input_node.isVisible()
                if should_hide != is_currently_hidden:
                    if should_hide:
                        node.split_input_node.hide()
                        # Also hide connections for this part
                        if hasattr(self, 'connection_mgr'):
                            self.connection_mgr.update_node_connections_visibility(node.split_input_node, False)
                    else:
                        node.split_input_node.show()
                        if hasattr(self, 'connection_mgr'):
                            self.connection_mgr.update_node_connections_visibility(node.split_input_node, True)
            
            if node.split_output_node:
                should_hide = not output_visible
                is_currently_hidden = not node.split_output_node.isVisible()
                if should_hide != is_currently_hidden:
                    if should_hide:
                        node.split_output_node.hide()
                        # Also hide connections for this part
                        if hasattr(self, 'connection_mgr'):
                            self.connection_mgr.update_node_connections_visibility(node.split_output_node, False)
                    else:
                        node.split_output_node.show()
                        if hasattr(self, 'connection_mgr'):
                            self.connection_mgr.update_node_connections_visibility(node.split_output_node, True)

    def _cleanup_orphaned_unified_sinks(self, all_ports: List[jack.Port]) -> None:
        """
        Clean up unified virtual sinks that no longer have corresponding JACK clients.
        This handles the edge case where the graph app is closed and reopened, but some
        JACK clients have disappeared while their unified sinks remain active.
        """
        if hasattr(self.connection_manager, 'unified_sink_manager'):
            try:
                return self.connection_manager.unified_sink_manager.cleanup_orphaned_unified_sinks(all_ports)
            except Exception as e:
                logger.error(f"Error during unified sink cleanup: {e}")
                return 0
        else:
            logger.debug("UnifiedSinkManager not available for cleanup.")
            logger.debug(f"Available attributes on connection_manager: {[attr for attr in dir(self.connection_manager) if not attr.startswith('_')]}")
            return 0

    def get_unified_nodes(self) -> List['NodeItem']:
        """Returns a list of all unified nodes in the scene."""
        unified_nodes = []
        for node in self.nodes.values():
            if (hasattr(node, 'is_input_unified') and node.is_input_unified) or \
               (hasattr(node, 'is_output_unified') and node.is_output_unified):
                unified_nodes.append(node)
        return unified_nodes

    def get_node_states(self) -> Dict[str, dict]:
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
        
        return copy.deepcopy(current_configs)
    
    def apply_unified_states(self, unified_clients: Dict[str, Any]) -> None:
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

    def restore_node_states(self, node_states: Dict[str, dict]) -> None:
        """
        Restores node positions and states from the provided configuration.
        
        Args:
            node_states (dict): A dictionary of node configurations
        """
        if not node_states:
            return

        targets: Dict[NodeItem, QPointF] = {}
            
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
                    targets[node] = config['pos']
                
                # Set manual_split flag if available
                if 'manual_split' in config:
                    if hasattr(node, 'config'):
                        if not node.config:
                            node.config = {}
                        node.config['manual_split'] = config['manual_split']
                
                # Set positions for input and output parts
                if 'split_input_pos' in config and node.split_input_node:
                    targets[node.split_input_node] = config['split_input_pos']
                
                if 'split_output_pos' in config and node.split_output_node:
                    targets[node.split_output_node] = config['split_output_pos']
                
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
                    targets[node] = config['pos']
                
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
        
        self._animate_nodes_to_targets(targets)

        # Update all connection paths to reflect the new node positions
        self.connection_mgr.update_all_connection_paths()

    def keyPressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
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
