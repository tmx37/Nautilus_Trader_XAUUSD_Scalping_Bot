"""Limiti di perdita ed esposizione (PIANO §2.3, R1.3 e R1.6).

- Rischio di una posizione corretto per i gap: q·(|P − SL| + G_i)·v, con P il prezzo di chiusura corrente.
  Una posizione senza SL ha rischio infinito: finché resta scoperta non si apre nulla (fail-closed).
- Limiti giornaliero e settimanale come soglie d'ingresso sulla perdita impegnata:
  (E_inizio_periodo − E) + Σ rischio aperto corretto per i gap + rischio del nuovo trade
  <= limite_stato · E_inizio_periodo. La base è l'equity d'inizio periodo, così la soglia resta fissa
  per tutto il giorno o la settimana.
- Heat cap, margine usato e rischio netto per valuta come frazioni dell'equity corrente.
- Una posizione per strumento: nessuna aggiunta, mediazione, griglia o martingala.
- Nessun ingresso nel blackout delle notizie e da venerdì alle 16:00 UTC fino a lunedì 00:00 UTC.

Ogni limite è lineare nella quantità q del nuovo trade (`used + q·per_unit <= limit`): `Capacity` ne dà
sia la quantità massima sia il controllo da scrivere nel journal.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time

from riskgov.core.config import RiskConfig
from riskgov.core.types import Check, NewsEvent, OpenPosition, Side

_NS_PER_S = 1_000_000_000
_NS_PER_MIN = 60 * _NS_PER_S


@dataclass(frozen=True, slots=True)
class Capacity:
    """Vincolo lineare sulla quantità del nuovo trade: used + q·per_unit <= limit."""

    name: str
    used: float
    limit: float
    per_unit: float

    def max_units(self) -> float:
        """Quantità massima ammessa (può essere negativa: nessuna quantità ammessa). 0 se non calcolabile."""
        room = self.limit - self.used
        if not (math.isfinite(room) and math.isfinite(self.per_unit) and self.per_unit > 0):
            return 0.0
        return room / self.per_unit

    def check(self, units: int) -> Check:
        value = self.used + units * self.per_unit
        return Check(self.name, value, self.limit, bool(value <= self.limit))


def position_risk(pos: OpenPosition, *, weekend: bool = False) -> float:
    """Rischio della posizione corretto per i gap, nella valuta del conto; infinito se non calcolabile.

    Se il prezzo ha già superato lo SL resta solo il gap: il broker chiuderà al prossimo prezzo.
    """
    if pos.stop_price is None:
        return math.inf
    dist = pos.mark_price - pos.stop_price if pos.side is Side.LONG else pos.stop_price - pos.mark_price
    gap = pos.weekend_gap if weekend else pos.gap
    if not (gap >= 0 and pos.value_per_unit > 0 and pos.quantity > 0):
        return math.inf
    risk = pos.quantity * (max(dist, 0.0) + gap) * pos.value_per_unit
    return risk if math.isfinite(risk) else math.inf


def open_heat(positions: Iterable[OpenPosition], *, weekend: bool = False) -> float:
    """Somma del rischio corretto per i gap delle posizioni aperte."""
    return sum((position_risk(p, weekend=weekend) for p in positions), 0.0)


def committed_loss(period_start_equity: float, equity: float, open_risk_gap_adjusted: float) -> float:
    """Perdita già impegnata nel periodo, prima del nuovo trade."""
    return (period_start_equity - equity) + open_risk_gap_adjusted


def currency_exposure(positions: Iterable[OpenPosition]) -> dict[str, float]:
    """Rischio netto con segno per valuta: un long è lungo la base e corto la quotata."""
    net: dict[str, float] = {}
    for p in positions:
        risk = position_risk(p)
        sign = 1.0 if p.side is Side.LONG else -1.0
        net[p.base_currency] = net.get(p.base_currency, 0.0) + sign * risk
        net[p.quote_currency] = net.get(p.quote_currency, 0.0) - sign * risk
    return net


def currency_capacity(
    currency: str, direction: float, net: Mapping[str, float], cap: float, per_unit: float
) -> Capacity:
    """Vincolo sul rischio netto di una valuta per un nuovo trade che la sposta nel verso `direction`.

    |net + direction·x| <= L con L = max(cap, |net|): se l'esposizione supera già il cap (es. una posizione
    estranea) sono ammessi solo trade che la riducono. Con x >= 0 il vincolo equivale a
    direction·net + x <= L.
    """
    name = f"currency_net_risk_{currency}"
    n = net.get(currency, 0.0)
    if not math.isfinite(n):
        # Posizione senza SL sulla valuta (±inf, o NaN se ce ne sono in versi opposti): nessuno spazio.
        return Capacity(name, math.inf, cap, per_unit)
    return Capacity(name, direction * n, max(cap, abs(n)), per_unit)


def news_blackout(
    ts_ns: int, currencies: Iterable[str], events: Iterable[NewsEvent], before_min: int, after_min: int
) -> NewsEvent | None:
    """Primo evento che mette in blackout uno strumento con queste valute, o None."""
    ccys = frozenset(currencies)
    for ev in events:
        if ev.currencies & ccys and (
            ev.ts_ns - before_min * _NS_PER_MIN <= ts_ns <= ev.ts_ns + after_min * _NS_PER_MIN
        ):
            return ev
    return None


def weekend_entry_block(ts_ns: int, cutoff: time) -> bool:
    """True da venerdì all'orario `cutoff` (UTC) fino a lunedì 00:00 UTC.

    Il PIANO dice "nessun ingresso dopo le 16:00 UTC di venerdì"; il blocco dura fino all'inizio di
    lunedì UTC, cioè copre anche la riapertura della domenica sera, quando gli spread sono più larghi.
    """
    dt = datetime.fromtimestamp(ts_ns // _NS_PER_S, tz=UTC)
    weekday = dt.weekday()  # lunedì = 0
    return weekday >= 5 or (weekday == 4 and dt.time() >= cutoff)


def weekend_closures(positions: Iterable[OpenPosition], equity: float, cfg: RiskConfig) -> tuple[str, ...]:
    """Strumenti da chiudere prima del weekend, dalla posizione più recente, finché la heat del weekend
    corretta per i gap non scende sotto `gaps.weekend_heat_cap`·E (PIANO §2.3, R1.6).

    Fail-closed: con equity non valida o una posizione senza SL si chiude tutto ciò che serve, fino a tutto.
    """
    cap = cfg.gaps.weekend_heat_cap * equity
    remaining = sorted(positions, key=lambda p: p.opened_ts_ns)
    to_close: list[str] = []
    while remaining and not open_heat(remaining, weekend=True) <= cap:
        to_close.append(remaining.pop().instrument)
    return tuple(to_close)
