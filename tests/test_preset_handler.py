"""Tests for PresetHandler preset management and serialization logic."""

import sys
import os
import json
import tempfile
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, Any, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cables.features.preset_handler import PresetHandler
from cable_core import config_keys as keys


@pytest.fixture
def mock_manager():
    """Create a mock manager implementing PresetHandlerInterface."""
    manager = Mock()
    
    # ConfigProvider
    manager.config_manager = Mock()
    manager.config_manager.get_str = Mock(return_value=None)
    manager.config_manager.set_str = Mock()
    manager.config_manager.get_bool = Mock(return_value=False)
    manager.config_manager.set_bool = Mock()
    
    # GraphAccessor
    manager._get_graph_main_window = Mock(return_value=None)
    manager._get_graph_scene = Mock(return_value=None)
    manager._get_graph_view = Mock(return_value=None)
    
    # PresetOperations
    manager.preset_manager = Mock()
    manager.preset_manager.get_preset_names = Mock(return_value=[])
    manager.preset_manager.presets_dir = '/tmp/presets'
    manager.preset_manager.config_dir = '/tmp/config'
    # Make sure load_and_apply_preset_with_layout returns a tuple
    manager.preset_manager.load_and_apply_preset_with_layout = Mock(return_value=(True, {}))
    manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    manager.disconnect_all_unified = Mock()
    manager.reconnect_all_unified = Mock()
    
    # ConnectionOperations
    manager.client = Mock()
    manager._get_current_connections = Mock(return_value=[])
    
    # UIRefreshProvider
    manager.refresh_ports = Mock()
    
    # ColorProvider
    from PyQt6.QtGui import QColor
    manager.text_color = QColor(255, 255, 255)
    manager.background_color = QColor(0, 0, 0)
    manager.highlight_color = QColor(100, 100, 255)
    
    # Other attributes
    manager.node_visibility_manager = None
    manager.action_manager = None
    manager.flatpak_env = False
    manager.sender = Mock(return_value=None)
    
    return manager


@pytest.fixture
def preset_handler(mock_manager):
    """Create a PresetHandler with mocked dependencies."""
    return PresetHandler(mock_manager)


# ── Initialization ────────────────────────────────────────────────────

def test_initialization_loads_startup_preset(mock_manager):
    """Test that initialization loads startup preset from config."""
    mock_manager.config_manager.get_str.return_value = 'my_preset'
    
    handler = PresetHandler(mock_manager)
    
    assert handler.startup_preset_name == 'my_preset'
    mock_manager.config_manager.get_str.assert_called_with(keys.STARTUP_PRESET)


def test_initialization_clears_active_preset(mock_manager):
    """Test that initialization clears active preset in config."""
    handler = PresetHandler(mock_manager)
    
    assert handler.current_preset_name is None
    mock_manager.config_manager.set_str.assert_called_with(keys.ACTIVE_PRESET, None)


def test_initialization_sets_attributes(preset_handler):
    """Test that initialization sets all required attributes."""
    assert preset_handler.original_preset_connections is None
    assert preset_handler.original_preset_layout_data is None
    assert preset_handler.save_button_initially_enabled is False
    assert isinstance(preset_handler.unified_clients, dict)


# ── Startup Preset ────────────────────────────────────────────────────

def test_set_startup_preset_updates_config(preset_handler, mock_manager):
    """Test that setting startup preset updates config."""
    preset_handler._set_startup_preset('test_preset')
    
    assert preset_handler.startup_preset_name == 'test_preset'
    mock_manager.config_manager.set_str.assert_called_with(keys.STARTUP_PRESET, 'test_preset')


def test_set_startup_preset_none_clears_config(preset_handler, mock_manager):
    """Test that setting startup preset to None clears config."""
    preset_handler._set_startup_preset(None)
    
    assert preset_handler.startup_preset_name is None
    mock_manager.config_manager.set_str.assert_called_with(keys.STARTUP_PRESET, None)


# ── Load Preset ───────────────────────────────────────────────────────

def test_load_preset_basic_success(preset_handler, mock_manager):
    """Test basic preset loading."""
    # Remove the enhanced manager method so it uses basic
    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        result = preset_handler.load_selected_preset('test_preset', is_startup=True)
    
    assert result is True
    assert preset_handler.current_preset_name == 'test_preset'
    mock_manager.config_manager.set_str.assert_called_with(keys.ACTIVE_PRESET, 'test_preset')


def test_load_preset_with_enhanced_manager(preset_handler, mock_manager):
    """Test preset loading with enhanced preset manager."""
    mock_manager.preset_manager.load_and_apply_preset_with_layout = Mock(
        return_value=(True, {'node_states': {}, 'graph_zoom_level': 1.0})
    )
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        result = preset_handler.load_selected_preset('test_preset')
    
    assert result is True
    mock_manager.disconnect_all_unified.assert_called_once()
    mock_manager.reconnect_all_unified.assert_called_once()


def test_load_preset_captures_original_state(preset_handler, mock_manager):
    """Test that loading preset captures original state."""
    mock_connections = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'}
    ]
    mock_manager._get_current_connections.return_value = mock_connections
    # Remove enhanced manager
    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        preset_handler.load_selected_preset('test_preset')
    
    assert preset_handler.original_preset_connections == mock_connections


def test_load_preset_refreshes_ports(preset_handler, mock_manager):
    """Test that loading preset refreshes ports."""
    # Remove enhanced manager
    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        preset_handler.load_selected_preset('test_preset')
    
    mock_manager.refresh_ports.assert_called_once()


def test_load_preset_stops_daemon_first(preset_handler, mock_manager):
    """Test that daemon mode is stopped before loading."""
    mock_manager.config_manager.get_bool.return_value = True  # daemon_mode enabled
    mock_manager.preset_manager.stop_daemon_mode = Mock()
    # Remove enhanced manager
    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        preset_handler.load_selected_preset('test_preset')
    
    mock_manager.preset_manager.stop_daemon_mode.assert_called_once()


# ── Save Preset ───────────────────────────────────────────────────────

def test_save_preset_basic(preset_handler, mock_manager):
    """Test basic preset saving."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(stdout='', stderr='')
        with patch('os.path.exists', return_value=False):
            with patch('os.makedirs'):
                with patch('cables.features.preset_handler.show_timed_messagebox'):
                    # Remove enhanced manager to avoid load call
                    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
                    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
                    preset_handler._perform_preset_save('new_preset')
    
    # Should call aj-snapshot
    mock_run.assert_called()
    args = mock_run.call_args[0][0]
    assert 'aj-snapshot' in args


def test_save_preset_asks_for_overwrite(preset_handler, mock_manager):
    """Test that saving existing preset asks for confirmation."""
    with patch('os.path.exists', return_value=True):
        with patch('PyQt6.QtWidgets.QMessageBox.question', return_value=Mock()):
            from PyQt6.QtWidgets import QMessageBox
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
                preset_handler._perform_preset_save('existing_preset')
    
    # Should not proceed with save
    # (actual save would call subprocess.run which we're not mocking here)


def test_save_preset_with_layout_data(preset_handler, mock_manager):
    """Test saving preset with layout data."""
    mock_scene = Mock()
    mock_scene.get_node_states = Mock(return_value={'client1': {'x': 100, 'y': 200}})
    mock_manager._get_graph_scene.return_value = mock_scene
    
    mock_view = Mock()
    mock_view.get_zoom_level = Mock(return_value=1.5)
    mock_manager._get_graph_view.return_value = mock_view
    
    mock_manager._get_graph_main_window.return_value = Mock()
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(stdout='', stderr='')
        with patch('os.path.exists', return_value=False):
            with patch('os.makedirs'):
                with patch('builtins.open', create=True) as mock_open:
                    mock_file = MagicMock()
                    mock_open.return_value.__enter__.return_value = mock_file
                    with patch('cables.features.preset_handler.show_timed_messagebox'):
                        # Remove enhanced manager to avoid load call
                        delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
                        mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
                        preset_handler._perform_preset_save('preset_with_layout')
    
    # Should save layout file
    mock_open.assert_called()


def test_save_current_loaded_preset_no_preset_loaded(preset_handler, mock_manager):
    """Test that saving without loaded preset shows warning."""
    preset_handler.current_preset_name = None
    
    with patch('PyQt6.QtWidgets.QMessageBox.warning') as mock_warning:
        preset_handler.save_current_loaded_preset()
        
        mock_warning.assert_called_once()


def test_save_current_loaded_preset_updates_original_state(preset_handler, mock_manager):
    """Test that saving updates the original state."""
    preset_handler.current_preset_name = 'test_preset'
    mock_connections = [{'output': 'out1', 'input': 'in1', 'type': 'audio'}]
    mock_manager._get_current_connections.return_value = mock_connections
    mock_manager.preset_manager.save_preset = Mock(return_value=True)
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        preset_handler.save_current_loaded_preset()
    
    assert preset_handler.original_preset_connections == mock_connections


# ── Delete Preset ─────────────────────────────────────────────────────

def test_delete_preset_asks_confirmation(preset_handler, mock_manager):
    """Test that deleting preset asks for confirmation."""
    with patch('PyQt6.QtWidgets.QMessageBox.question') as mock_question:
        from PyQt6.QtWidgets import QMessageBox
        mock_question.return_value = QMessageBox.StandardButton.No
        
        preset_handler._delete_selected_preset('test_preset')
        
        mock_question.assert_called_once()


def test_delete_preset_clears_current_if_active(preset_handler, mock_manager):
    """Test that deleting active preset clears current_preset_name."""
    preset_handler.current_preset_name = 'test_preset'
    mock_manager.preset_manager.delete_preset = Mock(return_value=True)
    
    with patch('PyQt6.QtWidgets.QMessageBox.question') as mock_question:
        from PyQt6.QtWidgets import QMessageBox
        mock_question.return_value = QMessageBox.StandardButton.Yes
        with patch('cables.features.preset_handler.show_timed_messagebox'):
            preset_handler._delete_selected_preset('test_preset')
    
    assert preset_handler.current_preset_name is None
    mock_manager.config_manager.set_str.assert_called_with(keys.ACTIVE_PRESET, None)


def test_delete_preset_clears_startup_if_startup(preset_handler, mock_manager):
    """Test that deleting startup preset clears startup_preset_name."""
    preset_handler.startup_preset_name = 'test_preset'
    mock_manager.preset_manager.delete_preset = Mock(return_value=True)
    
    with patch('PyQt6.QtWidgets.QMessageBox.question') as mock_question:
        from PyQt6.QtWidgets import QMessageBox
        mock_question.return_value = QMessageBox.StandardButton.Yes
        with patch('cables.features.preset_handler.show_timed_messagebox'):
            preset_handler._delete_selected_preset('test_preset')
    
    assert preset_handler.startup_preset_name is None
    mock_manager.config_manager.set_str.assert_called_with(keys.STARTUP_PRESET, None)


# ── JSON Serialization ────────────────────────────────────────────────

def test_json_serializer_handles_qpointf(preset_handler):
    """Test JSON serializer handles QPointF objects."""
    from PyQt6.QtCore import QPointF
    point = QPointF(100.5, 200.5)
    
    result = preset_handler._json_serializer_simple(point)
    
    assert result == {"x": 100.5, "y": 200.5}


def test_json_serializer_handles_other_objects(preset_handler):
    """Test JSON serializer converts other objects to string."""
    class CustomObject:
        def __str__(self):
            return "custom_value"
    
    obj = CustomObject()
    result = preset_handler._json_serializer_simple(obj)
    
    assert result == "custom_value"


# ── Change Detection ──────────────────────────────────────────────────

def test_connections_have_changed_detects_new_connection(preset_handler, mock_manager):
    """Test that new connections are detected."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_connections = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'}
    ]
    
    mock_manager._get_current_connections.return_value = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'},
        {'output': 'out2', 'input': 'in2', 'type': 'audio'}
    ]
    
    assert preset_handler._connections_have_changed() is True


def test_connections_have_changed_detects_removed_connection(preset_handler, mock_manager):
    """Test that removed connections are detected."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_connections = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'},
        {'output': 'out2', 'input': 'in2', 'type': 'audio'}
    ]
    
    mock_manager._get_current_connections.return_value = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'}
    ]
    
    assert preset_handler._connections_have_changed() is True


def test_connections_have_changed_no_changes(preset_handler, mock_manager):
    """Test that unchanged connections return False."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_connections = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'}
    ]
    
    mock_manager._get_current_connections.return_value = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'}
    ]
    
    assert preset_handler._connections_have_changed() is False


def test_connections_have_changed_no_preset_loaded(preset_handler):
    """Test that no preset loaded returns False."""
    preset_handler.current_preset_name = None
    
    assert preset_handler._connections_have_changed() is False


def test_layout_has_changed_detects_node_state_change(preset_handler, mock_manager):
    """Test that node state changes are detected."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_layout_data = {
        'node_states': {'client1': {'x': 100, 'y': 200}}
    }
    
    mock_scene = Mock()
    mock_scene.get_node_states = Mock(return_value={'client1': {'x': 150, 'y': 200}})
    mock_manager._get_graph_scene.return_value = mock_scene
    
    assert preset_handler._layout_has_changed() is True


def test_layout_has_changed_detects_zoom_change(preset_handler, mock_manager):
    """Test that zoom level changes are detected."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_layout_data = {
        'graph_zoom_level': 1.0
    }
    
    mock_view = Mock()
    mock_view.get_zoom_level = Mock(return_value=1.5)
    mock_manager._get_graph_view.return_value = mock_view
    
    assert preset_handler._layout_has_changed() is True


def test_layout_has_changed_no_changes(preset_handler, mock_manager):
    """Test that unchanged layout returns False."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_layout_data = {
        'node_states': {'client1': {'x': 100, 'y': 200}},
        'graph_zoom_level': 1.0
    }
    
    mock_scene = Mock()
    mock_scene.get_node_states = Mock(return_value={'client1': {'x': 100, 'y': 200}})
    mock_manager._get_graph_scene.return_value = mock_scene
    
    mock_view = Mock()
    mock_view.get_zoom_level = Mock(return_value=1.0)
    mock_manager._get_graph_view.return_value = mock_view
    
    assert preset_handler._layout_has_changed() is False


# ── Save Button State ─────────────────────────────────────────────────

def test_update_save_button_no_preset_disables(preset_handler, mock_manager):
    """Test that save button is disabled when no preset loaded."""
    preset_handler.current_preset_name = None
    mock_manager.save_preset_action = Mock()
    mock_manager.save_preset_action.isEnabled = Mock(return_value=True)
    
    preset_handler.update_save_button_enabled_state()
    
    mock_manager.save_preset_action.setEnabled.assert_called_with(False)


def test_update_save_button_with_changes_enables(preset_handler, mock_manager):
    """Test that save button is enabled when preset has changes."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_connections = []
    mock_manager._get_current_connections.return_value = [
        {'output': 'out1', 'input': 'in1', 'type': 'audio'}
    ]
    mock_manager.save_preset_action = Mock()
    mock_manager.save_preset_action.isEnabled = Mock(return_value=False)
    
    preset_handler.update_save_button_enabled_state()
    
    mock_manager.save_preset_action.setEnabled.assert_called_with(True)


def test_update_save_button_no_changes_disables(preset_handler, mock_manager):
    """Test that save button is disabled when preset has no changes."""
    preset_handler.current_preset_name = 'test_preset'
    preset_handler.original_preset_connections = []
    mock_manager._get_current_connections.return_value = []
    mock_manager.save_preset_action = Mock()
    mock_manager.save_preset_action.isEnabled = Mock(return_value=True)
    
    preset_handler.update_save_button_enabled_state()
    
    mock_manager.save_preset_action.setEnabled.assert_called_with(False)


# ── Mode Settings ─────────────────────────────────────────────────────

def test_set_strict_mode_updates_config(preset_handler, mock_manager):
    """Test that strict mode setting updates config."""
    # Remove enhanced manager to use basic preset manager
    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    preset_handler.current_preset_name = 'test_preset'
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        preset_handler._set_strict_mode(True)
    
    mock_manager.config_manager.set_bool.assert_called_with(keys.LOAD_PRESET_STRICT_MODE, True)


def test_set_strict_mode_reloads_preset(preset_handler, mock_manager):
    """Test that changing strict mode reloads current preset."""
    preset_handler.current_preset_name = 'test_preset'
    # Remove enhanced manager to use basic preset manager
    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        preset_handler._set_strict_mode(True)
    
    # Should reload the preset
    assert mock_manager.preset_manager.load_and_apply_preset.called


def test_set_daemon_mode_updates_config(preset_handler, mock_manager):
    """Test that daemon mode setting updates config."""
    preset_handler._set_daemon_mode(True)
    
    mock_manager.config_manager.set_bool.assert_called_with(keys.LOAD_PRESET_DAEMON_MODE, True)


def test_set_daemon_mode_stops_existing_daemon(preset_handler, mock_manager):
    """Test that enabling daemon mode stops existing daemon first."""
    preset_handler.current_preset_name = 'test_preset'
    mock_manager.preset_manager.stop_daemon_mode = Mock()
    # Remove enhanced manager to use basic preset manager
    delattr(mock_manager.preset_manager, 'load_and_apply_preset_with_layout')
    mock_manager.preset_manager.load_and_apply_preset = Mock(return_value=True)
    
    with patch('cables.features.preset_handler.show_timed_messagebox'):
        preset_handler._set_daemon_mode(True)
    
    mock_manager.preset_manager.stop_daemon_mode.assert_called_once()


def test_set_restore_layout_mode_updates_config(preset_handler, mock_manager):
    """Test that restore layout mode updates config."""
    preset_handler._set_restore_layout_mode(True)
    
    mock_manager.config_manager.set_bool.assert_called_with(keys.LOAD_PRESET_RESTORE_LAYOUT, True)


# ── Apply Layout Data ─────────────────────────────────────────────────

def test_apply_layout_data_applies_node_states(preset_handler, mock_manager):
    """Test that layout data applies node states."""
    mock_scene = Mock()
    mock_scene.restore_node_states = Mock()
    mock_manager._get_graph_scene.return_value = mock_scene
    
    layout_data = {
        'node_states': {'client1': {'x': 100, 'y': 200}}
    }
    
    preset_handler._apply_layout_data(layout_data)
    
    mock_scene.restore_node_states.assert_called_once_with({'client1': {'x': 100, 'y': 200}})


def test_apply_layout_data_applies_zoom_level(preset_handler, mock_manager):
    """Test that layout data applies zoom level."""
    mock_view = Mock()
    mock_view.set_zoom_level = Mock()
    mock_manager._get_graph_view.return_value = mock_view
    
    layout_data = {
        'graph_zoom_level': 1.5
    }
    
    preset_handler._apply_layout_data(layout_data)
    
    mock_view.set_zoom_level.assert_called_once_with(1.5)


def test_apply_layout_data_applies_visibility(preset_handler, mock_manager):
    """Test that layout data applies node visibility."""
    mock_visibility_manager = Mock()
    mock_visibility_manager.save_visibility_settings = Mock()
    mock_visibility_manager.apply_visibility_settings = Mock()
    mock_manager.node_visibility_manager = mock_visibility_manager
    
    layout_data = {
        'node_visibility': {
            'audio_input': {'client1': False},
            'audio_output': {'client1': True}
        }
    }
    
    preset_handler._apply_layout_data(layout_data)
    
    assert mock_visibility_manager.audio_input_visibility == {'client1': False}
    assert mock_visibility_manager.audio_output_visibility == {'client1': True}
    mock_visibility_manager.save_visibility_settings.assert_called_once()
    mock_visibility_manager.apply_visibility_settings.assert_called_once()


def test_apply_layout_data_handles_empty_data(preset_handler, mock_manager):
    """Test that empty layout data is handled gracefully."""
    # Should not raise an exception
    preset_handler._apply_layout_data(None)
    preset_handler._apply_layout_data({})
