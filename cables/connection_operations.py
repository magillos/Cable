"""Unified-sink connection operations extracted from JackConnectionManager.

These functions operate on the graph scene's unified (grouped) nodes:
disconnecting all their port connections, and reconnecting them to their
unified sink. They are kept as pure functions over explicit collaborators
so they can be characterized without a live JACK/graph environment.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def disconnect_all_unified(graph_scene: Any, jack_handler: Any) -> None:
    """Break every output connection belonging to unified (grouped) nodes.

    Iterates each unified node's output ports and calls
    ``jack_handler.break_connection`` for each connection item, swallowing
    per-connection errors so one failure does not abort the rest.
    """
    if not graph_scene:
        return
    unified_nodes = graph_scene.get_unified_nodes()

    for node in unified_nodes:
        for port_item in list(node.output_ports.values()):
            for conn_item in list(port_item.connections):
                if conn_item and conn_item.source_port and conn_item.dest_port:
                    try:
                        jack_handler.break_connection(
                            conn_item.source_port.port_name,
                            conn_item.dest_port.port_name,
                        )
                    except Exception as e:
                        logger.error(
                            f"Error breaking output connection for "
                            f"{port_item.port_name} of {node.client_name}: {e}"
                        )


def reconnect_all_unified(
    graph_scene: Any,
    jack_handler: Any,
    unified_sink_manager: Any,
    all_ports: Any,
) -> None:
    """Reconnect every unified node's ports to its unified sink."""
    if not graph_scene:
        return
    unified_nodes = graph_scene.get_unified_nodes()

    for node in unified_nodes:
        unified_sink_manager.connect_ports_to_unified_sink(
            node, jack_handler, all_ports
        )
