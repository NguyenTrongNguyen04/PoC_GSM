from __future__ import annotations


class TicketError(RuntimeError):
    """Base ticket store / service error."""


class InvalidTicketTransition(TicketError):
    """Requested status transition is not allowed by the state machine."""


class TicketNotFound(TicketError):
    """Ticket ID does not exist in the local store."""


class TicketAccessDenied(TicketError):
    """Trusted user is not the ticket owner."""


class ClosedTicketImmutable(TicketError):
    """Closed tickets cannot be mutated."""
