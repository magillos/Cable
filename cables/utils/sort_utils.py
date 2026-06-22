# cables/utils/sort_utils.py
"""
Shared sorting utilities used across cables and graph modules.
Centralizes natural sorting logic to avoid duplication.
Also provides stereo pair detection for per-pair bulk areas.
"""

import re
import logging
from typing import List, Tuple, Union, Optional

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Stereo pair detection for per-pair bulk areas
# ---------------------------------------------------------------------------

# Default L/R suffix pairs for Phase 1 detection.
#
# All entries are written in canonical lowercase — Phase 1 matching is
# case-insensitive (port names are lowercased before suffix lookup), so
# 'Output L' and 'OUTPUT L' both match ' l'. Casing no longer needs to be
# enumerated per convention.
#
# Each single-letter suffix keeps its separator explicitly (underscore,
# space, or dash) so that a bare 'l'/'r' does not greedily match unrelated
# words like 'vocal' or 'center'. Full-word suffixes ('left'/'right') are
# long enough to be unambiguous without a separator.
#
# Pairs are tried longest-first for specificity, so '_fl' is attempted
# before '_l' and won't let 'playback_FL' pair against a non-existent
# 'playback_R'. Surround variants (FL/FR, SL/SR, RL/RR) are listed for
# each separator in turn.
#
# These are defined here to avoid a cross-package import from graph.constants.
# If graph.constants.STEREO_PAIR_SUFFIXES exists, it should mirror this list.
_DEFAULT_STEREO_PAIR_SUFFIXES: List[Tuple[str, str]] = [
    # Front Left/Right — all three separators
    ('_fl', '_fr'),
    (' fl', ' fr'),
    ('-fl', '-fr'),
    # Side Left/Right
    ('_sl', '_sr'),
    (' sl', ' sr'),
    ('-sl', '-sr'),
    # Rear Left/Right
    ('_rl', '_rr'),
    (' rl', ' rr'),
    ('-rl', '-rr'),
    # Generic single-letter Left/Right — all three separators
    ('_l', '_r'),
    (' l', ' r'),
    ('-l', '-r'),
    # Full words — separator-agnostic (long enough to be unambiguous)
    ('left', 'right'),
]

# Regex to extract a trailing number from a port short name for Phase 2.
# Matches names ending in digits, e.g. "out1" → ("out", 1), "audio_in 2" → ("audio_in ", 2)
_trailing_number_re = re.compile(r'^(.*?)(\d+)$')

# Regex to strip trailing dash-numeric post-fixes from port short names.
# PipeWire/JACK appends identifiers like '-115', '-448' after the channel suffix.
_numeric_postfix_re = re.compile(r'^(.+?)-\d+$')


def _strip_numeric_postfix(name: str) -> str:
    """Strip a trailing dash-numeric post-fix from a port name.

    PipeWire/JACK sometimes appends numeric identifiers after the channel
    suffix (e.g. 'output_FL-115').  This strips the '-NNN' suffix so the
    name can be matched by Phase 1 L/R suffix detection.

    Returns the original name unchanged if no dash-numeric post-fix is found.
    """
    m = _numeric_postfix_re.match(name)
    return m.group(1) if m else name


def detect_stereo_pairs(
    ports: list,
    pair_suffixes: List[Tuple[str, str]] | None = None,
) -> Tuple[List[Tuple], List]:
    """Group audio ports into stereo pairs and return unpaired ports.

    Uses a two-phase approach:

    **Phase 1 — Explicit L/R suffix matching (case-insensitive):**
    Ports whose short_name ends with a recognised left/right suffix pair
    are paired when they share the same base name (the part before the
    suffix). Matching is case-insensitive: port names are lowercased before
    lookup, so ``Monitor L``, ``monitor l`` and ``MONITOR L`` all pair
    against the ``" l"`` suffix without casing having to be enumerated.

    The default suffix list covers the separators seen in the wild:
    underscore (``_L``/``_R``, ``_FL``/``_FR`` …), space (`` L``/`` R``,
    as emitted by jack_mixer), and dash (``-L``/``-R``). Single-letter
    suffixes always carry their separator so that a bare ``l``/``r`` does
    not match unrelated words such as ``vocal`` or ``center``; the full
    words ``left``/``right`` are unambiguous on their own.

    Longer suffixes are tried first to prevent ``_L`` from greedily
    matching a port whose name actually ends with ``_FL``.

    Phase 1 also handles PipeWire/JACK numeric post-fixes: a port named
    ``output_FL-115`` is treated as if it were ``output_FL`` for suffix
    matching, so it pairs with ``output_FR-116``.  The post-fix is stripped
    via :func:`_strip_numeric_postfix` before checking suffixes.

    **Phase 2 — Consecutive numbered pair matching:**
    Remaining unmatched audio ports are split into *(base, number)* using a
    trailing-number regex.  Ports that share the same base name are grouped
    and paired by consecutive even/odd numbers starting from the lowest
    number in the group: e.g. 1+2, 3+4 (1-based) or 0+1, 2+3 (0-based).
    Both conventions are supported so devices that number channels from 0
    are handled correctly.
    This handles DAW-style port naming (``out1``/``out2``,
    ``Master/audio_out 1``/``2``) as well as hardware interfaces that
    start channel numbering at 0 (e.g. ``L[0]``/``R[1]``).

    MIDI ports are **never** paired — they are always returned as unpaired.

    Args:
        ports: List of PortItem objects (must have ``short_name`` and
            ``is_midi`` attributes, or duck-type equivalents).
        pair_suffixes: Optional list of ``(left_suffix, right_suffix)``
            tuples for Phase 1.  Defaults to
            :data:`_DEFAULT_STEREO_PAIR_SUFFIXES`.  Suffixes are matched
            case-insensitively, so callers may pass any casing.

    Returns:
        A tuple of ``(pairs, unpaired)`` where *pairs* is a list of
        ``(left_port, right_port)`` tuples and *unpaired* is a list of
        ports that could not be paired.
    """
    if pair_suffixes is None:
        pair_suffixes = _DEFAULT_STEREO_PAIR_SUFFIXES

    # Separate audio from MIDI ports — MIDI never gets bulk areas.
    audio_ports: list = []
    unpaired: list = []
    for port in ports:
        if getattr(port, 'is_midi', False):
            unpaired.append(port)
        else:
            audio_ports.append(port)

    # Sort audio ports by natural key for deterministic ordering.
    audio_ports_sorted = sorted(audio_ports, key=natural_sort_key_for_port_item)

    pairs: List[Tuple] = []
    matched: set = set()  # indices into audio_ports_sorted

    # ------------------------------------------------------------------
    # Phase 1: Explicit L/R suffix matching (case-insensitive)
    # ------------------------------------------------------------------
    # Build a multi-valued lookup keyed on the lowercased name so that
    # 'Monitor L', 'monitor L', 'MONITOR L' all resolve to the same key.
    # Both the original short_name and its numeric-postfix-stripped form
    # are registered so that ports like "output_FL-115" can be found
    # via the key "output_fl".
    name_to_indices: dict[str, list[int]] = {}
    for idx, port in enumerate(audio_ports_sorted):
        if idx in matched:
            continue
        for name in (port.short_name, _strip_numeric_postfix(port.short_name)):
            name_to_indices.setdefault(name.lower(), []).append(idx)

    # Lowercase the suffixes once so the per-port endswith() checks don't
    # redo the work on every iteration; suffixes in
    # _DEFAULT_STEREO_PAIR_SUFFIXES are already lowercase, but a caller may
    # pass mixed-case custom suffixes.
    norm_suffixes = [(ls.lower(), rs.lower()) for ls, rs in pair_suffixes]

    for left_suf, right_suf in norm_suffixes:
        for idx, port in enumerate(audio_ports_sorted):
            if idx in matched:
                continue
            short = port.short_name
            stripped = _strip_numeric_postfix(short)
            short_l = short.lower()
            stripped_l = stripped.lower()

            # Determine which name variant matches the left suffix
            match_name = None
            if short_l.endswith(left_suf):
                match_name = short_l
            elif stripped_l != short_l and stripped_l.endswith(left_suf):
                match_name = stripped_l

            if match_name is None:
                continue

            base = match_name[: -len(left_suf)]
            candidate_right = base + right_suf

            # Find first unmatched port that resolves to candidate_right
            right_idx = None
            for ri in name_to_indices.get(candidate_right, []):
                if ri not in matched and ri != idx:
                    right_idx = ri
                    break

            if right_idx is not None:
                pairs.append((port, audio_ports_sorted[right_idx]))
                matched.add(idx)
                matched.add(right_idx)
                # Clean up lookup: remove matched indices from all lists
                for key in list(name_to_indices.keys()):
                    name_to_indices[key] = [
                        i for i in name_to_indices[key] if i not in (idx, right_idx)
                    ]
                    if not name_to_indices[key]:
                        del name_to_indices[key]

    # ------------------------------------------------------------------
    # Phase 2: Consecutive numbered pair matching
    # ------------------------------------------------------------------
    # Collect remaining unmatched audio ports and extract (base, number).
    remaining: list = []
    for idx, port in enumerate(audio_ports_sorted):
        if idx not in matched:
            remaining.append(port)

    # Group by base name
    base_groups: dict[str, list] = {}
    for port in remaining:
        m = _trailing_number_re.match(port.short_name)
        if m:
            base = m.group(1)
            num = int(m.group(2))
            base_groups.setdefault(base, []).append((num, port))

    for base, num_port_list in base_groups.items():
        # Sort by number within the group
        num_port_list.sort(key=lambda x: x[0])
        # Derive the expected parity of the first port from the minimum
        # channel number so both 0-based (0+1, 2+3 …) and 1-based
        # (1+2, 3+4 …) numbering schemes are handled correctly.
        base_parity = num_port_list[0][0] % 2
        i = 0
        while i < len(num_port_list) - 1:
            num_a, port_a = num_port_list[i]
            num_b, port_b = num_port_list[i + 1]
            # Pair consecutive ports: first must have the group's base parity,
            # second must immediately follow (diff == 1).
            if num_a % 2 == base_parity and num_b - num_a == 1:
                pairs.append((port_a, port_b))
                i += 2
            else:
                # port_a cannot be paired — it stays unpaired
                unpaired.append(port_a)
                i += 1
        # Handle last element if the loop ended with an unpaired port
        if i == len(num_port_list) - 1:
            unpaired.append(num_port_list[i][1])

    # Add any remaining unmatched audio ports that weren't in numbered groups
    numbered_ports = set()
    for base, num_port_list in base_groups.items():
        for _, port in num_port_list:
            numbered_ports.add(id(port))

    for port in remaining:
        if id(port) not in numbered_ports:
            unpaired.append(port)

    return pairs, unpaired
