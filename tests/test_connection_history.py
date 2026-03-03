"""Tests for ConnectionHistory undo/redo functionality."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cables.features.connection_history import ConnectionHistory


def test_empty_history_can_undo_is_false():
    h = ConnectionHistory()
    assert h.can_undo() is False


def test_empty_history_can_redo_is_false():
    h = ConnectionHistory()
    assert h.can_redo() is False


def test_empty_history_undo_returns_none():
    h = ConnectionHistory()
    assert h.undo() is None


def test_empty_history_redo_returns_none():
    h = ConnectionHistory()
    assert h.redo() is None


def test_add_single_action_can_undo():
    h = ConnectionHistory()
    h.add_action("connect", "out:port", "in:port", False)
    assert h.can_undo() is True


def test_add_single_action_can_redo_is_false():
    h = ConnectionHistory()
    h.add_action("connect", "out:port", "in:port", False)
    assert h.can_redo() is False


def test_undo_connect_returns_disconnect():
    h = ConnectionHistory()
    h.add_action("connect", "out:port", "in:port", False)
    result = h.undo()
    assert result == ("disconnect", "out:port", "in:port", False)


def test_undo_disconnect_returns_connect():
    h = ConnectionHistory()
    h.add_action("disconnect", "out:port", "in:port", False)
    result = h.undo()
    assert result == ("connect", "out:port", "in:port", False)


def test_redo_returns_original_action():
    h = ConnectionHistory()
    h.add_action("connect", "out:port", "in:port", False)
    h.undo()
    result = h.redo()
    assert result == ("connect", "out:port", "in:port", False)


def test_multiple_actions_undo_redo_sequence():
    h = ConnectionHistory()
    h.add_action("connect", "a:out", "b:in", False)
    h.add_action("disconnect", "c:out", "d:in", False)

    # Undo second action
    result = h.undo()
    assert result == ("connect", "c:out", "d:in", False)
    assert h.can_undo() is True
    assert h.can_redo() is True

    # Undo first action
    result = h.undo()
    assert result == ("disconnect", "a:out", "b:in", False)
    assert h.can_undo() is False
    assert h.can_redo() is True

    # Redo first action
    result = h.redo()
    assert result == ("connect", "a:out", "b:in", False)
    assert h.can_undo() is True
    assert h.can_redo() is True

    # Redo second action
    result = h.redo()
    assert result == ("disconnect", "c:out", "d:in", False)
    assert h.can_undo() is True
    assert h.can_redo() is False


def test_undo_then_add_truncates_future():
    h = ConnectionHistory()
    h.add_action("connect", "a:out", "b:in", False)
    h.add_action("connect", "c:out", "d:in", False)
    h.add_action("connect", "e:out", "f:in", False)

    # Undo twice (back to first action)
    h.undo()
    h.undo()

    # Add a new action — should truncate the two undone actions
    h.add_action("disconnect", "x:out", "y:in", True)

    assert h.can_redo() is False
    assert len(h.history) == 2
    assert h.history[0] == ("connect", "a:out", "b:in", False)
    assert h.history[1] == ("disconnect", "x:out", "y:in", True)


def test_full_undo_to_beginning():
    h = ConnectionHistory()
    h.add_action("connect", "a:out", "b:in", False)
    h.add_action("connect", "c:out", "d:in", False)
    h.add_action("connect", "e:out", "f:in", False)

    h.undo()
    h.undo()
    h.undo()

    assert h.can_undo() is False
    assert h.can_redo() is True
    assert h.undo() is None


def test_full_redo_to_end():
    h = ConnectionHistory()
    h.add_action("connect", "a:out", "b:in", False)
    h.add_action("connect", "c:out", "d:in", False)

    h.undo()
    h.undo()

    h.redo()
    h.redo()

    assert h.can_redo() is False
    assert h.can_undo() is True
    assert h.redo() is None


def test_midi_flag_preserved_through_undo():
    h = ConnectionHistory()
    h.add_action("connect", "midi:out", "midi:in", True)
    result = h.undo()
    assert result == ("disconnect", "midi:out", "midi:in", True)
    assert result[3] is True


def test_midi_flag_preserved_through_redo():
    h = ConnectionHistory()
    h.add_action("disconnect", "midi:out", "midi:in", True)
    h.undo()
    result = h.redo()
    assert result == ("disconnect", "midi:out", "midi:in", True)
    assert result[3] is True


def test_undo_all_redo_all_matches_original():
    actions = [
        ("connect", "a:out", "b:in", False),
        ("disconnect", "c:out", "d:in", True),
        ("connect", "e:out", "f:in", False),
    ]
    h = ConnectionHistory()
    for a in actions:
        h.add_action(*a)

    # Undo all
    h.undo()
    h.undo()
    h.undo()
    assert h.can_undo() is False

    # Redo all and collect results
    redone = []
    while h.can_redo():
        redone.append(h.redo())

    assert redone == actions
    assert h.current_index == len(actions) - 1
    assert h.can_redo() is False
