# cables/utils/sort_utils.py
"""
Shared sorting utilities used across cables and graph modules.
Centralizes natural sorting logic to avoid duplication.
"""

import re
from typing import List, Tuple, Union, Optional

tryint_re = re.compile(r"(\d+)")


def tryint(text: str) -> Union[int, str]:
    """
    Convert a string to an integer if possible, otherwise return lowercase string.
    Used for natural sorting of port names.
    """
    try:
        return int(text)
    except ValueError:
        return text.lower()


def _split_for_sort(text: str) -> List[Union[int, str]]:
    """Split text into numeric and non-numeric parts for natural sorting."""
    return [tryint(part) for part in tryint_re.split(text.lower())]


def _channel_order_index(name: str) -> int:
    """
    Return a sort index for standard audio channel suffixes.
    Follows the conventional surround channel map order:
    FL, FR, RL, RR, FC, LFE, SL, SR (and common stereo aliases).

    Returns a large value for unrecognized suffixes so they sort after
    known channels but still sort stably among themselves.
    """
    upper = name.upper()
    suffix = upper.rsplit("_", 1)[-1] if "_" in upper else upper

    _CHANNEL_ORDER = {
        "FL": 0,
        "L": 0,
        "LEFT": 0,
        "MONO": 0,
        "MONITOR_FL": 0,
        "FR": 1,
        "R": 1,
        "RIGHT": 1,
        "MONITOR_FR": 1,
        "FC": 2,
        "C": 2,
        "CENTER": 2,
        "MONITOR_FC": 2,
        "LFE": 3,
        "SUB": 3,
        "MONITOR_LFE": 3,
        "SL": 4,
        "MONITOR_SL": 4,
        "SR": 5,
        "MONITOR_SR": 5,
        "RL": 6,
        "BL": 6,
        "MONITOR_RL": 6,
        "RR": 7,
        "BR": 7,
        "MONITOR_RR": 7,
    }
    return _CHANNEL_ORDER.get(suffix, 1000)


def _port_type_prefix_key(name: str) -> List[Union[int, str]]:
    """
    Extract a sort key for the port type prefix (part before the channel suffix).

    This ensures ports with different type prefixes (e.g. capture_FL vs monitor_FL)
    are grouped by type first, then sorted by channel within each type.

    For 'capture_FL' returns the natural sort key of 'capture'.
    For 'input_FL-448' returns the natural sort key of 'input'.
    For names without a recognized channel suffix, returns an empty key.
    """
    _KNOWN_CHANNELS = {
        "FL",
        "FR",
        "FC",
        "LFE",
        "SL",
        "SR",
        "RL",
        "RR",
        "L",
        "R",
        "C",
        "LEFT",
        "RIGHT",
        "CENTER",
        "MONO",
        "SUB",
        "BL",
        "BR",
    }
    upper = name.upper()
    if "_" not in upper:
        return [""]
    base = re.sub(r"-\d+.*$", "", upper)
    if "_" not in base:
        return [""]
    prefix, suffix = base.rsplit("_", 1)
    if suffix in _KNOWN_CHANNELS:
        return _split_for_sort(prefix.lower())
    return [""]


def _extract_base_and_suffix(text: str) -> Tuple[str, str]:
    """Extract base name and suffix from a port name."""
    suffix_match = re.search(r"[-_](\d+.*?)$", text)
    if suffix_match:
        return text[: suffix_match.start()], suffix_match.group(1)
    return text, ""


def natural_sort_key(
    text: str, *, client_prefix: bool = False, channel_aware: bool = False
) -> Tuple:
    """
    Unified natural sort key for port names.

    Args:
        text: The port name or string to create a sort key for.
        client_prefix: If True, text is in "client:port" format and sorts by client first.
        channel_aware: If True, uses channel-map-aware ordering (FL, FR, FC, LFE, etc.).

    Returns:
        A tuple suitable for sorting.
    """
    if client_prefix:
        if ":" in text:
            client_part, port_part = text.split(":", 1)
        else:
            client_part, port_part = "", text
        client_key = _split_for_sort(client_part)
    else:
        port_part = text
        client_key = []

    base_name, suffix = _extract_base_and_suffix(port_part.lower())
    base_name_key = _split_for_sort(base_name)

    if channel_aware:
        channel_idx = _channel_order_index(port_part)
        prefix_key = _port_type_prefix_key(port_part)
    else:
        channel_idx = 0
        prefix_key = []

    if suffix:
        suffix_key = _split_for_sort(suffix)
        if client_prefix:
            return (
                client_key,
                prefix_key,
                [1],
                suffix_key,
                [channel_idx],
                base_name_key,
            )
        elif channel_aware:
            return ([1], prefix_key, [channel_idx], suffix_key, base_name_key)
        else:
            return ([1], suffix_key, base_name_key)
    else:
        if client_prefix:
            return (client_key, prefix_key, [0], [channel_idx], base_name_key, [])
        elif channel_aware:
            return ([0], prefix_key, [channel_idx], base_name_key, [])
        else:
            return ([0], base_name_key, [])


def simple_natural_sort_key(text: str) -> List[Union[int, str]]:
    """
    Simple natural sort key for strings.
    Splits text into alphabetic and numeric parts for proper sorting.

    Example: "port10" comes after "port2" (not before, as with string sort)

    Args:
        text: The string to create a sort key for.

    Returns:
        A list suitable for sorting.
    """
    return _split_for_sort(text.lower())


def natural_sort_key_for_port_item(port_item: object) -> Tuple[List[int], ...]:
    """
    Wrapper for natural_sort_key that works with PortItem objects.
    Uses channel-map-aware ordering so surround ports appear in the
    conventional audio channel order (FL, FR, FC, LFE, RL, RR, SL, SR)
    rather than alphabetically.

    Ports are grouped by type prefix first (e.g. capture before monitor),
    then sorted by channel within each group.

    Args:
        port_item: A PortItem object with a short_name attribute.

    Returns:
        A tuple suitable for sorting.
    """
    return natural_sort_key(port_item.short_name, channel_aware=True)


def natural_sort_key_for_full_port_name(
    port_name: str,
) -> Tuple[List[Union[int, str]], ...]:
    """
    Enhanced sort key for full port names (client:port format).
    Groups ports logically by client, then uses channel-map-aware ordering
    so surround ports appear in SMPTE/ITU order (FL, FR, FC, LFE, SL, SR, RL, RR).

    For example, ports like:
    - Equalizer:input_FL
    - Equalizer:input_FL-448
    - Equalizer:input_FR
    - Equalizer:input_FR-449

    Will be sorted as:
    - Equalizer:input_FL
    - Equalizer:input_FR
    - Equalizer:input_FL-448
    - Equalizer:input_FR-449

    Args:
        port_name: Full port name in "client:port" format.

    Returns:
        A tuple suitable for sorting.
    """
    return natural_sort_key(port_name, client_prefix=True, channel_aware=True)
