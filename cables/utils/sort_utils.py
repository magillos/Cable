# cables/utils/sort_utils.py
"""
Shared sorting utilities used across cables and graph modules.
Centralizes natural sorting logic to avoid duplication.
"""
import re
from typing import List, Tuple, Union


def tryint(text: str) -> Union[int, str]:
    """
    Convert a string to an integer if possible, otherwise return lowercase string.
    Used for natural sorting of port names.
    """
    try:
        return int(text)
    except ValueError:
        return text.lower()


def natural_sort_key(text: str) -> Tuple[List[int], ...]:
    """
    Creates an enhanced sort key that groups ports by base name.
    
    For example, ports like:
    - input_FL
    - input_FL-448
    - input_FL-458
    - input_FR
    - input_FR-449
    - input_FR-459
    
    Will be sorted as:
    - input_FL
    - input_FR
    - input_FL-448
    - input_FR-449
    - input_FL-458
    - input_FR-459
    
    Args:
        text: The port name or string to create a sort key for.
        
    Returns:
        A tuple suitable for sorting.
    """
    text = text.lower()
    
    # Extract base name and suffix from port name
    # Look for patterns like "input_FL-448" or "output_1-mono"
    base_name = text
    suffix = ''
    
    # Try to find a suffix pattern (dash followed by numbers/text)
    suffix_match = re.search(r'[-_](\d+.*?)$', text)
    if suffix_match:
        suffix = suffix_match.group(1)
        base_name = text[:suffix_match.start()]
    
    # Create sort key components
    base_name_key = [tryint(part) for part in re.split(r'(\d+)', base_name)]
    
    # For the desired sorting behavior:
    # 1. First show all base ports (no suffix) sorted by base name
    # 2. Then show suffixed ports, grouped by suffix value, with base names sorted within each suffix group
    if suffix:
        suffix_key = [tryint(part) for part in re.split(r'(\d+)', suffix)]
        # For suffixed ports: sort by (suffix, base_name)
        return ([1], suffix_key, base_name_key)  # [1] puts suffixed ports after base ports
    else:
        # For base ports: sort by (base_name)
        return ([0], base_name_key, [])  # [0] puts base ports first


def _channel_order_index(name: str) -> int:
    """
    Return a sort index for standard audio channel suffixes.
    Follows the conventional surround channel map order:
    FL, FR, RL, RR, FC, LFE, SL, SR (and common stereo aliases).
    
    Returns a large value for unrecognized suffixes so they sort after
    known channels but still sort stably among themselves.
    """
    # Extract the channel suffix (part after last underscore)
    upper = name.upper()
    suffix = upper.rsplit('_', 1)[-1] if '_' in upper else upper

    # SMPTE/ITU channel order (matches PipeWire's native port index assignment)
    _CHANNEL_ORDER = {
        'FL': 0, 'L': 0, 'LEFT': 0, 'MONO': 0, 'MONITOR_FL': 0,
        'FR': 1, 'R': 1, 'RIGHT': 1, 'MONITOR_FR': 1,
        'FC': 2, 'C': 2, 'CENTER': 2, 'MONITOR_FC': 2,
        'LFE': 3, 'SUB': 3, 'MONITOR_LFE': 3,
        'SL': 4, 'MONITOR_SL': 4,
        'SR': 5, 'MONITOR_SR': 5,
        'RL': 6, 'BL': 6, 'MONITOR_RL': 6,
        'RR': 7, 'BR': 7, 'MONITOR_RR': 7,
    }
    return _CHANNEL_ORDER.get(suffix, 1000)


def natural_sort_key_for_port_item(port_item: object) -> Tuple[List[int], ...]:
    """
    Wrapper for natural_sort_key that works with PortItem objects.
    Uses channel-map-aware ordering so surround ports appear in the
    conventional audio channel order (FL, FR, FC, LFE, RL, RR, SL, SR)
    rather than alphabetically.
    
    Args:
        port_item: A PortItem object with a short_name attribute.
        
    Returns:
        A tuple suitable for sorting.
    """
    name = port_item.short_name
    base_key = natural_sort_key(name)
    channel_idx = _channel_order_index(name)
    # Prepend channel index so known channels sort by map order,
    # while the rest fall through to natural sort.
    return ([base_key[0][0]], [channel_idx], base_key[1], base_key[2])


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
    return [tryint(part) for part in re.split(r'(\d+)', text.lower())]


def natural_sort_key_for_full_port_name(port_name: str) -> Tuple[List[Union[int, str]], ...]:
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
    # Split the port name into client and port parts
    if ':' in port_name:
        client_part, port_part = port_name.split(':', 1)
    else:
        client_part, port_part = '', port_name
    
    # Extract base name and suffix from port part
    # Look for patterns like "input_FL-448" or "output_1-mono"
    base_name = port_part
    suffix = ''
    
    # Try to find a suffix pattern (dash followed by numbers/text)
    suffix_match = re.search(r'[-_](\d+.*?)$', port_part)
    if suffix_match:
        suffix = suffix_match.group(1)
        base_name = port_part[:suffix_match.start()]
    
    # Create sort key components
    client_key = [tryint(part) for part in re.split(r'(\d+)', client_part.lower())]
    base_name_key = [tryint(part) for part in re.split(r'(\d+)', base_name.lower())]
    channel_idx = _channel_order_index(port_part)
    
    # For the desired sorting behavior:
    # 1. First show all base ports (no suffix) sorted by channel map order
    # 2. Then show suffixed ports, grouped by suffix value, sorted by channel map order within each group
    if suffix:
        suffix_key = [tryint(part) for part in re.split(r'(\d+)', suffix.lower())]
        # For suffixed ports: sort by (client, suffix, channel_order, base_name)
        return (client_key, [1], suffix_key, [channel_idx], base_name_key)
    else:
        # For base ports: sort by (client, channel_order, base_name)
        return (client_key, [0], [channel_idx], base_name_key, [])
