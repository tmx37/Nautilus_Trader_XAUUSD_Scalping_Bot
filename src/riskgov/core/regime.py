"""Macchina a stati del rischio NORMALE → DIFENSIVO → PAUSA → ARRESTO (stub F0, da implementare in F1).

Soglie, isteresi e condizioni di rientro in PIANO §2.3. Regole fisse:
- da PAUSA non si torna mai direttamente a NORMALE;
- da ARRESTO si esce solo con un evento manuale, e si va in PAUSA (OPS);
- DD >= arresto.enter_dd oppure equity <= floor portano sempre in ARRESTO.
"""

from __future__ import annotations

from riskgov.core.config import RiskConfig
from riskgov.core.types import PauseKind, RiskState


class RiskStateMachine:
    """Stato del rischio, aggiornato da equity, trade chiusi, eventi operativi e comandi manuali."""

    def __init__(self, cfg: RiskConfig, state: RiskState = RiskState.NORMALE) -> None:
        self._cfg = cfg
        self._state = state
        self._pause_kind: PauseKind | None = None

    @property
    def state(self) -> RiskState:
        return self._state

    @property
    def pause_kind(self) -> PauseKind | None:
        return self._pause_kind

    def on_equity(self, ts_ns: int, equity: float, hwm: float, floor: float) -> RiskState:
        raise NotImplementedError("F1: RiskStateMachine.on_equity")

    def on_trade_closed(self, ts_ns: int, r_multiple: float) -> RiskState:
        raise NotImplementedError("F1: RiskStateMachine.on_trade_closed (CUSUM, conteggi di rientro)")

    def on_ops_anomaly(self, ts_ns: int, reason: str) -> RiskState:
        raise NotImplementedError("F1: RiskStateMachine.on_ops_anomaly")

    def manual_unlock(self, ts_ns: int, operator: str, adr_id: str) -> RiskState:
        raise NotImplementedError("F1: RiskStateMachine.manual_unlock")
