"""
Selection utilities extracted from JackConnectionManager.

This module provides pure functions for analyzing tree widget selections,
computing sequential port pairs for group-to-port connections, and
managing connection button state — all moved out of the 1,852-line
JackConnectionManager god class.
"""

import logging
from typing import Optional, List, Tuple, Dict, Any, Set, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt6.QtGui import QAction

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QPushButton

logger = logging.getLogger(__name__)


# ── Selection analysis ──────────────────────────────────────────────────


def get_selected_item_info(
    tree_widget: QTreeWidget,
) -> Tuple[Optional[str], Optional[bool]]:
    """Get info about the current item in a tree widget.

    Returns:
        A tuple of (text_or_port_name, is_group) or (None, None) if
        no item is selected.
    """
    if not getattr(tree_widget, "currentItem", None):
        return None, None
    item = tree_widget.currentItem()
    if not item:
        return None, None

    is_group = item.childCount() > 0
    if is_group:
        return item.text(0), True
    else:
        port_name = item.data(0, Qt.ItemDataRole.UserRole)
        return port_name, False


def restore_selection(
    tree_widget: QTreeWidget,
    selection_info: Tuple[Optional[str], Optional[bool]],
) -> None:
    """Restore selection in a tree widget from saved info.

    Args:
        tree_widget: The tree widget to restore selection in.
        selection_info: (name_or_text, is_group) tuple from
            get_selected_item_info, or None.
    """
    if not selection_info or not getattr(tree_widget, "port_items", None):
        return

    name_or_text, is_group = selection_info
    if name_or_text is None:
        return

    item_to_select = None
    if is_group:
        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            if group_item.text(0) == name_or_text:
                item_to_select = group_item
                break
    else:
        item_to_select = tree_widget.port_items.get(name_or_text)

    if item_to_select and not item_to_select.isHidden():
        tree_widget.setCurrentItem(item_to_select)


def get_ports_from_selected_items(tree_widget: QTreeWidget) -> List[str]:
    """Extract port names from selected items in a tree widget.

    Args:
        tree_widget: The tree widget to extract ports from.

    Returns:
        List of port names.
    """
    port_names: Set[str] = set()
    for item in tree_widget.selectedItems():
        if not item:
            continue

        if item.childCount() == 0:
            # Leaf item (port)
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            if port_name:
                port_names.add(port_name)
        else:
            # Parent item (client/group) - get all child ports
            for i in range(item.childCount()):
                child = item.child(i)
                port_name = child.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    port_names.add(port_name)
    return list(port_names)


def analyze_tree_selection(tree_widget: QTreeWidget) -> Dict[str, Any]:
    """Analyze the current selection in a tree widget.

    Returns a dict with:
        - port_names: flat list of selected port names
        - is_single_port: True if exactly one leaf port is selected
        - single_port_name: the port name if is_single_port, else None
        - is_group: True if exactly one group (parent item) is selected
    """
    selected_items = tree_widget.selectedItems()
    port_names: List[str] = []
    leaf_items = [item for item in selected_items if item.childCount() == 0]
    group_items = [item for item in selected_items if item.childCount() > 0]

    for item in selected_items:
        if not item:
            continue
        if item.childCount() == 0:
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            if port_name:
                port_names.append(port_name)
        else:
            for i in range(item.childCount()):
                child = item.child(i)
                port_name = child.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    port_names.append(port_name)

    is_single_port = len(leaf_items) == 1 and len(group_items) == 0
    is_group = len(group_items) == 1 and len(leaf_items) == 0

    return {
        "port_names": port_names,
        "is_single_port": is_single_port,
        "single_port_name": port_names[0] if is_single_port else None,
        "is_group": is_group,
    }


# ── Sequential pairing ──────────────────────────────────────────────────


def compute_sequential_pairs(
    output_info: Dict[str, Any],
    input_info: Dict[str, Any],
    output_tree: QTreeWidget,
    input_tree: QTreeWidget,
) -> Optional[List[Tuple[str, str]]]:
    """Compute sequential port pairs for group→port or port→group connections.

    Mirrors the drag-and-drop logic in PortTreeWidget.dropEvent.

    Returns:
        A list of (output_port, input_port) tuples, or None to signal
        that no sequential mapping applies (fall through to standard logic).
    """
    out_is_single = output_info["is_single_port"]
    out_is_group = output_info["is_group"]
    in_is_single = input_info["is_single_port"]
    in_is_group = input_info["is_group"]

    if out_is_group and in_is_single and len(output_info["port_names"]) > 1:
        # Group → single port: discover the input port's siblings and pair sequentially
        input_port_name = input_info["single_port_name"]
        if input_port_name and getattr(input_tree, "_get_port_group_siblings", None) is not None:
            siblings = input_tree._get_port_group_siblings(input_port_name)
            if input_port_name in siblings:
                target_idx = siblings.index(input_port_name)
                pairs: List[Tuple[str, str]] = []
                for i, out_p in enumerate(output_info["port_names"]):
                    t_idx = target_idx + i
                    if t_idx >= len(siblings):
                        break
                    pairs.append((out_p, siblings[t_idx]))
                if pairs:
                    return pairs

    elif out_is_single and in_is_group and len(input_info["port_names"]) > 1:
        # Single port → group: discover the output port's siblings and pair sequentially
        output_port_name = output_info["single_port_name"]
        if output_port_name and getattr(output_tree, "_get_port_group_siblings", None) is not None:
            siblings = output_tree._get_port_group_siblings(output_port_name)
            if output_port_name in siblings:
                source_idx = siblings.index(output_port_name)
                pairs: List[Tuple[str, str]] = []
                for i, in_p in enumerate(input_info["port_names"]):
                    s_idx = source_idx + i
                    if s_idx >= len(siblings):
                        break
                    pairs.append((siblings[s_idx], in_p))
                if pairs:
                    return pairs

    # No sequential mapping applies
    return None


# ── Disconnect groups ───────────────────────────────────────────────────


def disconnect_selected_groups(
    jack_handler: Any, group_items: List[QTreeWidgetItem]
) -> None:
    """Disconnect all ports belonging to a list of group items.

    Args:
        jack_handler: The JackConnectionHandler instance.
        group_items: List of QTreeWidgetItem group items.
    """
    ports_to_disconnect: Set[str] = set()

    for group_item in group_items:
        if group_item and group_item.childCount() > 0:
            for i in range(group_item.childCount()):
                port_item = group_item.child(i)
                port_name = port_item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    ports_to_disconnect.add(port_name)

    if not ports_to_disconnect:
        return

    for port_name in ports_to_disconnect:
        jack_handler.disconnect_node(port_name)


# ── Button state management ─────────────────────────────────────────────


def update_port_connection_buttons(
    connection_manager: Any,
    input_tree: QTreeWidget,
    output_tree: QTreeWidget,
    connect_button: "QPushButton",
    disconnect_button: "QPushButton",
    connect_action: Optional[QAction] = None,
    disconnect_action: Optional[QAction] = None,
) -> None:
    """Update connect/disconnect button state based on tree selections.

    Args:
        connection_manager: The JackConnectionManager instance (for
            jack_handler access).
        input_tree: Input port tree widget.
        output_tree: Output port tree widget.
        connect_button: The connect QPushButton.
        disconnect_button: The disconnect QPushButton.
        connect_action: Optional QAction for connect (not disabled here).
        disconnect_action: Optional QAction for disconnect (not disabled here).
    """
    selected_input_ports = get_ports_from_selected_items(input_tree)
    selected_output_ports = get_ports_from_selected_items(output_tree)

    ports_selected = bool(selected_input_ports and selected_output_ports)

    can_connect = False
    can_disconnect = False

    if ports_selected:
        possible_connections: Set[Tuple[str, str]] = set()
        for out_p in selected_output_ports:
            for in_p in selected_input_ports:
                possible_connections.add((out_p, in_p))

        is_midi = input_tree in (
            getattr(connection_manager, "midi_input_tree", None),
        ) or output_tree in (getattr(connection_manager, "midi_output_tree", None),)
        existing_connections = connection_manager.jack_handler._get_existing_connections_between(
            selected_output_ports,
            selected_input_ports,
            is_midi=is_midi,
        )

        # Port-to-port / group-to-port / port-to-group: allow Connect if
        # there exists at least one not-yet-existing connection in the
        # selected cross-product.
        #
        # Group-to-group (multiple outputs and multiple inputs) is treated
        # as a single logical connection operation (suffix/sequential pairing),
        # not as a full cross-product.
        is_group_to_group = (
            len(selected_output_ports) > 1 and len(selected_input_ports) > 1
        )

        if is_group_to_group:
            can_connect = len(existing_connections) == 0
            can_disconnect = len(existing_connections) > 0
        else:
            if (
                len(possible_connections) > 0
                and possible_connections != existing_connections
            ):
                can_connect = True
            if len(existing_connections) > 0:
                can_disconnect = True

    connect_button.setEnabled(can_connect)
    disconnect_button.setEnabled(can_disconnect)

    # Do not disable the underlying QActions here.
    # Global shortcuts call QAction.trigger() on these actions; if the
    # action is disabled, trigger() becomes a no-op and shortcuts stop
    # working.


# ── Connection operations (audio) ───────────────────────────────────────


def make_connection_selected(connection_manager: Any) -> None:
    """Make connections based on current tree selection (audio tab)."""
    output_info = analyze_tree_selection(
        getattr(connection_manager, "output_tree", None)
    )
    input_info = analyze_tree_selection(
        getattr(connection_manager, "input_tree", None)
    )

    if not output_info or not input_info:
        return
    if not output_info["port_names"] or not input_info["port_names"]:
        logger.debug(
            "Make Connection: Select at least one input and one output item "
            "(port or group)."
        )
        return

    output_tree = getattr(connection_manager, "output_tree", None)
    input_tree = getattr(connection_manager, "input_tree", None)

    # Try sequential mapping (group→port or port→group) like drag-and-drop
    sequential_pairs = compute_sequential_pairs(
        output_info, input_info, output_tree, input_tree
    )

    jack_handler = connection_manager.jack_handler

    if sequential_pairs is not None:
        logger.debug(
            f"Making connections (button/shortcut, sequential): {sequential_pairs}"
        )
        for out_p, in_p in sequential_pairs:
            jack_handler.make_connection(out_p, in_p)
    else:
        logger.debug(
            f"Making connections (button/shortcut): "
            f"Outputs={output_info['port_names']}, "
            f"Inputs={input_info['port_names']}"
        )
        jack_handler.make_multiple_connections(
            output_info["port_names"], input_info["port_names"]
        )


def break_connection_selected(connection_manager: Any) -> None:
    """Break connections based on current tree selection (audio tab)."""
    selected_inputs = get_ports_from_selected_items(
        getattr(connection_manager, "input_tree", None)
    )
    selected_outputs = get_ports_from_selected_items(
        getattr(connection_manager, "output_tree", None)
    )

    if not selected_inputs or not selected_outputs:
        logger.debug(
            "Break Connection: Select at least one input and one output port."
        )
        return

    logger.debug(
        f"Breaking connections for: Outputs={selected_outputs}, "
        f"Inputs={selected_inputs}"
    )
    jack_handler = connection_manager.jack_handler
    for out_port in selected_outputs:
        for in_port in selected_inputs:
            jack_handler.break_connection(out_port, in_port)


# ── Connection operations (MIDI) ──────────────────────────────────────


def make_midi_connection_selected(connection_manager: Any) -> None:
    """Make connections based on current tree selection (MIDI tab)."""
    output_info = analyze_tree_selection(
        getattr(connection_manager, "midi_output_tree", None)
    )
    input_info = analyze_tree_selection(
        getattr(connection_manager, "midi_input_tree", None)
    )

    if not output_info or not input_info:
        return
    if not output_info["port_names"] or not input_info["port_names"]:
        logger.debug(
            "Make MIDI Connection: Select at least one input and one output "
            "item (port or group)."
        )
        return

    output_tree = getattr(connection_manager, "midi_output_tree", None)
    input_tree = getattr(connection_manager, "midi_input_tree", None)

    # Try sequential mapping (group→port or port→group) like drag-and-drop
    sequential_pairs = compute_sequential_pairs(
        output_info, input_info, output_tree, input_tree
    )

    jack_handler = connection_manager.jack_handler

    if sequential_pairs is not None:
        logger.debug(
            f"Making MIDI connections (button/shortcut, sequential): "
            f"{sequential_pairs}"
        )
        for out_p, in_p in sequential_pairs:
            jack_handler.make_midi_connection(out_p, in_p)
    else:
        logger.debug(
            f"Making MIDI connections (button/shortcut): "
            f"Outputs={output_info['port_names']}, "
            f"Inputs={input_info['port_names']}"
        )
        jack_handler.make_multiple_connections(
            output_info["port_names"], input_info["port_names"]
        )


def break_midi_connection_selected(connection_manager: Any) -> None:
    """Break connections based on current tree selection (MIDI tab)."""
    selected_inputs = get_ports_from_selected_items(
        getattr(connection_manager, "midi_input_tree", None)
    )
    selected_outputs = get_ports_from_selected_items(
        getattr(connection_manager, "midi_output_tree", None)
    )

    if not selected_inputs or not selected_outputs:
        logger.debug(
            "Break MIDI Connection: Select at least one input and one output "
            "MIDI port."
        )
        return

    logger.debug(
        f"Breaking MIDI connections for: Outputs={selected_outputs}, "
        f"Inputs={selected_inputs}"
    )
    jack_handler = connection_manager.jack_handler
    for out_port in selected_outputs:
        for in_port in selected_inputs:
            jack_handler.break_midi_connection(out_port, in_port)