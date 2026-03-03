import logging
from typing import Any
from .base import LayoutStrategy

logger = logging.getLogger(__name__)

class AutoLayoutStrategy(LayoutStrategy):
    """Layout strategy that delegates to the graphviz-based AutoLayoutManager."""
    
    def apply(self, layouter: 'GraphLayouter', scene: 'JackGraphScene', **kwargs: Any) -> bool:
        """
        Apply the auto-layout strategy.
        
        Kwargs:
            auto_split (bool): If True, automatically split/unsplit nodes for optimal layout.
        """
        auto_split = kwargs.get('auto_split', True)
        from graph.auto_layout_manager import AutoLayoutManager
        manager = AutoLayoutManager(scene)
        return manager.compute_and_apply(auto_split=auto_split)
