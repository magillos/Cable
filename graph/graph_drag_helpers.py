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
    """Determines action and color for port-to-bulk drag.

    Connects the single source port to all ports in the bulk's ``paired_ports``.
    """
    if not source_port or not target_bulk or not target_bulk.parent_node:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    parent_node = source_port.parent_node
    if parent_node == target_bulk.parent_node: # Self-connection attempt
        if parent_node and (parent_node.is_split_origin or parent_node.is_split_part):
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR # Disallow if split

    if source_port.is_input == target_bulk.is_input: # Must be different types
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Use only the bulk area's paired ports as targets
    target_ports = target_bulk.paired_ports

    if not target_ports:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Check if source_port is connected to all target_ports
    num_pairs = 0
    num_already_connected = 0
    for t_port in target_ports:
        num_pairs += 1
        s_port = source_port
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
    """Determines action and color for bulk-to-port drag.

    Connects all ports in the bulk's ``paired_ports`` to the single target port.
    """
    if not source_bulk or not target_port or not source_bulk.parent_node:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    parent_node = source_bulk.parent_node
    if parent_node == target_port.parent_node: # Self-connection attempt
        if parent_node and (parent_node.is_split_origin or parent_node.is_split_part):
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR # Disallow if split

    if source_bulk.is_input == target_port.is_input: # Must be different types
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Use only the bulk area's paired ports as sources
    source_ports = source_bulk.paired_ports

    if not source_ports:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Check if all source_ports are connected to target_port
    num_pairs = 0
    num_already_connected = 0
    for s_port in source_ports:
        num_pairs += 1
        t_port = target_port
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
    """Determines action and color for bulk-to-bulk drag (per-pair mapping).

    Uses each bulk area's ``paired_ports`` instead of all node ports.
    Sequential mapping: pairs source paired ports with target paired ports
    by index.
    """
    if not source_bulk or not target_bulk or not source_bulk.parent_node or not target_bulk.parent_node:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    parent_node_source = source_bulk.parent_node
    parent_node_target = target_bulk.parent_node

    if parent_node_source == parent_node_target: # Self-connection attempt
        if parent_node_source.is_split_origin or parent_node_source.is_split_part:
            return None, app_constants.DEFAULT_DRAG_LINE_COLOR
    if source_bulk.is_input == target_bulk.is_input:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    # Determine effective output and input ports from the paired ports
    if not source_bulk.is_input: # Source is an OUTPUT bulk area
        out_ports_for_drag = source_bulk.paired_ports
        in_ports_for_drag = target_bulk.paired_ports
    else: # Source is an INPUT bulk area
        in_ports_for_drag = source_bulk.paired_ports
        out_ports_for_drag = target_bulk.paired_ports

    if not out_ports_for_drag or not in_ports_for_drag:
        return "connect_all", app_constants.PORT_DRAG_COLOR

    num_potential_connections = min(len(out_ports_for_drag), len(in_ports_for_drag))

    if num_potential_connections == 0:
        return "connect_all", app_constants.PORT_DRAG_COLOR

    num_existing_connections_in_direction = 0
    for idx_out, out_port_item in enumerate(out_ports_for_drag):
        if idx_out >= num_potential_connections:
            continue

        for conn_item in out_port_item.connections:
            if conn_item.dest_port in in_ports_for_drag:
                idx_in = in_ports_for_drag.index(conn_item.dest_port)
                if idx_in < num_potential_connections and conn_item.dest_port.parent_node == in_ports_for_drag[idx_in].parent_node:
                    if out_ports_for_drag[idx_out] == conn_item.source_port and \
                        in_ports_for_drag[idx_in] == conn_item.dest_port and \
                        idx_out == idx_in:
                        num_existing_connections_in_direction += 1

    if num_existing_connections_in_direction >= num_potential_connections:
        return "disconnect_all", app_constants.PORT_DISCONNECT_DRAG_COLOR
    else:
        return "connect_all", app_constants.PORT_DRAG_COLOR