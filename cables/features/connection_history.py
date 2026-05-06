"""
ConnectionHistory - Tracks connection actions for undo/redo functionality.
Includes methods to execute the inverse actions via :class:`JackConnectionHandler`.
"""
from typing import List, Optional, Tuple


class ConnectionHistory:
    """
    Tracks connection and disconnection actions for undo/redo functionality.

    Maintains a history of connection actions and provides methods to
    both navigate the history and execute the corresponding inverse actions.
    """

    def __init__(self) -> None:
        """Initialize the connection history."""
        self.history: List[Tuple[str, str, str, bool]] = []
        self.current_index: int = -1

    def add_action(
        self, action: str, output_name: str, input_name: str, is_midi: bool
    ) -> None:
        """
        Add a connection action to the history.

        Args:
            action: The action type ('connect' or 'disconnect')
            output_name: The name of the output port
            input_name: The name of the input port
            is_midi: Boolean indicating if the ports are MIDI
        """
        # Truncate history if we're not at the end
        self.history = self.history[: self.current_index + 1]
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
        Undo the last action — returns the inverse action tuple only, without executing it.

        Returns:
            tuple: (inverse_action, output, input, is_midi) or None if empty
        """
        if self.can_undo():
            action, output_name, input_name, is_midi = self.history[
                self.current_index
            ]
            self.current_index -= 1
            inverse_action = "connect" if action == "disconnect" else "disconnect"
            return (inverse_action, output_name, input_name, is_midi)
        return None

    def redo(self) -> Optional[Tuple[str, str, str, bool]]:
        """
        Redo the next action — returns the action tuple only, without executing it.

        Returns:
            tuple: (action, output, input, is_midi) or None if empty
        """
        if self.can_redo():
            self.current_index += 1
            return self.history[self.current_index]
        return None

    # ── Execute-and-navigate methods ────────────────────────────────

    def undo_and_execute(
        self, connection_handler: "JackConnectionHandler"
    ) -> bool:
        """Undo the last action and execute the inverse connection operation.

        Args:
            connection_handler: The :class:`JackConnectionHandler` instance to
                call :meth:`~.JackConnectionHandler.break_connection` /
                :meth:`~.JackConnectionHandler.make_connection` on.

        Returns:
            True if an action was undone and executed, False if the history
            was empty.
        """
        result = self.undo()
        if result is None:
            return False
        inv_action, output_name, input_name, is_midi = result
        if is_midi:
            if inv_action == "connect":
                connection_handler.make_midi_connection(
                    output_name, input_name, is_undo_redo=True
                )
            else:
                connection_handler.break_midi_connection(
                    output_name, input_name, is_undo_redo=True
                )
        else:
            if inv_action == "connect":
                connection_handler.make_connection(
                    output_name, input_name, is_undo_redo=True
                )
            else:
                connection_handler.break_connection(
                    output_name, input_name, is_undo_redo=True
                )
        return True

    def redo_and_execute(
        self, connection_handler: "JackConnectionHandler"
    ) -> bool:
        """Redo the next action and execute the connection operation.

        Args:
            connection_handler: The :class:`JackConnectionHandler` instance to
                call :meth:`~.JackConnectionHandler.make_connection` /
                :meth:`~.JackConnectionHandler.break_connection` on.

        Returns:
            True if an action was redone and executed, False if the history
            was exhausted.
        """
        result = self.redo()
        if result is None:
            return False
        action, output_name, input_name, is_midi = result
        if is_midi:
            if action == "connect":
                connection_handler.make_midi_connection(
                    output_name, input_name, is_undo_redo=True
                )
            else:
                connection_handler.break_midi_connection(
                    output_name, input_name, is_undo_redo=True
                )
        else:
            if action == "connect":
                connection_handler.make_connection(
                    output_name, input_name, is_undo_redo=True
                )
            else:
                connection_handler.break_connection(
                    output_name, input_name, is_undo_redo=True
                )
        return True
