"""Fullscreen-mode orchestration helpers extracted from JackConnectionManager.

``toggle_fullscreen`` was the CCN-45 hotspot: it gathered chrome widgets,
saved their visibility, hid them, disabled all non-current tabs on enter,
then on exit walked the saved map distinguishing chrome widgets (restored
via ``.show()``) from tab pages (restored via ``setTabEnabled``).

The three pure functions here decompose that monolith over explicit
collaborators so the branching can be characterized without a live
QMainWindow.

The host (``JackConnectionManager.toggle_fullscreen``) still owns the
``self._is_fullscreen`` flag and calls ``showFullScreen()/showNormal()``,
but delegates the heavy lifting here.
"""

import logging
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


# ── Chrome gathering ────────────────────────────────────────────────────


def gather_chrome_components(
    main_window: Any, ui_manager: Any
) -> List[Any]:
    """Collect every "chrome" widget the fullscreen mode hides.

    Includes the menu bar, status bar, child toolbars (parent == main
    window), the tab bar, and the audio/midi matrix controls widgets.
    Missing parts are silently skipped.
    """
    from PyQt6.QtWidgets import QToolBar

    components: List[Any] = []

    menu_bar = main_window.menuBar() if hasattr(main_window, "menuBar") else None
    if menu_bar:
        components.append(menu_bar)

    status_bar = main_window.statusBar() if hasattr(main_window, "statusBar") else None
    if status_bar:
        components.append(status_bar)

    if hasattr(main_window, "findChildren"):
        for toolbar in main_window.findChildren(QToolBar):
            if toolbar.parent() == main_window:
                components.append(toolbar)

    tab_widget = getattr(ui_manager, "tab_widget", None)
    tab_bar_method = getattr(tab_widget, "tabBar", None) if tab_widget else None
    if tab_bar_method:
        tab_bar = tab_bar_method()
        if tab_bar:
            components.append(tab_bar)

    for pt in ("midi", "audio"):
        ctrl = getattr(main_window, f"{pt}_matrix_controls_widget", None)
        if ctrl:
            components.append(ctrl)

    return components


# ── Enter fullscreen ────────────────────────────────────────────────────


def enter_fullscreen(
    ctx: Any,
    current_tab_widget: Any,
) -> None:
    """Hide chrome and disable non-current tabs, saving visibility for exit.

    ``ctx`` is duck-typed: it exposes ``main_window``, ``ui_manager``,
    ``tab_manager``, ``visibility_map`` (a dict cleared then repopulated),
    and ``midi_matrix_controls_widget`` / ``audio_matrix_controls_widget``.
    """
    main_window = ctx.main_window
    ui_manager = ctx.ui_manager
    tab_widget = getattr(ui_manager, "tab_widget", None)
    visibility_map: Dict[Any, bool] = ctx.visibility_map
    visibility_map.clear()

    components = gather_chrome_components(main_window, ui_manager)

    matrix_ctrls = [
        getattr(main_window, "midi_matrix_controls_widget", None),
        getattr(main_window, "audio_matrix_controls_widget", None),
    ]

    for widget in components:
        if widget:
            is_matrix_ctrl = widget in matrix_ctrls
            visibility_map[widget] = (
                True if is_matrix_ctrl else widget.isVisible()
            )
            widget.hide()

    if hasattr(ctx, "tab_manager") and ctx.tab_manager is not None:
        ctx.tab_manager.show_bottom_controls(False)

    if tab_widget is not None:
        for i in range(tab_widget.count()):
            tab_page_widget = tab_widget.widget(i)
            if tab_page_widget != current_tab_widget:
                if tab_page_widget not in visibility_map:
                    visibility_map[tab_page_widget] = tab_widget.isTabEnabled(i)
                tab_widget.setTabEnabled(i, False)

    # Special case: graph tab internal controls
    graph_tab_widget = getattr(ui_manager, "graph_tab_widget", None)
    if current_tab_widget == graph_tab_widget and getattr(
        ctx, "toggle_graph_internal_controls", None
    ) is not None:
        ctx.toggle_graph_internal_controls(False)


# ── Exit fullscreen ──────────────────────────────────────────────────────


def exit_fullscreen(
    ctx: Any,
    current_tab_widget: Any,
) -> None:
    """Restore chrome visibility and re-enable tabs saved by ``enter_fullscreen``.

    Distinguishes chrome widgets (restored via ``.show()``) from tab pages
    (restored via ``setTabEnabled``, skipping the current tab). Clears
    ``ctx.visibility_map`` as the final step.
    """
    main_window = ctx.main_window
    ui_manager = ctx.ui_manager
    tab_widget = getattr(ui_manager, "tab_widget", None)
    visibility_map: Dict[Any, bool] = ctx.visibility_map

    # Special case: graph tab internal controls
    graph_tab_widget = getattr(ui_manager, "graph_tab_widget", None)
    if current_tab_widget == graph_tab_widget and getattr(
        ctx, "toggle_graph_internal_controls", None
    ) is not None:
        ctx.toggle_graph_internal_controls(True)

    chrome_on_exit = gather_chrome_components(main_window, ui_manager)

    for item_widget, original_state in list(visibility_map.items()):
        if item_widget in chrome_on_exit:
            if item_widget and original_state:
                item_widget.show()
        else:
            if tab_widget is None:
                continue
            tab_index_to_restore = -1
            for i in range(tab_widget.count()):
                if tab_widget.widget(i) == item_widget:
                    tab_index_to_restore = i
                    break

            if (
                tab_index_to_restore != -1
                and tab_widget.widget(tab_index_to_restore)
                != current_tab_widget
            ):
                if original_state:
                    tab_widget.setTabEnabled(tab_index_to_restore, True)

    visibility_map.clear()
