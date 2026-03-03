"""Tests for cables/utils/sort_utils.py sorting utilities."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cables.utils.sort_utils import (
    tryint,
    natural_sort_key,
    simple_natural_sort_key,
    natural_sort_key_for_full_port_name,
)


# --- tryint ---

def test_tryint_integer_string():
    assert tryint("42") == 42


def test_tryint_negative_integer_string():
    assert tryint("-7") == -7


def test_tryint_zero():
    assert tryint("0") == 0


def test_tryint_non_numeric():
    assert tryint("abc") == "abc"


def test_tryint_uppercase_returns_lowercase():
    assert tryint("ABC") == "abc"


def test_tryint_mixed_alpha_numeric():
    assert tryint("12abc") == "12abc"


def test_tryint_empty_string():
    assert tryint("") == ""


# --- simple_natural_sort_key ---

def test_simple_natural_sort_basic():
    items = ["port10", "port2", "port1"]
    assert sorted(items, key=simple_natural_sort_key) == ["port1", "port2", "port10"]


def test_simple_natural_sort_no_numbers():
    items = ["banana", "apple", "cherry"]
    assert sorted(items, key=simple_natural_sort_key) == ["apple", "banana", "cherry"]


def test_simple_natural_sort_case_insensitive():
    items = ["Port2", "port1", "PORT10"]
    assert sorted(items, key=simple_natural_sort_key) == ["port1", "Port2", "PORT10"]


def test_simple_natural_sort_multiple_numbers():
    items = ["a2b10", "a2b2", "a10b1"]
    assert sorted(items, key=simple_natural_sort_key) == ["a2b2", "a2b10", "a10b1"]


def test_simple_natural_sort_identical():
    items = ["port1", "port1"]
    assert sorted(items, key=simple_natural_sort_key) == ["port1", "port1"]


# --- natural_sort_key ---

def test_natural_sort_key_base_before_suffixed():
    """Base ports (no suffix) should sort before suffixed ports."""
    items = ["input_FL-448", "input_FL"]
    assert sorted(items, key=natural_sort_key) == ["input_FL", "input_FL-448"]


def test_natural_sort_key_grouping():
    """Ports should group: all base ports first, then suffixed grouped by suffix."""
    items = ["input_FL", "input_FR", "input_FL-448", "input_FR-449"]
    result = sorted(items, key=natural_sort_key)
    assert result == ["input_FL", "input_FR", "input_FL-448", "input_FR-449"]


def test_natural_sort_key_multiple_suffixes():
    """Multiple suffix groups should be sorted by suffix value."""
    items = [
        "input_FL-458",
        "input_FR-459",
        "input_FL-448",
        "input_FR-449",
        "input_FL",
        "input_FR",
    ]
    result = sorted(items, key=natural_sort_key)
    assert result == [
        "input_FL",
        "input_FR",
        "input_FL-448",
        "input_FR-449",
        "input_FL-458",
        "input_FR-459",
    ]


def test_natural_sort_key_case_insensitive():
    items = ["Input_FL", "input_fr"]
    result = sorted(items, key=natural_sort_key)
    assert result == ["Input_FL", "input_fr"]


def test_natural_sort_key_no_suffix():
    """Ports with no suffix should sort naturally among themselves."""
    items = ["output", "input"]
    result = sorted(items, key=natural_sort_key)
    assert result == ["input", "output"]


def test_natural_sort_key_numeric_base():
    items = ["port2", "port10", "port1"]
    result = sorted(items, key=natural_sort_key)
    assert result == ["port1", "port2", "port10"]


# --- natural_sort_key_for_full_port_name ---

def test_full_port_name_client_sorting():
    """Different clients should sort by client name first."""
    items = ["Zebra:port1", "Alpha:port1"]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == ["Alpha:port1", "Zebra:port1"]


def test_full_port_name_base_before_suffixed():
    """Within same client, base ports sort before suffixed."""
    items = [
        "Equalizer:input_FL-448",
        "Equalizer:input_FR",
        "Equalizer:input_FL",
    ]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == [
        "Equalizer:input_FL",
        "Equalizer:input_FR",
        "Equalizer:input_FL-448",
    ]


def test_full_port_name_full_grouping():
    """Full grouping: base ports first, then suffixed grouped by suffix."""
    items = [
        "Equalizer:input_FL",
        "Equalizer:input_FL-448",
        "Equalizer:input_FR",
        "Equalizer:input_FR-449",
    ]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == [
        "Equalizer:input_FL",
        "Equalizer:input_FR",
        "Equalizer:input_FL-448",
        "Equalizer:input_FR-449",
    ]


def test_full_port_name_no_colon():
    """Port name without colon should treat client as empty string."""
    items = ["port_b", "port_a"]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == ["port_a", "port_b"]


def test_full_port_name_no_colon_before_client():
    """Ports without client (empty string) sort before ports with client."""
    items = ["Client:port1", "port1"]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == ["port1", "Client:port1"]


def test_full_port_name_case_insensitive():
    items = ["EQUALIZER:input_FL", "equalizer:input_FR"]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == ["EQUALIZER:input_FL", "equalizer:input_FR"]


def test_full_port_name_numeric_clients():
    """Clients with numbers sort naturally."""
    items = ["Client10:port1", "Client2:port1", "Client1:port1"]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == ["Client1:port1", "Client2:port1", "Client10:port1"]


def test_full_port_name_mixed_clients_and_ports():
    """Complex scenario with multiple clients and port variations."""
    items = [
        "Beta:output_1",
        "Alpha:input_FL-448",
        "Alpha:input_FL",
        "Beta:output_2",
        "Alpha:input_FR",
    ]
    result = sorted(items, key=natural_sort_key_for_full_port_name)
    assert result == [
        "Alpha:input_FL",
        "Alpha:input_FR",
        "Alpha:input_FL-448",
        "Beta:output_1",
        "Beta:output_2",
    ]
