"""Graph animation helpers.

This module centralizes QGraphicsItem movement animations used by the graph scene.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional

from PyQt6.QtCore import QEasingCurve, QPointF, QVariantAnimation

from . import constants


class NodeAnimator:
    """Small helper to animate QGraphicsItem positions without requiring Qt properties."""

    def __init__(self, owner) -> None:
        self._owner = owner
        self._active: Dict[int, QVariantAnimation] = {}

    def stop_for_item(self, item) -> None:
        if item is None:
            return
        key = id(item)
        anim = self._active.pop(key, None)
        if anim is not None:
            anim.stop()

    def stop_all(self) -> None:
        for anim in list(self._active.values()):
            try:
                anim.stop()
            except Exception:
                pass
        self._active.clear()

    def animate_to(
        self,
        item,
        target: QPointF,
        *,
        duration_ms: int,
        easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
        start: Optional[QPointF] = None,
        on_finished=None,
    ) -> None:
        if item is None:
            return

        self.stop_for_item(item)

        animation = QVariantAnimation(self._owner)
        animation.setDuration(int(duration_ms))
        animation.setStartValue(start if start is not None else item.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(easing)

        animation.valueChanged.connect(lambda value: item.setPos(value))
        if on_finished is not None:
            animation.finished.connect(on_finished)

        self._active[id(item)] = animation

        def _cleanup() -> None:
            self._active.pop(id(item), None)

        animation.finished.connect(_cleanup)
        animation.start()


class GraphAnimationController:
    """High-level graph animation helpers.

    Intended to be owned by JackGraphScene and used for:
    - push-away animations
    - animating transitions between layouts
    """

    def __init__(self, owner, node_animator: NodeAnimator) -> None:
        self._owner = owner
        self._node_animator = node_animator

    def easing_from_name(self, easing_name: str, fallback: QEasingCurve.Type) -> QEasingCurve.Type:
        if not easing_name:
            return fallback
        curve_type = getattr(QEasingCurve.Type, easing_name, None)
        if curve_type is None:
            return fallback
        return curve_type

    def animate_nodes_to_targets(
        self,
        targets: Dict[object, QPointF],
        *,
        update_config_for_item: Callable[[object], None],
    ) -> None:
        if not targets:
            return

        if not constants.LAYOUT_ANIMATION_ENABLED:
            for item, pos in targets.items():
                item.setPos(pos)
                update_config_for_item(item)
            return

        easing = self.easing_from_name(constants.LAYOUT_ANIMATION_EASING, QEasingCurve.Type.OutCubic)
        duration_ms = int(constants.LAYOUT_ANIMATION_DURATION)
        min_dist = float(getattr(constants, 'LAYOUT_ANIMATION_MIN_DISTANCE', 0.0) or 0.0)

        for item, pos in targets.items():
            try:
                if min_dist > 0.0:
                    delta = pos - item.pos()
                    if (delta.x() * delta.x() + delta.y() * delta.y()) ** 0.5 < min_dist:
                        continue
                self._node_animator.animate_to(
                    item,
                    pos,
                    duration_ms=duration_ms,
                    easing=easing,
                    on_finished=lambda n=item: update_config_for_item(n),
                )
            except Exception:
                item.setPos(pos)
                update_config_for_item(item)

    def compute_layout_transition_targets(
        self,
        *,
        before_items: Iterable[object],
        before_pos: Dict[object, QPointF],
        after_pos: Dict[object, QPointF],
        origin_getter: Callable[[object], Optional[object]],
    ) -> tuple[Dict[object, QPointF], Dict[object, QPointF]]:
        """Compute targets + start positions for a layout transition.

        Returns:
            (targets, start_pos)
        """
        targets: Dict[object, QPointF] = dict(after_pos)
        start_pos: Dict[object, QPointF] = {}

        for item in targets.keys():
            if item in before_pos:
                start_pos[item] = before_pos[item]
                continue

            origin = origin_getter(item)
            if origin is not None and origin in before_pos:
                start_pos[item] = before_pos[origin]
                continue

            if origin is not None:
                try:
                    start_pos[item] = origin.pos()
                    continue
                except Exception:
                    pass

        return targets, start_pos
