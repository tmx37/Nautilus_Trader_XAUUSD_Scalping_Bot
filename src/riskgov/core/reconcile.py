"""Politica di riconciliazione fra stato locale e stato del broker (PIANO §2.3, R1.6).

Il broker è la fonte di verità per lo stato, il journal per l'intento. La tabella POLICY è la specifica;
la classificazione dei casi a partire dai report del broker è uno stub da implementare in F1.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from riskgov.core.types import PauseKind, RiskState


class ReconcileCase(StrEnum):
    KNOWN_WITH_SL = "KNOWN_WITH_SL"
    KNOWN_WITHOUT_SL = "KNOWN_WITHOUT_SL"
    UNKNOWN_POSITION = "UNKNOWN_POSITION"
    LOCAL_ORDER_MISSING_AT_BROKER = "LOCAL_ORDER_MISSING_AT_BROKER"
    FOREIGN_PENDING_ORDER = "FOREIGN_PENDING_ORDER"
    SIZE_MISMATCH_OR_STOP_OUT = "SIZE_MISMATCH_OR_STOP_OUT"
    EQUITY_MISMATCH = "EQUITY_MISMATCH"


@dataclass(frozen=True, slots=True)
class ReconcileAction:
    action: str
    # Stato di rischio imposto dal caso (None = invariato). Le condizioni aggiuntive sono nel testo.
    state: RiskState | None
    pause_kind: PauseKind | None


POLICY: Mapping[ReconcileCase, ReconcileAction] = {
    ReconcileCase.KNOWN_WITH_SL: ReconcileAction(
        "Riprendere; se lo SL al broker è più largo di quello voluto, riportarlo al voluto "
        "(PAUSA OPS se la modifica fallisce)",
        None,
        None,
    ),
    ReconcileCase.KNOWN_WITHOUT_SL: ReconcileAction(
        "Rimettere lo SL voluto; se il prezzo lo ha già superato, chiudere", RiskState.PAUSA, PauseKind.OPS
    ),
    ReconcileCase.UNKNOWN_POSITION: ReconcileAction(
        "Mettere uno SL a rischio <= r_NORMALE·E se manca; contarla nella heat; non chiuderla se lo SL "
        "si può mettere",
        RiskState.PAUSA,
        PauseKind.OPS,
    ),
    ReconcileCase.LOCAL_ORDER_MISSING_AT_BROKER: ReconcileAction(
        "Cercare nei deal per clientOrderId; se eseguito trattarlo come posizione nota, altrimenti segnarlo "
        "fallito; mai reinviarlo (3 casi in 24 h -> PAUSA OPS)",
        None,
        None,
    ),
    ReconcileCase.FOREIGN_PENDING_ORDER: ReconcileAction(
        "Cancellarlo: il sistema usa solo ingressi a mercato", RiskState.PAUSA, PauseKind.OPS
    ),
    ReconcileCase.SIZE_MISMATCH_OR_STOP_OUT: ReconcileAction(
        "Adottare il valore del broker; ARRESTO se l'evento è del server (isServerEvent)", None, None
    ),
    ReconcileCase.EQUITY_MISMATCH: ReconcileAction(
        "Equity del broker diversa da quella locale oltre lo 0,5%: fidarsi del broker",
        RiskState.PAUSA,
        PauseKind.OPS,
    ),
}


def classify(*args: object, **kwargs: object) -> list[ReconcileCase]:
    """Casi di riconciliazione a partire dai report del broker e dal journal (firma definitiva in F1)."""
    raise NotImplementedError("F1: riskgov.core.reconcile.classify")
