"""
Logging configuration for Cable and Cables applications.

Call setup_logging() once at startup in both Cable.py and connection-manager.py.
Each module should use: logger = logging.getLogger(__name__)
"""

import logging
import os
import sys
import configparser
from typing import List


class JackErrorFilter:
    """Filter stderr to suppress harmless python-jack-client cffi callback assertion errors.

    These errors originate from python-jack-client internals (not from Cable)
    when PipeWire video/non-audio ports trigger JACK callbacks that the library
    cannot handle.  They are benign but very noisy, so we silently drop them.

    DO NOT REMOVE — without this filter the terminal is flooded with traceback
    spam every time a PipeWire client like plasmashell or kwin_wayland appears.
    """

    def __init__(self, original_stderr: object) -> None:
        self.original_stderr = original_stderr
        self._buffer: List[str] = []
        self._in_traceback: bool = False
        self._is_jack_error: bool = False
        self._traceback_lines: List[str] = []

    def write(self, text: str) -> None:
        lines = text.split("\n")

        for i, line in enumerate(lines):
            # Add newline back except for last segment (may be incomplete)
            if i < len(lines) - 1:
                self._process_line(line + "\n")
            elif line:  # Last segment, no newline yet
                self._buffer.append(line)

    def _process_line(self, line: str) -> None:
        # Flush any buffered incomplete line first
        if self._buffer:
            line = "".join(self._buffer) + line
            self._buffer = []

        # Detect start of traceback
        if line.startswith("Traceback (most recent call last):"):
            self._in_traceback = True
            self._is_jack_error = False
            self._traceback_lines = [line]
            return

        if line.startswith("Exception ignored from cffi callback"):
            self._in_traceback = True
            self._is_jack_error = True  # Definitely a jack cffi error
            self._traceback_lines = [line]
            return

        if self._in_traceback:
            self._traceback_lines.append(line)

            # Check if this is a jack-related error
            if "jack.py" in line or "_wrap_port_ptr" in line or "callback_wrapper" in line:
                self._is_jack_error = True

            # End of traceback detection
            if line.startswith("AssertionError") or (line.strip() and not line.startswith(" ") and not line.startswith("File ")):
                self._in_traceback = False
                # Only output if NOT a jack error
                if not self._is_jack_error:
                    for tline in self._traceback_lines:
                        self.original_stderr.write(tline)
                self._traceback_lines = []
                self._is_jack_error = False
            return

        # Normal line - output directly
        self.original_stderr.write(line)

    def flush(self) -> None:
        if self._buffer:
            text = "".join(self._buffer)
            if not self._in_traceback:
                self.original_stderr.write(text)
            self._buffer = []
        self.original_stderr.flush()

    def fileno(self) -> int:
        return self.original_stderr.fileno()

    def isatty(self) -> bool:
        return self.original_stderr.isatty()


def _install_jack_error_filter() -> None:
    """Install the JackErrorFilter on stderr if not already installed."""
    if not isinstance(sys.stderr, JackErrorFilter):
        sys.stderr = JackErrorFilter(sys.stderr)


def _load_verbose_setting() -> bool:
    """Load verbose setting from config file to determine log level."""
    config_file = os.path.expanduser("~/.config/cable/config.ini")
    if os.path.exists(config_file):
        try:
            config = configparser.ConfigParser()
            config.read(config_file, encoding='utf-8')
            if config.has_option('DEFAULT', 'verbose_output'):
                return config.getboolean('DEFAULT', 'verbose_output')
        except (configparser.Error, ValueError):
            pass
    return False  # Default to verbose off


def setup_logging(verbose_override: bool = False) -> None:
    """Configure root logger and install stderr filters.

    Call once at application startup.

    Args:
        verbose_override: If True, force verbose output for this session,
                         regardless of the config setting. This is typically
                         set via -v/--verbose command line flag.

    When verbose_output is False in config (and no override), sets level to WARNING
    so that info/debug messages are suppressed (matching old verbose.py behavior).
    """
    # Command-line override takes precedence over config setting
    if verbose_override:
        verbose = True
    else:
        verbose = _load_verbose_setting()

    # Suppress verbose output when not in a terminal to avoid flooding journalctl
    # (unless explicitly overridden via command line)
    if verbose and not sys.stdout.isatty() and not verbose_override:
        verbose = False

    level = logging.DEBUG if verbose else logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(name)s: %(message)s",
    )

    # Suppress harmless python-jack-client cffi assertion errors on stderr
    _install_jack_error_filter()
