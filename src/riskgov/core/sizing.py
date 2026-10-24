"""Dimensionamento delle posizioni (PIANO §2.3, ADR 0004).

Regole:
- budget di rischio = min(r_stato·E, m·(E − F)), misurato alla distanza dello SL (cioè in R);
- i limiti giornaliero, settimanale, di heat, di margine e per valuta sono vincoli ulteriori sulla
  quantità, calcolati in `riskgov.core.limits` sul rischio corretto per i gap;
- quantità = arrotondamento PER DIFETTO al passo di volume del broker;
- se la quantità è sotto il volume minimo il trade si RIFIUTA: mai arrotondare per eccesso
  (l'EA legacy lo faceva, vedi legacy/README.md);
- CAP_INIZIALE non entra mai nel calcolo: si usa solo l'equity corrente (R1.2).

Fail-closed: input non finiti o non positivi danno budget 0 e quantità 0 (rifiuto).
"""

from __future__ import annotations

import math
from collections.abc import Callable

from riskgov.core.config import RiskConfig
from riskgov.core.types import AccountSnapshot, RiskState


def risk_fraction(state: RiskState, cfg: RiskConfig, ramp_active: bool = False) -> float:
    """Rischio per trade dello stato, come frazione dell'equity; la rampa di F4 lo può solo ridurre."""
    r = cfg.r_state[state]
    if ramp_active:
        r = min(r, cfg.f4_ramp.r_normale)
    return r


def risk_budget(snapshot: AccountSnapshot, cfg: RiskConfig) -> float:
    """Rischio massimo alla distanza dello SL, nella valuta del conto: min(r_stato·E, m·(E − F)).

    Non include i limiti di periodo, di heat e di esposizione: quelli dipendono dallo strumento e
    dal gap, e sono vincoli separati sulla quantità.
    """
    e, f = snapshot.equity, snapshot.floor
    if not (math.isfinite(e) and math.isfinite(f) and e > 0):
        return 0.0
    r = risk_fraction(snapshot.state, cfg, snapshot.ramp_active)
    return max(0.0, min(r * e, cfg.cppi.m * (e - f)))


def round_down_volume(units: float, min_volume: int, step_volume: int, max_volume: int) -> int:
    """Quantità valida per il broker non superiore a `units`; 0 se sotto il minimo o input non validi."""
    if not volume_spec_ok(min_volume, step_volume, max_volume):
        return 0
    if math.isnan(units) or units < min_volume:
        return 0
    cap = min(units, float(max_volume))
    q = math.floor(cap / step_volume) * step_volume
    return q if q >= min_volume else 0


def position_size(
    budget: float,
    stop_distance: float,
    value_per_unit: float,
    min_volume: int,
    step_volume: int,
    max_volume: int,
) -> int:
    """Quantità in unità intere tale che quantità × distanza × valore unitario <= budget; 0 = rifiuto.

    `stop_distance` è la distanza arrotondata effettivamente inviata al broker; `value_per_unit` è il
    valore nella valuta del conto di un movimento di 1 unità di prezzo per 1 unità di strumento.
    """
    values = (budget, stop_distance, value_per_unit)
    if not all(math.isfinite(x) for x in values) or budget <= 0 or stop_distance <= 0 or value_per_unit <= 0:
        return 0
    unit_risk = stop_distance * value_per_unit
    q = round_down_volume(budget / unit_risk, min_volume, step_volume, max_volume)
    return shrink_until(q, step_volume, min_volume, lambda units: units * unit_risk <= budget)


def shrink_until(q: int, step_volume: int, min_volume: int, ok: Callable[[int], bool]) -> int:
    """Riduce q di un passo finché `ok(q)` è vero; 0 se scende sotto il minimo.

    La divisione e il prodotto in virgola mobile possono differire di un ulp: la verifica finale usa lo
    stesso prodotto del controllo, così il vincolo vale esattamente. Bastano al più due passi; oltre è
    un errore numerico e il trade si rifiuta.
    """
    for _ in range(3):
        if q < min_volume:
            return 0
        if ok(q):
            return q
        q -= step_volume
    return 0


def volume_spec_ok(min_volume: int, step_volume: int, max_volume: int) -> bool:
    """Volumi del broker coerenti: passo > 0, 0 < minimo <= massimo, minimo multiplo del passo."""
    return step_volume > 0 and 0 < min_volume <= max_volume and min_volume % step_volume == 0
