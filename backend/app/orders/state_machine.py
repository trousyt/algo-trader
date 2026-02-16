"""Order state machine -- pure transition logic with validation.

No I/O, no database, no versioning. Validates state transitions
and raises on invalid ones.
"""

from __future__ import annotations

from typing import ClassVar

from app.orders.types import TERMINAL_STATES, OrderState


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: OrderState, to_state: OrderState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}")


class OrderStateMachine:
    """Pure state transition logic for order lifecycle.

    Validates from->to transitions against a static transition table.
    Raises InvalidTransitionError on invalid transitions.
    """

    TRANSITIONS: ClassVar[dict[OrderState, frozenset[OrderState]]] = {
        OrderState.PENDING_SUBMIT: frozenset(
            {
                OrderState.SUBMITTED,
                OrderState.SUBMIT_FAILED,
            }
        ),
        OrderState.SUBMITTED: frozenset(
            {
                OrderState.ACCEPTED,
                OrderState.REJECTED,
                OrderState.FILLED,
                OrderState.CANCELED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.ACCEPTED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCELED,
                OrderState.EXPIRED,
            }
        ),
        OrderState.PARTIALLY_FILLED: frozenset(
            {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCELED,
            }
        ),
    }

    def __init__(self, state: OrderState) -> None:
        self._state = state

    @property
    def state(self) -> OrderState:
        """Current state."""
        return self._state

    @property
    def is_terminal(self) -> bool:
        """Whether the current state is terminal (no further transitions)."""
        return self._state in TERMINAL_STATES

    def transition(self, to: OrderState) -> None:
        """Validate and apply a state transition.

        Raises:
            InvalidTransitionError: If the transition is not allowed.
        """
        if self.is_terminal:
            raise InvalidTransitionError(self._state, to)

        valid_targets = self.TRANSITIONS.get(self._state, frozenset())
        if to not in valid_targets:
            raise InvalidTransitionError(self._state, to)

        self._state = to

    def force_state(
        self,
        new_state: OrderState,
        *,
        _reconciliation: bool = False,
    ) -> None:
        """Force-set state without transition validation.

        Used ONLY during startup reconciliation to correct local state
        that diverged from broker while the system was down.

        Args:
            new_state: The target state to force.
            _reconciliation: Must be True. Guards against accidental misuse.

        Raises:
            RuntimeError: If _reconciliation is not True.
        """
        if not _reconciliation:
            raise RuntimeError("force_state() can only be called during reconciliation")
        self._state = new_state
