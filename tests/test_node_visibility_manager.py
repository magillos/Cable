"""Tests for NodeVisibilityManager visibility logic."""

import sys
import os
import json
import tempfile
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cables.features.node_visibility_manager import NodeVisibilityManager


@pytest.fixture
def mock_connection_manager():
    """Create a mock connection manager implementing NodeVisibilityManagerInterface."""
    manager = Mock()
    manager.input_tree = Mock()
    manager.output_tree = Mock()
    manager.midi_input_tree = Mock()
    manager.midi_output_tree = Mock()
    manager.midi_matrix_widget = Mock()
    manager._get_graph_scene = Mock(return_value=None)
    manager._get_selected_item_info = Mock(return_value=None)
    manager._restore_selection = Mock()
    manager._refresh_single_port_type = Mock()
    manager.refresh_visualizations = Mock()
    return manager


@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager."""
    config = Mock()
    config.get_bool = Mock(return_value=False)
    config.set_bool = Mock()
    return config


@pytest.fixture
def temp_config_file():
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        config_path = f.name
    yield config_path
    # Cleanup
    if os.path.exists(config_path):
        os.unlink(config_path)


@pytest.fixture
def visibility_manager(mock_connection_manager, mock_config_manager, temp_config_file):
    """Create a NodeVisibilityManager with mocked dependencies."""
    manager = NodeVisibilityManager(mock_connection_manager, mock_config_manager)
    manager.config_path = temp_config_file
    return manager


# ── Initialization ────────────────────────────────────────────────────

def test_initialization_creates_empty_visibility_dicts(visibility_manager):
    """Test that initialization creates empty visibility dictionaries."""
    assert isinstance(visibility_manager.audio_input_visibility, dict)
    assert isinstance(visibility_manager.audio_output_visibility, dict)
    assert isinstance(visibility_manager.midi_input_visibility, dict)
    assert isinstance(visibility_manager.midi_output_visibility, dict)


def test_load_visibility_settings_from_file(mock_connection_manager, mock_config_manager, temp_config_file):
    """Test loading visibility settings from config file."""
    # Write test data to config file
    test_data = {
        'audio_input': {'client1': False, 'client2': True},
        'audio_output': {'client1': True, 'client2': False},
        'midi_input': {'midi_client': False},
        'midi_output': {'midi_client': True}
    }
    with open(temp_config_file, 'w') as f:
        json.dump(test_data, f)
    
    manager = NodeVisibilityManager(mock_connection_manager, mock_config_manager)
    manager.config_path = temp_config_file
    manager.load_visibility_settings()
    
    assert manager.audio_input_visibility == {'client1': False, 'client2': True}
    assert manager.audio_output_visibility == {'client1': True, 'client2': False}
    assert manager.midi_input_visibility == {'midi_client': False}
    assert manager.midi_output_visibility == {'midi_client': True}


def test_load_visibility_handles_missing_file(visibility_manager):
    """Test that loading handles missing config file gracefully."""
    visibility_manager.config_path = '/nonexistent/path/config.json'
    visibility_manager.load_visibility_settings()
    
    # Should have empty dicts
    assert visibility_manager.audio_input_visibility == {}
    assert visibility_manager.audio_output_visibility == {}


# ── Save Visibility Settings ──────────────────────────────────────────

def test_save_visibility_settings_writes_file(visibility_manager):
    """Test that save_visibility_settings writes to config file."""
    visibility_manager.audio_input_visibility = {'client1': False}
    visibility_manager.audio_output_visibility = {'client1': True}
    visibility_manager.midi_input_visibility = {'midi1': False}
    visibility_manager.midi_output_visibility = {'midi1': True}
    
    visibility_manager.save_visibility_settings()
    
    # Read back the file
    with open(visibility_manager.config_path, 'r') as f:
        data = json.load(f)
    
    assert data['audio_input'] == {'client1': False}
    assert data['audio_output'] == {'client1': True}
    assert data['midi_input'] == {'midi1': False}
    assert data['midi_output'] == {'midi1': True}


def test_save_visibility_creates_directory(mock_connection_manager, mock_config_manager):
    """Test that save creates config directory if it doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, 'subdir', 'config.json')
        
        manager = NodeVisibilityManager(mock_connection_manager, mock_config_manager)
        manager.config_path = config_path
        manager.save_visibility_settings()
        
        assert os.path.exists(config_path)


# ── Extract Client Name ───────────────────────────────────────────────

def test_extract_client_name_from_port(visibility_manager):
    """Test extracting client name from port name."""
    assert visibility_manager._extract_client_name('client:port') == 'client'


def test_extract_client_name_from_split_audio(visibility_manager):
    """Test extracting client name from split audio node."""
    assert visibility_manager._extract_client_name('client (Audio)') == 'client'


def test_extract_client_name_from_split_midi(visibility_manager):
    """Test extracting client name from split MIDI node."""
    assert visibility_manager._extract_client_name('client (MIDI)') == 'client'


def test_extract_client_name_from_split_inputs(visibility_manager):
    """Test extracting client name from split inputs node."""
    assert visibility_manager._extract_client_name('client (Inputs)') == 'client'


def test_extract_client_name_from_split_outputs(visibility_manager):
    """Test extracting client name from split outputs node."""
    assert visibility_manager._extract_client_name('client (Outputs)') == 'client'


def test_extract_client_name_from_port_with_suffix(visibility_manager):
    """Test extracting client name from port with suffix."""
    assert visibility_manager._extract_client_name('client (Audio):port') == 'client'


def test_extract_client_name_plain(visibility_manager):
    """Test extracting client name from plain client name."""
    assert visibility_manager._extract_client_name('client') == 'client'


# ── Node Visibility Checks ────────────────────────────────────────────

def test_is_node_visible_default_true(visibility_manager):
    """Test that nodes are visible by default."""
    assert visibility_manager.is_node_visible('unknown_client', is_midi=False) is True
    assert visibility_manager.is_node_visible('unknown_client', is_midi=True) is True


def test_is_node_visible_audio_both_hidden(visibility_manager):
    """Test audio node visibility when both input and output are hidden."""
    visibility_manager.audio_input_visibility = {'client': False}
    visibility_manager.audio_output_visibility = {'client': False}
    
    # Node should be hidden only if BOTH parts are hidden
    assert visibility_manager.is_node_visible('client', is_midi=False) is False


def test_is_node_visible_audio_input_visible(visibility_manager):
    """Test audio node visibility when only input is visible."""
    visibility_manager.audio_input_visibility = {'client': True}
    visibility_manager.audio_output_visibility = {'client': False}
    
    # Node should be visible if ANY part is visible (OR logic)
    assert visibility_manager.is_node_visible('client', is_midi=False) is True


def test_is_node_visible_audio_output_visible(visibility_manager):
    """Test audio node visibility when only output is visible."""
    visibility_manager.audio_input_visibility = {'client': False}
    visibility_manager.audio_output_visibility = {'client': True}
    
    # Node should be visible if ANY part is visible (OR logic)
    assert visibility_manager.is_node_visible('client', is_midi=False) is True


def test_is_node_visible_midi_both_hidden(visibility_manager):
    """Test MIDI node visibility when both input and output are hidden."""
    visibility_manager.midi_input_visibility = {'midi_client': False}
    visibility_manager.midi_output_visibility = {'midi_client': False}
    
    assert visibility_manager.is_node_visible('midi_client', is_midi=True) is False


def test_is_node_visible_midi_partial(visibility_manager):
    """Test MIDI node visibility with partial visibility."""
    visibility_manager.midi_input_visibility = {'midi_client': True}
    visibility_manager.midi_output_visibility = {'midi_client': False}
    
    # Should be visible if ANY part is visible
    assert visibility_manager.is_node_visible('midi_client', is_midi=True) is True


# ── Input/Output Visibility Checks ────────────────────────────────────

def test_is_input_visible_default_true(visibility_manager):
    """Test that inputs are visible by default."""
    assert visibility_manager.is_input_visible('client', is_midi=False) is True
    assert visibility_manager.is_input_visible('midi_client', is_midi=True) is True


def test_is_input_visible_audio_hidden(visibility_manager):
    """Test audio input visibility when explicitly hidden."""
    visibility_manager.audio_input_visibility = {'client': False}
    
    assert visibility_manager.is_input_visible('client', is_midi=False) is False


def test_is_input_visible_audio_visible(visibility_manager):
    """Test audio input visibility when explicitly visible."""
    visibility_manager.audio_input_visibility = {'client': True}
    
    assert visibility_manager.is_input_visible('client', is_midi=False) is True


def test_is_input_visible_midi_hidden(visibility_manager):
    """Test MIDI input visibility when explicitly hidden."""
    visibility_manager.midi_input_visibility = {'midi_client': False}
    
    assert visibility_manager.is_input_visible('midi_client', is_midi=True) is False


def test_is_output_visible_default_true(visibility_manager):
    """Test that outputs are visible by default."""
    assert visibility_manager.is_output_visible('client', is_midi=False) is True
    assert visibility_manager.is_output_visible('midi_client', is_midi=True) is True


def test_is_output_visible_audio_hidden(visibility_manager):
    """Test audio output visibility when explicitly hidden."""
    visibility_manager.audio_output_visibility = {'client': False}
    
    assert visibility_manager.is_output_visible('client', is_midi=False) is False


def test_is_output_visible_midi_visible(visibility_manager):
    """Test MIDI output visibility when explicitly visible."""
    visibility_manager.midi_output_visibility = {'midi_client': True}
    
    assert visibility_manager.is_output_visible('midi_client', is_midi=True) is True


# ── MIDI Matrix Visibility ────────────────────────────────────────────

def test_is_midi_matrix_input_visible_default_true(visibility_manager):
    """Test that MIDI matrix inputs are visible by default."""
    assert visibility_manager.is_midi_matrix_input_visible('midi_client') is True


def test_is_midi_matrix_input_visible_hidden(visibility_manager):
    """Test MIDI matrix input visibility when explicitly hidden."""
    visibility_manager.midi_matrix_input_visibility = {'midi_client': False}
    
    assert visibility_manager.is_midi_matrix_input_visible('midi_client') is False


def test_is_midi_matrix_output_visible_default_true(visibility_manager):
    """Test that MIDI matrix outputs are visible by default."""
    assert visibility_manager.is_midi_matrix_output_visible('midi_client') is True


def test_is_midi_matrix_output_visible_hidden(visibility_manager):
    """Test MIDI matrix output visibility when explicitly hidden."""
    visibility_manager.midi_matrix_output_visibility = {'midi_client': False}
    
    assert visibility_manager.is_midi_matrix_output_visible('midi_client') is False


# ── Unhide All Nodes ──────────────────────────────────────────────────

def test_unhide_all_nodes_clears_visibility_dicts(visibility_manager):
    """Test that unhide_all_nodes clears all visibility dictionaries."""
    # Set some hidden nodes
    visibility_manager.audio_input_visibility = {'client1': False}
    visibility_manager.audio_output_visibility = {'client2': False}
    visibility_manager.midi_input_visibility = {'midi1': False}
    visibility_manager.midi_output_visibility = {'midi2': False}
    
    visibility_manager.unhide_all_nodes()
    
    # All dicts should be empty (meaning all visible)
    assert visibility_manager.audio_input_visibility == {}
    assert visibility_manager.audio_output_visibility == {}
    assert visibility_manager.midi_input_visibility == {}
    assert visibility_manager.midi_output_visibility == {}


def test_unhide_all_nodes_saves_settings(visibility_manager):
    """Test that unhide_all_nodes saves the cleared settings."""
    visibility_manager.audio_input_visibility = {'client': False}
    
    visibility_manager.unhide_all_nodes()
    
    # Check that file was written
    with open(visibility_manager.config_path, 'r') as f:
        data = json.load(f)
    
    assert data['audio_input'] == {}


def test_unhide_all_nodes_applies_settings(visibility_manager, mock_connection_manager):
    """Test that unhide_all_nodes applies the visibility changes."""
    visibility_manager.unhide_all_nodes()
    
    # Should call refresh methods
    mock_connection_manager._refresh_single_port_type.assert_called()
    mock_connection_manager.refresh_visualizations.assert_called()


# ── Apply Visibility Settings ─────────────────────────────────────────

def test_apply_visibility_settings_updates_trees(visibility_manager, mock_connection_manager):
    """Test that apply_visibility_settings updates port trees."""
    visibility_manager.apply_visibility_settings()
    
    # Should refresh both audio and MIDI tabs
    assert mock_connection_manager._refresh_single_port_type.call_count >= 2


def test_apply_visibility_settings_updates_midi_matrix(visibility_manager, mock_connection_manager):
    """Test that apply_visibility_settings updates MIDI matrix."""
    visibility_manager.apply_visibility_settings()
    
    mock_connection_manager.midi_matrix_widget.refresh_matrix.assert_called_once()


def test_apply_visibility_settings_updates_graph(visibility_manager, mock_connection_manager):
    """Test that apply_visibility_settings updates graph scene."""
    mock_scene = Mock()
    mock_scene.node_visibility_manager = None
    mock_scene.set_node_visibility_manager = Mock()
    mock_scene.full_graph_refresh = Mock()
    mock_connection_manager._get_graph_scene.return_value = mock_scene
    
    visibility_manager.apply_visibility_settings()
    
    mock_scene.set_node_visibility_manager.assert_called_once_with(visibility_manager)
    mock_scene.full_graph_refresh.assert_called_once()


# ── Legacy Format Conversion ──────────────────────────────────────────

def test_convert_legacy_settings_audio(mock_connection_manager, mock_config_manager, temp_config_file):
    """Test converting legacy audio visibility settings."""
    # Write legacy format
    legacy_data = {
        'audio': {'client1': False, 'client2': True}
    }
    with open(temp_config_file, 'w') as f:
        json.dump(legacy_data, f)
    
    manager = NodeVisibilityManager(mock_connection_manager, mock_config_manager)
    manager.config_path = temp_config_file
    manager.load_visibility_settings()
    
    # Should convert to new format (both input and output)
    assert manager.audio_input_visibility == {'client1': False, 'client2': True}
    assert manager.audio_output_visibility == {'client1': False, 'client2': True}


def test_convert_legacy_settings_midi(mock_connection_manager, mock_config_manager, temp_config_file):
    """Test converting legacy MIDI visibility settings."""
    # Write legacy format
    legacy_data = {
        'midi': {'midi_client': False}
    }
    with open(temp_config_file, 'w') as f:
        json.dump(legacy_data, f)
    
    manager = NodeVisibilityManager(mock_connection_manager, mock_config_manager)
    manager.config_path = temp_config_file
    manager.load_visibility_settings()
    
    # Should convert to new format (both input and output)
    assert manager.midi_input_visibility == {'midi_client': False}
    assert manager.midi_output_visibility == {'midi_client': False}


def test_new_format_takes_precedence_over_legacy(mock_connection_manager, mock_config_manager, temp_config_file):
    """Test that new format takes precedence when both exist."""
    # Write both formats
    mixed_data = {
        'audio': {'client': False},  # Legacy
        'audio_input': {'client': True},  # New format
        'audio_output': {'client': False}  # New format
    }
    with open(temp_config_file, 'w') as f:
        json.dump(mixed_data, f)
    
    manager = NodeVisibilityManager(mock_connection_manager, mock_config_manager)
    manager.config_path = temp_config_file
    manager.load_visibility_settings()
    
    # Should use new format
    assert manager.audio_input_visibility == {'client': True}
    assert manager.audio_output_visibility == {'client': False}
