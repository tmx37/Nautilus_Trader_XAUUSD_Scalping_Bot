"""Limiti di perdita ed esposizione (stub F0, da implementare in F1).

- Limiti giornaliero e settimanale come soglie d'ingresso sulla perdita impegnata:
  (E_inizio_periodo − E) + Σ rischio aperto corretto per i gap + rischio del nuovo trade.
- Heat cap, margine usato, numero di posizioni, una posizione per strumento, rischio netto per valuta.
- Nessuna aggiunta, mediazione, griglia o martingala.
"""

from __future__ import annotations

from riskgov.core.config import RiskConfig
from riskgov.core.types import AccountSnapshot, Check, TradeProposal


def committed_loss(period_start_equity: float, equity: float, open_risk_gap_adjusted: float) -> float:
    """Perdita già impegnata nel periodo, prima del nuovo trade."""
    raise NotImplementedError("F1: riskgov.core.limits.committed_loss")


def check_limits(
    proposal: TradeProposal, new_risk: float, snapshot: AccountSnapshot, cfg: RiskConfig
) -> tuple[Check, ...]:
    """Tutti i controlli di limite per una proposta; ognuno finisce nel journal."""
    raise NotImplementedError("F1: riskgov.core.limits.check_limits")
