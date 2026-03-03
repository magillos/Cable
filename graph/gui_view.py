"""
QGraphicsView providing zoom, pan, context menus, and wallpaper for the graph scene.
"""
import os
from PyQt6.QtWidgets import QGraphicsView, QMenu, QDialog, QVBoxLayout, QDialogButtonBox, QLabel, QCheckBox, QFileDialog, QHBoxLayout, QPushButton, QButtonGroup, QRadioButton, QWidget
from PyQt6.QtGui import QPainter, QCursor, QMouseEvent, QPixmap, QBrush, QFont, QWheelEvent, QKeyEvent, QContextMenuEvent # Import QMouseEvent
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from typing import Optional, Tuple

import logging
logger = logging.getLogger(__name__)

# Import JackGraphScene for type hinting
from .gui_scene import JackGraphScene
from . import constants # Import constants
from cable_core import config_keys as keys
from cable_core.dialogs import CombinedSinkSourceDialog
from cable_core.config import ConfigManager as CableCoreConfigManager

# Shared ConfigManager instance for wallpaper settings
_cable_core_config = None

def _get_cable_core_config() -> CableCoreConfigManager:
    """Get or create the shared ConfigManager instance."""
    global _cable_core_config
    if _cable_core_config is None:
        _cable_core_config = CableCoreConfigManager()
    return _cable_core_config

class JackGraphView(QGraphicsView):
    """The view widget for the JACK graph scene."""
    # Signal to notify the main window to toggle fullscreen
    fullscreen_request_signal = pyqtSignal()
    zoom_changed = pyqtSignal(float) # Signal to emit when zoom level changes
 
    def __init__(self, scene: JackGraphScene, parent: Optional[QWidget] = None) -> None:
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

        # Wallpaper reload throttling
        self._last_scene_size = None
        self._wallpaper_loaded = False

        # Connect scene changes to scrollbar update
        if self.scene():
            self.scene().changed.connect(self._update_scrollbar_visibility)
            self.scene().changed.connect(self._reload_wallpaper_if_needed)

        # Set the initial cursor to the standard arrow
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        # Load wallpaper if set
        self._load_wallpaper()

        # Reduced zoom factor for more precise control
        self.zoom_factor_base = 1.05  # Changed from 1.15 for slower, more controlled zooming
        self.min_zoom_scale = 0.1  # Minimum zoom level (e.g., 10%)
        self.max_zoom_scale = 5.0  # Maximum zoom level (e.g., 500%)


    def _update_scrollbar_visibility(self) -> None:
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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Override mouse press to set closed hand cursor during drag or initiate panning."""
        if event.button() == Qt.MouseButton.MiddleButton or \
           (event.button() == Qt.MouseButton.LeftButton and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor) # Indicate grabbable
            event.accept() # Consume the event to prevent RubberBandDrag
        else:
            super().mousePressEvent(event) # Call base implementation for selection etc.
            # Original logic for ScrollHandDrag if it was set some other way (though less likely now)
            if self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag and event.button() == Qt.MouseButton.LeftButton:
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
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

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Override mouse release to reset cursor after drag or panning."""
        if self._is_panning and (event.button() == Qt.MouseButton.LeftButton or event.button() == Qt.MouseButton.MiddleButton):
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
                event.accept() # Accept it here as the view handled it.
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
            self.scale(self.max_zoom_scale / current_scale, self.max_zoom_scale / current_scale)
        self.zoom_changed.emit(self.get_zoom_level()) # Emit signal
 
    def zoom_out(self) -> None:
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

    def get_zoom_level(self) -> float:
        """Returns the current horizontal scale factor (zoom level) of the view."""
        return self.transform().m11() # m11 is horizontal scale, m22 is vertical

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
 
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_U and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            graph_mw = self.scene().parent()
            if graph_mw and hasattr(graph_mw, 'untangle_action'):
                graph_mw.untangle_action.trigger()
                event.accept()
            else:
                super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_F:
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

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Show a context menu when right-clicking on empty areas of the canvas."""
        # First, let's check if there's an item under the cursor
        item_under_cursor = self.itemAt(event.pos())

        # Only show our custom context menu if there's no item under the cursor
        if item_under_cursor is None:
            menu = QMenu(self)
            create_combined_action = menu.addAction("Create virtual sink/source")
            unload_all_sinks_action = menu.addAction("Unload all sinks")
            remove_saved_sinks_action = menu.addAction("Remove all saved virtual sinks")
            menu.addSeparator()
            unhide_all_nodes_action = menu.addAction("Unhide all nodes")
            unsplit_all_nodes_action = menu.addAction("Unsplit all nodes")
            
            # Gray out "Unsplit all nodes" when I/O layout is active
            main_window = self.scene().parent()
            if main_window and hasattr(main_window, 'current_untangle_setting'):
                # I/O layout is represented by 0
                unsplit_all_nodes_action.setEnabled(main_window.current_untangle_setting != 0)
            
            menu.addSeparator()
            wallpaper_action = menu.addAction("Wallpaper")

            # Connect to handlers
            clicked_scene_pos = self.mapToScene(event.pos())
            logger.debug(f"Context menu clicked at scene position: {clicked_scene_pos}")
            create_combined_action.triggered.connect(
                lambda checked=False, pos=clicked_scene_pos: self._show_combined_sink_dialog(pos)
            )
            unload_all_sinks_action.triggered.connect(self._unload_all_sinks)
            remove_saved_sinks_action.triggered.connect(self._remove_all_saved_virtual_sinks)
            unhide_all_nodes_action.triggered.connect(self._unhide_all_nodes)
            unsplit_all_nodes_action.triggered.connect(self._unsplit_all_nodes)
            wallpaper_action.triggered.connect(self._show_wallpaper_dialog)

            menu.exec(event.globalPos())
            event.accept()
        else:
            # If there's an item, pass the event to the parent implementation
            super().contextMenuEvent(event)
            
    def _show_combined_sink_dialog(self, scene_pos: Optional[QPointF] = None) -> None:
        """Show the dialog for creating a combined virtual sink/source."""
        dialog = CombinedSinkSourceDialog(self)
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            sink_name, channel_map = dialog.get_values()
            self._create_combined_sink_source(sink_name, channel_map, scene_pos)

    def _show_wallpaper_dialog(self) -> None:
        """Show a dialog to select wallpaper image and set it as background."""
        # Create wallpaper dialog
        dialog = QDialog(self.window())
        dialog.setWindowTitle("Select Wallpaper")
        dialog.setModal(True)
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)

        # Get current settings using cable_core ConfigManager
        current_scaling = "scaled"
        try:
            current_scaling = _get_cable_core_config().get_str_setting(keys.GRAPH_WALLPAPER_SCALING, "scaled")
        except Exception as e:
            logger.warning(f"Warning: Could not read wallpaper config: {e}")

        # Scaling options
        scaling_group = QButtonGroup(dialog)
        scaling_layout = QVBoxLayout()
        scaling_label = QLabel("Scaling mode:")
        scaling_layout.addWidget(scaling_label)

        scale_radio = QRadioButton("Scaled - Fill canvas (may distort)")
        scale_radio.setChecked(current_scaling == "scaled")
        scaling_group.addButton(scale_radio, 0)
        scaling_layout.addWidget(scale_radio)

        center_radio = QRadioButton("Centered - Original size, centered")
        center_radio.setChecked(current_scaling == "centered")
        scaling_group.addButton(center_radio, 1)
        scaling_layout.addWidget(center_radio)

        layout.addLayout(scaling_layout)

        # Instructions
        instructions = QLabel("Choose a JPG or PNG image file to use as graph background wallpaper.")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()

        select_button = QPushButton("Select Image...")
        select_button.clicked.connect(lambda: self._select_wallpaper_file(dialog, scaling_group))
        button_layout.addWidget(select_button)

        clear_button = QPushButton("Clear Wallpaper")
        clear_button.clicked.connect(lambda: self._clear_wallpaper(dialog))
        button_layout.addWidget(clear_button)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(lambda: self._save_wallpaper_settings(dialog, scaling_group))
        button_box.rejected.connect(dialog.reject)
        button_layout.addWidget(button_box)

        layout.addLayout(button_layout)

        dialog.exec()

    def _select_wallpaper_file(self, parent_dialog: QDialog, scaling_group: QButtonGroup) -> None:
        """Open file dialog to select wallpaper image."""
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Select Wallpaper Image")
        file_dialog.setNameFilter("Image files (*.jpg *.jpeg *.png);;All files (*)")
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)

        # Try to start from the last wallpaper directory
        try:
            last_dir = _get_cable_core_config().get_str_setting(keys.GRAPH_WALLPAPER_LAST_DIR, "")
            if last_dir and os.path.exists(last_dir):
                file_dialog.setDirectory(last_dir)
        except Exception as e:
            logger.warning(f"Warning: Could not set last wallpaper directory: {e}")

        if file_dialog.exec() == QDialog.DialogCode.Accepted:
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                image_path = selected_files[0]

                # Save the directory for next time
                try:
                    image_dir = os.path.dirname(image_path)
                    _get_cable_core_config().set_str_setting(keys.GRAPH_WALLPAPER_LAST_DIR, image_dir)
                except Exception as e:
                    logger.warning(f"Warning: Could not save last wallpaper directory: {e}")

                # Get scaling mode
                scaling_mode = "scaled"
                checked_button = scaling_group.checkedButton()
                if checked_button and "Centered" in checked_button.text():
                    scaling_mode = "centered"
                # else default to "scaled"

                self._set_wallpaper(image_path, scaling_mode)
                parent_dialog.accept()

    def _set_wallpaper(self, image_path: str, scaling_mode: str = "scaled") -> None:
        """Set the wallpaper image as background."""
        try:
            config = _get_cable_core_config()
            config.set_str_setting(keys.GRAPH_WALLPAPER_PATH, image_path)
            config.set_str_setting(keys.GRAPH_WALLPAPER_SCALING, scaling_mode)
            self._load_wallpaper()
            logger.info(f"Set wallpaper to: {image_path}, mode: {scaling_mode}")
        except Exception as e:
            logger.error(f"Error setting wallpaper: {e}")

    def _clear_wallpaper(self, parent_dialog: Optional[QDialog] = None) -> None:
        """Clear the wallpaper (no background image)."""
        try:
            config = _get_cable_core_config()
            config.set_str_setting(keys.GRAPH_WALLPAPER_PATH, '')
            config.set_str_setting(keys.GRAPH_WALLPAPER_SCALING, 'scaled')
            self._load_wallpaper()
            logger.info("Cleared wallpaper")
            if parent_dialog:
                parent_dialog.accept()
        except Exception as e:
            logger.error(f"Error clearing wallpaper: {e}")

    def _save_wallpaper_settings(self, parent_dialog: QDialog, scaling_group: QButtonGroup) -> None:
        """Save the wallpaper settings when dialog is accepted."""
        try:
            config = _get_cable_core_config()
            current_wallpaper = config.get_str_setting(keys.GRAPH_WALLPAPER_PATH, '')
            current_scaling = config.get_str_setting(keys.GRAPH_WALLPAPER_SCALING, 'scaled')

            # Update scaling if changed
            scaling_mode = "scaled"
            checked_button = scaling_group.checkedButton()
            if checked_button and "Centered" in checked_button.text():
                scaling_mode = "centered"

            if scaling_mode != current_scaling:
                config.set_str_setting(keys.GRAPH_WALLPAPER_SCALING, scaling_mode)
                if current_wallpaper:
                    self._load_wallpaper()  # Reload with new scaling

            parent_dialog.accept()
        except Exception as e:
            logger.error(f"Error saving wallpaper settings: {e}")

    def _load_wallpaper(self) -> None:
        """Load and set the wallpaper image as background."""
        try:
            config = _get_cable_core_config()

            # Try to migrate old wallpaper setting if it exists but new ones don't
            wallpaper_path = config.get_str_setting(keys.GRAPH_WALLPAPER_PATH, '')
            if not wallpaper_path:
                # Check for old wallpaper setting to migrate
                old_wallpaper = config.get_str_setting('graph_wallpaper', '')
                if old_wallpaper and os.path.exists(old_wallpaper):
                    wallpaper_path = old_wallpaper
                    config.set_str_setting(keys.GRAPH_WALLPAPER_PATH, wallpaper_path)
                    # Clean up old setting
                    config.set_str_setting('graph_wallpaper', '')
                    logger.info(f"Migrated old wallpaper setting: {wallpaper_path}")

            scaling_mode = config.get_str_setting(keys.GRAPH_WALLPAPER_SCALING, 'scaled')

            if wallpaper_path and os.path.exists(wallpaper_path):
                # Load the image
                original_pixmap = QPixmap(wallpaper_path)
                if not original_pixmap.isNull():
                    pixmap = self._scale_pixmap_for_mode(original_pixmap, scaling_mode)
                    # Set the pixmap as background brush for the scene
                    brush = QBrush(pixmap)
                    self.scene().setBackgroundBrush(brush)
                    logger.info(f"Loaded wallpaper: {wallpaper_path}, mode: {scaling_mode}")
                else:
                    logger.debug(f"Invalid image file: {wallpaper_path}")
                    self.scene().setBackgroundBrush(QBrush())
            else:
                # Clear background
                self.scene().setBackgroundBrush(QBrush())

        except Exception as e:
            logger.error(f"Error loading wallpaper: {e}")
            self.scene().setBackgroundBrush(QBrush())

    def _reload_wallpaper_if_needed(self) -> None:
        """Reload wallpaper when scene size changes significantly (throttled to prevent spam)."""
        try:
            scene_rect = self.scene().sceneRect()
            current_size = (int(scene_rect.width()), int(scene_rect.height()))

            # Only reload if scene size changed significantly and wallpaper wasn't recently loaded
            if self._last_scene_size != current_size and current_size[0] > 100 and current_size[1] > 100:
                wallpaper_path = _get_cable_core_config().get_str_setting(keys.GRAPH_WALLPAPER_PATH, '')

                if wallpaper_path and os.path.exists(wallpaper_path) and not self._wallpaper_loaded:
                    self._last_scene_size = current_size
                    self._wallpaper_loaded = True
                    self._load_wallpaper()

        except Exception as e:
            logger.error(f"Error checking wallpaper reload: {e}")

    def _scale_pixmap_for_mode(self, original_pixmap: QPixmap, scaling_mode: str) -> QPixmap:
        """Scale the pixmap according to the selected scaling mode."""
        # Get scene rect for scaling calculations
        scene_rect = self.scene().sceneRect()

        if scaling_mode == "centered":
            # Return original pixmap, it will be centered automatically
            return original_pixmap

        else:  # "scaled" - default
            # Scale to fill canvas, may distort
            canvas_width = int(scene_rect.width())
            canvas_height = int(scene_rect.height())

            if canvas_width > 0 and canvas_height > 0:
                return original_pixmap.scaled(canvas_width, canvas_height,
                                             Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
            else:
                return original_pixmap

    def _show_unload_all_sinks_confirmation_dialog(self) -> Tuple[bool, bool]:
        """
        Show a confirmation dialog for unloading all sinks with 'don't show again' checkbox.

        Returns:
            tuple: (confirmed, dont_show_again) where confirmed is True if user accepted,
                   and dont_show_again is True if the checkbox was checked
        """
        # Create a custom dialog
        dialog = QDialog(self.window())
        dialog.setWindowTitle("Unload All Sinks")
        dialog.setModal(True)

        # Create layout
        layout = QVBoxLayout(dialog)

        # Add message
        message = "This will unload ALL virtual sink modules from PulseAudio/PipeWire.\n\n"
        message += "This action cannot be undone and may affect active audio connections.\n\n"
        message += "Are you sure you want to continue?"
        label = QLabel(message)
        layout.addWidget(label)

        # Add checkbox
        checkbox = QCheckBox("Don't show this confirmation again")
        layout.addWidget(checkbox)

        # Add buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # Execute dialog
        result = dialog.exec() == QDialog.DialogCode.Accepted

        return result, checkbox.isChecked()

    def _create_combined_sink_source(self, sink_name: str, channel_map: str, scene_pos: Optional[QPointF] = None) -> None:
        """Execute the pactl command to create the combined virtual sink/source."""
        import subprocess
        import json

        command = ["pactl", "load-module", "module-null-sink"]
        channel_map_param = "stereo"

        if channel_map == "Mono":
            channel_map_param = "mono"
            command.extend(["media.class=Audio/Sink", f"sink_name={sink_name}", f"channel_map={channel_map_param}"])
        else:
            if channel_map == "5.1":
                channel_map_param = "surround-51"
            elif channel_map == "7.1":
                channel_map_param = "surround-71"

            command.extend([f"sink_name={sink_name}", f"channel_map={channel_map_param}"])

        scene = self.scene()
        if scene_pos is not None and scene is not None and hasattr(scene, 'register_pending_node_position'):
            logger.info(f"Registering pending position {scene_pos} for sink {sink_name}")
            scene.register_pending_node_position(sink_name, scene_pos)

        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            module_id = result.stdout.strip()

            # Save the module ID to config
            self._save_module_id(sink_name, module_id)

            logger.info(f"Created combined virtual sink/source: {sink_name} with channel map {channel_map}")
            logger.debug(f"Module ID: {module_id}")
        except subprocess.CalledProcessError as e:
            if scene_pos is not None and scene is not None and hasattr(scene, 'unregister_pending_node_position'):
                scene.unregister_pending_node_position(sink_name)
            logger.error(f"Error creating combined virtual sink/source: {e}")

    def _save_module_id(self, sink_name: str, module_id: str) -> None:
        """Save the module ID to config file for later unloading."""
        try:
            import json
            config = _get_cable_core_config()

            # Get existing module IDs, or initialize empty dict
            module_ids_json = config.get_str_setting(keys.VIRTUAL_SINK_MODULE_IDS, '{}')
            try:
                module_ids = json.loads(module_ids_json) if module_ids_json else {}
            except json.JSONDecodeError:
                module_ids = {}

            # Add/update the module ID
            module_ids[sink_name] = module_id

            # Save back to config
            config.set_str_setting(keys.VIRTUAL_SINK_MODULE_IDS, json.dumps(module_ids))

        except Exception as e:
            logger.error(f"Error saving module ID for {sink_name}: {e}")

    def _unload_all_sinks(self) -> None:
        """Unload all virtual sinks in the system."""
        import subprocess

        try:
            # Check if we should show the confirmation dialog
            show_confirmation = True
            try:
                # Try to get config manager from the main window
                config_manager = None
                main_window = self.window()
                if main_window and hasattr(main_window, 'config_manager'):
                    config_manager = main_window.config_manager
                else:
                    # Fallback to using shared config instance
                    config_manager = _get_cable_core_config()

                show_confirmation = True
                if config_manager:
                    show_confirmation = config_manager.get_bool(keys.SHOW_UNLOAD_ALL_SINKS_CONFIRMATION, default=True)
            except Exception as e:
                logger.warning(f"Warning: Could not read config for unload confirmation: {e}")

            if show_confirmation:
                confirmed, dont_show_again = self._show_unload_all_sinks_confirmation_dialog()
                if not confirmed:
                    return

                # Save the "don't show again" preference if checked
                if dont_show_again and config_manager:
                    try:
                        if hasattr(config_manager, 'set_bool'):
                            config_manager.set_bool(keys.SHOW_UNLOAD_ALL_SINKS_CONFIRMATION, False)
                        else:
                            logger.warning("Warning: ConfigManager does not have set_bool method")
                    except Exception as e:
                        logger.warning(f"Warning: Could not save config: {e}")

            # Get all modules to find null-sink modules
            list_command = ["pactl", "list", "modules"]
            list_result = subprocess.run(list_command, check=True, capture_output=True, text=True)
            output_lines = list_result.stdout.split('\n')

            # Parse the output to find null-sink modules
            # Output format is: Module #<id>\n\tName: <name>\n\t...\n\n
            null_sink_modules = []
            current_module_id = None
            for line in output_lines:
                line = line.strip()
                if line.startswith('Module #'):
                    current_module_id = line.split('#')[1].strip()
                elif line.startswith('Name: ') and 'module-null-sink' in line:
                    null_sink_modules.append(current_module_id)
                    current_module_id = None

            if not null_sink_modules:
                logger.debug("No virtual sinks to unload")
                return

            # Unload each null-sink module
            unloaded_count = 0
            for module_id in null_sink_modules:
                try:
                    command = ["pactl", "unload-module", str(module_id)]
                    subprocess.run(command, check=True, capture_output=True, text=True)
                    logger.info(f"Unloaded virtual sink module {module_id}")
                    unloaded_count += 1
                except subprocess.CalledProcessError as e:
                    logger.error(f"Error unloading module {module_id}: {e}")

            # Clear the module IDs from config if any were unloaded (preserves backward compatibility)
            if unloaded_count > 0:
                try:
                    _get_cable_core_config().set_str_setting(keys.VIRTUAL_SINK_MODULE_IDS, '{}')
                except Exception as e:
                    logger.warning(f"Warning: Could not clear config: {e}")

                logger.info(f"Successfully unloaded {unloaded_count} virtual sink(s)")

        except Exception as e:
            logger.error(f"Error unloading virtual sinks: {e}")

    def _remove_all_saved_virtual_sinks(self) -> None:
        """Clear all virtual sinks stored for recreation at auto-start."""
        try:
            # Use the connection_manager's config so node_item reads the same cache
            scene = self.scene()
            cm = getattr(scene, 'connection_manager', None) if scene else None
            config = getattr(cm, 'config_manager', None) if cm else _get_cable_core_config()
            config.set_str_setting(keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, '{}')
            logger.info("Removed all saved virtual sinks from autostart config")

            # Repaint virtual sink nodes to remove reddish border
            scene = self.scene()
            if scene:
                from .node_item import NodeItem
                for item in scene.items():
                    if isinstance(item, NodeItem) and getattr(item, 'is_virtual_sink', False):
                        item.update()
        except Exception as e:
            logger.error(f"Error removing saved virtual sinks: {e}")

    def _unhide_all_nodes(self) -> None:
        """Unhide all hidden nodes in the graph."""
        try:
            scene = self.scene()
            if not scene:
                return
            
            # Get the connection_manager from the scene
            if hasattr(scene, 'connection_manager') and scene.connection_manager:
                connection_manager = scene.connection_manager
                
                # Get the node_visibility_manager
                if hasattr(connection_manager, 'node_visibility_manager') and connection_manager.node_visibility_manager:
                    connection_manager.node_visibility_manager.unhide_all_nodes()
                    logger.info("All nodes have been unhidden")
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
                if isinstance(item, NodeItem) and getattr(item, 'is_split_origin', False):
                    split_nodes.append(item)
            
            if not split_nodes:
                logger.debug("No split nodes to unsplit")
                return
            
            # Unsplit each node
            unsplit_count = 0
            for node in split_nodes:
                try:
                    if hasattr(node, 'split_handler') and node.split_handler:
                        node.split_handler.unsplit_node(save_state=True)
                        unsplit_count += 1
                except Exception as e:
                    logger.error(f"Error unsplitting node {node.client_name}: {e}")
            
            logger.info(f"Successfully unsplit {unsplit_count} node(s)")
            
            # Reapply currently active untangle layout
            main_window = self.scene().parent()
            if main_window and hasattr(main_window, 'current_untangle_setting') and hasattr(main_window, '_apply_untangle_layout'):
                # If there's an active untangle setting, reapply it
                if main_window.untangle_button_clicked and main_window.current_untangle_setting != -1:  # -1 is ORIGINAL_LAYOUT
                    logger.debug(f"Reapplying active untangle layout: {main_window.current_untangle_setting}")
                    main_window._apply_untangle_layout(main_window.current_untangle_setting)
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
        if self.scene() and hasattr(self.scene(), 'parent') and self.scene().parent():
            main_window = self.scene().parent()
            if hasattr(main_window, 'save_current_layout'):
                main_window.save_current_layout()
                logger.debug("Requested to save current layout")
