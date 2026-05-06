"""
QGraphicsView providing zoom, pan, context menus, and wallpaper for the graph scene.

Wallpaper management is delegated to :class:`WallpaperManager` and virtual sink
operations to :class:`VirtualSinkCreator`.
"""

from PyQt6.QtWidgets import (
    QGraphicsView,
    QMenu,
    QWidget,
)
from PyQt6.QtGui import (
    QPainter,
    QCursor,
    QMouseEvent,
    QWheelEvent,
    QKeyEvent,
    QContextMenuEvent,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from typing import Optional

import logging

logger = logging.getLogger(__name__)

from .gui_scene import JackGraphScene
from . import constants
from .wallpaper_manager import WallpaperManager
from .virtual_sink_creator import VirtualSinkCreator


class JackGraphView(QGraphicsView):
    """The view widget for the JACK graph scene."""

    # Signal to notify the main window to toggle fullscreen
    fullscreen_request_signal = pyqtSignal()
    zoom_changed = pyqtSignal(float)  # Signal to emit when zoom level changes

    def __init__(self, scene: JackGraphScene, parent: Optional[QWidget] = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._default_drag_mode = QGraphicsView.DragMode.RubberBandDrag
        self.setDragMode(self._default_drag_mode)
        self._is_panning = False
        self._last_pan_pos = None
        self._rubber_band_used = False
        self.rubberBandChanged.connect(self._on_rubber_band_changed)

        # Delegate wallpaper management to WallpaperManager
        self.wallpaper_mgr = WallpaperManager(scene)

        # Delegate virtual sink operations to VirtualSinkCreator
        self.virtual_sink_creator = VirtualSinkCreator(scene, self)

        # Connect scene changes to scrollbar update
        if self.scene():
            self.scene().changed.connect(self._update_scrollbar_visibility)

        # Set the initial cursor to the standard arrow
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        # Reduced zoom factor for more precise control
        self.zoom_factor_base = (
            1.05  # Changed from 1.15 for slower, more controlled zooming
        )
        self.min_zoom_scale = 0.1  # Minimum zoom level (e.g., 10%)
        self.max_zoom_scale = 5.0  # Maximum zoom level (e.g., 500%)

    def _update_scrollbar_visibility(self) -> None:
        """
        Updates the visibility of scrollbars based on whether all scene items
        are currently visible within the viewport.
        """
        items_rect = self.scene().itemsBoundingRect()

        # Create a padded version of the items bounding rect
        padded_items_rect = items_rect.adjusted(
            -constants.VIEW_PADDING,
            -constants.VIEW_PADDING,
            constants.VIEW_PADDING,
            constants.VIEW_PADDING,
        )

        # Ensure the sceneRect is updated to encompass all items with padding.
        # This is crucial for QGraphicsView to correctly assess scrollbar needs and for centering.
        if self.scene().sceneRect() != padded_items_rect:
            self.scene().setSceneRect(padded_items_rect)

        # For the contains check, we use the scene's actual rect, which is now padded.
        scene_rect_for_check = self.scene().sceneRect()

        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()

        # A small margin to prevent floating point inaccuracies from showing scrollbars unnecessarily
        margin = 1.0
        # Epsilon for floating point comparisons.
        # We effectively make the visible_rect slightly larger for the contains check.
        # This ensures that if the scene_rect_for_check is equal to, or infinitesimally larger
        # than visible_rect due to float precision, it's still considered contained.
        epsilon = 0.1  # A small tolerance value
        # Make the viewport rect slightly larger for a more lenient contains check
        comparison_viewport_rect = visible_rect.adjusted(
            -epsilon, -epsilon, epsilon, epsilon
        )

        if comparison_viewport_rect.contains(scene_rect_for_check):
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel events for zooming and scrolling."""
        # Check if Ctrl key is pressed for zooming
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Zoom with mouse wheel when Ctrl is pressed
            zoom_factor = self.zoom_factor_base

            # Get the angle delta to determine zoom direction
            angle_delta = event.angleDelta().y()

            # Apply a dampening factor based on the delta to smooth out rapid scrolling
            if abs(angle_delta) > 120:  # If scrolling quickly
                zoom_factor = 1.0 + (zoom_factor - 1.0) * 0.7  # Dampen the zoom factor

            current_scale = self.transform().m11()

            if angle_delta > 0:
                # Zoom in
                if current_scale * zoom_factor <= self.max_zoom_scale:
                    self.scale(zoom_factor, zoom_factor)
                elif current_scale < self.max_zoom_scale:  # If not at max, scale to max
                    self.scale(
                        self.max_zoom_scale / current_scale,
                        self.max_zoom_scale / current_scale,
                    )
            else:
                # Zoom out
                if current_scale / zoom_factor >= self.min_zoom_scale:
                    self.scale(1.0 / zoom_factor, 1.0 / zoom_factor)
                elif current_scale > self.min_zoom_scale:  # If not at min, scale to min
                    self.scale(
                        self.min_zoom_scale / current_scale,
                        self.min_zoom_scale / current_scale,
                    )
            self.zoom_changed.emit(self.get_zoom_level())  # Emit signal
            # Accept the event to prevent default handling
            event.accept()
        else:
            # No modifier key, use default scrolling behavior
            super().wheelEvent(event)
        # Update scrollbars after zoom, as visible area might change relative to scene content
        self._update_scrollbar_visibility()

    def _on_rubber_band_changed(
        self, rubberBandRect, fromScenePoint, toScenePoint
    ) -> None:
        """Track whether a rubber band drag actually occurred."""
        if not rubberBandRect.isNull():
            self._rubber_band_used = True

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Override mouse press to set closed hand cursor during drag or initiate panning."""
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.viewport().setCursor(
                Qt.CursorShape.OpenHandCursor
            )  # Indicate grabbable
            event.accept()  # Consume the event to prevent RubberBandDrag
        else:
            # Check if there's an item under cursor - only allow rubber band from empty space
            item_under_cursor = self.itemAt(event.pos())
            if (
                event.button() == Qt.MouseButton.LeftButton
                and item_under_cursor is not None
            ):
                # If clicking on an item, temporarily disable rubber band drag
                original_drag_mode = self.dragMode()
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                super().mousePressEvent(event)
                # Restore drag mode after event processing
                self.setDragMode(original_drag_mode)
                event.accept()
            else:
                super().mousePressEvent(
                    event
                )  # Call base implementation for selection etc.
            # Original logic for ScrollHandDrag if it was set some other way (though less likely now)
            if (
                self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move for panning."""
        if self._is_panning and self._last_pan_pos is not None:
            self.viewport().setCursor(
                Qt.CursorShape.ClosedHandCursor
            )  # Indicate grabbing
            delta = event.pos() - self._last_pan_pos
            self._last_pan_pos = event.pos()

            # Scroll the view
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            hs.setValue(hs.value() - delta.x())
            vs.setValue(vs.value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Override mouse release to reset cursor after drag or panning."""
        if self._is_panning and (
            event.button() == Qt.MouseButton.LeftButton
            or event.button() == Qt.MouseButton.MiddleButton
        ):
            self._is_panning = False
            self._last_pan_pos = None
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)  # Reset to arrow
            event.accept()
        else:
            super().mouseReleaseEvent(event)  # Call base implementation
            # Original logic for ScrollHandDrag if it was set some other way
            if (
                self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.viewport().setCursor(
                    Qt.CursorShape.ArrowCursor
                )  # Explicitly set back to Arrow

            # After rubber band drag, deselect ports and bulk areas so
            # only nodes remain selected.  Regular clicks are unaffected.
            if self._rubber_band_used and event.button() == Qt.MouseButton.LeftButton:
                self._rubber_band_used = False
                from .node_item import NodeItem

                for item in self.scene().selectedItems():
                    if not isinstance(item, NodeItem):
                        item.setSelected(False)

        # Update scrollbars after mouse release (e.g., after dragging an item or panning)
        self._update_scrollbar_visibility()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Handle mouse double-click events.
        Allows items in the scene to handle it first (e.g., for folding nodes).
        If not handled by an item, toggles fullscreen.
        """
        # First, let the scene and its items process the double-click.
        # This allows NodeItem to handle folding on header double-click.
        super().mouseDoubleClickEvent(event)

        # If the event was accepted by an item in the scene (e.g., NodeItem for folding),
        # then don't proceed with the view's default double-click action (fullscreen).
        if event.isAccepted():
            return

        # If the event was not accepted by an item, and it's a left button double-click,
        # then proceed with the fullscreen toggle.
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if the click was on an empty area of the scene.
            # itemAt() returns None if no item is at the event's position.
            item_under_cursor = self.itemAt(event.pos())
            if item_under_cursor is None:
                self.fullscreen_request_signal.emit()
                event.accept()  # Accept it here as the view handled it.
            # If an item was under cursor but didn't accept the event,
            # we also don't toggle fullscreen from the view level.
            # This prevents fullscreen if double-clicking a non-interactive part of an item.

    def zoom_in(self) -> None:
        """Scales the view to zoom in."""
        # Use a consistent zoom factor for button and shortcut zooming
        zoom_factor = self.zoom_factor_base
        current_scale = self.transform().m11()
        if current_scale * zoom_factor <= self.max_zoom_scale:
            self.scale(zoom_factor, zoom_factor)
        elif current_scale < self.max_zoom_scale:
            self.scale(
                self.max_zoom_scale / current_scale, self.max_zoom_scale / current_scale
            )
        self.zoom_changed.emit(self.get_zoom_level())  # Emit signal

    def zoom_out(self) -> None:
        """Scales the view to zoom out."""
        # Use a consistent zoom factor for button and shortcut zooming
        zoom_factor = 1.0 / self.zoom_factor_base  # This is actually scale_down_factor
        current_scale = self.transform().m11()
        scale_down_factor = 1.0 / self.zoom_factor_base

        if current_scale * scale_down_factor >= self.min_zoom_scale:
            self.scale(scale_down_factor, scale_down_factor)
        elif current_scale > self.min_zoom_scale:
            self.scale(
                self.min_zoom_scale / current_scale, self.min_zoom_scale / current_scale
            )
        self.zoom_changed.emit(self.get_zoom_level())  # Emit signal

    def get_zoom_level(self) -> float:
        """Returns the current horizontal scale factor (zoom level) of the view."""
        return self.transform().m11()  # m11 is horizontal scale, m22 is vertical

    def set_zoom_level(self, zoom_level: float) -> None:
        """Sets the view's zoom level to the specified value.

        Args:
            zoom_level (float): The desired zoom level. e.g., 1.0 for normal size.
        """
        # It's important to reset the transform before applying a new absolute scale
        # to avoid cumulative scaling issues if this method is called multiple times.
        # However, QGraphicsView doesn't have a simple setScale().
        # We need to scale relative to the current scale or reset and scale.
        # Let's reset and then scale to the desired absolute level.
        current_transform = self.transform()
        self.resetTransform()  # Resets to identity matrix
        # Need to re-apply translation if any was part of the original transform
        # For simplicity, we assume AnchorUnderMouse or AnchorViewCenter handles positioning.
        # If not, we might need to preserve and re-apply the translation part.

        # Clamp the zoom_level to min/max
        clamped_zoom_level = max(
            self.min_zoom_scale, min(zoom_level, self.max_zoom_scale)
        )

        self.scale(clamped_zoom_level, clamped_zoom_level)
        # A more robust way might involve QTransform.fromScale and setTransform,
        # but self.scale() is the standard QGraphicsView method.
        # If issues arise with panning/centering, this might need adjustment.
        self._update_scrollbar_visibility()  # Update after explicit zoom set
        self.zoom_changed.emit(self.get_zoom_level())  # Emit signal

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_U and (
            event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            graph_mw = self.scene().parent()
            if graph_mw and getattr(graph_mw, "untangle_action", None) is not None:
                graph_mw.untangle_action.trigger()
                event.accept()
            else:
                super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_F:
            self.fullscreen_request_signal.emit()
            event.accept()  # Indicate event was handled
        elif event.key() == Qt.Key.Key_Escape:
            # Only emit the signal if the window is currently fullscreen.
            # self.window() gets the top-level window (QMainWindow), which has isFullScreen().
            if self.window().isFullScreen():
                self.fullscreen_request_signal.emit()  # Request a toggle, which will exit fullscreen
            event.accept()  # Indicate event was handled, even if not fullscreen (to consume Esc)
        else:
            super().keyPressEvent(event)  # Pass to base class for other keys

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Show a context menu when right-clicking on empty areas of the canvas."""
        item_under_cursor = self.itemAt(event.pos())

        if item_under_cursor is None:
            menu = QMenu(self)
            create_combined_action = menu.addAction("Create virtual sink/source")
            unload_all_sinks_action = menu.addAction("Unload all sinks")
            remove_saved_sinks_action = menu.addAction("Remove all saved virtual sinks")
            menu.addSeparator()
            unhide_all_nodes_action = menu.addAction("Unhide all nodes")
            unsplit_all_nodes_action = menu.addAction("Unsplit all nodes")

            main_window = self.scene().parent()
            if main_window is not None:
                unsplit_all_nodes_action.setEnabled(
                    getattr(main_window, "current_untangle_setting", -1) != 0
                )

            menu.addSeparator()
            wallpaper_action = menu.addAction("Wallpaper")

            clicked_scene_pos = self.mapToScene(event.pos())
            logger.debug(f"Context menu clicked at scene position: {clicked_scene_pos}")
            create_combined_action.triggered.connect(
                lambda checked=False, pos=clicked_scene_pos: (
                    self.virtual_sink_creator.show_combined_sink_dialog(pos)
                )
            )
            unload_all_sinks_action.triggered.connect(
                self.virtual_sink_creator.unload_all_sinks
            )
            remove_saved_sinks_action.triggered.connect(
                self.virtual_sink_creator.remove_all_saved_virtual_sinks
            )
            unhide_all_nodes_action.triggered.connect(self._unhide_all_nodes)
            unsplit_all_nodes_action.triggered.connect(self._unsplit_all_nodes)
            wallpaper_action.triggered.connect(
                lambda: self.wallpaper_mgr.show_wallpaper_dialog(self)
            )

            menu.exec(event.globalPos())
            event.accept()
        else:
            super().contextMenuEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        """Override to draw wallpaper without tiling."""
        super().drawBackground(painter, rect)
        self.wallpaper_mgr.draw_background(painter, rect)


    def _unhide_all_nodes(self) -> None:
        """Unhide all hidden nodes in the graph."""
        try:
            scene = self.scene()
            if not scene:
                return

            # Get the connection_manager from the scene
            connection_manager = getattr(scene, "connection_manager", None)
            if connection_manager is not None:
                node_visibility_mgr = getattr(connection_manager, "node_visibility_manager", None)
                if node_visibility_mgr is not None:
                    # Only unhide nodes in the graph tab, not other tabs
                    connection_manager.node_visibility_manager.unhide_all_nodes(
                        tab_type="graph"
                    )
                    logger.info("All nodes have been unhidden in graph")
                else:
                    logger.warning("NodeVisibilityManager not available")
            else:
                logger.warning("Connection manager not available")

        except Exception as e:
            logger.error(f"Error unhiding all nodes: {e}")

    def _unsplit_all_nodes(self) -> None:
        """Unsplit all split nodes in the graph and reapply active untangle layout."""
        try:
            scene = self.scene()
            if not scene:
                return

            # Find all nodes that are split origins
            from .node_item import NodeItem

            split_nodes = []
            for item in scene.items():
                if isinstance(item, NodeItem) and getattr(
                    item, "is_split_origin", False
                ):
                    split_nodes.append(item)

            if not split_nodes:
                logger.debug("No split nodes to unsplit")
                return

            # Unsplit each node
            unsplit_count = 0
            for node in split_nodes:
                try:
                    split_handler = getattr(node, "split_handler", None)
                    if split_handler is not None:
                        split_handler.unsplit_node(save_state=True)
                        unsplit_count += 1
                except Exception as e:
                    logger.error(f"Error unsplitting node {node.client_name}: {e}")

            logger.info(f"Successfully unsplit {unsplit_count} node(s)")

            # Reapply currently active untangle layout
            main_window = self.scene().parent()
            if main_window is not None:
                current_untangle = getattr(main_window, "current_untangle_setting", -1)
                apply_layout = getattr(main_window, "_apply_untangle_layout", None)
                if apply_layout is not None:
                    # If there's an active untangle setting, reapply it
                    if (
                        main_window.untangle_button_clicked
                        and main_window.current_untangle_setting != -1
                    ):  # -1 is ORIGINAL_LAYOUT
                        logger.debug(
                            f"Reapplying active untangle layout: {main_window.current_untangle_setting}"
                        )
                        main_window._apply_untangle_layout(
                            main_window.current_untangle_setting
                        )
                    else:
                        # If no untangle option is active, apply Auto layout
                        logger.debug("No active untangle layout, applying Auto layout")
                        main_window._apply_untangle_layout(-2)  # -2 is AUTO_LAYOUT

        except Exception as e:
            logger.error(f"Error unsplitting all nodes: {e}")

    def _request_save_layout(self) -> None:
        """Signal to the main window to save the current layout."""
        # We'll emit a signal that can be connected to a method in MainWindow
        # Since we don't have a dedicated signal for this yet, we'll create one
        # For now, let's try to access the parent MainWindow and call its method directly
        scene = self.scene()
        if scene is not None:
            main_window = scene.parent()
            if main_window is not None and getattr(main_window, "save_current_layout", None) is not None:
                main_window.save_current_layout()
                logger.debug("Requested to save current layout")