"""Dimensionamento delle posizioni (stub F0, da implementare in F1).

Regole (PIANO §2.3, ADR 0004):
- budget = min(r_stato·E, m·(E − F), spazio residuo sotto i limiti giornaliero, settimanale e di heat);
- quantità = arrotondamento PER DIFETTO al passo di volume del broker;
- se la quantità è sotto il volume minimo il trade si RIFIUTA: mai arrotondare per eccesso
  (l'EA legacy lo faceva, vedi legacy/README.md);
- CAP_INIZIALE non entra mai nel calcolo: si usa solo l'equity corrente (R1.2).
"""

from __future__ import annotations

from riskgov.core.config import RiskConfig
from riskgov.core.types import AccountSnapshot


def risk_budget(snapshot: AccountSnapshot, cfg: RiskConfig) -> float:
    """Rischio massimo, nella valuta del conto, consentito per il prossimo ingresso."""
    raise NotImplementedError("F1: riskgov.core.sizing.risk_budget")


def position_size(
    budget: float,
    stop_distance: float,
    value_per_unit: float,
    min_volume: int,
    step_volume: int,
    max_volume: int,
) -> int:
    """Quantità in unità intere; 0 significa rifiuto (sotto il minimo o input non validi).

    `stop_distance` è la distanza arrotondata effettivamente inviata al broker; `value_per_unit` è il
    valore nella valuta del conto di un movimento di 1 unità di prezzo per 1 unità di strumento.
    """
    raise NotImplementedError("F1: riskgov.core.sizing.position_size")
