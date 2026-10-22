"""Decisione finale su ogni proposta (stub F0, da implementare in F1).

`decide()` deve essere pura e deterministica: stessi input, stessa decisione. Così il Monte Carlo di
calibrazione e il nodo live usano esattamente la stessa logica, e uno snapshot ripristinato dopo un
riavvio produce le stesse decisioni.
"""

from __future__ import annotations

from riskgov.core.config import RiskConfig
from riskgov.core.types import AccountSnapshot, Decision, TradeProposal


def decide(proposal: TradeProposal, snapshot: AccountSnapshot, cfg: RiskConfig) -> Decision:
    """Approva, riduce o rifiuta una proposta d'ingresso.

    Le uscite non passano da qui: sono sempre approvate.
    """
    raise NotImplementedError("F1: riskgov.core.governor.decide")
