"""Floor di equity a cricchetto, stile CPPI (stub F0, da implementare in F1).

F = max(F_prec, E0·(1 − K) + λ·(HWM − E0)). Il floor non scende mai, neanche dopo uno sblocco
manuale. Con K >= D_kill e λ <= 1 − D_kill il kill switch scatta sempre prima del floor (ADR 0004).
Un prelievo riscala HWM ed F in proporzione.
"""

from __future__ import annotations

from riskgov.core.config import CppiConfig


def update_floor(prev_floor: float, e0: float, hwm: float, cfg: CppiConfig) -> float:
    """Nuovo valore del floor dato il massimo di equity corrente."""
    raise NotImplementedError("F1: riskgov.core.floor.update_floor")


def rescale_on_withdrawal(
    hwm: float, floor: float, equity_before: float, equity_after: float
) -> tuple[float, float]:
    """HWM e floor riscalati dopo un prelievo, così che non venga letto come drawdown."""
    raise NotImplementedError("F1: riskgov.core.floor.rescale_on_withdrawal")
