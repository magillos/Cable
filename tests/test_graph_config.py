"""Tests for graph.config_utils.GraphConfigManager."""

import sys
import json
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PyQt6.QtCore import QPointF

from graph.config_utils import GraphConfigManager


@pytest.fixture
def graph_config(tmp_path):
    """Create a GraphConfigManager using a temp directory."""
    mgr = GraphConfigManager.__new__(GraphConfigManager)
    mgr.config_dir = tmp_path
    mgr.node_positions_file = tmp_path / "node_positions.json"
    mgr.graph_settings_file = tmp_path / "graph_settings.json"
    mgr._dirty = False
    mgr._cached_data = {}
    mgr._graph_settings_dirty = False
    mgr._cached_graph_settings = {}
    return mgr


def test_initial_state(graph_config):
    """load_node_states returns empty dict and None zoom level on fresh instance."""
    config, zoom = graph_config.load_node_states()
    assert config == {}
    assert zoom is None


def test_dirty_flag_starts_false(graph_config):
    """Dirty flag starts as False."""
    assert graph_config._dirty is False


def test_flush_no_changes_no_files(graph_config, tmp_path):
    """Flushing with no changes does not create any files."""
    graph_config.flush()
    assert not graph_config.node_positions_file.exists()
    assert not graph_config.graph_settings_file.exists()


def test_save_load_keep_untangled_true(graph_config):
    """save_keep_untangled(True) roundtrips via load_keep_untangled."""
    graph_config.save_keep_untangled(True)
    assert graph_config.load_keep_untangled() is True


def test_save_load_keep_untangled_false(graph_config):
    """save_keep_untangled(False) roundtrips via load_keep_untangled."""
    graph_config.save_keep_untangled(False)
    assert graph_config.load_keep_untangled() is False


def test_keep_untangled_default(graph_config):
    """load_keep_untangled returns False when nothing has been saved."""
    assert graph_config.load_keep_untangled() is False


def test_graph_settings_persistence(graph_config):
    """Graph settings survive flush and reload from disk."""
    graph_config.save_keep_untangled(True)
    graph_config.flush()

    assert graph_config.graph_settings_file.exists()

    # Simulate reload by reading JSON directly
    with open(graph_config.graph_settings_file) as f:
        data = json.load(f)
    assert data["keep_untangled"] is True


def test_save_node_states_as_default_roundtrip(graph_config):
    """save_node_states_as_default writes correct JSON and load_node_states reads it back."""
    node_states = {
        "MyClient": {
            "pos": QPointF(100.0, 200.0),
            "is_split": False,
            GraphConfigManager.IS_FOLDED_KEY: True,
        },
        "AnotherClient": {
            "pos": QPointF(-50.5, 300.25),
            "is_split": True,
            GraphConfigManager.IS_FOLDED_KEY: False,
        },
    }

    graph_config.save_node_states_as_default(node_states, graph_zoom_level=1.5)
    graph_config.flush()

    assert graph_config.node_positions_file.exists()

    # Verify raw JSON content
    with open(graph_config.node_positions_file) as f:
        raw = json.load(f)
    assert raw["MyClient"]["pos"] == {"x": 100.0, "y": 200.0}
    assert raw["MyClient"]["is_split"] is False
    assert raw["AnotherClient"]["pos"] == {"x": -50.5, "y": 300.25}
    assert raw["AnotherClient"]["is_split"] is True
    assert raw[GraphConfigManager.GRAPH_ZOOM_LEVEL_KEY] == 1.5

    # Verify load_node_states reconstructs QPointF positions
    loaded_config, loaded_zoom = graph_config.load_node_states()
    assert loaded_zoom == 1.5

    my_cfg = loaded_config["MyClient"]
    assert isinstance(my_cfg["pos"], QPointF)
    assert my_cfg["pos"].x() == 100.0
    assert my_cfg["pos"].y() == 200.0
    assert my_cfg.get(GraphConfigManager.IS_FOLDED_KEY) is True

    another_cfg = loaded_config["AnotherClient"]
    assert isinstance(another_cfg["pos"], QPointF)
    assert another_cfg["pos"].x() == -50.5
    assert another_cfg["pos"].y() == 300.25
    assert another_cfg["is_split"] is True


def test_zoom_level_roundtrip(graph_config):
    """Zoom level saved via save_node_states_as_default is returned by load_node_states."""
    node_states = {
        "Node1": {"pos": QPointF(0, 0), "is_split": False},
    }
    graph_config.save_node_states_as_default(node_states, graph_zoom_level=2.75)
    graph_config.flush()

    loaded_config, loaded_zoom = graph_config.load_node_states()
    assert loaded_zoom == 2.75


def test_constants_start_with_double_colon():
    """All key constants are strings starting with '::'."""
    key_attrs = [
        GraphConfigManager.IS_SPLIT_KEY,
        GraphConfigManager.SPLIT_INPUT_POS_KEY,
        GraphConfigManager.SPLIT_OUTPUT_POS_KEY,
        GraphConfigManager.GRAPH_ZOOM_LEVEL_KEY,
        GraphConfigManager.CURRENT_UNTANGLE_SETTING_KEY,
        GraphConfigManager.IS_FOLDED_KEY,
        GraphConfigManager.INPUT_PART_FOLDED_KEY,
        GraphConfigManager.OUTPUT_PART_FOLDED_KEY,
        GraphConfigManager.MANUAL_SPLIT_KEY,
        GraphConfigManager.IS_INPUT_UNIFIED_KEY,
        GraphConfigManager.IS_OUTPUT_UNIFIED_KEY,
        GraphConfigManager.UNIFIED_INPUT_SINK_NAME_KEY,
        GraphConfigManager.UNIFIED_OUTPUT_SINK_NAME_KEY,
        GraphConfigManager.UNIFIED_INPUT_MODULE_ID_KEY,
        GraphConfigManager.UNIFIED_OUTPUT_MODULE_ID_KEY,
    ]
    for key in key_attrs:
        assert isinstance(key, str), f"Expected str, got {type(key)}"
        assert key.startswith("::"), f"Key {key!r} does not start with '::'"
