"""
WallpaperManager — Handles graph background wallpaper loading, selection, and persistence.

Extracted from :class:`JackGraphView` to separate wallpaper concerns from view logic.
"""

import os
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
)
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPixmap, QBrush, QPainter
from PyQt6.QtWidgets import QGraphicsScene

from cable_core import config_keys as keys
from cable_core.config import ConfigManager as CableCoreConfigManager

logger = logging.getLogger(__name__)


# Shared ConfigManager instance for wallpaper settings
_cable_core_config: Optional[CableCoreConfigManager] = None


def _get_cable_core_config() -> CableCoreConfigManager:
    """Get or create the shared ConfigManager instance."""
    global _cable_core_config
    if _cable_core_config is None:
        _cable_core_config = CableCoreConfigManager()
    return _cable_core_config


class WallpaperManager:
    """Manages graph background wallpaper: load, select, clear, and paint."""

    def __init__(self, scene: QGraphicsScene) -> None:
        self._scene = scene
        self._wallpaper_pixmap: Optional[QPixmap] = None
        self._load_wallpaper()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def wallpaper_pixmap(self) -> Optional[QPixmap]:
        """The currently loaded wallpaper pixmap, or None."""
        return self._wallpaper_pixmap

    def show_wallpaper_dialog(self, parent_widget) -> None:
        """Show a dialog to select wallpaper image and set it as background."""
        dialog = QDialog(parent_widget.window())
        dialog.setWindowTitle("Select Wallpaper")
        dialog.setModal(True)
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)

        instructions = QLabel(
            "Choose a JPG or PNG image file to use as graph background wallpaper."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        layout.addStretch()

        button_layout = QHBoxLayout()

        select_button = QPushButton("Select Image...")
        select_button.clicked.connect(lambda: self._select_wallpaper_file(dialog))
        button_layout.addWidget(select_button)

        clear_button = QPushButton("Clear Wallpaper")
        clear_button.clicked.connect(lambda: self._clear_wallpaper(dialog))
        button_layout.addWidget(clear_button)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(dialog.reject)
        button_layout.addWidget(button_box)

        layout.addLayout(button_layout)

        dialog.exec()

    def draw_background(self, painter: QPainter, rect: QRectF) -> None:
        """Draw the wallpaper centered in the scene, without tiling.

        Call this from ``QGraphicsView.drawBackground()``.
        """
        if self._wallpaper_pixmap is None or self._wallpaper_pixmap.isNull():
            return

        scene_rect = self._scene.sceneRect()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        pix_w = self._wallpaper_pixmap.width()
        pix_h = self._wallpaper_pixmap.height()
        cx = scene_rect.center().x()
        cy = scene_rect.center().y()
        target_rect = QRectF(cx - pix_w / 2.0, cy - pix_h / 2.0, pix_w, pix_h)

        painter.drawPixmap(
            target_rect,
            self._wallpaper_pixmap,
            QRectF(self._wallpaper_pixmap.rect()),
        )

        painter.restore()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load_wallpaper(self) -> None:
        """Load and set the wallpaper image as background."""
        try:
            config = _get_cable_core_config()

            wallpaper_path = config.get_str_setting(keys.GRAPH_WALLPAPER_PATH, "")
            if not wallpaper_path:
                old_wallpaper = config.get_str_setting("graph_wallpaper", "")
                if old_wallpaper and os.path.exists(old_wallpaper):
                    wallpaper_path = old_wallpaper
                    config.set_str_setting(keys.GRAPH_WALLPAPER_PATH, wallpaper_path)
                    config.set_str_setting("graph_wallpaper", "")
                    logger.info(f"Migrated old wallpaper setting: {wallpaper_path}")

            if wallpaper_path and os.path.exists(wallpaper_path):
                original_pixmap = QPixmap(wallpaper_path)
                if not original_pixmap.isNull():
                    self._wallpaper_pixmap = original_pixmap
                    self._scene.setBackgroundBrush(QBrush())
                    self._scene.invalidate(
                        self._scene.sceneRect(),
                        QGraphicsScene.SceneLayer.BackgroundLayer,
                    )
                    logger.info(f"Loaded wallpaper: {wallpaper_path}")
                else:
                    logger.debug(f"Invalid image file: {wallpaper_path}")
                    self._wallpaper_pixmap = None
                    self._scene.setBackgroundBrush(QBrush())
            else:
                self._wallpaper_pixmap = None
                self._scene.setBackgroundBrush(QBrush())

        except Exception as e:
            logger.error(f"Error loading wallpaper: {e}")
            self._wallpaper_pixmap = None
            self._scene.setBackgroundBrush(QBrush())

    def _set_wallpaper(self, image_path: str) -> None:
        """Set the wallpaper image as background."""
        try:
            config = _get_cable_core_config()
            config.set_str_setting(keys.GRAPH_WALLPAPER_PATH, image_path)
            self._load_wallpaper()
            logger.info(f"Set wallpaper to: {image_path}")
        except Exception as e:
            logger.error(f"Error setting wallpaper: {e}")

    def _clear_wallpaper(self, parent_dialog: Optional[QDialog] = None) -> None:
        """Clear the wallpaper (no background image)."""
        try:
            config = _get_cable_core_config()
            config.set_str_setting(keys.GRAPH_WALLPAPER_PATH, "")
            self._load_wallpaper()
            logger.info("Cleared wallpaper")
            if parent_dialog:
                parent_dialog.accept()
        except Exception as e:
            logger.error(f"Error clearing wallpaper: {e}")

    def _select_wallpaper_file(self, parent_dialog: QDialog) -> None:
        """Open file dialog to select wallpaper image."""
        file_dialog = QFileDialog()
        file_dialog.setWindowTitle("Select Wallpaper Image")
        file_dialog.setNameFilter("Image files (*.jpg *.jpeg *.png);;All files (*)")
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)

        try:
            last_dir = _get_cable_core_config().get_str_setting(
                keys.GRAPH_WALLPAPER_LAST_DIR, ""
            )
            if last_dir and os.path.exists(last_dir):
                file_dialog.setDirectory(last_dir)
        except Exception as e:
            logger.warning(f"Warning: Could not set last wallpaper directory: {e}")

        if file_dialog.exec() == QDialog.DialogCode.Accepted:
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                image_path = selected_files[0]

                try:
                    image_dir = os.path.dirname(image_path)
                    _get_cable_core_config().set_str_setting(
                        keys.GRAPH_WALLPAPER_LAST_DIR, image_dir
                    )
                except Exception as e:
                    logger.warning(f"Warning: Could not save last wallpaper directory: {e}")

                self._set_wallpaper(image_path)
                parent_dialog.accept()
