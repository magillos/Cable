"""
Helper functions for determining drag actions and visual feedback during port/bulk-area interactions.
"""
import typing
from PyQt6.QtGui import QColor

# Import constants and other necessary types
from . import constants
from .port_item import PortItem
from .bulk_area_item import BulkAreaItem
from .node_item import NodeItem
from cables.utils.sort_utils import natural_sort_key_for_port_item as _port_sort_key

if typing.TYPE_CHECKING:
    # These are already imported above but good for explicit type checking context
    pass


def get_ports_in_visual_order(port_dict: dict[str, PortItem]) -> list[PortItem]:
    """Return ports sorted in visual layout order: audio first (natural sort), then MIDI."""
    audio = [p for p in port_dict.values() if not p.port_obj.is_midi]
    midi = [p for p in port_dict.values() if p.port_obj.is_midi]
    return sorted(audio, key=_port_sort_key) + sorted(midi, key=_port_sort_key)


def determine_port_to_port_action(source_port: PortItem, target_port: PortItem, app_constants: typing.Any) -> tuple[typing.Optional[str], QColor]:
    """Determines action (connect/disconnect) and color for port-to-port drag."""
    if not source_port or not target_port:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Check for self-connection
    if source_port.parent_node == target_port.parent_node:
        parent_node = source_port.parent_node
        # Allow self-connection only if the node is not split
        if parent_node and (parent_node.is_split_origin or parent_node.is_split_part):
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR # Cannot connect to same node if split
        # If unsplit, proceed to check connection validity (e.g. IN to OUT)

    out_p, in_p = (source_port, target_port) if not source_port.is_input and target_port.is_input else \
                  (target_port, source_port) if source_port.is_input and not target_port.is_input else \
                  (None, None)

    if not out_p or not in_p:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR # Invalid type combination

    is_already_connected = any(
        (conn.source_port == out_p and conn.dest_port == in_p)
        for conn in out_p.connections # Check connections of the output port
    )

    if is_already_connected:
        return "disconnect", app_constants.PORT_DISCONNECT_DRAG_COLOR
    else:
        return "connect", app_constants.PORT_DRAG_COLOR

def determine_port_to_bulk_action(source_port: PortItem, target_bulk: BulkAreaItem, app_constants: typing.Any) -> tuple[typing.Optional[str], QColor]:
    """Determines action and color for port-to-bulk drag (sequential mapping)."""
    if not source_port or not target_bulk or not target_bulk.parent_node:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    parent_node = source_port.parent_node
    if parent_node == target_bulk.parent_node: # Self-connection attempt
        if parent_node and (parent_node.is_split_origin or parent_node.is_split_part):
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR # Disallow if split

    if source_port.is_input == target_bulk.is_input: # Must be different types
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Get target ports from the bulk area (in visual order)
    if not source_port.is_input and target_bulk.is_input:
        target_ports = get_ports_in_visual_order(target_bulk.parent_node.input_ports)
    elif source_port.is_input and not target_bulk.is_input:
        target_ports = get_ports_in_visual_order(target_bulk.parent_node.output_ports)
    else:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    if not target_ports:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Get source port's siblings in visual order and find its index
    if not source_port.is_input:
        source_siblings = get_ports_in_visual_order(parent_node.output_ports)
    else:
        source_siblings = get_ports_in_visual_order(parent_node.input_ports)

    try:
        source_idx = source_siblings.index(source_port)
    except ValueError:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Build sequential pairs and check connections
    num_pairs = 0
    num_already_connected = 0
    for i, t_port in enumerate(target_ports):
        s_idx = source_idx + i
        if s_idx >= len(source_siblings):
            break
        num_pairs += 1
        s_port = source_siblings[s_idx]
        out_p, in_p = (s_port, t_port) if not s_port.is_input else (t_port, s_port)
        if any(conn.source_port == out_p and conn.dest_port == in_p for conn in out_p.connections):
            num_already_connected += 1

    if num_pairs == 0:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    if num_already_connected == num_pairs:
        return "disconnect", app_constants.PORT_DISCONNECT_DRAG_COLOR
    else:
        return "connect", app_constants.PORT_DRAG_COLOR

def determine_bulk_to_port_action(source_bulk: BulkAreaItem, target_port: PortItem, app_constants: typing.Any) -> tuple[typing.Optional[str], QColor]:
    """Determines action and color for bulk-to-port drag (sequential mapping)."""
    if not source_bulk or not target_port or not source_bulk.parent_node:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    parent_node = source_bulk.parent_node
    if parent_node == target_port.parent_node: # Self-connection attempt
        if parent_node and (parent_node.is_split_origin or parent_node.is_split_part):
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR # Disallow if split

    if source_bulk.is_input == target_port.is_input: # Must be different types
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Get source ports in visual order
    if source_bulk.is_input:
        source_ports = get_ports_in_visual_order(source_bulk.parent_node.input_ports)
    else:
        source_ports = get_ports_in_visual_order(source_bulk.parent_node.output_ports)
    source_ports = [sp for sp in source_ports if sp.is_input != target_port.is_input]

    if not source_ports:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Get target port's siblings in visual order and find its index
    target_node = target_port.parent_node
    if target_port.is_input:
        target_siblings = get_ports_in_visual_order(target_node.input_ports)
    else:
        target_siblings = get_ports_in_visual_order(target_node.output_ports)

    try:
        target_idx = target_siblings.index(target_port)
    except ValueError:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Build sequential pairs and check connections
    num_pairs = 0
    num_already_connected = 0
    for i, s_port in enumerate(source_ports):
        t_idx = target_idx + i
        if t_idx >= len(target_siblings):
            break
        num_pairs += 1
        t_port = target_siblings[t_idx]
        out_p, in_p = (s_port, t_port) if not s_port.is_input else (t_port, s_port)
        if any(conn.source_port == out_p and conn.dest_port == in_p for conn in out_p.connections):
            num_already_connected += 1

    if num_pairs == 0:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    if num_already_connected == num_pairs:
        return "disconnect", app_constants.PORT_DISCONNECT_DRAG_COLOR
    else:
        return "connect", app_constants.PORT_DRAG_COLOR

def determine_bulk_to_bulk_action(source_bulk: BulkAreaItem, target_bulk: BulkAreaItem, app_constants: typing.Any) -> tuple[typing.Optional[str], QColor]:
    """Determines action and color for bulk-to-bulk drag, considering specific direction."""
    if not source_bulk or not target_bulk or not source_bulk.parent_node or not target_bulk.parent_node:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    parent_node_source = source_bulk.parent_node
    parent_node_target = target_bulk.parent_node

    if parent_node_source == parent_node_target: # Self-connection attempt
        if parent_node_source.is_split_origin or parent_node_source.is_split_part:
            # Cannot connect a node to itself via bulk areas if split
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR
        # If unsplit, proceed to check if IN to OUT or OUT to IN for self-connection
        if source_bulk.is_input == target_bulk.is_input: # e.g. IN bulk to IN bulk on same node
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR
    elif source_bulk.is_input == target_bulk.is_input: # For different nodes, still disallow IN-IN or OUT-OUT
        # Cannot connect IN to IN or OUT to OUT
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Determine effective output and input nodes/ports for the current drag direction
    source_node = source_bulk.parent_node
    target_node = target_bulk.parent_node

    out_node_for_drag: NodeItem
    in_node_for_drag: NodeItem
    out_ports_for_drag: list[PortItem]
    in_ports_for_drag: list[PortItem]

    if not source_bulk.is_input:  # Source is an OUTPUT bulk area
        # Target must be an INPUT bulk area (checked by source_bulk.is_input == target_bulk.is_input)
        out_node_for_drag = source_node
        out_ports_for_drag = list(source_node.output_ports.values())
        in_node_for_drag = target_node
        in_ports_for_drag = list(target_node.input_ports.values())
    else:  # Source is an INPUT bulk area
        # Target must be an OUTPUT bulk area
        in_node_for_drag = source_node
        in_ports_for_drag = list(source_node.input_ports.values())
        out_node_for_drag = target_node
        out_ports_for_drag = list(target_node.output_ports.values())

    if not out_ports_for_drag or not in_ports_for_drag:
        return "connect_all", app_constants.PORT_DRAG_COLOR

    num_potential_connections = min(len(out_ports_for_drag), len(in_ports_for_drag))

    if num_potential_connections == 0:
         return "connect_all", app_constants.PORT_DRAG_COLOR

    num_existing_connections_in_direction = 0
    for out_port_item in out_ports_for_drag:
        idx_out = out_ports_for_drag.index(out_port_item)
        if idx_out >= num_potential_connections:
            continue

        for conn_item in out_port_item.connections:
            if conn_item.dest_port in in_ports_for_drag:
                idx_in = in_ports_for_drag.index(conn_item.dest_port)
                if idx_in < num_potential_connections and conn_item.dest_port.parent_node == in_node_for_drag:
                    if out_ports_for_drag[idx_out] == conn_item.source_port and \
                       in_ports_for_drag[idx_in] == conn_item.dest_port and \
                       idx_out == idx_in:
                        num_existing_connections_in_direction += 1

    if num_existing_connections_in_direction >= num_potential_connections:
        return "disconnect_all", app_constants.PORT_DISCONNECT_DRAG_COLOR
    else:
        return "connect_all", app_constants.PORT_DRAG_COLOR