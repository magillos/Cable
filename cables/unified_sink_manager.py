#!/usr/bin/env python3
"""
Unified Sink Manager for Cables

This module provides unified sink management functionality, including:
- Creation and removal of PulseAudio virtual sinks
- Connection management for unified client ports
- Orphan cleanup and configuration persistence
"""

import re
import subprocess
import json
import traceback
from cable_core import config_keys as keys
from typing import Dict, List, Optional, Any, TYPE_CHECKING
if TYPE_CHECKING:
    from cables.graph.node_item import NodeItem
    from cables.graph.port_item import PortItem
    from cables.graph.jack_handler import JackHandler
    from cables.jack_connection_handler import JackConnectionHandler
    import jack
from cables.utils.sort_utils import natural_sort_key_for_port_item

import logging
logger = logging.getLogger(__name__)

# PipeWire may auto-rename duplicate JACK clients by appending "-<number>"
# e.g. "my-sink Audio/Sink sink" becomes "my-sink Audio/Sink sink-122"
_SINK_SUFFIX_RE = re.compile(r' Audio/Sink sink(?:-\d+)?$')


def _has_sink_suffix(name: str) -> bool:
    """Check if name ends with ' Audio/Sink sink' with optional PipeWire rename postfix."""
    return bool(_SINK_SUFFIX_RE.search(name))


def _strip_sink_suffix(name: str) -> str:
    """Remove the ' Audio/Sink sink[-N]' suffix from a client name."""
    return _SINK_SUFFIX_RE.sub('', name)


class UnifiedSinkManager:
    """Manages unified virtual sinks for JACK clients."""

    def __init__(self, config_manager: Optional[Any] = None) -> None:
        """Initialize the UnifiedSinkManager.

        Args:
            config_manager: ConfigManager instance for persistence
        """
        self.config_manager = config_manager
        self._waiting_sinks = {}  # sink_name: node_item

    def create_unified_sink(self, sink_name: str) -> Optional[str]:
        """Create a PulseAudio virtual sink for a unified client.

        First checks if a sink with this name already exists. If so, finds
        and stores the module ID rather than creating a duplicate.

        Args:
            sink_name: Name for the virtual sink

        Returns:
            Module ID if successful, None otherwise
        """
        # First, check if a sink with this name already exists
        try:
            existing = subprocess.run(["pactl", "list", "short", "sinks"],
                                     capture_output=True, text=True, check=True)
            for line in existing.stdout.splitlines():
                parts = line.split('\t')
                if len(parts) >= 2 and parts[1].strip() == sink_name:
                    logger.debug(f"Sink {sink_name} already exists, finding its module ID...")
                    module_id = self.find_module_id_for_external_sink(sink_name)
                    if module_id:
                        self._save_unified_module_id(sink_name, str(module_id))
                        logger.debug(f"Using existing sink {sink_name} with module ID {module_id}")
                        return str(module_id)
                    return None
        except Exception as e:
            logger.error(f"Error checking for existing sinks: {e}")

        # Sink doesn't exist, create it
        command = ["pactl", "load-module", "module-null-sink",
                  f"sink_name={sink_name}", "channel_map=stereo"]

        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            module_id = result.stdout.strip()

            # Save the module ID to config
            self._save_unified_module_id(sink_name, module_id)

            logger.info(f"Created unified virtual sink: {sink_name}")
            logger.debug(f"Module ID: {module_id}")
            return module_id
        except subprocess.CalledProcessError as e:
            logger.error(f"Error creating unified virtual sink: {e}")
            # If creation failed, it might be because it already exists
            # Try to find the module ID
            module_id = self.find_module_id_for_external_sink(sink_name)
            if module_id:
                self._save_unified_module_id(sink_name, str(module_id))
                logger.debug(f"Found existing sink {sink_name} with module ID {module_id}")
                return str(module_id)
            return None

    def remove_unified_sink(self, sink_name: str) -> bool:
        """Unload a unified virtual sink.

        Resolves the current module ID dynamically first (stored IDs can
        become stale across restarts), falls back to stored config ID.

        Args:
            sink_name: Name of the sink to remove

        Returns:
            True if successful, False otherwise
        """
        # Prefer resolving the CURRENT module id from pactl by sink name.
        # Stored IDs can become stale across restarts and will cause unload to fail.
        module_id = self._get_unified_module_id(sink_name)
        resolved_module_id = self.find_module_id_for_external_sink(sink_name)
        if resolved_module_id:
            module_id = str(resolved_module_id)

        if not module_id:
            logger.debug(f"No module ID found for unified sink {sink_name}")
            return False

        command = ["pactl", "unload-module", module_id]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            logger.info(f"Unloaded unified virtual sink: {sink_name}")

            # Remove the module ID from config
            self._remove_unified_module_id(sink_name)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error unloading unified virtual sink: {e}")
            return False

    def connect_ports_to_unified_sink(self, node_item: 'NodeItem', jack_handler: 'JackHandler', all_ports: List['jack.Port']) -> None:
        """Connect a unified node's ports to its virtual sink.

        Args:
            node_item: The NodeItem with unified ports
            jack_handler: JACK handler for making connections
            all_ports: List of all JACK ports
        """
        if node_item.is_output_unified and node_item.unified_output_sink_name:
            sink_client_name = f"{node_item.unified_output_sink_name} Audio/Sink sink"
            self._connect_output_ports(node_item, all_ports, sink_client_name, jack_handler)
            
        if node_item.is_input_unified and node_item.unified_input_sink_name:
            sink_client_name = f"{node_item.unified_input_sink_name} Audio/Sink sink"
            self._connect_input_ports(node_item, all_ports, sink_client_name, jack_handler)

    def _connect_output_ports(self, node_item: 'NodeItem', all_ports: List['jack.Port'], sink_client_name: str, connection_handler: 'JackConnectionHandler') -> None:
        """Connect output ports to sink inputs."""
        node_outputs = sorted([p for p in node_item.output_ports.values()],
                            key=self._natural_sort_key)

        # Find sink input ports that belong to our specific unified sink
        sink_inputs = self._find_sink_ports(all_ports, sink_client_name, is_input=True)
        sink_inputs = [p for p in sink_inputs if 'playback_FL' in p.name or 'playback_FR' in p.name]

        logger.debug(f"Connecting output unified node to sink '{node_item.unified_output_sink_name}':")
        logger.debug(f"  Node outputs: {[p.port_name for p in node_outputs]}")
        logger.debug(f"  Sink inputs found: {[p.name for p in sink_inputs]}")

        if not node_outputs or not sink_inputs:
            logger.debug("Unified sink connection failed: No node outputs or sink inputs found.")
            return

        # Match and connect outputs to inputs
        for i, port_item in enumerate(node_outputs):
            sink_input = self._match_channel_to_sink_input(port_item, sink_inputs, i)
            if sink_input:
                self._make_connection(connection_handler, port_item.port_name, sink_input.name)

    def _connect_input_ports(self, node_item: 'NodeItem', all_ports: List['jack.Port'], sink_client_name: str, connection_handler: 'JackConnectionHandler') -> None:
        """Connect sink outputs to input ports."""
        node_inputs = sorted([p for p in node_item.input_ports.values()],
                           key=self._natural_sort_key)

        # Find sink output ports that belong to our specific unified sink
        sink_outputs = self._find_sink_ports(all_ports, sink_client_name, is_input=False)
        sink_outputs = [p for p in sink_outputs if 'monitor_FL' in p.name or 'monitor_FR' in p.name]

        logger.debug(f"Connecting input unified node to sink '{node_item.unified_input_sink_name}':")
        logger.debug(f"  Node inputs: {[p.port_name for p in node_inputs]}")
        logger.debug(f"  Sink outputs found: {[p.name for p in sink_outputs]}")

        if not node_inputs or not sink_outputs:
            logger.debug("Unified sink connection failed: No node inputs or sink outputs found.")
            return

        # Match and connect sink outputs to node inputs
        for i, port_item in enumerate(node_inputs):
            sink_output = self._match_channel_to_sink_output(port_item, sink_outputs, i)
            if sink_output:
                self._make_connection(connection_handler, sink_output.name, port_item.port_name)

    def connect_new_port_to_unified_sink(self, port_item: 'PortItem', all_ports: List['jack.Port'], jack_connection_handler: 'JackConnectionHandler') -> None:
        """Connect a newly added port to the unified sink.

        Args:
            port_item: The new PortItem to connect
            all_ports: List of all JACK ports
            jack_connection_handler: Handler for making JACK connections
        """
        # Determine which sink to connect to based on port type
        sink_name_base = None
        if port_item.is_input:
             # Input port added -> connect to input unified sink (monitor)
             if port_item.parentItem().is_input_unified:
                 sink_name_base = port_item.parentItem().unified_input_sink_name
        else:
             # Output port added -> connect to output unified sink (playback)
             if port_item.parentItem().is_output_unified:
                 sink_name_base = port_item.parentItem().unified_output_sink_name

        if not sink_name_base:
            return

        # Find sink input ports
        sink_inputs = self._find_sink_ports(all_ports, sink_name_base, is_input=True, legacy_mode=True)

        if not sink_inputs:
            logger.debug(f"Unified sink not found for {port_item.port_name}")
            return

        # Match port to sink input based on channel name
        target_sink_input = self._match_new_port_to_sink_input(port_item, sink_inputs)

        if target_sink_input:
            try:
                jack_connection_handler.make_connection(port_item.port_name, target_sink_input)
                logger.debug(f"Auto-connected new port {port_item.port_name} to unified sink")
            except Exception as e:
                logger.error(f"Error auto-connecting {port_item.port_name} to {target_sink_input}: {e}")

    def test_sink_functionality(self, unified_virtual_sink_name: str, unified_ports_type: str,
                              all_ports: List['jack.Port']) -> bool:
        """Test if a unified sink is functional.

        Args:
            unified_virtual_sink_name: Name of the sink to test
            unified_ports_type: 'input' or 'output'
            all_ports: List of all JACK ports

        Returns:
            True if functional, False otherwise
        """
        try:
            # Try to find the sink ports
            sink_client_name = f"{unified_virtual_sink_name} Audio/Sink sink"

            if unified_ports_type == 'output':
                sink_inputs = self._find_sink_ports(all_ports, sink_client_name, is_input=True)
                sink_inputs = [p for p in sink_inputs if 'playback_FL' in p.name or 'playback_FR' in p.name]
                return len(sink_inputs) >= 2  # Should have at least left and right channels

            elif unified_ports_type == 'input':
                sink_outputs = self._find_sink_ports(all_ports, sink_client_name, is_input=False)
                sink_outputs = [p for p in sink_outputs if 'monitor_FL' in p.name or 'monitor_FR' in p.name]
                return len(sink_outputs) >= 2  # Should have at least left and right channels

            return False
        except Exception as e:
            logger.error(f"Error testing sink functionality for {unified_virtual_sink_name}: {e}")
            return False

    def classify_virtual_sink(self, client_name: str) -> Dict[str, Any]:
        """Check if a client name represents a virtual sink and classify it.

        Args:
            client_name: JACK client name to check

        Returns:
            Dict with keys: is_virtual_sink, module_id, external_sink, is_unified_sink
        """
        result = {
            'is_virtual_sink': False,
            'module_id': None,
            'external_sink': False,
            'is_unified_sink': False,
        }

        if not self.config_manager:
            # No config, but still check for virtual sink pattern
            if _has_sink_suffix(client_name):
                result['is_virtual_sink'] = True
                result['external_sink'] = True
            return result

        module_ids_json = self.config_manager.get_str(keys.VIRTUAL_SINK_MODULE_IDS, '{}')

        if module_ids_json:
            module_ids = json.loads(module_ids_json)
            # Check exact match first (full client name in config)
            if client_name in module_ids:
                result['is_virtual_sink'] = True
                result['module_id'] = module_ids[client_name]
            else:
                # Check if client name starts with any sink name (app-created sinks)
                for sink_name in module_ids.keys():
                    if client_name.startswith(sink_name):
                        rest = client_name[len(sink_name):]
                        if rest and rest[0] == ' ':
                            # Original match: "sink_name Audio/Sink sink"
                            result['is_virtual_sink'] = True
                            result['module_id'] = module_ids[sink_name]
                            break
                        elif rest and rest[0] in '-.':
                            # PipeWire auto-rename suffix (e.g., "-124", ".2")
                            suffix_after_sep = rest[1:]
                            if suffix_after_sep and suffix_after_sep[0].isdigit():
                                result['is_virtual_sink'] = True
                                result['module_id'] = module_ids[sink_name]
                                break

                # Fallback: Check for any virtual sink pattern (external sinks)
                if not result['is_virtual_sink'] and _has_sink_suffix(client_name):
                    result['is_virtual_sink'] = True
                    result['external_sink'] = True
        else:
            # No config entries, but still check for virtual sink pattern
            if _has_sink_suffix(client_name):
                result['is_virtual_sink'] = True
                result['external_sink'] = True

        # Check if this virtual sink was created by Unify toggle
        if result['is_virtual_sink']:
            sink_base_name = _strip_sink_suffix(client_name)
            normalized_sink_base = sink_base_name.replace(' ', '_').lower()
            if (
                normalized_sink_base.startswith('unified-input-')
                or normalized_sink_base.startswith('unified_output-')
                or normalized_sink_base.startswith('unified-output-')
                or normalized_sink_base.startswith('unified_input-')
                or normalized_sink_base.startswith('unified-input_')
                or normalized_sink_base.startswith('unified-output_')
                or normalized_sink_base.startswith('unified_input_')
                or normalized_sink_base.startswith('unified_output_')
            ):
                result['is_unified_sink'] = True

            unified_sinks_json = self.config_manager.get_str(keys.UNIFIED_VIRTUAL_SINKS, '{}')
            if unified_sinks_json:
                unified_sinks = json.loads(unified_sinks_json)
                # Check if this sink is a unified sink
                for unified_sink_name in unified_sinks.keys():
                    client_base = _strip_sink_suffix(client_name)
                    if (client_name == unified_sink_name or
                        client_base == unified_sink_name):
                        result['is_unified_sink'] = True
                        logger.debug(f"Detected unified sink: {client_name} matches {unified_sink_name}")
                        break

                    sink_base_from_client = client_base.replace(' ', '_').replace('-', '_')
                    unified_sink_name_normalized = unified_sink_name.replace(' ', '_').replace('-', '_')
                    if unified_sink_name_normalized.startswith(sink_base_from_client + '_'):
                        result['is_unified_sink'] = True
                        logger.debug(f"Detected unified sink (pattern match): {client_name} matches {unified_sink_name}")
                        break

        return result

    def unload_virtual_sink(self, client_name: str) -> bool:
        """Unload a virtual sink using the stored module ID or finding it dynamically.

        Args:
            client_name: JACK client name of the virtual sink

        Returns:
            True if successfully unloaded, False otherwise
        """
        info = self.classify_virtual_sink(client_name)

        if not info['is_virtual_sink']:
            logger.debug(f"Cannot unload sink: {client_name} is not identified as a virtual sink")
            return False

        # Extract sink name from client name (remove " Audio/Sink sink[-N]" suffix)
        sink_name = _strip_sink_suffix(client_name)

        # Get module ID - prefer PipeWire node lookup for accuracy when
        # multiple sinks share the same name (PipeWire appends node ID as suffix)
        module_id = self._find_module_id_by_pipewire_node(client_name)
        if not module_id:
            module_id = info['module_id']
        if not module_id:
            module_id = self.find_module_id_for_external_sink(sink_name)

        if not module_id:
            logger.debug(f"Cannot unload sink: No module ID found for {client_name}")
            return False

        command = ["pactl", "unload-module", str(module_id)]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            sink_type = "external" if info['external_sink'] else "tracked"
            logger.info(f"Successfully unloaded {sink_type} virtual sink: {client_name} (module ID: {module_id})")

            # For tracked sinks: Remove from stored module IDs
            if not info['external_sink'] and self.config_manager:
                try:
                    module_ids_json = self.config_manager.get_str(keys.VIRTUAL_SINK_MODULE_IDS, '{}')
                    if module_ids_json:
                        module_ids = json.loads(module_ids_json)

                        # Find the key that matches this client (either exact or partial match)
                        key_to_remove = None
                        for stored_sink_name in module_ids.keys():
                            if client_name == stored_sink_name:
                                key_to_remove = stored_sink_name
                                break
                            if client_name.startswith(stored_sink_name):
                                rest = client_name[len(stored_sink_name):]
                                if rest and rest[0] == ' ':
                                    key_to_remove = stored_sink_name
                                    break
                                elif rest and rest[0] in '-.' and len(rest) > 1 and rest[1].isdigit():
                                    key_to_remove = stored_sink_name
                                    break

                        if key_to_remove:
                            del module_ids[key_to_remove]
                            self.config_manager.set_str(keys.VIRTUAL_SINK_MODULE_IDS, json.dumps(module_ids))
                            logger.info(f"Removed module ID {module_id} from config for sink '{key_to_remove}' (client: {client_name})")
                        else:
                            logger.warning(f"Warning: Could not find config entry to remove for {client_name}")

                except Exception as e:
                    logger.error(f"Error removing module ID from config for {client_name}: {e}")

            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error unloading virtual sink {client_name}: {e}")
            return False

    def force_recreate_unified_sink(self, sink_name: str) -> Optional[str]:
        """Remove and recreate a unified sink.

        Args:
            sink_name: Name of the sink to recreate

        Returns:
            New module ID if successful, None otherwise
        """
        self.remove_unified_sink(sink_name)
        return self.create_unified_sink(sink_name)

    def _find_module_id_by_pipewire_node(self, client_name: str) -> Optional[str]:
        """Find the pactl module ID for a JACK client via its PipeWire node.

        When PipeWire creates duplicate JACK clients, it appends the node ID
        as a suffix (e.g. "my-sink Audio/Sink sink-185" where 185 is the
        PipeWire node ID). This method uses pw-dump to look up the specific
        node and return its pulse.module.id.

        For no-suffix clients, finds the matching node whose ID doesn't
        appear as a suffix (i.e. the primary client).

        Args:
            client_name: Full JACK client name

        Returns:
            Module ID string if found, None otherwise
        """
        sink_name = _strip_sink_suffix(client_name)

        # Extract PipeWire node ID from JACK client name suffix
        m = re.search(r'-(\d+)$', client_name)
        target_node_id = int(m.group(1)) if m else None

        try:
            result = subprocess.run(["pw-dump", "Node"],
                                    capture_output=True, text=True, check=True)
            nodes = json.loads(result.stdout)

            matching = []
            for node in nodes:
                if node.get('type') != 'PipeWire:Interface:Node':
                    continue
                props = node.get('info', {}).get('props', {})
                if props.get('node.name') == sink_name:
                    nid = node.get('id')
                    pmid = props.get('pulse.module.id')
                    matching.append((nid, pmid))

            if not matching:
                return None

            if target_node_id is not None:
                # Suffixed client — find by exact node ID
                for nid, pmid in matching:
                    if nid == target_node_id:
                        return str(pmid) if pmid is not None else None
            elif len(matching) == 1:
                # Only one node, must be this one
                nid, pmid = matching[0]
                return str(pmid) if pmid is not None else None
            else:
                # No suffix with multiple nodes — the primary (no-suffix)
                # JACK client is the first-created node. PipeWire assigns
                # the lowest object.serial to the first-created node, which
                # also appears first in pw-dump output and pactl list sinks.
                # Pick the node with the lowest serial.
                best = None
                for node in nodes:
                    if node.get('type') != 'PipeWire:Interface:Node':
                        continue
                    props = node.get('info', {}).get('props', {})
                    if props.get('node.name') != sink_name:
                        continue
                    serial = int(props.get('object.serial', 0))
                    pmid = props.get('pulse.module.id')
                    if best is None or serial < best[0]:
                        best = (serial, pmid)
                if best and best[1] is not None:
                    return str(best[1])

        except Exception as e:
            logger.error(f"Error finding module by PipeWire node for {client_name}: {e}")

        return None

    def find_module_id_for_external_sink(self, sink_name: str) -> Optional[str]:
        """Find module ID for an external virtual sink using pactl list sinks.

        Args:
            sink_name: Name of the sink

        Returns:
            Module ID if found, None otherwise
        """
        try:
            result = subprocess.run(["pactl", "list", "sinks"],
                                  capture_output=True, text=True, check=True)

            lines = result.stdout.split('\n')
            in_target_sink = False

            for line in lines:
                line = line.strip()

                # Start of target sink
                if not in_target_sink and line == f'Name: {sink_name}':
                    in_target_sink = True

                # Found Owner Module within target sink
                elif in_target_sink and 'Owner Module:' in line:
                    module_id = line.split(':', 1)[1].strip()
                    # Validate it's a real module ID
                    if module_id.isdigit():
                        module_id_int = int(module_id)
                        if module_id_int != 4294967295:  # Error value
                            return module_id
                        else:
                            logger.warning(f"Warning: Invalid module ID {module_id} for sink '{sink_name}' (error value)")
                            return None
                    else:
                        logger.warning(f"Warning: Non-numeric module ID '{module_id}' for sink '{sink_name}'")
                        return None

                # Exit sink block when we hit the next sink
                elif in_target_sink and line.startswith('Name: ') and line != f'Name: {sink_name}':
                    break

            logger.warning(f"Warning: Could not find valid Owner Module for sink '{sink_name}'")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running pactl list sinks: {e}")
            return None
        except Exception as e:
            logger.error(f"Error finding module ID for external sink '{sink_name}': {e}")
            return None

    def cleanup_orphaned_unified_sinks(self, all_ports: List['jack.Port']) -> int:
        """Clean up unified virtual sinks that no longer have corresponding JACK clients.

        Args:
            all_ports: List of all JACK ports

        Returns:
            Number of sinks cleaned up
        """
        logger.debug("Checking for orphaned unified sinks...")

        if not self.config_manager:
            return 0

        unified_sinks_json = self.config_manager.get_str(keys.UNIFIED_VIRTUAL_SINKS, '{}')

        try:
            unified_sinks = json.loads(unified_sinks_json) if unified_sinks_json else {}
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing unified virtual sinks config: {e}")
            return 0

        if not unified_sinks:
            logger.debug("No unified virtual sinks found in config.")
            return 0

        # Create a set of current JACK client names
        current_client_names = set()
        for port in all_ports:
            if ':' in port.name:
                client_name, port_short_name = port.name.split(':', 1)
                current_client_names.add(client_name)

        # Check each configured unified sink
        sinks_to_remove = []

        for sink_name, module_id in list(unified_sinks.items()):
            # Check if this sink is orphaned (sink exists but original client doesn't)
            sink_has_ports = self._sink_has_ports(all_ports, sink_name)
            original_client_exists = self._original_client_exists(current_client_names, sink_name)
            
            if sink_has_ports and not original_client_exists:
                logger.debug(f"Found orphaned unified sink {sink_name} (module ID: {module_id}), unloading...")
                
                # Try to resolve the current module ID dynamically
                resolved_module_id = self.find_module_id_for_external_sink(sink_name)
                if resolved_module_id:
                    module_id = resolved_module_id
                    logger.debug(f"Resolved current module ID: {module_id}")
                
                try:
                    result = subprocess.run(["pactl", "unload-module", str(module_id)],
                                          check=True, capture_output=True, text=True)
                    logger.info(f"Successfully unloaded orphaned unified sink: {sink_name}")
                    sinks_to_remove.append(sink_name)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Error unloading orphaned unified sink {sink_name}: {e}")
                    # Still remove from config even if unload failed (sink might already be gone)
                    sinks_to_remove.append(sink_name)
            elif not sink_has_ports and not original_client_exists:
                # Sink is already gone and client is gone, just clean up config
                logger.debug(f"Sink {sink_name} and its client are both gone, cleaning up config")
                sinks_to_remove.append(sink_name)

        # Remove unloaded sinks from config
        for sink_name in sinks_to_remove:
            if sink_name in unified_sinks:
                del unified_sinks[sink_name]

        # Save updated config
        if sinks_to_remove:
            self.config_manager.set_str(keys.UNIFIED_VIRTUAL_SINKS, json.dumps(unified_sinks))
            logger.info(f"Cleaned up {len(sinks_to_remove)} orphaned unified sinks from config.")

        return len(sinks_to_remove)

    # Helper methods

    def _save_unified_module_id(self, sink_name: str, module_id: str) -> None:
        """Save the unified module ID to config file."""
        if not self.config_manager:
            return

        try:
            # Get existing module IDs
            module_ids_json = self.config_manager.get_str(keys.UNIFIED_VIRTUAL_SINKS, '{}')
            module_ids = json.loads(module_ids_json) if module_ids_json else {}

            # Add/update the module ID
            module_ids[sink_name] = module_id

            # Save back to config
            self.config_manager.set_str(keys.UNIFIED_VIRTUAL_SINKS, json.dumps(module_ids))
        except Exception as e:
            logger.error(f"Error saving unified module ID for {sink_name}: {e}")

    def _remove_unified_module_id(self, sink_name: str) -> None:
        """Remove the unified module ID from config file."""
        if not self.config_manager:
            return

        try:
            module_ids_json = self.config_manager.get_str(keys.UNIFIED_VIRTUAL_SINKS, '{}')
            module_ids = json.loads(module_ids_json) if module_ids_json else {}

            if sink_name in module_ids:
                del module_ids[sink_name]

            self.config_manager.set_str(keys.UNIFIED_VIRTUAL_SINKS, json.dumps(module_ids))
        except Exception as e:
            logger.error(f"Error removing unified module ID for {sink_name}: {e}")

    def _get_unified_module_id(self, sink_name: str) -> Optional[str]:
        """Get the module ID for a unified sink."""
        if not self.config_manager:
            return None

        try:
            module_ids_json = self.config_manager.get_str(keys.UNIFIED_VIRTUAL_SINKS, '{}')
            module_ids = json.loads(module_ids_json) if module_ids_json else {}
            return module_ids.get(sink_name)
        except Exception as e:
            return None

    def _find_sink_ports(self, all_ports: List['jack.Port'], sink_client_name: str, is_input: bool,
                        legacy_mode: bool = False) -> List['jack.Port']:
        """Find sink ports that match the given criteria."""
        if legacy_mode:
            # Legacy mode: check starts with sink_name_base or full client name
            sink_name_base = sink_client_name.replace(' Audio/Sink sink', '')
            ports = [p for p in all_ports if
                    (p.name.startswith(sink_name_base + ':') or
                     p.name.startswith(sink_client_name + ':')) and
                    p.is_input == is_input]
        else:
            # Standard mode: exact sink client name match
            ports = [p for p in all_ports if
                    p.name.startswith(sink_client_name + ':') and
                    p.is_input == is_input]

        return sorted(ports, key=lambda p: p.name)

    def _match_channel_to_sink_input(self, port_item: 'PortItem', sink_inputs: List['jack.Port'], index: int) -> Optional['jack.Port']:
        """Match a port to an appropriate sink input channel."""
        port_name = port_item.short_name.lower()
        target_sink_input = None

        if 'left' in port_name or 'fl' in port_name:
            target_sink_input = sink_inputs[0] if len(sink_inputs) > 0 else None
        elif 'right' in port_name or 'fr' in port_name:
            target_sink_input = sink_inputs[1] if len(sink_inputs) > 1 else sink_inputs[0] if len(sink_inputs) > 0 else None
        else:
            target_sink_input = sink_inputs[index % len(sink_inputs)] if sink_inputs else None

        return target_sink_input

    def _match_channel_to_sink_output(self, port_item: 'PortItem', sink_outputs: List['jack.Port'], index: int) -> Optional['jack.Port']:
        """Match a port to an appropriate sink output channel."""
        port_name = port_item.short_name.lower()
        source_sink_output = None

        if 'left' in port_name or 'fl' in port_name:
            source_sink_output = sink_outputs[0] if len(sink_outputs) > 0 else None
        elif 'right' in port_name or 'fr' in port_name:
            source_sink_output = sink_outputs[1] if len(sink_outputs) > 1 else sink_outputs[0] if len(sink_outputs) > 0 else None
        else:
            source_sink_output = sink_outputs[index % len(sink_outputs)] if sink_outputs else None

        return source_sink_output

    def _match_new_port_to_sink_input(self, port_item: 'PortItem', sink_inputs: List['jack.Port']) -> Optional[str]:
        """Match a new port to an appropriate sink input for auto-connection."""
        port_name_lower = port_item.short_name.lower()
        target_sink_input = None

        if 'left' in port_name_lower or 'fl' in port_name_lower or 'l' == port_name_lower:
            target_sink_input = sink_inputs[0].name if len(sink_inputs) > 0 else None
        elif 'right' in port_name_lower or 'fr' in port_name_lower or 'r' == port_name_lower:
            target_sink_input = sink_inputs[1].name if len(sink_inputs) > 1 else sink_inputs[0].name if len(sink_inputs) > 0 else None
        else:
            # Try to match by position
            node = port_item.parentItem()
            node_outputs = sorted([p for p in node.output_ports.values()], key=self._natural_sort_key)
            port_index = node_outputs.index(port_item) if port_item in node_outputs else 0
            target_sink_input = sink_inputs[port_index % len(sink_inputs)].name if sink_inputs else None

        return target_sink_input

    def _sink_has_ports(self, all_ports: List['jack.Port'], sink_name: str) -> bool:
        """Check if a sink has ports in the JACK system."""
        for port in all_ports:
            if port.name.startswith(f"{sink_name} Audio/Sink sink"):
                return True
        return False

    def _original_client_exists(self, current_client_names: set, sink_name: str) -> bool:
        """Check if the original client exists for a unified sink."""
        # The sink name format is "unified-<original_client_name_with_underscores>"
        # Or "unified-input-..." / "unified-output-..."
        
        original_client_name = sink_name
        if sink_name.startswith('unified-input-'):
            original_client_name = sink_name.replace('unified-input-', '', 1)
        elif sink_name.startswith('unified-output-'):
            original_client_name = sink_name.replace('unified-output-', '', 1)
        elif sink_name.startswith('unified-'):
            original_client_name = sink_name.replace('unified-', '', 1)

        # Try the derived name first (with underscores)
        if original_client_name in current_client_names:
            return True

        # Convert underscores back to spaces (reverse of unify logic)
        client_name_with_spaces = original_client_name.replace('_', ' ')
        return client_name_with_spaces in current_client_names

    def _make_connection(self, connection_handler: 'JackConnectionHandler', source_port: str, dest_port: str) -> None:
        """Make a JACK connection between two ports."""
        try:
            connection_handler.make_connection(source_port, dest_port)
            logger.debug(f"  Connected {source_port} -> {dest_port}")
        except Exception as e:
            logger.error(f"Error connecting {source_port} to {dest_port}: {e}")

    @staticmethod
    def _natural_sort_key(port_item: 'PortItem') -> Any:
        """Creates an enhanced sort key that groups ports by base name."""
        return natural_sort_key_for_port_item(port_item)
