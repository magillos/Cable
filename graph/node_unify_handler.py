"""
Handler for unifying multiple sink/source nodes into combined virtual devices via PipeWire.
"""
from __future__ import annotations
import logging
import traceback
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Set

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QRadioButton, QDialogButtonBox
from PyQt6.QtCore import QTimer, Qt

from cables.unified_sink_manager import client_family_base

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .node_item import NodeItem
    from .port_item import PortItem
    from PyQt6.QtWidgets import QMenu
    from cables.unified_sink_manager import UnifiedSinkManager


class NodeUnifyHandler:
    """Handles unified virtual sink logic for a NodeItem."""

    def __init__(self, node_item: NodeItem) -> None:
        self.node_item = node_item

    def _get_unified_sink_manager(self) -> Optional['UnifiedSinkManager']:
        """Get the UnifiedSinkManager from the scene's connection_manager."""
        ni = self.node_item
        scene = ni.scene()
        if not scene:
            return None
        cm = getattr(scene, 'connection_manager', None)
        return getattr(cm, 'unified_sink_manager', None) if cm else None

    def get_family_base(self) -> str:
        """Return the logical client family base name for this node.

        Clients that recreate themselves per stream/recording appear as
        e.g. ``Application``, ``Application-119``, ``Application-89``.  All of
        these share the same family base (``Application``) so their ports can
        be funnelled into a single unified sink.
        """
        ni = self.node_item
        name = ni.original_client_name or ni.client_name
        return client_family_base(name)

    @staticmethod
    def _sink_name_for(is_input: bool, base_name: str) -> str:
        """Build the unified sink name for a given family base name."""
        prefix = "unified-input-" if is_input else "unified-output-"
        return f"{prefix}{base_name.replace(' ', '_')}"

    def has_other_family_member(self, require_ports_input: Optional[bool] = None) -> bool:
        """Return True if another real node of the same client family exists.

        Used to decide whether a unified sink may be unloaded when one node of
        a family disappears.  The sink must stay alive until the *last* family
        member is gone.

        Args:
            require_ports_input: If ``True``, only count siblings that currently
                have input ports.  If ``False``, only count siblings with output
                ports.  If ``None``, count any sibling.
        """
        ni = self.node_item
        base = self.get_family_base()
        scene = ni.scene()
        if not scene:
            return False
        for node in getattr(scene, 'nodes', {}).values():
            if node is ni or getattr(node, 'is_virtual_sink', False):
                continue
            if node.is_split_origin or node.is_split_part:
                continue
            node_base = client_family_base(
                node.original_client_name or node.client_name
            )
            if node_base != base:
                continue
            if require_ports_input is True and not node.input_ports:
                continue
            if require_ports_input is False and not node.output_ports:
                continue
            return True
        return False

    def find_family_nodes(self) -> List['NodeItem']:
        """Return all normal nodes in the scene that belong to this client family.

        Virtual sinks, split origins and split parts are excluded — only real,
        visible client nodes participate in unification.  The originating node
        is always included even if the scene is unavailable.
        """
        ni = self.node_item
        scene = ni.scene()
        base = self.get_family_base()
        family: List['NodeItem'] = []
        if scene:
            for node in getattr(scene, 'nodes', {}).values():
                if getattr(node, 'is_virtual_sink', False):
                    continue
                if node.is_split_origin or node.is_split_part:
                    continue
                node_base = client_family_base(
                    node.original_client_name or node.client_name
                )
                if node_base == base:
                    family.append(node)
        if ni not in family:
            family.append(ni)
        return family

    def ensure_sink_exists(self) -> None:
        """Check if the unified sinks exist and recreate them if not or if broken."""
        ni = self.node_item
        if getattr(ni, 'is_virtual_sink', False):
            return

        # Skip MIDI-only nodes (no audio ports to unify)
        if ni.is_midi and not any(
            getattr(pi.port_obj, 'is_audio', False)
            for pl in (ni.input_ports, ni.output_ports)
            for pi in pl.values()
        ):
            return

        # Check input unified sink
        if ni.is_input_unified and ni.unified_input_sink_name:
            self._ensure_specific_sink_exists(is_input=True)

        # Check output unified sink
        if ni.is_output_unified and ni.unified_output_sink_name:
            self._ensure_specific_sink_exists(is_input=False)

    def _ensure_specific_sink_exists(self, is_input: bool) -> None:
        """Helper to ensure a specific unified sink exists."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return

        # Check if we have ports to unify
        has_ports = bool(ni.input_ports) if is_input else bool(ni.output_ports)

        jack_handler = ni.jack_handler if ni.jack_handler else getattr(ni.scene(), 'jack_connection_handler', None)
        if not jack_handler:
            return

        all_ports = jack_handler.get_ports()
        sink_client_name = f"{sink_name} Audio/Sink sink"
        sink_ports = [p for p in all_ports if p.name.startswith(sink_client_name)]

        if not has_ports:
            if sink_ports:
                # Keep the sink alive while any sibling family node still has
                # ports routed through it.
                if self.has_other_family_member(require_ports_input=is_input):
                    logger.debug(
                        f"Unified {'input' if is_input else 'output'} sink {sink_name} "
                        f"has no ports on {ni.client_name}, but sibling family nodes "
                        f"still use it. Keeping it alive."
                    )
                else:
                    logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} exists but node has no ports. Unloading...")
                    self._unload_unified_sink(is_input=is_input)
            return

        if not sink_ports:
            # Sink doesn't exist, recreate it
            logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} not found, recreating...")
            self._create_unified_sink(is_input=is_input)
            self._wait_for_sink_and_connect(is_input=is_input)
        else:
            logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} found, testing connections...")
            # Test if the sink is functional by trying to make a test connection
            if self._test_sink_functionality(is_input=is_input):
                logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} is functional, ensuring connections...")
                # Disconnect any existing connections to prevent self-connections
                self._disconnect_sink_self_connections(sink_client_name, all_ports)
                self._connect_to_unified_sink(is_input=is_input)
            else:
                logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} is broken, recreating...")
                usm = self._get_unified_sink_manager()
                if usm:
                    new_module_id = usm.force_recreate_unified_sink(sink_name)
                    if new_module_id:
                        if is_input:
                            ni.unified_input_module_id = new_module_id
                        else:
                            ni.unified_output_module_id = new_module_id
                    else:
                        if is_input:
                            ni.unified_input_module_id = None
                        else:
                            ni.unified_output_module_id = None
                self._wait_for_sink_and_connect(is_input=is_input)

    def _test_sink_functionality(self, is_input: bool) -> bool:
        """Test if the unified sink is functional via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return False

        usm = self._get_unified_sink_manager()
        if not usm:
            return False

        jack_handler = ni.jack_handler
        if not jack_handler:
            return False

        all_ports = jack_handler.get_ports()
        ports_type = 'input' if is_input else 'output'
        return usm.test_sink_functionality(sink_name, ports_type, all_ports)

    def _disconnect_sink_self_connections(self, sink_client_name: str, all_ports: List[Any]) -> None:
        """Disconnect any connections between the sink's own ports (monitor -> playback)."""
        ni = self.node_item
        if not ni.scene() or not getattr(ni.scene(), 'jack_connection_handler', None) is not None:
            return
        
        connection_handler = ni.scene().jack_connection_handler
        
        # Find all sink ports
        sink_outputs = [p for p in all_ports if p.is_output and p.name.startswith(sink_client_name + ':')]
        sink_inputs = [p for p in all_ports if p.is_input and p.name.startswith(sink_client_name + ':')]
        
        # Check for and break any connections between sink's own ports
        for sink_output in sink_outputs:
            try:
                # Get connections for this output port
                connections = connection_handler.get_all_connections(sink_output.name)
                for out_port, in_port in connections:
                    # Check if the input port belongs to the same sink
                    if in_port.startswith(sink_client_name + ':'):
                        logger.debug(f"Breaking self-connection: {out_port} -> {in_port}")
                        try:
                            connection_handler.break_connection(out_port, in_port)
                        except Exception as e:
                            logger.error(f"Error breaking self-connection: {e}")
            except Exception as e:
                logger.error(f"Error checking connections for {sink_output.name}: {e}")

    def apply_preset(self, unify_data: Dict[str, Any]) -> None:
        """Applies the unified state to the node from a preset."""
        ni = self.node_item
        if getattr(ni, 'is_virtual_sink', False):
            return

        # Skip MIDI-only nodes (no audio ports to unify)
        if ni.is_midi and not any(
            getattr(pi.port_obj, 'is_audio', False)
            for pl in (ni.input_ports, ni.output_ports)
            for pi in pl.values()
        ):
            return

        # Handle split states
        if unify_data.get('is_input_unified'):
            ni.is_input_unified = True
            ni.unified_input_sink_name = unify_data.get('unified_input_sink_name')
            if not ni.unified_input_sink_name:
                base_name = (ni.original_client_name or ni.client_name).replace(' ', '_')
                ni.unified_input_sink_name = f"unified-input-{base_name}"
        
        if unify_data.get('is_output_unified'):
            ni.is_output_unified = True
            ni.unified_output_sink_name = unify_data.get('unified_output_sink_name')
            if not ni.unified_output_sink_name:
                base_name = (ni.original_client_name or ni.client_name).replace(' ', '_')
                ni.unified_output_sink_name = f"unified-output-{base_name}"

        # Skip sink creation here, ensure_sink_exists will handle it
        ni.update()

    def _create_unified_sink(self, is_input: bool) -> None:
        """Create the unified virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            logger.warning("Cannot create unified sink: UnifiedSinkManager not available")
            return

        module_id = usm.create_unified_sink(sink_name)
        if module_id:
            if is_input:
                ni.unified_input_module_id = module_id
            else:
                ni.unified_output_module_id = module_id
            logger.info(f"Created unified {'input' if is_input else 'output'} virtual sink: {sink_name}")

    def _save_unified_module_id(self, sink_name: str, module_id: str) -> None:
        """Save the unified module ID to config via UnifiedSinkManager."""
        usm = self._get_unified_sink_manager()
        if usm:
            usm._save_unified_module_id(sink_name, module_id)

    def _unload_unified_sink(self, is_input: bool) -> None:
        """Unload the unified virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            logger.warning("Cannot unload unified sink: UnifiedSinkManager not available")
            return

        if usm.remove_unified_sink(sink_name):
            logger.info(f"Unloaded unified {'input' if is_input else 'output'} virtual sink: {sink_name}")

        # Clear local state
        if is_input:
            ni.unified_input_module_id = None
        else:
            ni.unified_output_module_id = None

    def _remove_unified_module_id(self, sink_name: str) -> None:
        """Remove the unified module ID from config via UnifiedSinkManager."""
        usm = self._get_unified_sink_manager()
        if usm:
            usm._remove_unified_module_id(sink_name)

    def _connect_to_unified_sink(self, is_input: bool) -> None:
        """Connect this node's ports to the unified sink via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        
        if not sink_name or not ni.scene() or not getattr(ni.scene(), 'jack_connection_handler', None) is not None:
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            return

        jack_handler = ni.jack_handler
        all_ports = jack_handler.get_ports()
        connection_handler = ni.scene().jack_connection_handler

        # Connect only the specified direction
        if not is_input:
            sink_client_name = f"{sink_name} Audio/Sink sink"
            usm._connect_output_ports(ni, all_ports, sink_client_name, connection_handler)
        else:
            sink_client_name = f"{sink_name} Audio/Sink sink"
            usm._connect_input_ports(ni, all_ports, sink_client_name, connection_handler)

    def connect_new_port(self, port_item: 'PortItem', is_input: bool) -> None:
        """Connect a newly added port to the unified sink via UnifiedSinkManager."""
        ni = self.node_item
        usm = self._get_unified_sink_manager()
        if not usm:
            return

        if not ni.scene() or not getattr(ni.scene(), 'jack_connection_handler', None) is not None:
            return

        jack_handler = ni.jack_handler
        if not jack_handler:
            return

        all_ports = jack_handler.get_ports()
        usm.connect_new_port_to_unified_sink(port_item, all_ports, ni.scene().jack_connection_handler)

    def _wait_for_sink_and_connect(self, is_input: bool) -> None:
        """Waits for the unified sink to appear and then connects to it."""
        ni = self.node_item
        MAX_RETRIES = 50 # 50 * 100ms = 5 seconds
        if ni.wait_for_sink_retries >= MAX_RETRIES:
            logger.debug("Unified sink did not appear in time.")
            ni.wait_for_sink_retries = 0
            return

        sink_name_base = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name_base:
            logger.debug("No unified sink name available for connection attempt.")
            ni.wait_for_sink_retries = 0
            return

        jack_handler = ni.jack_handler
        all_ports = jack_handler.get_ports()

        # Look specifically for ports that belong to the sink we created for this node
        # The full JACK client name will be: "sink_name_base Audio/Sink sink"
        sink_client_name = f"{sink_name_base} Audio/Sink sink"
        
        # We check for ANY ports from this sink to confirm its existence
        sink_ports = sorted([p for p in all_ports if (
            p.name.startswith(sink_client_name + ':')
        )], key=lambda p: p.name)

        logger.debug(f"Waiting for sink - name_base: '{sink_name_base}', found {len(sink_ports)} sink ports")
        if sink_ports:
            for port in sink_ports[:5]:  # Show first 5
                logger.debug(f"  Found sink port: {port.name}")

        if sink_ports:
            ni.wait_for_sink_retries = 0
            self._connect_to_unified_sink(is_input=is_input)
        else:
            ni.wait_for_sink_retries += 1
            ni.wait_for_sink_timer = QTimer()
            ni.wait_for_sink_timer.setSingleShot(True)
            ni.wait_for_sink_timer.timeout.connect(lambda: self._wait_for_sink_and_connect(is_input))
            ni.wait_for_sink_timer.start(100)

    def toggle_input(self, checked: bool) -> None:
        """Toggle unification for input ports."""
        ni = self.node_item
        try:
            if getattr(ni, 'is_virtual_sink', False):
                if ni.unify_input_action:
                    ni.unify_input_action.setChecked(False)
                return

            base = self.get_family_base()

            if checked:
                # Enabling: configure THIS node and then apply the same unified
                # sink to every other node in the client family.
                ni.is_input_unified = True
                ni.unified_input_sink_name = self._sink_name_for(True, base)
                self._persist_family_state()
                self._create_unified_sink(is_input=True)
                self._wait_for_sink_and_connect(is_input=True)
                self._propagate_to_family(is_input=True, source=ni)
            else:
                # Disabling: tear down the family's unified sink completely and
                # clear the unified flag on all sibling nodes.
                sink_name = ni.unified_input_sink_name or self._sink_name_for(True, base)
                family = self.find_family_nodes()
                self._unload_unified_sink_for_name(sink_name, is_input=True)
                for node in family:
                    try:
                        if node is ni:
                            node.is_input_unified = False
                            node.unified_input_sink_name = None
                            node.unified_input_module_id = None
                        else:
                            node.unify_handler.disable_input_unification(
                                sink_name=sink_name
                            )
                    except Exception as e:
                        logger.error(
                            f"Error clearing input unification on family node "
                            f"{getattr(node, 'client_name', '?')}: {e}"
                        )
                # Clear any preserved unified state in the scene's node_configs
                # so it is not resurrected when the client reappears.
                self._clear_preserved_unified_state(is_input=True)
                # Always persist, even if a sibling failed to clear, so the
                # family entry does not linger and resurrect unification on
                # the next app start.
                self._persist_family_state(clearing_input=True)

            ni.update()
            self.update_config_state()

        except Exception as e:
            logger.error(f"Error toggling input unification: {e}")
            traceback.print_exc()

    def toggle_output(self, checked: bool) -> None:
        """Toggle unification for output ports."""
        ni = self.node_item
        try:
            if getattr(ni, 'is_virtual_sink', False):
                if ni.unify_output_action:
                    ni.unify_output_action.setChecked(False)
                return

            base = self.get_family_base()

            if checked:
                # Enabling: configure THIS node and then apply the same unified
                # sink to every other node in the client family.
                ni.is_output_unified = True
                ni.unified_output_sink_name = self._sink_name_for(False, base)
                self._persist_family_state()
                self._create_unified_sink(is_input=False)
                self._wait_for_sink_and_connect(is_input=False)
                self._propagate_to_family(is_input=False, source=ni)
            else:
                # Disabling: tear down the family's unified sink completely and
                # clear the unified flag on all sibling nodes.
                sink_name = ni.unified_output_sink_name or self._sink_name_for(False, base)
                family = self.find_family_nodes()
                self._unload_unified_sink_for_name(sink_name, is_input=False)
                for node in family:
                    try:
                        if node is ni:
                            node.is_output_unified = False
                            node.unified_output_sink_name = None
                            node.unified_output_module_id = None
                        else:
                            node.unify_handler.disable_output_unification(
                                sink_name=sink_name
                            )
                    except Exception as e:
                        logger.error(
                            f"Error clearing output unification on family node "
                            f"{getattr(node, 'client_name', '?')}: {e}"
                        )
                # Clear any preserved unified state in the scene's node_configs
                # so it is not resurrected when the client reappears.
                self._clear_preserved_unified_state(is_input=False)
                # Always persist, even if a sibling failed to clear, so the
                # family entry does not linger and resurrect unification on
                # the next app start.
                self._persist_family_state(clearing_output=True)

            ni.update()
            self.update_config_state()

        except Exception as e:
            logger.error(f"Error toggling output unification: {e}")
            traceback.print_exc()

    # --- Client-family unification helpers ---

    def _propagate_to_family(self, is_input: bool, source: 'NodeItem') -> None:
        """Mirror the enabled unified state onto all sibling family nodes.

        The sink always keeps the family-base name (independent of which
        sibling was toggled) so that new siblings appearing later connect to
        the same sink.
        """
        base = self.get_family_base()
        sink_name = self._sink_name_for(is_input, base)
        direction = 'input' if is_input else 'output'

        for node in self.find_family_nodes():
            if node is source:
                continue
            # Respect per-node capability: skip nodes without ports of the
            # relevant direction (they may gain them later and be picked up
            # by ensure_sink_exists).
            if is_input and not node.input_ports:
                continue
            if not is_input and not node.output_ports:
                continue

            if is_input:
                node.is_input_unified = True
                node.unified_input_sink_name = sink_name
            else:
                node.is_output_unified = True
                node.unified_output_sink_name = sink_name

            # The sink may still be materialising (created asynchronously by
            # the toggling node).  Poll for it so late siblings connect too.
            node.unify_handler._wait_for_sink_and_connect(is_input=is_input)
            node.unify_handler.update_config_state()
            node.update()
            logger.debug(
                f"Family-unified {direction} for sibling node {node.client_name} "
                f"-> {sink_name}"
            )

    def disable_input_unification(self, sink_name: Optional[str] = None) -> None:
        """Clear input-unified state on this node without unloading the sink.

        Used when a sibling node in the same client family is toggled off; the
        sink is unloaded once by the toggling node.
        """
        ni = self.node_item
        ni.is_input_unified = False
        ni.unified_input_sink_name = None
        ni.unified_input_module_id = None
        ni.update()
        self.update_config_state()

    def disable_output_unification(self, sink_name: Optional[str] = None) -> None:
        """Clear output-unified state on this node without unloading the sink."""
        ni = self.node_item
        ni.is_output_unified = False
        ni.unified_output_sink_name = None
        ni.unified_output_module_id = None
        ni.update()
        self.update_config_state()

    def _clear_preserved_unified_state(self, is_input: bool) -> None:
        """Clear preserved unified state from the scene's node_configs.

        When a node is removed (e.g. its JACK client disappears), the scene
        preserves the unified state in ``node_configs`` so it can be restored
        when the client reappears.  If the user has explicitly disabled
        unification, that preserved state must be cleared or the node will
        resurrect as unified on the next client restart.

        Args:
            is_input: True to clear input-unified state, False for output.
        """
        ni = self.node_item
        scene = ni.scene()
        if scene is None:
            return
        node_configs = getattr(scene, 'node_configs', None)
        if node_configs is None:
            return

        base = self.get_family_base()
        key = 'is_input_unified' if is_input else 'is_output_unified'
        sink_key = 'unified_input_sink_name' if is_input else 'unified_output_sink_name'

        # Clear preserved state for every known family member.
        for client_name, config in node_configs.items():
            if client_family_base(client_name) != base:
                continue
            if key in config:
                config.pop(key, None)
                config.pop(sink_key, None)
                logger.debug(
                    f"Cleared preserved unified state in node_configs for {client_name}"
                )

    def _unload_unified_sink_for_name(self, sink_name: Optional[str], is_input: bool) -> None:
        """Unload a unified sink identified by an explicit sink name.

        ``_unload_unified_sink`` reads the name from the node's attributes.  When
        disabling an inherited family unification the node may only have its own
        name populated, so set it temporarily to ensure the correct sink is
        removed.
        """
        ni = self.node_item
        attr = 'unified_input_sink_name' if is_input else 'unified_output_sink_name'
        previous = getattr(ni, attr, None)
        setattr(ni, attr, sink_name)
        try:
            self._unload_unified_sink(is_input=is_input)
        finally:
            setattr(ni, attr, previous)

    def _persist_family_state(self, clearing_input: bool = False, clearing_output: bool = False) -> None:
        """Persist (or clear) the family-level unified state in the config manager.

        Args:
            clearing_input: True when called from the input-disable path. The
                toggling node's own flag has already been cleared, so force the
                persisted input flag to False regardless of any stale sibling
                state that could not be cleared (e.g. a node whose client
                disappeared mid-operation).
            clearing_output: Same as ``clearing_input`` for the output direction.
        """
        ni = self.node_item
        cm = getattr(ni, 'config_manager', None)
        if cm is None or not hasattr(cm, 'set_family_unified_state'):
            return
        try:
            base = self.get_family_base()
            is_input_unified = False if clearing_input else bool(
                ni.is_input_unified
                or self._family_has_input_unified()
            )
            is_output_unified = False if clearing_output else bool(
                ni.is_output_unified
                or self._family_has_output_unified()
            )
            logger.debug(
                f"_persist_family_state {ni.client_name}: base={base}, "
                f"is_input_unified={is_input_unified}, is_output_unified={is_output_unified}, "
                f"clearing_input={clearing_input}, clearing_output={clearing_output}"
            )
            cm.set_family_unified_state(
                base,
                is_input_unified=is_input_unified,
                is_output_unified=is_output_unified,
                unified_input_sink_name=(
                    ni.unified_input_sink_name
                    if ni.unified_input_sink_name
                    else self._sink_name_for(True, base) if is_input_unified else None
                ),
                unified_output_sink_name=(
                    ni.unified_output_sink_name
                    if ni.unified_output_sink_name
                    else self._sink_name_for(False, base) if is_output_unified else None
                ),
            )
        except Exception as e:
            logger.error(f"Error persisting family unified state: {e}")

    def _family_has_input_unified(self) -> bool:
        return any(node.is_input_unified for node in self.find_family_nodes())

    def _family_has_output_unified(self) -> bool:
        return any(node.is_output_unified for node in self.find_family_nodes())

    def apply_family_unification(self) -> None:
        """Auto-unify this node if a sibling in its client family is unified.

        Called when a node is created/applied from config.  Handles the case
        where e.g. ``Application`` was unified and a new ``Application-119``
        node appears later — it is picked up automatically.
        """
        ni = self.node_item
        if getattr(ni, 'is_virtual_sink', False):
            return

        base = self.get_family_base()
        state = None
        cm = getattr(ni, 'config_manager', None)
        if cm is not None and hasattr(cm, 'get_family_unified_state'):
            state = cm.get_family_unified_state(base)

        # First preference: live sibling state in the current scene.
        input_sink = None
        output_sink = None
        family_has_input = self._family_has_input_unified()
        family_has_output = self._family_has_output_unified()
        if family_has_input:
            input_sink = self._sink_name_for(True, base)
        if family_has_output:
            output_sink = self._sink_name_for(False, base)

        logger.debug(
            f"apply_family_unification {ni.client_name}: base={base}, "
            f"family_has_input={family_has_input}, family_has_output={family_has_output}, "
            f"persisted_state={state}, "
            f"ni.is_input_unified={ni.is_input_unified}, ni.is_output_unified={ni.is_output_unified}"
        )

        # Fall back to persisted family state (e.g. after a restart).
        if state:
            if state.get('is_input_unified'):
                input_sink = state.get('unified_input_sink_name') or self._sink_name_for(True, base)
            if state.get('is_output_unified'):
                output_sink = state.get('unified_output_sink_name') or self._sink_name_for(False, base)

        if input_sink and ni.input_ports and not ni.is_input_unified:
            ni.is_input_unified = True
            ni.unified_input_sink_name = input_sink
            logger.info(
                f"Auto-unified input for family sibling {ni.client_name} -> {input_sink}"
            )
            self.update_config_state()
            self._create_unified_sink(is_input=True)
            self._wait_for_sink_and_connect(is_input=True)

        if output_sink and ni.output_ports and not ni.is_output_unified:
            ni.is_output_unified = True
            ni.unified_output_sink_name = output_sink
            logger.info(
                f"Auto-unified output for family sibling {ni.client_name} -> {output_sink}"
            )
            self.update_config_state()
            self._create_unified_sink(is_input=False)
            self._wait_for_sink_and_connect(is_input=False)

    def update_config_state(self) -> None:
        """Updates the unified state in the saved configuration.
        
        Uses GraphConfigManager's cache to avoid overwriting data on flush.
        """
        ni = self.node_item
        if getattr(ni, 'config_manager', None) is not None:
            if getattr(ni, 'is_virtual_sink', False):
                return
            try:
                # Use the config manager's cache instead of direct file access
                cached_data = ni.config_manager._cached_data
                if cached_data is None:
                    cached_data = {}
                    ni.config_manager._cached_data = cached_data

                client_config = cached_data.get(ni.client_name, {})

                # Update input unified state
                if ni.is_input_unified:
                    client_config[ni.config_manager.IS_INPUT_UNIFIED_KEY] = True
                    client_config[ni.config_manager.UNIFIED_INPUT_SINK_NAME_KEY] = ni.unified_input_sink_name
                    client_config[ni.config_manager.UNIFIED_INPUT_MODULE_ID_KEY] = ni.unified_input_module_id
                else:
                    client_config.pop(ni.config_manager.IS_INPUT_UNIFIED_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_INPUT_SINK_NAME_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_INPUT_MODULE_ID_KEY, None)

                # Update output unified state
                if ni.is_output_unified:
                    client_config[ni.config_manager.IS_OUTPUT_UNIFIED_KEY] = True
                    client_config[ni.config_manager.UNIFIED_OUTPUT_SINK_NAME_KEY] = ni.unified_output_sink_name
                    client_config[ni.config_manager.UNIFIED_OUTPUT_MODULE_ID_KEY] = ni.unified_output_module_id
                else:
                    client_config.pop(ni.config_manager.IS_OUTPUT_UNIFIED_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_OUTPUT_SINK_NAME_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_OUTPUT_MODULE_ID_KEY, None)

                # Update cache and mark dirty for deferred write
                cached_data[ni.client_name] = client_config
                ni.config_manager._dirty = True

            except Exception as e:
                logger.error(f"Error updating unified state in config: {e}")

    def show_choice_dialog(self) -> Optional[str]:
        """
        Show a dialog to choose whether to unify input ports or output ports.

        Returns:
            str or None: 'input', 'output', or None if canceled
        """
        ni = self.node_item
        # Get the main window as parent for proper centering
        parent = None
        if ni.scene() and ni.scene().views():
            parent = ni.scene().views()[0]

        dialog = QDialog(parent)
        dialog.setWindowTitle("Choose Ports to Unify")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        # Add instruction text
        instruction = QLabel("Unify:")
        instruction.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(instruction)

        # Create radio buttons
        output_radio = QRadioButton("Output ports")
        output_radio.setChecked(True)  # Default selection
        layout.addWidget(output_radio)

        input_radio = QRadioButton("Input ports")
        layout.addWidget(input_radio)

        # Add buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # Center the dialog in the main window
        if parent:
            dialog.adjustSize()  # Ensure the dialog size is calculated
            parent_center = parent.rect().center()
            dialog_center = dialog.rect().center()
            dialog.move(parent.mapToGlobal(parent_center - dialog_center))

        # Execute dialog
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            if input_radio.isChecked():
                return 'input'
            elif output_radio.isChecked():
                return 'output'
            else:
                return None
        else:
            return None

    def classify_node(self, client_name: str) -> None:
        """Check if this node represents a virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        try:
            usm = self._get_unified_sink_manager()
            if not usm:
                ni.is_virtual_sink = False
                ni.module_id = None
                return

            info = usm.classify_virtual_sink(client_name)
            ni.is_virtual_sink = info.get('is_virtual_sink', False)
            ni.module_id = info.get('module_id')
            ni.external_sink = info.get('external_sink', False)
            ni.is_unified_sink = info.get('is_unified_sink', False)

            if ni.is_unified_sink:
                ni.update()

        except Exception as e:
            logger.error(f"Error checking if node is virtual sink for {client_name}: {e}")
            ni.is_virtual_sink = False
            ni.module_id = None

    def _find_module_id_for_external_sink(self, sink_name: str) -> Optional[str]:
        """Find module ID for an external virtual sink via UnifiedSinkManager."""
        usm = self._get_unified_sink_manager()
        if usm:
            return usm.find_module_id_for_external_sink(sink_name)
        return None

    def unload_sink(self) -> None:
        """Unload this virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        if not ni.is_virtual_sink:
            logger.debug(f"Cannot unload sink: {ni.client_name} is not identified as a virtual sink")
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            logger.warning("Cannot unload sink: UnifiedSinkManager not available")
            return

        if usm.unload_virtual_sink(ni.client_name):
            sink_type = "external" if getattr(ni, 'external_sink', False) else "tracked"
            logger.info(f"Successfully unloaded {sink_type} virtual sink: {ni.client_name}")

    def build_context_menu(self, menu: 'QMenu') -> None:
        """Add unify-related items to a context menu for a normal node."""
        ni = self.node_item
        
        # Check if this is a MIDI node - Unify toggle should not be available for MIDI nodes
        is_midi_node = ni.is_midi
        
        # Check if this is a virtual sink (any virtual sink)
        is_virtual_sink = getattr(ni, 'is_virtual_sink', False)
        
        # Add separate toggles for Input and Output unification only for audio nodes that aren't virtual sinks
        if not is_midi_node and not is_virtual_sink:
            from PyQt6.QtGui import QAction
            # Add separator before Unify section
            menu.addSeparator()
            
            # Unify Input Ports
            if bool(ni.input_ports):
                ni.unify_input_action = QAction("Unify input ports", menu)
                ni.unify_input_action.setCheckable(True)
                ni.unify_input_action.setChecked(ni.is_input_unified)
                ni.unify_input_action.toggled.connect(self.toggle_input)
                menu.addAction(ni.unify_input_action)
            
            # Unify Output Ports
            if bool(ni.output_ports):
                ni.unify_output_action = QAction("Unify output ports", menu)
                ni.unify_output_action.setCheckable(True)
                ni.unify_output_action.setChecked(ni.is_output_unified)
                ni.unify_output_action.toggled.connect(self.toggle_output)
                menu.addAction(ni.unify_output_action)
            
            # Add help text
            help_text = QAction("Route client ports through\ndedicated stereo virtual sinks", menu)
            help_text.setEnabled(False)
            menu.addAction(help_text)

    def handle_new_port(self, port_item: 'PortItem', is_input: bool) -> None:
        """Handle auto-connecting a newly added port to unified sink."""
        ni = self.node_item
        if is_input and ni.is_input_unified and ni.unified_input_sink_name:
            if not ni.unified_input_module_id:
                self._create_unified_sink(is_input=True)
                self._wait_for_sink_and_connect(is_input=True)
            elif ni.scene() and getattr(ni.scene(), 'jack_connection_handler', None) is not None:
                self.connect_new_port(port_item, is_input=True)
        elif not is_input and ni.is_output_unified and ni.unified_output_sink_name:
            if not ni.unified_output_module_id:
                self._create_unified_sink(is_input=False)
                self._wait_for_sink_and_connect(is_input=False)
            elif ni.scene() and getattr(ni.scene(), 'jack_connection_handler', None) is not None:
                self.connect_new_port(port_item, is_input=False)
