from PyQt6.QtWidgets import QGraphicsView, QMenu
from PyQt6.QtGui import QPainter, QCursor, QMouseEvent # Import QMouseEvent
from PyQt6.QtCore import Qt, pyqtSignal

# Import JackGraphScene for type hinting
from .gui_scene import JackGraphScene
from . import constants # Import constants

class JackGraphView(QGraphicsView):
    """The view widget for the JACK graph scene."""
    # Signal to notify the main window to toggle fullscreen
    fullscreen_request_signal = pyqtSignal()
    zoom_changed = pyqtSignal(float) # Signal to emit when zoom level changes
 
    def __init__(self, scene: JackGraphScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Set DragMode - RubberBandDrag allows selecting items, ScrollHandDrag allows panning.
        # Let's keep RubberBandDrag as primary and rely on default panning or future implementation.
        # If panning is the priority, ScrollHandDrag should be uncommented and RubberBandDrag commented.
        self._default_drag_mode = QGraphicsView.DragMode.RubberBandDrag
        self.setDragMode(self._default_drag_mode) # Allow selecting items
        # self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag) # Enable panning with mouse drag
        self._is_panning = False
        self._last_pan_pos = None

        # Connect scene changes to scrollbar update
        if self.scene():
            self.scene().changed.connect(self._update_scrollbar_visibility)

        # Set the initial cursor to the standard arrow
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        
        # Reduced zoom factor for more precise control
        self.zoom_factor_base = 1.05  # Changed from 1.15 for slower, more controlled zooming
        self.min_zoom_scale = 0.1  # Minimum zoom level (e.g., 10%)
        self.max_zoom_scale = 5.0  # Maximum zoom level (e.g., 500%)


    def _update_scrollbar_visibility(self):
        """
        Updates the visibility of scrollbars based on whether all scene items
        are currently visible within the viewport.
        """
        items_rect = self.scene().itemsBoundingRect()
        
        # Create a padded version of the items bounding rect
        padded_items_rect = items_rect.adjusted(-constants.VIEW_PADDING,
                                                -constants.VIEW_PADDING,
                                                constants.VIEW_PADDING,
                                                constants.VIEW_PADDING)

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
        epsilon = 0.1 # A small tolerance value
        # Make the viewport rect slightly larger for a more lenient contains check
        comparison_viewport_rect = visible_rect.adjusted(-epsilon, -epsilon, epsilon, epsilon)

        if comparison_viewport_rect.contains(scene_rect_for_check):
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def wheelEvent(self, event):
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
                elif current_scale < self.max_zoom_scale: # If not at max, scale to max
                    self.scale(self.max_zoom_scale / current_scale, self.max_zoom_scale / current_scale)
            else:
                # Zoom out
                if current_scale / zoom_factor >= self.min_zoom_scale:
                    self.scale(1.0 / zoom_factor, 1.0 / zoom_factor)
                elif current_scale > self.min_zoom_scale: # If not at min, scale to min
                    self.scale(self.min_zoom_scale / current_scale, self.min_zoom_scale / current_scale)
            self.zoom_changed.emit(self.get_zoom_level()) # Emit signal
            # Accept the event to prevent default handling
            event.accept()
        else:
            # No modifier key, use default scrolling behavior
            super().wheelEvent(event)
        # Update scrollbars after zoom, as visible area might change relative to scene content
        self._update_scrollbar_visibility()

    def mousePressEvent(self, event: QMouseEvent):
        """Override mouse press to set closed hand cursor during drag or initiate panning."""
        if event.button() == Qt.MouseButton.LeftButton and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor) # Indicate grabbable
            event.accept() # Consume the event to prevent RubberBandDrag
        else:
            super().mousePressEvent(event) # Call base implementation for selection etc.
            # Original logic for ScrollHandDrag if it was set some other way (though less likely now)
            if self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag and event.button() == Qt.MouseButton.LeftButton:
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for panning."""
        if self._is_panning and self._last_pan_pos is not None:
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor) # Indicate grabbing
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

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Override mouse release to reset cursor after drag or panning."""
        if self._is_panning and event.button() == Qt.MouseButton.LeftButton:
            self._is_panning = False
            self._last_pan_pos = None
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor) # Reset to arrow
            event.accept()
        else:
            super().mouseReleaseEvent(event) # Call base implementation
            # Original logic for ScrollHandDrag if it was set some other way
            if self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag and event.button() == Qt.MouseButton.LeftButton:
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor) # Explicitly set back to Arrow
        
        # Update scrollbars after mouse release (e.g., after dragging an item or panning)
        self._update_scrollbar_visibility()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
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
                event.accept() # Accept it here as the view handled it.
            # If an item was under cursor but didn't accept the event,
            # we also don't toggle fullscreen from the view level.
            # This prevents fullscreen if double-clicking a non-interactive part of an item.

    def zoom_in(self):
        """Scales the view to zoom in."""
        # Use a consistent zoom factor for button and shortcut zooming
        zoom_factor = self.zoom_factor_base
        current_scale = self.transform().m11()
        if current_scale * zoom_factor <= self.max_zoom_scale:
            self.scale(zoom_factor, zoom_factor)
        elif current_scale < self.max_zoom_scale:
            self.scale(self.max_zoom_scale / current_scale, self.max_zoom_scale / current_scale)
        self.zoom_changed.emit(self.get_zoom_level()) # Emit signal
 
    def zoom_out(self):
        """Scales the view to zoom out."""
        # Use a consistent zoom factor for button and shortcut zooming
        zoom_factor = 1.0 / self.zoom_factor_base # This is actually scale_down_factor
        current_scale = self.transform().m11()
        scale_down_factor = 1.0 / self.zoom_factor_base

        if current_scale * scale_down_factor >= self.min_zoom_scale:
            self.scale(scale_down_factor, scale_down_factor)
        elif current_scale > self.min_zoom_scale:
             self.scale(self.min_zoom_scale / current_scale, self.min_zoom_scale / current_scale)
        self.zoom_changed.emit(self.get_zoom_level()) # Emit signal

    def get_zoom_level(self):
        """Returns the current horizontal scale factor (zoom level) of the view."""
        return self.transform().m11() # m11 is horizontal scale, m22 is vertical

    def set_zoom_level(self, zoom_level):
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
        self.resetTransform() # Resets to identity matrix
        # Need to re-apply translation if any was part of the original transform
        # For simplicity, we assume AnchorUnderMouse or AnchorViewCenter handles positioning.
        # If not, we might need to preserve and re-apply the translation part.
        
        # Clamp the zoom_level to min/max
        clamped_zoom_level = max(self.min_zoom_scale, min(zoom_level, self.max_zoom_scale))
        
        self.scale(clamped_zoom_level, clamped_zoom_level)
        # A more robust way might involve QTransform.fromScale and setTransform,
        # but self.scale() is the standard QGraphicsView method.
        # If issues arise with panning/centering, this might need adjustment.
        self._update_scrollbar_visibility() # Update after explicit zoom set
        self.zoom_changed.emit(self.get_zoom_level()) # Emit signal
 
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F:
            self.fullscreen_request_signal.emit()
            event.accept() # Indicate event was handled
        elif event.key() == Qt.Key.Key_Escape:
            # Only emit the signal if the window is currently fullscreen.
            # self.window() gets the top-level window (QMainWindow), which has isFullScreen().
            if self.window().isFullScreen():
                self.fullscreen_request_signal.emit() # Request a toggle, which will exit fullscreen
            event.accept() # Indicate event was handled, even if not fullscreen (to consume Esc)
        else:
            super().keyPressEvent(event) # Pass to base class for other keys

    def contextMenuEvent(self, event):
        """Show a context menu when right-clicking on empty areas of the canvas."""
        # First, let's check if there's an item under the cursor
        item_under_cursor = self.itemAt(event.pos())
        
        # Only show our custom context menu if there's no item under the cursor
        if item_under_cursor is None:
            menu = QMenu(self)
            save_layout_action = menu.addAction("Save current layout")
            
            # Connect to a signal that will be handled by the main window
            save_layout_action.triggered.connect(self._request_save_layout)
            
            menu.exec(event.globalPos())
            event.accept()
        else:
            # If there's an item, pass the event to the parent implementation
            super().contextMenuEvent(event)
            
    def _request_save_layout(self):
        """Signal to the main window to save the current layout."""
        # We'll emit a signal that can be connected to a method in MainWindow
        # Since we don't have a dedicated signal for this yet, we'll create one
        # For now, let's try to access the parent MainWindow and call its method directly
        if self.scene() and hasattr(self.scene(), 'parent') and self.scene().parent():
            main_window = self.scene().parent()
            if hasattr(main_window, 'save_current_layout'):
                main_window.save_current_layout()
                print("Requested to save current layout")