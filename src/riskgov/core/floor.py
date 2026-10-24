"""Riferimenti di equity: E0, massimo di equity (HWM) e floor a cricchetto in stile CPPI (PIANO §2.3).

- HWM = massimo dell'equity di chiusura giornaliera (confine alle 17:00 di New York): si aggiorna solo
  alla chiusura del giorno, così i ritracciamenti intraday non lo spostano.
- F = max(F_prec, E0·(1 − K) + λ·(HWM − E0)). Il floor non scende mai, neanche dopo uno sblocco manuale.
  Con K >= D_kill e λ <= 1 − D_kill il kill switch scatta sempre prima del floor (ADR 0004).
- Un prelievo riscala E0, HWM ed F in proporzione: DD ed E/F restano invariati, quindi il prelievo non
  viene letto come drawdown. Senza riscalare E0 la formula porterebbe F sopra l'equity dopo un prelievo
  grande (es. metà del conto) e farebbe scattare un ARRESTO immediato.

Queste funzioni aggiornano stato persistito: con input non validi sollevano ValueError (è un errore
dell'integrazione, che lo tratta come anomalia operativa), non restituiscono valori di ripiego.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from riskgov.core.config import CppiConfig


@dataclass(frozen=True, slots=True)
class EquityMarks:
    """Riferimenti di equity persistiti fra un riavvio e l'altro.

    `e0` nasce uguale a CAP_INIZIALE e cambia solo con i prelievi; serve solo al floor, mai al sizing.
    """

    e0: float
    hwm: float
    floor: float


def drawdown(equity: float, hwm: float) -> float:
    """DD = 1 − E/HWM. Negativo se l'equity intraday supera il massimo di chiusura."""
    _require_positive(hwm, "hwm")
    _require_finite(equity, "equity")
    return 1.0 - equity / hwm


def floor_target(e0: float, hwm: float, cfg: CppiConfig) -> float:
    """Valore del floor senza cricchetto: E0·(1 − K) + λ·(HWM − E0)."""
    return e0 * (1.0 - cfg.k) + cfg.lam * (hwm - e0)


def update_floor(prev_floor: float, e0: float, hwm: float, cfg: CppiConfig) -> float:
    """Nuovo valore del floor dato il massimo di equity corrente (non scende mai)."""
    _require_finite(prev_floor, "prev_floor")
    _require_positive(e0, "e0")
    _require_positive(hwm, "hwm")
    return max(prev_floor, floor_target(e0, hwm, cfg))


def initial_marks(cap_iniziale: float, cfg: CppiConfig) -> EquityMarks:
    """Riferimenti all'avvio del conto: HWM = E0 = CAP_INIZIALE, F = E0·(1 − K)."""
    _require_positive(cap_iniziale, "cap_iniziale")
    return EquityMarks(e0=cap_iniziale, hwm=cap_iniziale, floor=floor_target(cap_iniziale, cap_iniziale, cfg))


def on_daily_close(marks: EquityMarks, close_equity: float, cfg: CppiConfig) -> EquityMarks:
    """Aggiornamento alla chiusura del giorno di trading: HWM = max(HWM, E_chiusura), poi il floor."""
    _require_finite(close_equity, "close_equity")
    hwm = max(marks.hwm, close_equity)
    return EquityMarks(e0=marks.e0, hwm=hwm, floor=update_floor(marks.floor, marks.e0, hwm, cfg))


def rescale_on_withdrawal(marks: EquityMarks, equity_before: float, equity_after: float) -> EquityMarks:
    """E0, HWM e floor riscalati dopo un prelievo, così che non venga letto come drawdown.

    Un aumento di equity non è un prelievo: un deposito è vietato (R1.1) e va gestito come anomalia.
    """
    _require_positive(equity_before, "equity_before")
    _require_positive(equity_after, "equity_after")
    if equity_after >= equity_before:
        raise ValueError(
            f"prelievo con equity non in calo ({equity_before} -> {equity_after}): un deposito è un'anomalia"
        )
    ratio = equity_after / equity_before
    return EquityMarks(e0=marks.e0 * ratio, hwm=marks.hwm * ratio, floor=marks.floor * ratio)


def rebase_after_unlock(marks: EquityMarks, equity: float) -> EquityMarks:
    """Dopo uno sblocco manuale dell'ARRESTO: HWM ribasato all'equity corrente, floor mantenuto.

    Se l'equity non supera il floor lo sblocco è impossibile: il capitale sotto F non si rischia più,
    e ripartire richiede un ADR con nuovi parametri.
    """
    _require_finite(equity, "equity")
    if equity <= marks.floor:
        raise ValueError(f"sblocco impossibile: equity {equity} <= floor {marks.floor}")
    return EquityMarks(e0=marks.e0, hwm=equity, floor=marks.floor)


def _require_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} non finito: {value!r}")


def _require_positive(value: float, name: str) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} deve essere finito e > 0: {value!r}")
