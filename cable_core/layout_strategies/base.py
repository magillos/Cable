from typing import Protocol, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graph.jack_graph_scene import JackGraphScene
    from graph.layout import GraphLayouter

class LayoutStrategy(Protocol):
    """Protocol defining the interface for all graph layout strategies."""
    
    def apply(self, layouter: 'GraphLayouter', scene: 'JackGraphScene', **kwargs: Any) -> bool:
        """
        Apply the layout strategy to the graph.
        
        Args:
            layouter: The GraphLayouter instance to use for positioning calculations.
            scene: The JackGraphScene to lay out.
            **kwargs: Additional strategy-specific arguments.
            
        Returns:
            bool: True if the layout was applied successfully, False otherwise.
        """
        ...
