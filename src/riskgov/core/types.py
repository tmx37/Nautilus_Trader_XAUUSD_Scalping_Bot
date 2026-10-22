"""Tipi del core del rischio. Immutabili, senza dipendenze da NautilusTrader.

Convenzioni: importi nella valuta del conto; prezzi come float nella valuta di quotazione; quantità in
unità intere dello strumento (es. 1.000 unità = 0,01 lot EURUSD), così l'arrotondamento al passo è esatto.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class RiskState(StrEnum):
    """Stati della macchina a stati del rischio (PIANO §2.3)."""

    NORMALE = "NORMALE"
    DIFENSIVO = "DIFENSIVO"
    PAUSA = "PAUSA"
    ARRESTO = "ARRESTO"


class PauseKind(StrEnum):
    """Motivo della PAUSA: PERF si chiude da sola con le condizioni di rientro, OPS solo a mano."""

    PERF = "PERF"
    OPS = "OPS"


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class DecisionKind(StrEnum):
    APPROVED = "APPROVED"
    REDUCED = "REDUCED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """Proposta di ingresso pubblicata da un Actor di segnale. Il governor decide la quantità."""

    proposal_id: str
    source: str
    instrument: str
    side: Side
    reference_price: float
    stop_price: float
    take_profit_price: float | None
    ts_ns: int
    indicators: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Stato del conto e del rischio al momento della decisione."""

    ts_ns: int
    equity: float
    balance: float
    hwm: float
    floor: float
    day_start_equity: float
    week_start_equity: float
    open_risk_gap_adjusted: float
    margin_used: float
    open_positions: int
    state: RiskState
    pause_kind: PauseKind | None = None


@dataclass(frozen=True, slots=True)
class Check:
    """Esito di un singolo controllo, scritto nel journal insieme alla decisione."""

    name: str
    value: float
    limit: float
    passed: bool


@dataclass(frozen=True, slots=True)
class Decision:
    """Risposta del governor a una proposta."""

    proposal_id: str
    kind: DecisionKind
    quantity: int
    risk_amount: float
    checks: tuple[Check, ...]
    reason: str
