from enum import StrEnum


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    WAITING_CUSTOMER = "WAITING_CUSTOMER"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class MemoryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class MemoryType(StrEnum):
    TICKET_REFERENCE = "TICKET_REFERENCE"
    SUPPORT_SUMMARY = "SUPPORT_SUMMARY"
    SUPPORT_PREFERENCE = "SUPPORT_PREFERENCE"


class ActionType(StrEnum):
    NONE = "NONE"
    CREATE_TICKET = "CREATE_TICKET"
    GET_TICKET_STATUS = "GET_TICKET_STATUS"
    UPDATE_TICKET = "UPDATE_TICKET"
    CLOSE_TICKET = "CLOSE_TICKET"
    CLARIFY = "CLARIFY"
    ABSTAIN = "ABSTAIN"


class BaselineId(StrEnum):
    B0 = "B0"
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
