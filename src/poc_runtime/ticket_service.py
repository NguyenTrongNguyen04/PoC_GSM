from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from poc_runtime.clock import Clock, SystemClock
from poc_runtime.db import init_db
from poc_runtime.errors import (
    ClosedTicketImmutable,
    InvalidTicketTransition,
    TicketAccessDenied,
    TicketError,
    TicketNotFound,
)
from poc_runtime.models import (
    TicketLookupCode,
    TicketLookupOutcome,
    TicketRecord,
    TicketStatus,
)
from poc_runtime.state_machine import TicketStateMachine


class TicketService:
    """Ticket Store system of record. Never called directly by LLM."""

    def __init__(
        self,
        db_path: Path,
        *,
        state_machine: TicketStateMachine,
        clock: Clock | None = None,
    ) -> None:
        self.db_path = db_path
        self.state_machine = state_machine
        self.clock = clock or SystemClock()
        self.conn = init_db(db_path)

    def close(self) -> None:
        self.conn.close()

    def _now(self) -> str:
        return self.clock.now_iso()

    def create_ticket(
        self,
        *,
        trusted_user_id: str,
        complaint_type: str,
        summary: str = "",
        ticket_id: str | None = None,
    ) -> TicketRecord:
        if not trusted_user_id:
            raise TicketError("trusted_user_id required")
        if not complaint_type:
            raise TicketError("complaint_type required")
        tid = ticket_id or f"TKT-{uuid.uuid4().hex[:12].upper()}"
        now = self._now()
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO tickets(ticket_id, user_id, complaint_type, status, summary, resolution, version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, NULL, 1, ?, ?)
                    """,
                    (tid, trusted_user_id, complaint_type, TicketStatus.OPEN.value, summary, now, now),
                )
                self.conn.execute(
                    """
                    INSERT INTO ticket_events(ticket_id, user_id, event_type, from_status, to_status, payload_json, created_at)
                    VALUES (?, ?, 'CREATE', NULL, ?, ?, ?)
                    """,
                    (tid, trusted_user_id, TicketStatus.OPEN.value, json.dumps({"summary": summary}), now),
                )
        except Exception as exc:
            raise TicketError(f"create_ticket failed: {exc}") from exc
        return self.get_ticket(trusted_user_id=trusted_user_id, ticket_id=tid)

    def seed_ticket(self, fixture: dict[str, Any]) -> TicketRecord:
        """Materialize initial_state.ticket_store entry. Not an LLM-executed action."""
        tid = str(fixture["ticket_id"])
        owner = str(fixture["user_id"])
        complaint_type = str(fixture["complaint_type"])
        status = TicketStatus(str(fixture["status"]))
        summary = str(fixture.get("summary") or "")
        resolution = fixture.get("resolution")
        version = int(fixture.get("version") or 1)
        created_at = str(fixture.get("created_at") or self._now())
        updated_at = str(fixture.get("updated_at") or created_at)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO tickets(ticket_id, user_id, complaint_type, status, summary, resolution, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    owner,
                    complaint_type,
                    status.value,
                    summary,
                    resolution,
                    version,
                    created_at,
                    updated_at,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO ticket_events(ticket_id, user_id, event_type, from_status, to_status, payload_json, created_at)
                VALUES (?, ?, 'SEED', NULL, ?, ?, ?)
                """,
                (
                    tid,
                    owner,
                    status.value,
                    json.dumps({"seed": True, "summary": summary}, ensure_ascii=False),
                    created_at,
                ),
            )
        # Return record without ownership filter (seed may be cross-user fixture).
        return self._row_to_record(self._fetch_row(tid))

    def lookup_ticket(
        self, *, trusted_user_id: str, ticket_id: str | None
    ) -> TicketLookupOutcome:
        if not ticket_id:
            return TicketLookupOutcome(code=TicketLookupCode.NOT_REQUESTED, ticket=None)
        row = self._fetch_row(ticket_id)
        if row is None:
            return TicketLookupOutcome(code=TicketLookupCode.NOT_FOUND, ticket=None)
        if row["user_id"] != trusted_user_id:
            return TicketLookupOutcome(code=TicketLookupCode.ACCESS_DENIED, ticket=None)
        return TicketLookupOutcome(
            code=TicketLookupCode.FOUND, ticket=self._row_to_record(row)
        )

    def get_ticket(self, *, trusted_user_id: str, ticket_id: str) -> TicketRecord:
        outcome = self.lookup_ticket(trusted_user_id=trusted_user_id, ticket_id=ticket_id)
        if outcome.code == TicketLookupCode.NOT_FOUND:
            raise TicketNotFound(f"ticket not found: {ticket_id}")
        if outcome.code == TicketLookupCode.ACCESS_DENIED:
            raise TicketAccessDenied("cross-user ticket access denied")
        assert outcome.ticket is not None
        return outcome.ticket

    def list_user_tickets(self, *, trusted_user_id: str) -> list[TicketRecord]:
        rows = self.conn.execute(
            "SELECT * FROM tickets WHERE user_id = ? ORDER BY created_at, ticket_id",
            (trusted_user_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_all_tickets(self) -> list[TicketRecord]:
        rows = self.conn.execute(
            "SELECT * FROM tickets ORDER BY ticket_id"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count_events(self, *, event_type: str | None = None) -> int:
        if event_type is None:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM ticket_events").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM ticket_events WHERE event_type = ?",
                (event_type,),
            ).fetchone()
        return int(row["c"])

    def business_state_sha256(self) -> str:
        tickets = []
        for t in self.list_all_tickets():
            tickets.append(
                {
                    "ticket_id": t.ticket_id,
                    "user_id": t.user_id,
                    "complaint_type": t.complaint_type,
                    "status": t.status.value,
                    "summary": t.summary,
                    "resolution": t.resolution,
                    "version": t.version,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                }
            )
        payload = {"tickets": tickets}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        return hashlib.sha256(raw).hexdigest()

    def update_ticket(
        self,
        *,
        trusted_user_id: str,
        ticket_id: str,
        summary: str | None = None,
        resolution: str | None = None,
        expected_version: int | None = None,
    ) -> TicketRecord:
        current = self.get_ticket(trusted_user_id=trusted_user_id, ticket_id=ticket_id)
        if current.status == TicketStatus.CLOSED:
            raise ClosedTicketImmutable("closed ticket is immutable")
        if expected_version is not None and current.version != expected_version:
            raise TicketError("optimistic version conflict")
        now = self._now()
        new_summary = current.summary if summary is None else summary
        new_resolution = current.resolution if resolution is None else resolution
        with self.conn:
            self.conn.execute(
                """
                UPDATE tickets SET summary = ?, resolution = ?, version = version + 1, updated_at = ?
                WHERE ticket_id = ? AND user_id = ?
                """,
                (new_summary, new_resolution, now, ticket_id, trusted_user_id),
            )
            self.conn.execute(
                """
                INSERT INTO ticket_events(ticket_id, user_id, event_type, from_status, to_status, payload_json, created_at)
                VALUES (?, ?, 'UPDATE', ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    trusted_user_id,
                    current.status.value,
                    current.status.value,
                    json.dumps({"summary": new_summary, "resolution": new_resolution}),
                    now,
                ),
            )
        return self.get_ticket(trusted_user_id=trusted_user_id, ticket_id=ticket_id)

    def transition_ticket(
        self,
        *,
        trusted_user_id: str,
        ticket_id: str,
        to_status: TicketStatus,
    ) -> TicketRecord:
        current = self.get_ticket(trusted_user_id=trusted_user_id, ticket_id=ticket_id)
        if current.status == TicketStatus.CLOSED:
            raise ClosedTicketImmutable("closed ticket is immutable")
        # Enforce at service layer even if Policy was bypassed.
        self.state_machine.require_transition(current.status, to_status)
        now = self._now()
        try:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE tickets SET status = ?, version = version + 1, updated_at = ?
                    WHERE ticket_id = ? AND user_id = ?
                    """,
                    (to_status.value, now, ticket_id, trusted_user_id),
                )
                self.conn.execute(
                    """
                    INSERT INTO ticket_events(ticket_id, user_id, event_type, from_status, to_status, payload_json, created_at)
                    VALUES (?, ?, 'TRANSITION', ?, ?, '{}', ?)
                    """,
                    (ticket_id, trusted_user_id, current.status.value, to_status.value, now),
                )
        except InvalidTicketTransition:
            raise
        except Exception as exc:
            raise TicketError(f"transition_ticket failed: {exc}") from exc
        return self.get_ticket(trusted_user_id=trusted_user_id, ticket_id=ticket_id)

    def close_ticket(self, *, trusted_user_id: str, ticket_id: str) -> TicketRecord:
        current = self.get_ticket(trusted_user_id=trusted_user_id, ticket_id=ticket_id)
        if current.status == TicketStatus.CLOSED:
            return current
        return self.transition_ticket(
            trusted_user_id=trusted_user_id,
            ticket_id=ticket_id,
            to_status=TicketStatus.CLOSED,
        )

    def _fetch_row(self, ticket_id: str):
        return self.conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()

    @staticmethod
    def _row_to_record(row) -> TicketRecord:
        return TicketRecord.model_validate(dict(row))
