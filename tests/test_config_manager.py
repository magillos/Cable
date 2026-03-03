"""Tests for ConfigManager (cable_core.config)."""

import os
import sys
import configparser

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cable_core.config as config_module
from cable_core import config_keys as keys


@pytest.fixture
def config_manager(tmp_path):
    """Create a ConfigManager that uses a temporary config file."""
    config_dir = tmp_path / ".config" / "cable"
    config_dir.mkdir(parents=True)
    config_file = str(config_dir / "config.ini")

    original_expanduser = os.path.expanduser

    def fake_expanduser(path):
        if "~/.config/cable" in path:
            return path.replace(original_expanduser("~"), str(tmp_path))
        return original_expanduser(path)

    old_expanduser = os.path.expanduser
    os.path.expanduser = fake_expanduser
    try:
        mgr = config_module.ConfigManager()
    finally:
        os.path.expanduser = old_expanduser

    # Point at temp file and reset in-memory state
    mgr.config_file = config_file
    mgr._config = None
    mgr._dirty = False
    mgr._changed_keys = set()
    mgr._ensure_config_exists()

    yield mgr


# ── get / set int ──────────────────────────────────────────────────────

def test_set_and_get_int(config_manager):
    config_manager.set_int_setting("test_int", 42)
    assert config_manager.get_int_setting("test_int") == 42


def test_get_int_default_when_missing(config_manager):
    assert config_manager.get_int_setting("nonexistent_int", default=99) == 99


def test_get_int_default_zero(config_manager):
    assert config_manager.get_int_setting("nonexistent_int") == 0


# ── get / set bool ─────────────────────────────────────────────────────

def test_set_and_get_bool_true(config_manager):
    config_manager.set_bool_setting("test_bool", True)
    assert config_manager.get_bool_setting("test_bool") is True
    # Internally stored as "1"
    raw = config_manager._get_cached_config().get("DEFAULT", "test_bool")
    assert raw == "1"


def test_set_and_get_bool_false(config_manager):
    config_manager.set_bool_setting("test_bool", False)
    assert config_manager.get_bool_setting("test_bool") is False
    raw = config_manager._get_cached_config().get("DEFAULT", "test_bool")
    assert raw == "0"


def test_get_bool_default_when_missing(config_manager):
    assert config_manager.get_bool_setting("missing_bool") is False
    assert config_manager.get_bool_setting("missing_bool", default=True) is True


# ── get / set str ──────────────────────────────────────────────────────

def test_set_and_get_str(config_manager):
    config_manager.set_str_setting("test_str", "hello")
    assert config_manager.get_str_setting("test_str") == "hello"


def test_set_str_none_stores_empty(config_manager):
    config_manager.set_str_setting("test_str", None)
    assert config_manager.get_str_setting("test_str") == ""


def test_get_str_default_when_missing(config_manager):
    assert config_manager.get_str_setting("missing_str") == ""
    assert config_manager.get_str_setting("missing_str", default="fallback") == "fallback"


# ── get / set float ───────────────────────────────────────────────────

def test_set_and_get_float(config_manager):
    config_manager.set_float_setting("test_float", 3.14)
    assert config_manager.get_float_setting("test_float") == pytest.approx(3.14)


def test_get_float_default_when_missing(config_manager):
    assert config_manager.get_float_setting("missing_float") == 0.0
    assert config_manager.get_float_setting("missing_float", default=1.5) == 1.5


# ── short-name aliases ────────────────────────────────────────────────

def test_aliases_roundtrip(config_manager):
    config_manager.set_int("alias_int", 7)
    assert config_manager.get_int("alias_int") == 7

    config_manager.set_bool("alias_bool", True)
    assert config_manager.get_bool("alias_bool") is True

    config_manager.set_str("alias_str", "abc")
    assert config_manager.get_str("alias_str") == "abc"


def test_get_str_alias_default_none(config_manager):
    """get_str (alias) returns None by default when key is missing."""
    assert config_manager.get_str("no_such_key") is None
    assert config_manager.get_str("no_such_key", default="x") == "x"


# ── dirty flag ─────────────────────────────────────────────────────────

def test_dirty_flag_set_on_write(config_manager):
    config_manager._dirty = False
    config_manager._changed_keys.clear()
    config_manager.set_int_setting("dirty_test", 1)
    assert config_manager._dirty is True
    assert "dirty_test" in config_manager._changed_keys


def test_flush_clears_dirty(config_manager):
    config_manager.set_int_setting("flush_test", 10)
    assert config_manager._dirty is True
    config_manager.flush()
    assert config_manager._dirty is False
    assert len(config_manager._changed_keys) == 0


# ── flush persists to disk ────────────────────────────────────────────

def test_flush_persists_and_reloads(config_manager, tmp_path):
    config_manager.set_str_setting("persist_key", "persist_value")
    config_manager.flush()

    # Read same file with a fresh ConfigParser to verify on-disk state
    cp = configparser.ConfigParser(allow_no_value=True)
    cp.read(config_manager.config_file, encoding="utf-8")
    assert cp.get("DEFAULT", "persist_key") == "persist_value"


def test_flush_persists_across_instances(config_manager, tmp_path):
    config_manager.set_int_setting("cross_inst", 123)
    config_manager.flush()

    # Build a second manager pointing at the same file
    mgr2 = config_module.ConfigManager.__new__(config_module.ConfigManager)
    mgr2.parent = None
    mgr2.config_file = config_manager.config_file
    mgr2._dirty = False
    mgr2._changed_keys = set()
    mgr2._config = None
    assert mgr2.get_int_setting("cross_inst") == 123


# ── get_list_from_config ──────────────────────────────────────────────

def test_get_list_active_values(config_manager):
    config_manager.set_str_setting("my_list", "10,20,#30,40")
    result = config_manager.get_list_from_config("my_list", [])
    assert result == [10, 20, 40]  # #30 excluded


def test_get_list_default_when_missing(config_manager):
    result = config_manager.get_list_from_config("no_list", [1, 2, 3])
    assert result == [1, 2, 3]


def test_get_list_skips_non_numeric(config_manager):
    config_manager.set_str_setting("bad_list", "5,abc,10")
    result = config_manager.get_list_from_config("bad_list", [])
    assert result == [5, 10]


# ── get_all_values_from_config ────────────────────────────────────────

def test_get_all_values_includes_commented(config_manager):
    config_manager.set_str_setting("all_list", "10,#20,30")
    result = config_manager.get_all_values_from_config("all_list", [])
    assert result == [10, 20, 30]  # #20 included (stripped)


def test_get_all_values_default(config_manager):
    result = config_manager.get_all_values_from_config("missing_all", [7, 8])
    assert result == [7, 8]


# ── clear_settings ────────────────────────────────────────────────────

def test_clear_settings_removes_keys(config_manager):
    config_manager.set_str_setting("to_clear", "value")
    config_manager.set_int_setting("to_keep", 5)
    config_manager.clear_settings(["to_clear"])
    assert config_manager.get_str_setting("to_clear") == ""
    assert config_manager.get_int_setting("to_keep") == 5


def test_clear_settings_nonexistent_key_no_error(config_manager):
    config_manager.clear_settings(["nonexistent_key"])  # should not raise


# ── defaults created by _ensure_config_exists ─────────────────────────

def test_defaults_quantum_values(config_manager):
    vals = config_manager.get_list_from_config(keys.QUANTUM_VALUES, [])
    assert 1024 in vals
    assert 48 in vals


def test_defaults_sample_rate_values(config_manager):
    vals = config_manager.get_list_from_config(keys.SAMPLE_RATE_VALUES, [])
    assert 48000 in vals
    assert 96000 in vals


def test_defaults_quantum(config_manager):
    assert config_manager.get_int_setting(keys.QUANTUM) == 1024


def test_defaults_sample_rate(config_manager):
    assert config_manager.get_int_setting(keys.SAMPLE_RATE) == 48000


def test_defaults_virtual_sink_module_ids(config_manager):
    raw = config_manager.get_str_setting(keys.VIRTUAL_SINK_MODULE_IDS)
    assert raw == "{}"


# ── get with missing key returns default ──────────────────────────────

def test_missing_key_int_returns_default(config_manager):
    assert config_manager.get_int_setting("zzz_missing", default=77) == 77


def test_missing_key_bool_returns_default(config_manager):
    assert config_manager.get_bool_setting("zzz_missing", default=True) is True


def test_missing_key_str_returns_default(config_manager):
    assert config_manager.get_str_setting("zzz_missing", default="def") == "def"


def test_missing_key_float_returns_default(config_manager):
    assert config_manager.get_float_setting("zzz_missing", default=2.5) == 2.5


# ── write_config ──────────────────────────────────────────────────────

def test_write_config_marks_dirty(config_manager):
    cp = configparser.ConfigParser()
    cp["DEFAULT"] = {"custom_key": "custom_val"}
    config_manager._dirty = False
    config_manager._changed_keys.clear()
    config_manager.write_config(cp)
    assert config_manager._dirty is True
    assert "custom_key" in config_manager._changed_keys


# ── ensure_config_lists ───────────────────────────────────────────────

def test_ensure_config_lists_idempotent(config_manager):
    """Calling ensure_config_lists when lists already exist should not re-dirty."""
    config_manager.flush()
    config_manager._dirty = False
    config_manager._changed_keys.clear()
    config_manager.ensure_config_lists()
    # Lists already present from defaults, so nothing should be marked dirty
    assert config_manager._dirty is False


# ── load_defaults (Cables-specific) ──────────────────────────────────

def test_load_defaults_sets_cables_keys(config_manager):
    config_manager.load_defaults()
    assert config_manager.get_bool_setting(keys.AUTO_REFRESH_ENABLED) is True
    assert config_manager.get_bool_setting(keys.COLLAPSE_ALL_ENABLED) is False
    assert config_manager.get_int_setting(keys.PORT_LIST_FONT_SIZE) == 10
    assert config_manager.get_int_setting(keys.LAST_ACTIVE_TAB) == 0
