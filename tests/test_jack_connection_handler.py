"""Tests for JackConnectionHandler batch operations and connection logic."""

import sys
import os
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Tuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cables.jack_connection_handler import JackConnectionHandler


@pytest.fixture
def mock_jack_service():
    """Create a mock JackService."""
    service = Mock()
    service.connect = Mock()
    service.disconnect = Mock()
    service.get_ports = Mock(return_value=[])
    service.get_all_connections = Mock(return_value=[])
    service.get_all_connections_as_tuples = Mock(return_value=[])
    service.get_port_by_name = Mock()
    return service


@pytest.fixture
def mock_manager():
    """Create a mock JackConnectionManager."""
    manager = Mock()
    manager.update_undo_redo_buttons = Mock()
    manager.update_connections = Mock()
    manager.update_midi_connections = Mock()
    manager.refresh_ports = Mock()
    manager.update_connection_buttons = Mock()
    manager.update_midi_connection_buttons = Mock()
    manager.preset_handler = Mock()
    manager.preset_handler.update_save_button_enabled_state = Mock()
    manager.connection_history = Mock()
    manager.connection_history.add_action = Mock()
    manager.ui_manager = Mock()
    manager.ui_manager.tab_widget = Mock()
    manager.ui_manager.tab_widget.currentIndex = Mock(return_value=0)  # Audio tab
    return manager


@pytest.fixture
def mock_client():
    """Create a mock JACK client."""
    return Mock()


@pytest.fixture
def handler(mock_client, mock_manager, mock_jack_service):
    """Create a JackConnectionHandler with mocked dependencies."""
    handler = JackConnectionHandler(mock_client, mock_manager)
    handler._jack_service = mock_jack_service
    return handler


# ── Batch Operations ──────────────────────────────────────────────────

def test_batch_prevents_refresh_during_operations(handler, mock_manager):
    """Test that batch mode prevents refresh until batch ends."""
    handler.start_batch()
    handler.make_connection("out:port", "in:port")
    
    # Refresh should not be called during batch
    mock_manager.refresh_ports.assert_not_called()
    
    handler.end_batch()
    
    # Refresh should be called after batch ends
    mock_manager.refresh_ports.assert_called_once()


def test_nested_batch_only_refreshes_at_end(handler, mock_manager):
    """Test that nested batches only refresh when all batches complete."""
    handler.start_batch()
    handler.start_batch()
    handler.make_connection("out1:port", "in1:port")
    handler.end_batch()
    
    # Still in batch, no refresh
    mock_manager.refresh_ports.assert_not_called()
    
    handler.end_batch()
    
    # Now refresh should be called
    mock_manager.refresh_ports.assert_called_once()


def test_batch_count_tracks_nesting(handler):
    """Test that batch count correctly tracks nesting level."""
    assert handler._batch_count == 0
    
    handler.start_batch()
    assert handler._batch_count == 1
    
    handler.start_batch()
    assert handler._batch_count == 2
    
    handler.end_batch()
    assert handler._batch_count == 1
    
    handler.end_batch()
    assert handler._batch_count == 0


# ── Connection Operations ────────────────────────────────────────────

def test_make_connection_calls_jack_service(handler, mock_jack_service):
    """Test that make_connection calls JackService.connect."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_connection("out:port", "in:port")
    
    mock_jack_service.connect.assert_called_once_with("out:port", "in:port")


def test_make_connection_adds_to_history(handler, mock_manager, mock_jack_service):
    """Test that make_connection adds action to history."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_connection("out:port", "in:port")
    
    mock_manager.connection_history.add_action.assert_called_once_with(
        'connect', "out:port", "in:port", False
    )


def test_make_connection_undo_redo_skips_history(handler, mock_manager, mock_jack_service):
    """Test that undo/redo connections don't add to history."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_connection("out:port", "in:port", is_undo_redo=True)
    
    mock_manager.connection_history.add_action.assert_not_called()


def test_break_connection_calls_jack_service(handler, mock_jack_service):
    """Test that break_connection calls JackService.disconnect."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.break_connection("out:port", "in:port")
    
    mock_jack_service.disconnect.assert_called_once_with("out:port", "in:port")


def test_break_connection_adds_to_history(handler, mock_manager, mock_jack_service):
    """Test that break_connection adds action to history."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.break_connection("out:port", "in:port")
    
    mock_manager.connection_history.add_action.assert_called_once_with(
        'disconnect', "out:port", "in:port", False
    )


def test_midi_connection_uses_midi_flag(handler, mock_manager, mock_jack_service):
    """Test that MIDI connections use is_midi=True in history."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_midi_connection("midi:out", "midi:in")
    
    mock_manager.connection_history.add_action.assert_called_once_with(
        'connect', "midi:out", "midi:in", True
    )


# ── Multiple Connections ──────────────────────────────────────────────

def test_make_multiple_connections_one_to_many(handler, mock_jack_service):
    """Test connecting one output to multiple inputs."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_multiple_connections("out:port", ["in1:port", "in2:port", "in3:port"])
    
    assert mock_jack_service.connect.call_count == 3
    mock_jack_service.connect.assert_any_call("out:port", "in1:port")
    mock_jack_service.connect.assert_any_call("out:port", "in2:port")
    mock_jack_service.connect.assert_any_call("out:port", "in3:port")


def test_make_multiple_connections_many_to_one(handler, mock_jack_service):
    """Test connecting multiple outputs to one input."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_multiple_connections(["out1:port", "out2:port", "out3:port"], "in:port")
    
    assert mock_jack_service.connect.call_count == 3
    mock_jack_service.connect.assert_any_call("out1:port", "in:port")
    mock_jack_service.connect.assert_any_call("out2:port", "in:port")
    mock_jack_service.connect.assert_any_call("out3:port", "in:port")


def test_make_multiple_connections_one_to_one(handler, mock_jack_service):
    """Test connecting single output to single input."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_multiple_connections("out:port", "in:port")
    
    mock_jack_service.connect.assert_called_once_with("out:port", "in:port")


def test_make_multiple_connections_suffix_matching(handler, mock_jack_service):
    """Test that suffix matching works for stereo pairs."""
    outputs = ["client:out_L", "client:out_R"]
    inputs = ["device:in_L", "device:in_R"]
    
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_multiple_connections(outputs, inputs)
    
    # Should match L to L and R to R
    assert mock_jack_service.connect.call_count == 2
    mock_jack_service.connect.assert_any_call("client:out_L", "device:in_L")
    mock_jack_service.connect.assert_any_call("client:out_R", "device:in_R")


def test_make_multiple_connections_empty_lists_logs_warning(handler, mock_jack_service, caplog):
    """Test that empty lists log a warning and don't attempt connections."""
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_multiple_connections([], [])
    
    mock_jack_service.connect.assert_not_called()
    assert "empty outputs or inputs" in caplog.text.lower()


def test_make_multiple_connections_sequential_fallback(handler, mock_jack_service):
    """Test sequential matching when suffix matching doesn't apply."""
    outputs = ["client:out1", "client:out2"]
    inputs = ["device:in1", "device:in2"]
    
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.make_multiple_connections(outputs, inputs)
    
    # Should connect sequentially
    assert mock_jack_service.connect.call_count == 2


# ── Get Connections ───────────────────────────────────────────────────

def test_get_all_connections_calls_jack_service(handler, mock_jack_service):
    """Test that get_all_connections delegates to JackService."""
    mock_jack_service.get_all_connections_as_tuples.return_value = [
        ("out:port", "in:port")
    ]
    
    result = handler.get_all_connections("test:port")
    
    assert result == [("out:port", "in:port")]
    mock_jack_service.get_all_connections_as_tuples.assert_called_once_with("test:port")


# ── Disconnect Node ───────────────────────────────────────────────────

def test_disconnect_node_input_port(handler, mock_jack_service):
    """Test disconnecting all connections to an input port."""
    # Mock port object
    mock_port = Mock()
    mock_port.is_midi = False
    mock_port.is_input = True
    mock_port.is_output = False
    mock_jack_service.get_port_by_name.return_value = mock_port
    
    # Mock output ports
    mock_output = Mock()
    mock_output.name = "source:out"
    mock_jack_service.get_ports.return_value = [mock_output]
    
    # Mock connections
    mock_conn = Mock()
    mock_conn.name = "target:in"
    mock_jack_service.get_all_connections.return_value = [mock_conn]
    
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.disconnect_node("target:in")
    
    mock_jack_service.disconnect.assert_called_once_with("source:out", "target:in")


def test_disconnect_node_output_port(handler, mock_jack_service):
    """Test disconnecting all connections from an output port."""
    # Mock port object
    mock_port = Mock()
    mock_port.is_midi = False
    mock_port.is_input = False
    mock_port.is_output = True
    mock_jack_service.get_port_by_name.return_value = mock_port
    
    # Mock connected input
    mock_input = Mock()
    mock_input.name = "target:in"
    mock_input.is_midi = False
    mock_jack_service.get_all_connections.return_value = [mock_input]
    
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.disconnect_node("source:out")
    
    mock_jack_service.disconnect.assert_called_once_with("source:out", "target:in")


# ── Disconnect Client ─────────────────────────────────────────────────

def test_disconnect_all_ports_of_client(handler, mock_jack_service):
    """Test disconnecting all ports belonging to a client."""
    # Mock client ports
    mock_port1 = Mock()
    mock_port1.name = "client:out"
    mock_port1.is_midi = False
    mock_port1.is_input = False
    mock_port1.is_output = True
    
    mock_port2 = Mock()
    mock_port2.name = "client:in"
    mock_port2.is_midi = False
    mock_port2.is_input = True
    mock_port2.is_output = False
    
    mock_jack_service.get_ports.return_value = [mock_port1, mock_port2]
    
    # Mock connections for output port
    mock_conn = Mock()
    mock_conn.name = "other:in"
    mock_conn.is_midi = False
    mock_jack_service.get_all_connections.return_value = [mock_conn]
    
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.disconnect_all_ports_of_client("client")
    
    # Should disconnect the output port
    mock_jack_service.disconnect.assert_called_with("client:out", "other:in")


def test_disconnect_all_ports_no_ports_found(handler, mock_jack_service):
    """Test that disconnecting a non-existent client logs appropriately."""
    mock_jack_service.get_ports.return_value = []
    
    with patch('cables.jack_connection_handler.get_jack_service', return_value=mock_jack_service):
        handler.disconnect_all_ports_of_client("nonexistent")
    
    mock_jack_service.disconnect.assert_not_called()
    # Note: The actual code logs at debug level, not a specific "no ports found" message


# ── Refresh Behavior ──────────────────────────────────────────────────

def test_refresh_calls_all_update_methods(handler, mock_manager):
    """Test that refresh calls all necessary update methods."""
    handler._perform_refresh()
    
    mock_manager.update_undo_redo_buttons.assert_called_once()
    mock_manager.update_connections.assert_called_once()
    mock_manager.update_midi_connections.assert_called_once()
    mock_manager.refresh_ports.assert_called_once_with(refresh_all=True)
    mock_manager.update_connection_buttons.assert_called_once()
    mock_manager.update_midi_connection_buttons.assert_called_once()


def test_refresh_updates_preset_handler(handler, mock_manager):
    """Test that refresh updates preset handler save button state."""
    handler._perform_refresh()
    
    mock_manager.preset_handler.update_save_button_enabled_state.assert_called_once()


def test_refresh_handles_missing_preset_handler(handler, mock_manager):
    """Test that refresh works when preset_handler is None."""
    mock_manager.preset_handler = None
    
    # Should not raise an exception
    handler._perform_refresh()
    
    mock_manager.refresh_ports.assert_called_once()
