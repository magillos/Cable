"""Stylesheet refresh + button-animation helpers extracted from JackConnectionManager.

The two functions here used to be long methods on the god class:

  * ``refresh_tab_stylesheets`` — re-applies every tab stylesheet that stores
    colors at init time (port trees, connection views, pw-top, latency tab,
    buttons). It was the CCN-26 hotspot because it cascaded styling across
    ~20 widgets.

  * ``animate_button_press`` — a 150ms visual "pressed" style flash that
    restores the original stylesheet on a singleShot timer.

Both are pure functions over a duck-typed ``target`` (which exposes all the
widget attributes the original ``self`` did) and explicit collaborators
(``ui_manager``, ``config_manager``, ``color_scheme``). They can be
characterized without a live Qt widget hierarchy.
"""

import logging
from typing import Any, Optional, TYPE_CHECKING

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor

from cable_core import config_keys as keys

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QPushButton

logger = logging.getLogger(__name__)


# Widget attribute tuples centralised so the host can also iterate them for
# force-repaint without re-listing them.
_AUDIO_MIDI_TREES = (
    "input_tree",
    "output_tree",
    "midi_input_tree",
    "midi_output_tree",
)
_CONNECTION_VIEWS = (
    "connection_view",
    "midi_connection_view",
)
_LATENCY_BUTTONS = (
    "latency_refresh_button",
    "latency_run_button",
    "latency_stop_button",
    "latency_apply_offset_button",
)
_LABEL_ATTRS = (
    "audio_input_label",
    "audio_output_label",
    "midi_input_label",
    "midi_output_label",
)
_LATENCY_DURATION_ATTRS = (
    "latency_duration_text_before",
    "latency_duration_text_after",
    "latency_duration_spinbox",
)
_LATENCY_REPAINT_TAIL = (
    "latency_instructions_label",
    *_LATENCY_DURATION_ATTRS,
    *_LATENCY_BUTTONS,
)


def refresh_tab_stylesheets(
    target: Any, ui_manager: Any, config_manager: Any
) -> None:
    """Re-apply every tab stylesheet that stores colors at init time.

    ``target`` is any object exposing the same widget attributes as the
    original JackConnectionManager (port trees, connection views, pw-top
    text, latency widgets, etc.). A missing attribute is treated as a
    missing widget and skipped.
    """
    if ui_manager is None:
        return

    mgr = ui_manager
    tree_style = mgr.list_stylesheet()
    text_color = mgr.text_color.name()
    bg_color = mgr.background_color.name()

    _apply_tree_and_view_styles(target, mgr, tree_style, text_color, bg_color)
    _apply_latency_styles(target, mgr, text_color, bg_color, config_manager)

    # Force repaint on all updated widgets so the new stylesheet takes effect.
    for attr in (
        *_AUDIO_MIDI_TREES,
        "pwtop_text",
        "latency_results_text",
        *_LATENCY_REPAINT_TAIL,
    ):
        w = getattr(target, attr, None)
        if w is not None:
            w.update()


def _apply_stylesheet_to_attrs(target: Any, attrs: tuple, style: str) -> None:
    """Apply ``style`` to every widget attribute in ``attrs`` that exists."""
    for attr in attrs:
        widget = getattr(target, attr, None)
        if widget is not None:
            widget.setStyleSheet(style)


def _apply_tree_header_foreground(target: Any, header_color: QColor) -> None:
    """Set the header foreground color on every port tree that has a header."""
    for attr in _AUDIO_MIDI_TREES:
        tree = getattr(target, attr, None)
        if tree is not None and tree.headerItem() is not None:
            for col in range(tree.columnCount()):
                tree.headerItem().setForeground(col, header_color)


def _apply_tree_and_view_styles(
    target: Any, mgr: Any, tree_style: str, text_color: str, bg_color: str
) -> None:
    """Apply port-tree, header, connection-view and tab-label stylesheets."""
    # --- Audio / MIDI port trees ---
    _apply_stylesheet_to_attrs(target, _AUDIO_MIDI_TREES, tree_style)

    # Tree header foreground
    header_color = QColor("#ffffff") if mgr.dark_mode else QColor("#000000")
    _apply_tree_header_foreground(target, header_color)

    # Connection views
    _apply_stylesheet_to_attrs(
        target, _CONNECTION_VIEWS, f"background: {bg_color}; border: none;"
    )

    # Tab labels (set in TabUIManager with inline stylesheet)
    _apply_stylesheet_to_attrs(target, _LABEL_ATTRS, f"color: {text_color};")


def _apply_text_edit_style(
    target: Any, attr: str, bg_color: str, text_color: str, font_size: str
) -> None:
    """Apply a monospace QTextEdit stylesheet to a single widget attribute."""
    widget = getattr(target, attr, None)
    if widget is not None:
        widget.setStyleSheet(
            f"""
                QTextEdit {{
                    background-color: {bg_color};
                    color: {text_color};
                    font-family: monospace;
                    font-size: {font_size};
                }}
            """
        )


def _apply_latency_styles(
    target: Any, mgr: Any, text_color: str, bg_color: str, config_manager: Any
) -> None:
    """Apply pw-top, latency results/combos/buttons and checkbox stylesheets."""
    # --- pw-top tab ---
    pwtop_font_size = config_manager.get_int_setting(keys.PWTOP_FONT_SIZE_PT, 13)
    _apply_text_edit_style(target, "pwtop_text", bg_color, text_color, f"{pwtop_font_size}pt")

    # --- Latency tab ---
    _apply_text_edit_style(target, "latency_results_text", bg_color, text_color, "14pt")
    _apply_stylesheet_to_attrs(
        target,
        ("latency_input_combo", "latency_output_combo"),
        mgr.list_stylesheet(),
    )
    _apply_stylesheet_to_attrs(
        target, ("latency_raw_output_checkbox",), f"color: {text_color};"
    )
    _apply_stylesheet_to_attrs(
        target, ("latency_instructions_label",), f"color: {text_color}; font-size: 11pt;"
    )
    _apply_stylesheet_to_attrs(
        target, _LATENCY_DURATION_ATTRS, f"color: {text_color}; font-size: 11pt;"
    )

    # Latency buttons — re-apply the live button stylesheet
    _apply_stylesheet_to_attrs(target, _LATENCY_BUTTONS, mgr.button_stylesheet())


def animate_button_press(
    button: "Optional[QPushButton]",
    color_scheme: Any,
    timer_factory: Any = QTimer,
) -> None:
    """Apply a 150ms "pressed" highlight flash to ``button``.

    Skips the animation if the button already uses an inline ``inset`` style
    (another press in flight). Restores the original stylesheet via a
    ``singleShot(150, ...)`` timer. ``timer_factory`` is injectable so tests
    do not need a real Qt event loop.
    """
    if not button:
        return

    original_style = button.styleSheet()

    if "inset" in original_style:
        return

    pressed_style = f"""
        QPushButton {{
            background-color: {color_scheme["highlight"].name()};
            color: {color_scheme["text"].name()};
            border: 2px inset {color_scheme["highlight"].darker(120).name()};
        }}
    """
    button.setStyleSheet(pressed_style)

    timer_factory.singleShot(150, lambda: button.setStyleSheet(original_style))
