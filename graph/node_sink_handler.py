"""
Handler for PipeWire sink operations (default sink, channel map, recreation, PW node ID).
Extracted from NodeItem to separate subprocess/config logic from the visual item.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING, Any, Optional

from cable_core import config_keys as keys

if TYPE_CHECKING:
    from .node_item import NodeItem
    from cable_core.pipewire import PipewireManager

logger = logging.getLogger(__name__)


class NodeSinkHandler:
    """Handles PipeWire sink operations for a NodeItem.

    All subprocess calls (pw-dump, wpctl, pactl) are routed through
    :class:`~cable_core.pipewire.PipewireManager` for consistent Flatpak
    handling. Config reads/writes are encapsulated here.
    """

    def __init__(self, node_item: NodeItem, pipewire_manager: Any = None) -> None:
        """
        Args:
            node_item: The NodeItem instance this handler is associated with.
            pipewire_manager: Optional PipewireManager for subprocess calls.
        """
        self.node_item = node_item
        self._pw_manager = pipewire_manager

    # ── PipewireManager lazy accessor ───────────────────────────────

    def _get_pw_manager(self) -> Any:
        """Return the stored PipewireManager or create one on demand."""
        if self._pw_manager is not None:
            return self._pw_manager
        # Fallback: create a PipewireManager from the scene's config manager
        from cable_core.pipewire import PipewireManager
        scene = self.node_item.scene()
        cm = getattr(scene, "connection_manager", None) if scene else None
        config_mgr = getattr(cm, "config_manager", None) if cm else None
        flatpak_env = os.path.exists("/.flatpak-info")
        self._pw_manager = PipewireManager(flatpak_env, config_mgr)
        return self._pw_manager

    # ── ConfigManager helper ─────────────────────────────────────────

    def _get_config_manager(self) -> Any:
        """Get ConfigManager from the scene's connection_manager."""
        scene = self.node_item.scene()
        if not scene:
            return None
        cm = getattr(scene, "connection_manager", None)
        return getattr(cm, "config_manager", None) if cm else None

    # ── Sink base name ───────────────────────────────────────────────

    def get_sink_base_name(self) -> str:
        """Get the base sink name (without JACK suffix) for config lookups."""
        from cables.unified_sink_manager import _strip_sink_suffix

        return _strip_sink_suffix(self.node_item.client_name)

    # ── PipeWire node ID ─────────────────────────────────────────────

    def get_pw_node_id(self) -> Optional[int]:
        """Resolve the PipeWire node ID for this virtual sink via pw-dump."""
        client_name = self.node_item.client_name

        # Extract PipeWire node ID from JACK client name suffix
        m = re.search(r"-(\d+)$", client_name)
        target_node_id = int(m.group(1)) if m else None

        sink_base_name = self.get_sink_base_name()

        pw = self._get_pw_manager()
        data = pw.get_pw_dump()
        if not data:
            return None

        matching_nodes = []

        for node in data:
            if node.get("type") != "PipeWire:Interface:Node":
                continue

            node_id = int(node["id"])
            props = node.get("info", {}).get("props", {})

            # If we have a target node ID from suffix, use it to exactly match the node
            if target_node_id is not None and node_id == target_node_id:
                return node_id

            # Original fallback exact match
            if props.get("node.description") == client_name:
                return node_id

            # Match by base sink name
            if props.get("node.name") == sink_base_name:
                serial = int(props.get("object.serial", 0))
                matching_nodes.append((serial, node_id))

        if target_node_id is None and matching_nodes:
            # No suffix -> we want the primary node. PipeWire assigns the lowest serial
            # to the first-created node. Pick the node with the lowest serial.
            matching_nodes.sort(key=lambda x: x[0])
            return matching_nodes[0][1]

        return None

    # ── Default sink ─────────────────────────────────────────────────

    def is_default_sink(self) -> bool:
        """Check if this virtual sink is currently the default audio sink."""
        node_id = self.get_pw_node_id()
        if node_id is None:
            return False

        pw = self._get_pw_manager()
        output = pw.inspect_default_sink()
        if output is None:
            return False

        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("id "):
                current_id = stripped.split(",")[0].split()[-1].strip()
                return str(node_id) == current_id
        return False

    def toggle_default_sink(self, checked: bool) -> None:
        """Set or clear this virtual sink as the default audio sink."""
        client_name = self.node_item.client_name
        node_id = self.get_pw_node_id()
        if node_id is None:
            logger.error(
                f"Cannot toggle default: failed to resolve PipeWire ID for '{client_name}'"
            )
            return

        pw = self._get_pw_manager()

        try:
            if checked:
                pw.set_default_node(node_id)
                logger.info(f"Set default sink to '{client_name}' (ID {node_id})")
            else:
                pw.clear_default_node()
                logger.info(f"Cleared default audio sink (was '{client_name}')")
        except Exception as e:
            logger.error(f"Error toggling default sink for '{client_name}': {e}")

    # ── Channel map detection ────────────────────────────────────────

    def detect_channel_map(self, sink_name: str) -> str:
        """Detect the channel map of a running sink via pactl."""
        pw = self._get_pw_manager()
        return pw.detect_channel_map(sink_name)

    # ── Recreate-at-autostart ─────────────────────────────────────────

    def is_recreate_at_autostart(self) -> bool:
        """Check if this virtual sink is marked for recreation at auto-start."""
        config = self._get_config_manager()
        if not config:
            return False
        try:
            data = json.loads(
                config.get_str(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, "{}") or "{}"
            )
            return self.node_item.client_name in data
        except (json.JSONDecodeError, Exception):
            return False

    def toggle_recreate_at_autostart(self, checked: bool) -> None:
        """Toggle the 'recreate at auto-start' setting for this virtual sink."""
        config = self._get_config_manager()
        if not config:
            return
        try:
            data = json.loads(
                config.get_str(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, "{}") or "{}"
            )
            if checked:
                sink_name = self.get_sink_base_name()
                channel_map = self.detect_channel_map(sink_name)
                data[self.node_item.client_name] = {
                    "sink_name": sink_name,
                    "channel_map": channel_map,
                }
            else:
                data.pop(self.node_item.client_name, None)
            config.set_str(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, json.dumps(data))
            self.node_item.update()
        except Exception as e:
            logger.error(
                f"Error toggling recreate-at-autostart for {self.node_item.client_name}: {e}"
            )