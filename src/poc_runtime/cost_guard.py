from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from poc_runtime.llm.errors import ProviderError, ProviderErrorCategory


@dataclass
class CostEstimate:
    input_tokens: int
    output_tokens: int
    estimated_usd: float


@dataclass
class CostLedgerSummary:
    hard_cap_usd: float
    spent_usd: float
    reserved_usd: float
    attempts_authorized: int
    attempts_committed: int
    input_tokens_total: int
    output_tokens_total: int
    pricing_input_per_1m: float
    pricing_output_per_1m: float
    pricing_note: str


class CostGuard:
    """Run-scoped cost ledger shared across all scenarios in a run."""

    def __init__(
        self,
        *,
        hard_cap_usd: float = 15.0,
        input_per_1m: float = 0.3,
        output_per_1m: float = 2.5,
        pricing_note: str = "estimation snapshot; re-verify before paid canary",
        zero_cost: bool = False,
    ) -> None:
        self.hard_cap_usd = hard_cap_usd
        self.input_per_1m = input_per_1m
        self.output_per_1m = output_per_1m
        self.pricing_note = pricing_note
        self.zero_cost = zero_cost
        self.spent_usd = 0.0
        self.reserved_usd = 0.0
        self.attempts_authorized = 0
        self.attempts_committed = 0
        self.input_tokens_total = 0
        self.output_tokens_total = 0
        self._open_reservations: list[float] = []

    @classmethod
    def from_project(
        cls,
        project_root: Path,
        *,
        hard_cap_usd: float | None = None,
        zero_cost: bool = False,
    ) -> CostGuard:
        path = project_root / "config" / "experiment.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pricing = data.get("pricing_snapshot") or {}
        gen = pricing.get("generation_standard_per_1m_tokens") or {}
        budget = data.get("budget") or {}
        return cls(
            hard_cap_usd=float(
                hard_cap_usd if hard_cap_usd is not None else budget.get("hard_cap_usd", 15.0)
            ),
            input_per_1m=float(gen.get("input", 0.3)),
            output_per_1m=float(gen.get("output", 2.5)),
            pricing_note=str(
                pricing.get("note")
                or "Snapshot for estimation only; re-verify immediately before paid run."
            ),
            zero_cost=zero_cost,
        )

    def estimate(self, *, input_tokens: int, output_tokens: int) -> CostEstimate:
        if self.zero_cost:
            return CostEstimate(0, 0, 0.0)
        cost = (
            input_tokens / 1_000_000.0 * self.input_per_1m
            + output_tokens / 1_000_000.0 * self.output_per_1m
        )
        return CostEstimate(input_tokens, output_tokens, cost)

    def authorize(self, estimate: CostEstimate) -> None:
        """Pre-authorize one provider attempt (including retries)."""
        if self.zero_cost:
            self.attempts_authorized += 1
            self._open_reservations.append(0.0)
            return
        projected = self.spent_usd + self.reserved_usd + estimate.estimated_usd
        if projected > self.hard_cap_usd:
            raise ProviderError(
                ProviderErrorCategory.BUDGET_REJECTED,
                f"cost guard reject: projected ${projected:.6f} exceeds hard cap ${self.hard_cap_usd}",
                retryable=False,
            )
        self.reserved_usd += estimate.estimated_usd
        self._open_reservations.append(estimate.estimated_usd)
        self.attempts_authorized += 1

    def commit(self, estimate: CostEstimate, *, actual_usd: float | None = None) -> None:
        """Settle the latest reservation with actual usage when available."""
        reserved = self._open_reservations.pop() if self._open_reservations else 0.0
        self.reserved_usd = max(0.0, self.reserved_usd - reserved)
        if self.zero_cost:
            self.attempts_committed += 1
            return
        charge = reserved if actual_usd is None else float(actual_usd)
        # Conservative: if attempt failed without usage metadata, keep reserved estimate.
        projected = self.spent_usd + charge
        if projected > self.hard_cap_usd:
            raise ProviderError(
                ProviderErrorCategory.BUDGET_REJECTED,
                f"cost guard reject on commit: projected ${projected:.6f} exceeds hard cap ${self.hard_cap_usd}",
                retryable=False,
            )
        self.spent_usd += charge
        self.input_tokens_total += estimate.input_tokens
        self.output_tokens_total += estimate.output_tokens
        self.attempts_committed += 1

    def release_reservation_keep_charge(self, estimate: CostEstimate) -> None:
        """On failed attempt without usage: charge reserved estimate conservatively."""
        self.commit(estimate, actual_usd=None)

    @property
    def cumulative_run_cost_usd(self) -> float:
        return self.spent_usd + self.reserved_usd

    def summary(self) -> CostLedgerSummary:
        return CostLedgerSummary(
            hard_cap_usd=self.hard_cap_usd,
            spent_usd=self.spent_usd,
            reserved_usd=self.reserved_usd,
            attempts_authorized=self.attempts_authorized,
            attempts_committed=self.attempts_committed,
            input_tokens_total=self.input_tokens_total,
            output_tokens_total=self.output_tokens_total,
            pricing_input_per_1m=self.input_per_1m,
            pricing_output_per_1m=self.output_per_1m,
            pricing_note=self.pricing_note,
        )

    def summary_dict(self) -> dict[str, Any]:
        s = self.summary()
        return {
            "hard_cap_usd": s.hard_cap_usd,
            "spent_usd": s.spent_usd,
            "reserved_usd": s.reserved_usd,
            "cumulative_run_cost_usd": self.cumulative_run_cost_usd,
            "attempts_authorized": s.attempts_authorized,
            "attempts_committed": s.attempts_committed,
            "input_tokens_total": s.input_tokens_total,
            "output_tokens_total": s.output_tokens_total,
            "pricing_input_per_1m": s.pricing_input_per_1m,
            "pricing_output_per_1m": s.pricing_output_per_1m,
            "pricing_note": s.pricing_note,
            "zero_cost": self.zero_cost,
        }
