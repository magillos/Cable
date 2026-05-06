"""
PresetOperations — Pure business logic for preset file I/O and state comparison.

This module contains no Qt imports, making it testable in isolation.
PresetHandler delegates data operations here and handles UI concerns itself.
"""

import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple

import logging

logger = logging.getLogger(__name__)


class PresetOperations:
    """Pure data operations for preset save/load/delete and state comparison.

    All methods are either static or classmethods and operate on data
    passed in explicitly — no references to Qt widgets or managers.
    """

    # ------------------------------------------------------------------ #
    # Layout data collection
    # ------------------------------------------------------------------ #

    @staticmethod
    def collect_layout_data(
        scene: Any,
        view: Any,
        node_visibility_manager: Any,
        config_manager: Any,
    ) -> Dict[str, Any]:
        """Collect current graph layout state into a serialisable dict.

        Args:
            scene: The graph scene (or None).
            view: The graph view (or None).
            node_visibility_manager: The visibility manager (or None).
            config_manager: App config manager (for split_audio_midi).

        Returns:
            A dict with keys ``node_states``, ``graph_zoom_level``,
            ``node_visibility``, ``split_audio_midi``, or an empty dict
            if nothing is available.
        """
        layout_data: Dict[str, Any] = {}

        if scene is not None:
            get_states = getattr(scene, "get_node_states", None)
            if get_states is not None:
                layout_data["node_states"] = get_states()

        if view is not None:
            get_zoom = getattr(view, "get_zoom_level", None)
            if get_zoom is not None:
                layout_data["graph_zoom_level"] = get_zoom()

        if node_visibility_manager is not None:
            layout_data["node_visibility"] = {
                "audio_input": dict(
                    getattr(node_visibility_manager, "audio_input_visibility", {})
                ),
                "audio_output": dict(
                    getattr(node_visibility_manager, "audio_output_visibility", {})
                ),
                "midi_input": dict(
                    getattr(node_visibility_manager, "midi_input_visibility", {})
                ),
                "midi_output": dict(
                    getattr(node_visibility_manager, "midi_output_visibility", {})
                ),
            }

        if config_manager is not None:
            from cable_core import config_keys as keys

            layout_data["split_audio_midi"] = config_manager.get_bool(
                keys.GRAPH_SPLIT_AUDIO_MIDI_CLIENTS, False
            )

        return layout_data

    # ------------------------------------------------------------------ #
    # File I/O — .snap (aj-snapshot) and layout JSON
    # ------------------------------------------------------------------ #

    @staticmethod
    def save_snap_file(preset_name: str, presets_dir: str) -> bool:
        """Save connections via aj-snapshot subprocess.

        Args:
            preset_name: Name of the preset (without extension).
            presets_dir: Directory where .snap files are stored.

        Returns:
            True if the subprocess succeeded, False otherwise.
        """
        preset_file = os.path.join(presets_dir, f"{preset_name}.snap")
        try:
            command = ["aj-snapshot", "-f", preset_file]
            subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
            logger.debug(f"aj-snapshot saved to {preset_file}")
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"aj-snapshot timed out for {preset_name}")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"aj-snapshot failed for {preset_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving .snap for {preset_name}: {e}")
            return False

    @staticmethod
    def save_layout_file(
        preset_name: str,
        layout_presets_dir: str,
        layout_data: Dict[str, Any],
    ) -> bool:
        """Persist layout data (node positions, visibility, zoom) to JSON.

        Args:
            preset_name: Name of the preset (without extension).
            layout_presets_dir: Directory for layout JSON files.
            layout_data: The data dict from :meth:`collect_layout_data`.

        Returns:
            True on success, False on failure.
        """
        if not layout_data:
            return False
        try:
            os.makedirs(layout_presets_dir, exist_ok=True)
            layout_file = os.path.join(layout_presets_dir, f"{preset_name}.json")
            with open(layout_file, "w") as f:
                json.dump(layout_data, f, indent=4, default=PresetOperations._json_serializer)
            logger.debug(f"Layout data saved to {layout_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save layout file for {preset_name}: {e}")
            return False

    @staticmethod
    def load_layout_file(preset_name: str, layout_presets_dir: str) -> Optional[Dict[str, Any]]:
        """Load layout data from a preset's JSON file.

        Returns:
            The deserialised dict, or None if the file doesn't exist or is invalid.
        """
        layout_file = os.path.join(layout_presets_dir, f"{preset_name}.json")
        if not os.path.exists(layout_file):
            return None
        try:
            with open(layout_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load layout file {layout_file}: {e}")
            return None

    @staticmethod
    def delete_snap_file(preset_name: str, presets_dir: str) -> bool:
        """Delete a .snap preset file."""
        preset_file = os.path.join(presets_dir, f"{preset_name}.snap")
        try:
            if os.path.exists(preset_file):
                os.remove(preset_file)
                logger.debug(f"Deleted .snap file: {preset_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete .snap file {preset_file}: {e}")
            return False

    @staticmethod
    def delete_layout_file(preset_name: str, layout_presets_dir: str) -> bool:
        """Delete a layout JSON preset file."""
        layout_file = os.path.join(layout_presets_dir, f"{preset_name}.json")
        try:
            if os.path.exists(layout_file):
                os.remove(layout_file)
                logger.debug(f"Deleted layout file: {layout_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete layout file {layout_file}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # State comparison helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def connections_have_changed(
        current_connections: List[Dict[str, str]],
        original_connections: Optional[List[Dict[str, str]]],
    ) -> bool:
        """Compare two connection lists (order-independent)."""
        if original_connections is None:
            return False

        def _to_set(conns: List[Dict[str, str]]) -> Set[Tuple[str, str]]:
            result: Set[Tuple[str, str]] = set()
            for c in conns:
                out_ = c.get("output", "")
                in_ = c.get("input", "")
                if out_ and in_:
                    result.add((out_, in_))
            return result

        return _to_set(current_connections) != _to_set(original_connections)

    @staticmethod
    def layout_has_changed(
        current_layout_data: Optional[Dict[str, Any]],
        original_layout_data: Optional[Dict[str, Any]],
    ) -> bool:
        """Compare two layout data dicts."""
        if not current_layout_data or not original_layout_data:
            return False
        # Compare node_states
        if current_layout_data.get("node_states") != original_layout_data.get("node_states"):
            return True
        # Compare zoom level
        if current_layout_data.get("graph_zoom_level") != original_layout_data.get("graph_zoom_level"):
            return True
        # Compare visibility
        if current_layout_data.get("node_visibility") != original_layout_data.get("node_visibility"):
            return True
        return False

    # ------------------------------------------------------------------ #
    # Serialisation helper
    # ------------------------------------------------------------------ #

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        """Serialize non-JSON-safe objects (e.g. QPointF) for json.dump."""
        if callable(getattr(obj, "x", None)) and callable(getattr(obj, "y", None)):
            return {"x": obj.x(), "y": obj.y()}
        return str(obj)
