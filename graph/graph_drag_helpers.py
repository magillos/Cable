"""
Helper functions for determining drag actions and visual feedback during port/bulk-area interactions.

All public ``determine_*_to_*_action`` functions share the same pipeline:
  1. Validate source & target (null guards).
  2. Reject self‑connections (same split node).
  3. Reject same‑direction dragging.
  4. Resolve the effective output/input port lists.
  5. Count existing connections & return ``(action, color)``.
"""
from __future__ import annotations

import typing

from PyQt6.QtGui import QColor

from . import constants
from .port_item import PortItem
from .bulk_area_item import BulkAreaItem
from .node_item import NodeItem
from cables.utils.sort_utils import natural_sort_key_for_port_item as _port_sort_key

if typing.TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Port sorting helper
# ---------------------------------------------------------------------------

def get_ports_in_visual_order(port_dict: dict[str, PortItem]) -> list[PortItem]:
    """Return ports sorted in visual layout order: audio first (natural sort), then MIDI."""
    audio = [p for p in port_dict.values() if not p.port_obj.is_midi]
    midi = [p for p in port_dict.values() if p.port_obj.is_midi]
    return sorted(audio, key=_port_sort_key) + sorted(midi, key=_port_sort_key)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_self_connection(a: typing.Any, b: typing.Any) -> bool:
    """Return True if *a* and *b* belong to the same split node (disallow self-connection)."""
    parent_a = getattr(a, "parent_node", None)
    parent_b = getattr(b, "parent_node", None)
    if parent_a is not None and parent_a == parent_b:
        if parent_a.is_split_origin or parent_a.is_split_part:
            return True
    return False


def _is_connected(out_port: PortItem, in_port: PortItem) -> bool:
    """Check if *out_port* is already connected to *in_port*."""
    return any(
        conn.source_port == out_port and conn.dest_port == in_port
        for conn in out_port.connections
    )


def _count_existing_connections(
    sources: list[PortItem], targets: list[PortItem]
) -> tuple[int, int]:
    """Count how many of the *source→target* pairs are already connected.

    Returns ``(total_pairs, already_connected_count)``.
    """
    total = 0
    connected = 0
    for s in sources:
        for t in targets:
            total += 1
            out_p, in_p = (s, t) if not s.is_input else (t, s)
            if _is_connected(out_p, in_p):
                connected += 1
    return total, connected


# ---------------------------------------------------------------------------
# Port-list resolution helpers
# ---------------------------------------------------------------------------

def _resolve_bulk_or_port_ports(
    source_is_bulk: bool, target_is_bulk: bool,
    source: PortItem | BulkAreaItem,
    target: PortItem | BulkAreaItem,
) -> tuple[list[PortItem] | None, list[PortItem] | None]:
    """Resolve the effective output/input port lists for any source→target pair.

    Returns ``(out_ports, in_ports)`` or ``(None, None)`` if direction
    cannot be determined.
    """
    # Single port ↔ single port
    if not source_is_bulk and not target_is_bulk:
        s, t = typing.cast(PortItem, source), typing.cast(PortItem, target)
        if s.is_input == t.is_input:
            return None, None
        out_ports = [s] if not s.is_input else [t]
        in_ports = [t] if not s.is_input else [s]
        return out_ports, in_ports

    # Bulk ↔ single (either order)
    bulk, single = (source, target) if source_is_bulk else (target, source)
    bulk_item = typing.cast(BulkAreaItem, bulk)
    single_port = typing.cast(PortItem, single)

    if not source_is_bulk and target_is_bulk:
        # Single → bulk: single is source if output, bulk is target if input
        if not bulk_item.is_input:
            # bulk is output, single should be input
            if not single_port.is_input:
                return None, None
            return [single_port], list(bulk_item.paired_ports)
        else:
            # bulk is input, single should be output
            if single_port.is_input:
                return None, None
            return list(bulk_item.paired_ports), [single_port]
    else:
        # Bulk → single: bulk is input → bulk ports are targets
        if not bulk_item.is_input:
            if single_port.is_input:
                return list(bulk_item.paired_ports), [single_port]
            return None, None
        else:
            if not single_port.is_input:
                return [single_port], list(bulk_item.paired_ports)
            return None, None

    return None, None


def _resolve_bulk_to_bulk_ports(
    source_bulk: BulkAreaItem, target_bulk: BulkAreaItem,
) -> tuple[list[PortItem], list[PortItem]]:
    """Resolve output/input port lists for a bulk→bulk drag (index-paired)."""
    if not source_bulk.is_input:
        return list(source_bulk.paired_ports), list(target_bulk.paired_ports)
    else:
        return list(target_bulk.paired_ports), list(source_bulk.paired_ports)


# ---------------------------------------------------------------------------
# Core action pipeline
# ---------------------------------------------------------------------------

def _action_and_color(
    all_connected: bool, has_any: bool, app_constants: typing.Any,
) -> tuple[str | None, QColor]:
    """Return the action string and colour based on connection state."""
    if not has_any:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR
    if all_connected:
        return "disconnect_all", app_constants.PORT_DISCONNECT_DRAG_COLOR
    return "connect_all", app_constants.PORT_DRAG_COLOR


def _exists(a: typing.Any) -> bool:
    """Guard predicate — True if *a* is not ``None`` and has a ``parent_node``."""
    return a is not None and getattr(a, "parent_node", None) is not None


def _drag_pair_rejection_color(
    source: typing.Any, target: typing.Any, app_constants: typing.Any,
) -> QColor | None:
    """Return the default drag color if *source*/*target* is an invalid pair, else None.

    Shared prelude of every ``determine_*_action`` entry point. A pair is
    rejected when either side is missing, when both items belong to the
    same split node (self-connection), or when both ports face the same
    direction (input↔input or output↔output).
    """
    if not _exists(source) or not _exists(target):
        return app_constants.DEFAULT_DRAG_LINE_COLOR
    if _check_self_connection(source, target):
        return app_constants.DEFAULT_DRAG_LINE_COLOR
    if source.is_input == target.is_input:
        return app_constants.DEFAULT_DRAG_LINE_COLOR
    return None


def _count_bulk_to_bulk_connections(
    out_ports: list[PortItem], in_ports: list[PortItem],
) -> tuple[int, int]:
    """Count index-paired connections for bulk→bulk drag.

    Returns ``(num_potential, num_existing)``.
    """
    num_potential = min(len(out_ports), len(in_ports))
    num_existing = 0
    for idx in range(num_potential):
        out_p = out_ports[idx]
        in_p = in_ports[idx]
        if _is_connected(out_p, in_p):
            num_existing += 1
    return num_potential, num_existing


# ---------------------------------------------------------------------------
# Public API — each wraps the shared pipeline
# ---------------------------------------------------------------------------

def determine_port_to_port_action(
    source_port: PortItem, target_port: PortItem, app_constants: typing.Any,
) -> tuple[str | None, QColor]:
    """Determines action (connect/disconnect) and colour for port→port drag."""
    rejection = _drag_pair_rejection_color(source_port, target_port, app_constants)
    if rejection is not None:
        return None, rejection

    out_ports, in_ports = _resolve_bulk_or_port_ports(
        False, False, source_port, target_port,
    )
    if not out_ports or not in_ports:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    if _is_connected(out_ports[0], in_ports[0]):
        return "disconnect", app_constants.PORT_DISCONNECT_DRAG_COLOR
    else:
        return "connect", app_constants.PORT_DRAG_COLOR


def determine_port_to_bulk_action(
    source_port: PortItem, target_bulk: BulkAreaItem, app_constants: typing.Any,
) -> tuple[str | None, QColor]:
    """Determines action and colour for port→bulk drag.

    Connects the single source port to **all** ports in the bulk's
    ``paired_ports``.
    """
    rejection = _drag_pair_rejection_color(source_port, target_bulk, app_constants)
    if rejection is not None:
        return None, rejection

    out_ports, in_ports = _resolve_bulk_or_port_ports(
        False, True, source_port, target_bulk,
    )
    if not out_ports or not in_ports:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    total, connected = _count_existing_connections(out_ports, in_ports)
    if total == 0:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    if connected == total:
        return "disconnect", app_constants.PORT_DISCONNECT_DRAG_COLOR
    return "connect", app_constants.PORT_DRAG_COLOR


def determine_bulk_to_port_action(
    source_bulk: BulkAreaItem, target_port: PortItem, app_constants: typing.Any,
) -> tuple[str | None, QColor]:
    """Determines action and colour for bulk→port drag.

    Connects **all** ports in the bulk's ``paired_ports`` to the single
    target port.
    """
    rejection = _drag_pair_rejection_color(source_bulk, target_port, app_constants)
    if rejection is not None:
        return None, rejection

    out_ports, in_ports = _resolve_bulk_or_port_ports(
        True, False,
        source_bulk, target_port,
    )
    if not out_ports or not in_ports:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    total, connected = _count_existing_connections(out_ports, in_ports)
    if total == 0:
        return None, app_constants.DEFAULT_DRAG_LINE_COLOR

    if connected == total:
        return "disconnect", app_constants.PORT_DISCONNECT_DRAG_COLOR
    return "connect", app_constants.PORT_DRAG_COLOR


def determine_bulk_to_bulk_action(
    source_bulk: BulkAreaItem, target_bulk: BulkAreaItem, app_constants: typing.Any,
) -> tuple[str | None, QColor]:
    """Determines action and colour for bulk→bulk drag (per-pair mapping).

    Uses each bulk area's ``paired_ports`` instead of **all** node ports.
    Sequential mapping: pairs source paired ports with target paired ports
    by index.
    """
    rejection = _drag_pair_rejection_color(source_bulk, target_bulk, app_constants)
    if rejection is not None:
        return None, rejection

    out_ports, in_ports = _resolve_bulk_to_bulk_ports(source_bulk, target_bulk)
    num_potential, num_existing = _count_bulk_to_bulk_connections(out_ports, in_ports)

    if num_potential == 0:
        return "connect_all", app_constants.PORT_DRAG_COLOR

    return _action_and_color(
        num_existing >= num_potential, True, app_constants,
    )