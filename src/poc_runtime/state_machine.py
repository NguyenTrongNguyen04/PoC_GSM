from __future__ import annotations

from pathlib import Path

import yaml

from poc_runtime.errors import InvalidTicketTransition
from poc_runtime.models import TicketStatus


class TicketStateMachine:
    """Single source of truth for ticket transitions (from config/policy.yaml)."""

    def __init__(self, allowed_transitions: dict[str, list[str]]) -> None:
        self._allowed = {
            str(k): [str(x) for x in (v or [])] for k, v in (allowed_transitions or {}).items()
        }

    @classmethod
    def from_policy_file(cls, project_root: Path) -> TicketStateMachine:
        path = project_root / "config" / "policy.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        transitions = (data.get("ticket") or {}).get("allowed_transitions") or {}
        return cls(transitions)

    def allowed_targets(self, from_status: TicketStatus) -> list[str]:
        return list(self._allowed.get(from_status.value, []))

    def can_transition(self, from_status: TicketStatus, to_status: TicketStatus) -> bool:
        return to_status.value in self.allowed_targets(from_status)

    def require_transition(self, from_status: TicketStatus, to_status: TicketStatus) -> None:
        if not self.can_transition(from_status, to_status):
            raise InvalidTicketTransition(
                f"invalid transition {from_status.value} -> {to_status.value}"
            )
