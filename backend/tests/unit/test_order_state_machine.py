"""Tests for OrderStateMachine -- pure state transition logic.

Covers all valid transitions, all invalid transitions, terminal state
detection, and Hypothesis property-based testing.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.orders.state_machine import InvalidTransitionError, OrderStateMachine
from app.orders.types import TERMINAL_STATES, OrderState


# --- Valid transition test data ---

VALID_TRANSITIONS: list[tuple[OrderState, OrderState]] = [
    # From PENDING_SUBMIT
    (OrderState.PENDING_SUBMIT, OrderState.SUBMITTED),
    (OrderState.PENDING_SUBMIT, OrderState.SUBMIT_FAILED),
    # From SUBMITTED
    (OrderState.SUBMITTED, OrderState.ACCEPTED),
    (OrderState.SUBMITTED, OrderState.REJECTED),
    (OrderState.SUBMITTED, OrderState.FILLED),
    (OrderState.SUBMITTED, OrderState.CANCELED),
    (OrderState.SUBMITTED, OrderState.EXPIRED),
    # From ACCEPTED
    (OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED),
    (OrderState.ACCEPTED, OrderState.FILLED),
    (OrderState.ACCEPTED, OrderState.CANCELED),
    (OrderState.ACCEPTED, OrderState.EXPIRED),
    # From PARTIALLY_FILLED
    (OrderState.PARTIALLY_FILLED, OrderState.PARTIALLY_FILLED),
    (OrderState.PARTIALLY_FILLED, OrderState.FILLED),
    (OrderState.PARTIALLY_FILLED, OrderState.CANCELED),
]


class TestOrderStateMachineValidTransitions:
    """All valid transitions succeed."""

    @pytest.mark.parametrize(
        ("from_state", "to_state"),
        VALID_TRANSITIONS,
        ids=[f"{f.value}->{t.value}" for f, t in VALID_TRANSITIONS],
    )
    def test_valid_transition(
        self,
        from_state: OrderState,
        to_state: OrderState,
    ) -> None:
        sm = OrderStateMachine(from_state)
        sm.transition(to_state)
        assert sm.state == to_state


class TestOrderStateMachineInvalidTransitionErrors:
    """Invalid transitions raise InvalidTransitionError."""

    def _all_invalid_for(self, from_state: OrderState) -> list[OrderState]:
        """Get all states that are NOT valid targets from from_state."""
        valid = OrderStateMachine.TRANSITIONS.get(from_state, frozenset())
        return [s for s in OrderState if s not in valid]

    @pytest.mark.parametrize("from_state", list(OrderState))
    def test_invalid_transitions_raise(self, from_state: OrderState) -> None:
        invalid_targets = self._all_invalid_for(from_state)
        for to_state in invalid_targets:
            sm = OrderStateMachine(from_state)
            with pytest.raises(InvalidTransitionError) as exc_info:
                sm.transition(to_state)
            assert exc_info.value.from_state == from_state
            assert exc_info.value.to_state == to_state

    def test_terminal_state_rejects_all_transitions(self) -> None:
        for terminal in TERMINAL_STATES:
            for target in OrderState:
                sm = OrderStateMachine(terminal)
                with pytest.raises(InvalidTransitionError):
                    sm.transition(target)


class TestOrderStateMachineTerminalDetection:
    """Terminal state detection works correctly."""

    @pytest.mark.parametrize("state", list(TERMINAL_STATES))
    def test_terminal_states(self, state: OrderState) -> None:
        sm = OrderStateMachine(state)
        assert sm.is_terminal is True

    @pytest.mark.parametrize(
        "state",
        [s for s in OrderState if s not in TERMINAL_STATES],
    )
    def test_non_terminal_states(self, state: OrderState) -> None:
        sm = OrderStateMachine(state)
        assert sm.is_terminal is False


class TestOrderStateMachineSelfTransition:
    """PARTIALLY_FILLED -> PARTIALLY_FILLED is valid (multiple partial fills)."""

    def test_self_transition(self) -> None:
        sm = OrderStateMachine(OrderState.PARTIALLY_FILLED)
        sm.transition(OrderState.PARTIALLY_FILLED)
        assert sm.state == OrderState.PARTIALLY_FILLED
        # Can do it multiple times
        sm.transition(OrderState.PARTIALLY_FILLED)
        sm.transition(OrderState.PARTIALLY_FILLED)
        assert sm.state == OrderState.PARTIALLY_FILLED


class TestOrderStateMachineProperties:
    """Property-based tests with Hypothesis."""

    def test_state_counts(self) -> None:
        """All 9 states are defined."""
        assert len(OrderState) == 9

    def test_terminal_count(self) -> None:
        """5 terminal states."""
        assert len(TERMINAL_STATES) == 5

    def test_non_terminal_states_have_transitions(self) -> None:
        """Every non-terminal state has at least one valid transition."""
        for state in OrderState:
            if state not in TERMINAL_STATES:
                assert state in OrderStateMachine.TRANSITIONS
                assert len(OrderStateMachine.TRANSITIONS[state]) > 0

    @given(
        events=st.lists(
            st.sampled_from(list(OrderState)),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=300)
    def test_random_event_sequences_never_corrupt(
        self,
        events: list[OrderState],
    ) -> None:
        """Random event sequences never produce an invalid internal state.

        Either a transition succeeds (state changes to a valid OrderState)
        or InvalidTransitionError is raised (state unchanged).
        """
        sm = OrderStateMachine(OrderState.PENDING_SUBMIT)
        for target in events:
            old_state = sm.state
            try:
                sm.transition(target)
                # If transition succeeded, state must be the target
                assert sm.state == target
                assert sm.state in OrderState
            except InvalidTransitionError:
                # State must be unchanged
                assert sm.state == old_state

    @given(
        events=st.lists(
            st.sampled_from(list(OrderState)),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=300)
    def test_terminal_states_are_absorbing(
        self,
        events: list[OrderState],
    ) -> None:
        """Once a terminal state is reached, no further transitions are possible."""
        sm = OrderStateMachine(OrderState.PENDING_SUBMIT)
        reached_terminal = False
        for target in events:
            if reached_terminal:
                with pytest.raises(InvalidTransitionError):
                    sm.transition(target)
            else:
                try:
                    sm.transition(target)
                    if sm.is_terminal:
                        reached_terminal = True
                except InvalidTransitionError:
                    pass


class TestOrderStateMachineInit:
    """Construction and basic properties."""

    def test_initial_state(self) -> None:
        sm = OrderStateMachine(OrderState.PENDING_SUBMIT)
        assert sm.state == OrderState.PENDING_SUBMIT
        assert sm.is_terminal is False

    def test_construct_from_any_state(self) -> None:
        for state in OrderState:
            sm = OrderStateMachine(state)
            assert sm.state == state


class TestInvalidTransitionError:
    """InvalidTransitionError exception formatting."""

    def test_message_includes_states(self) -> None:
        err = InvalidTransitionError(OrderState.FILLED, OrderState.ACCEPTED)
        assert "filled" in str(err)
        assert "accepted" in str(err)
        assert err.from_state == OrderState.FILLED
        assert err.to_state == OrderState.ACCEPTED
