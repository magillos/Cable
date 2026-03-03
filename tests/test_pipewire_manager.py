"""Tests for PipewireManager command construction and output parsing."""

import sys
import os
from unittest.mock import Mock, patch, MagicMock
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cable_core.pipewire import PipewireManager


@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager."""
    config = Mock()
    config.save_quantum_setting = Mock()
    config.save_sample_rate_setting = Mock()
    config.clear_settings = Mock()
    config.flush = Mock()
    return config


@pytest.fixture
def pw_manager(mock_config_manager):
    """Create a PipewireManager with mocked config."""
    return PipewireManager(flatpak_env=False, config_manager=mock_config_manager)


@pytest.fixture
def pw_manager_flatpak(mock_config_manager):
    """Create a PipewireManager in Flatpak environment."""
    return PipewireManager(flatpak_env=True, config_manager=mock_config_manager)


# ── Command Construction ──────────────────────────────────────────────

def test_run_command_basic(pw_manager):
    """Test basic command execution without Flatpak."""
    with patch('subprocess.check_output') as mock_check:
        mock_check.return_value = "test output\n"
        
        result = pw_manager.run_command(['pw-cli', 'ls'])
        
        assert result == "test output"
        mock_check.assert_called_once()
        args = mock_check.call_args[0][0]
        assert args == ['pw-cli', 'ls']


def test_run_command_flatpak_wraps_command(pw_manager_flatpak):
    """Test that Flatpak environment wraps commands with flatpak-spawn."""
    with patch('subprocess.check_output') as mock_check:
        mock_check.return_value = "output\n"
        
        pw_manager_flatpak.run_command(['pw-cli', 'ls'])
        
        args = mock_check.call_args[0][0]
        assert args[:2] == ['flatpak-spawn', '--host']
        assert args[2:] == ['pw-cli', 'ls']


def test_run_command_no_output_mode(pw_manager):
    """Test command execution without capturing output."""
    with patch('subprocess.run') as mock_run:
        result = pw_manager.run_command(['wpctl', 'status'], check_output=False)
        
        assert result is True
        mock_run.assert_called_once()


def test_run_command_handles_failure(pw_manager):
    """Test that command failures return None."""
    with patch('subprocess.check_output') as mock_check:
        from subprocess import CalledProcessError
        mock_check.side_effect = CalledProcessError(1, 'cmd')
        
        result = pw_manager.run_command(['pw-cli', 'invalid'])
        
        assert result is None


# ── Metadata Parsing ──────────────────────────────────────────────────

def test_get_metadata_value_parses_output(pw_manager):
    """Test parsing metadata values from pw-metadata output."""
    mock_output = """
Found "settings" metadata 0
 key:'clock.force-quantum' value:'1024' type:''
 key:'clock.force-rate' value:'48000' type:''
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.get_metadata_value('clock.force-quantum')
        
        assert result == '1024'


def test_get_metadata_value_returns_none_when_missing(pw_manager):
    """Test that missing metadata keys return None."""
    mock_output = """
Found "settings" metadata 0
 key:'clock.force-rate' value:'48000' type:''
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.get_metadata_value('nonexistent.key')
        
        assert result is None


def test_get_metadata_value_handles_empty_output(pw_manager):
    """Test handling of empty metadata output."""
    with patch.object(pw_manager, 'run_command', return_value=None):
        result = pw_manager.get_metadata_value('any.key')
        
        assert result is None


# ── Device/Node Loading ───────────────────────────────────────────────

def test_load_devices_parses_pw_cli_output(pw_manager):
    """Test parsing device list from pw-cli ls Device."""
    mock_output = """
id 45, type PipeWire:Interface:Device/3
        device.description = "Built-in Audio"
        device.name = "alsa_card.pci-0000_00_1f.3"
id 46, type PipeWire:Interface:Device/3
        device.description = "USB Audio Device"
        device.name = "alsa_card.usb-0000_01_00.0"
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_devices()
        
        assert result['ok'] is True
        assert len(result['data']) == 2
        assert result['data'][0]['id'] == '45'
        assert result['data'][0]['description'] == 'Built-in Audio'
        assert result['data'][0]['name'] == 'alsa_card.pci-0000_00_1f.3'


def test_load_devices_filters_non_alsa(pw_manager):
    """Test that only ALSA devices are included."""
    mock_output = """
id 45, type PipeWire:Interface:Device/3
        device.description = "Built-in Audio"
        device.name = "alsa_card.pci-0000_00_1f.3"
id 46, type PipeWire:Interface:Device/3
        device.description = "Bluetooth Device"
        device.name = "bluez_card.00_11_22_33_44_55"
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_devices()
        
        # Should only include ALSA device
        assert len(result['data']) == 1
        assert result['data'][0]['name'].startswith('alsa_')


def test_load_nodes_includes_io_type(pw_manager):
    """Test that node loading includes input/output type."""
    mock_output = """
id 50, type PipeWire:Interface:Node/3
        node.description = "Built-in Audio Analog Stereo"
        node.name = "alsa_output.pci-0000_00_1f.3.analog-stereo"
id 51, type PipeWire:Interface:Node/3
        node.description = "Built-in Audio Analog Stereo"
        node.name = "alsa_input.pci-0000_00_1f.3.analog-stereo"
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_nodes()
        
        assert result['ok'] is True
        assert len(result['data']) == 2
        assert result['data'][0]['io_type'] == 'Output'
        assert result['data'][1]['io_type'] == 'Input'


def test_load_devices_handles_command_failure(pw_manager):
    """Test error handling when pw-cli command fails."""
    with patch.object(pw_manager, 'run_command', return_value=None):
        result = pw_manager.load_devices()
        
        # Empty output returns ok=True with empty data list (logs error but doesn't fail)
        assert result['ok'] is True
        assert result['data'] == []


# ── Latency Offset ────────────────────────────────────────────────────

def test_load_latency_offset_parses_nanoseconds(pw_manager):
    """Test parsing latency offset in nanoseconds."""
    mock_output = """
Object: size 32, type Spa:Pod:Object:Param:ProcessLatency (262146), id Spa:Enum:ParamId:ProcessLatency (19)
  Prop: key Spa:Pod:Object:Param:ProcessLatency:ns (1), flags 00000000
    Long 5000000
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_latency_offset('50')
        
        assert result['ok'] is True
        assert result['data']['value'] == '5000000'
        assert result['data']['is_nanoseconds'] is True


def test_load_latency_offset_parses_rate(pw_manager):
    """Test parsing latency offset in rate (samples)."""
    mock_output = """
Object: size 32, type Spa:Pod:Object:Param:ProcessLatency (262146), id Spa:Enum:ParamId:ProcessLatency (19)
  Prop: key Spa:Pod:Object:Param:ProcessLatency:rate (2), flags 00000000
    Int 256
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_latency_offset('50')
        
        assert result['ok'] is True
        assert result['data']['value'] == '256'
        assert result['data']['is_nanoseconds'] is False


def test_load_latency_offset_handles_zero_values(pw_manager):
    """Test that zero latency values return empty string."""
    mock_output = """
Object: size 32, type Spa:Pod:Object:Param:ProcessLatency (262146), id Spa:Enum:ParamId:ProcessLatency (19)
  Prop: key Spa:Pod:Object:Param:ProcessLatency:ns (1), flags 00000000
    Long 0
"""
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_latency_offset('50')
        
        assert result['ok'] is True
        assert result['data']['value'] == ''


# ── Profile Loading ───────────────────────────────────────────────────

def test_load_profiles_parses_pw_dump(pw_manager):
    """Test parsing profiles from pw-dump output."""
    mock_output = json.dumps([{
        "id": 45,
        "info": {
            "params": {
                "Profile": [{"index": 2}],
                "EnumProfile": [
                    {"index": 0, "description": "Off"},
                    {"index": 1, "description": "Analog Stereo Duplex"},
                    {"index": 2, "description": "Analog Stereo Output"}
                ]
            }
        }
    }])
    
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_profiles('45')
        
        assert result['ok'] is True
        assert result['data']['active_index'] == 2
        assert len(result['data']['profiles']) == 3
        assert result['data']['profiles'][1]['description'] == 'Analog Stereo Duplex'


def test_load_profiles_handles_missing_data(pw_manager):
    """Test handling of incomplete profile data."""
    mock_output = json.dumps([{"id": 45, "info": {}}])
    
    with patch.object(pw_manager, 'run_command', return_value=mock_output):
        result = pw_manager.load_profiles('45')
        
        assert result['ok'] is True
        assert result['data']['profiles'] == []
        assert result['data']['active_index'] is None


# ── Apply Settings ────────────────────────────────────────────────────

def test_apply_quantum_settings_constructs_command(pw_manager, mock_config_manager):
    """Test quantum setting command construction."""
    with patch.object(pw_manager, 'run_command', return_value=True) as mock_run:
        result = pw_manager.apply_quantum_settings('512', remember_settings=True)
        
        assert result['ok'] is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ['pw-metadata', '-n', 'settings', '0', 'clock.force-quantum', '512']
        mock_config_manager.save_quantum_setting.assert_called_once()


def test_apply_quantum_settings_rejects_invalid_value(pw_manager):
    """Test that non-numeric quantum values are rejected."""
    result = pw_manager.apply_quantum_settings('invalid')
    
    assert result['ok'] is False
    assert 'error' in result
    assert 'ui' in result
    assert result['ui']['revert'] is True


def test_apply_sample_rate_settings_constructs_command(pw_manager, mock_config_manager):
    """Test sample rate setting command construction."""
    with patch.object(pw_manager, 'run_command', return_value=True) as mock_run:
        result = pw_manager.apply_sample_rate_settings('96000', remember_settings=True)
        
        assert result['ok'] is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ['pw-metadata', '-n', 'settings', '0', 'clock.force-rate', '96000']
        mock_config_manager.save_sample_rate_setting.assert_called_once()


def test_apply_settings_skip_save_when_requested(pw_manager, mock_config_manager):
    """Test that skip_save prevents config writes."""
    with patch.object(pw_manager, 'run_command', return_value=True):
        pw_manager.apply_quantum_settings('512', skip_save=True, remember_settings=True)
        
        mock_config_manager.save_quantum_setting.assert_not_called()


def test_apply_latency_settings_nanoseconds(pw_manager):
    """Test applying latency settings in nanoseconds."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(stdout='', stderr='')
        
        result = pw_manager.apply_latency_settings('50', '5000000', use_nanoseconds=True)
        
        assert result['ok'] is True
        args = mock_run.call_args[0][0]
        assert 'ns = 5000000' in ' '.join(args)


def test_apply_latency_settings_rate(pw_manager):
    """Test applying latency settings in rate (samples)."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(stdout='', stderr='')
        
        result = pw_manager.apply_latency_settings('50', '256', use_nanoseconds=False)
        
        assert result['ok'] is True
        args = mock_run.call_args[0][0]
        assert 'rate = 256' in ' '.join(args)


def test_apply_profile_settings_constructs_command(pw_manager):
    """Test profile setting command construction."""
    with patch.object(pw_manager, 'run_command', return_value=True) as mock_run:
        result = pw_manager.apply_profile_settings('45', 2)
        
        assert result['ok'] is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ['wpctl', 'set-profile', '45', '2']


# ── Reset Settings ────────────────────────────────────────────────────

def test_reset_quantum_settings_clears_config(pw_manager, mock_config_manager):
    """Test that resetting quantum clears config."""
    with patch.object(pw_manager, 'run_command', return_value=True):
        result = pw_manager.reset_quantum_settings()
        
        assert result['ok'] is True
        mock_config_manager.clear_settings.assert_called_once()
        mock_config_manager.flush.assert_called_once()


def test_reset_sample_rate_settings_clears_config(pw_manager, mock_config_manager):
    """Test that resetting sample rate clears config."""
    with patch.object(pw_manager, 'run_command', return_value=True):
        result = pw_manager.reset_sample_rate_settings()
        
        assert result['ok'] is True
        mock_config_manager.clear_settings.assert_called_once()
        mock_config_manager.flush.assert_called_once()


def test_reset_quantum_sets_metadata_to_zero(pw_manager):
    """Test that reset sets metadata value to 0."""
    with patch.object(pw_manager, 'run_command', return_value=True) as mock_run:
        pw_manager.reset_quantum_settings()
        
        args = mock_run.call_args[0][0]
        assert args == ['pw-metadata', '-n', 'settings', '0', 'clock.force-quantum', '0']


# ── Get Current Settings ──────────────────────────────────────────────

def test_get_current_settings_returns_all_values(pw_manager):
    """Test that get_current_settings returns all clock values."""
    def mock_get_metadata(key):
        values = {
            'clock.force-rate': '48000',
            'clock.force-quantum': '1024',
            'clock.rate': '48000',
            'clock.quantum': '1024'
        }
        return values.get(key)
    
    with patch.object(pw_manager, 'get_metadata_value', side_effect=mock_get_metadata):
        result = pw_manager.get_current_settings()
        
        assert result['quantum'] == '1024'
        assert result['sample_rate'] == '48000'
        assert result['forced_quantum'] == '1024'
        assert result['forced_rate'] == '48000'


def test_get_current_settings_uses_unforced_when_zero(pw_manager):
    """Test that unforced values are used when forced values are 0."""
    def mock_get_metadata(key):
        values = {
            'clock.force-rate': '0',
            'clock.force-quantum': '0',
            'clock.rate': '44100',
            'clock.quantum': '512'
        }
        return values.get(key)
    
    with patch.object(pw_manager, 'get_metadata_value', side_effect=mock_get_metadata):
        result = pw_manager.get_current_settings()
        
        assert result['quantum'] == '512'
        assert result['sample_rate'] == '44100'


# ── Reset All Latency ─────────────────────────────────────────────────

def test_reset_all_latency_processes_multiple_nodes(pw_manager):
    """Test resetting latency for multiple nodes."""
    with patch.object(pw_manager, 'run_command', return_value=True) as mock_run:
        result = pw_manager.reset_all_latency(['50', '51', '52'])
        
        assert result['ok'] is True
        assert mock_run.call_count == 3
        assert result['data']['results']['50'] is True
        assert result['data']['results']['51'] is True
        assert result['data']['results']['52'] is True


def test_reset_all_latency_handles_failures(pw_manager):
    """Test that individual node failures are tracked."""
    def mock_run_command(args, check_output=True):
        # Fail for node 51
        if '51' in args:
            return None
        return True
    
    with patch.object(pw_manager, 'run_command', side_effect=mock_run_command):
        result = pw_manager.reset_all_latency(['50', '51', '52'])
        
        assert result['ok'] is True
        assert result['data']['results']['50'] is True
        assert result['data']['results']['51'] is False
        assert result['data']['results']['52'] is True


def test_reset_all_latency_skips_empty_ids(pw_manager):
    """Test that empty node IDs are skipped."""
    with patch.object(pw_manager, 'run_command', return_value=True) as mock_run:
        pw_manager.reset_all_latency(['50', '', '52', None])
        
        # Should only call for valid IDs
        assert mock_run.call_count == 2
