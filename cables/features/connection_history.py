"""
ConnectionHistory - Tracks connection actions for undo/redo functionality
"""
from typing import List, Optional, Tuple


class ConnectionHistory:
    """
    Tracks connection and disconnection actions for undo/redo functionality.
    
    This class maintains a history of connection actions (connect/disconnect)
    and provides methods to undo and redo these actions.
    """
    
    def __init__(self) -> None:
        """Initialize the connection history."""
        self.history: List[Tuple[str, str, str, bool]] = []
        self.current_index: int = -1
    
    def add_action(self, action: str, output_name: str, input_name: str, is_midi: bool) -> None:
        """
        Add a connection action to the history.
        
        Args:
            action: The action type ('connect' or 'disconnect')
            output_name: The name of the output port
            input_name: The name of the input port
            is_midi: Boolean indicating if the ports are MIDI
        """
        # Truncate history if we're not at the end
        self.history = self.history[:self.current_index + 1]
        self.history.append((action, output_name, input_name, is_midi))
        self.current_index += 1
    
    def can_undo(self) -> bool:
        """
        Check if there are actions that can be undone.
        
        Returns:
            bool: True if there are actions that can be undone, False otherwise
        """
        return self.current_index >= 0
    
    def can_redo(self) -> bool:
        """
        Check if there are actions that can be redone.
        
        Returns:
            bool: True if there are actions that can be redone, False otherwise
        """
        return self.current_index < len(self.history) - 1
    
    def undo(self) -> Optional[Tuple[str, str, str, bool]]:
        """
        Undo the last action.
        
        Returns:
            tuple: A tuple containing the inverse action, output port name, input port name, and is_midi flag,
                  or None if there are no actions to undo
        """
        if self.can_undo():
            action, output_name, input_name, is_midi = self.history[self.current_index]
            self.current_index -= 1
            # Return the inverse action
            inverse_action = 'connect' if action == 'disconnect' else 'disconnect'
            return (inverse_action, output_name, input_name, is_midi)
        return None
    
    def redo(self) -> Optional[Tuple[str, str, str, bool]]:
        """
        Redo the next action.
        
        Returns:
            tuple: A tuple containing the action, output port name, input port name, and is_midi flag,
                  or None if there are no actions to redo
        """
        if self.can_redo():
            self.current_index += 1
            return self.history[self.current_index] # Returns (action, output_name, input_name, is_midi)
        return None
