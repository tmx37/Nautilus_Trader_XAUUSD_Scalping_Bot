"""Costruttori e strategie hypothesis condivisi dai test di riskgov.core.

Valori realistici per un conto in EUR su Pepperstone EU (major FX, leva ESMA 1:30, 0,01 lot = 1.000 unità).
I tassi di conversione sono approssimati: servono solo a dare ordini di grandezza plausibili.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import strategies as st

from riskgov.core.config import load_risk_config
from riskgov.core.types import (
    AccountSnapshot,
    InstrumentSpec,
    MarketContext,
    NewsEvent,
    OpenPosition,
    PauseKind,
    RiskState,
    Side,
    TradeProposal,
)

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config" / "risk.example.yaml"
CFG = load_risk_config(EXAMPLE_CONFIG)

NS = 1_000_000_000
HOUR_NS = 3600 * NS
DAY_NS = 24 * HOUR_NS


def utc_ns(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp()) * NS


WED_NOON_NS = utc_ns(2026, 10, 21, 12, 0)  # mercoledì

EURUSD = InstrumentSpec("EURUSD", "EUR", "USD", 1e-5, 1_000, 1_000, 10_000_000, 0.0, 1 / 30)
GBPUSD = InstrumentSpec("GBPUSD", "GBP", "USD", 1e-5, 1_000, 1_000, 10_000_000, 0.0, 1 / 30)
USDJPY = InstrumentSpec("USDJPY", "USD", "JPY", 1e-3, 1_000, 1_000, 10_000_000, 0.0, 1 / 30)
AUDUSD = InstrumentSpec("AUDUSD", "AUD", "USD", 1e-5, 1_000, 1_000, 10_000_000, 0.0, 1 / 20)
SPECS = {s.instrument: s for s in (EURUSD, GBPUSD, USDJPY, AUDUSD)}

PRICE = {"EURUSD": 1.1, "GBPUSD": 1.3, "USDJPY": 150.0, "AUDUSD": 0.65}
# EUR per 1,0 di prezzo per unità (conversione della valuta quotata in EUR).
VALUE_PER_UNIT = {"EURUSD": 1 / 1.1, "GBPUSD": 1 / 1.1, "USDJPY": 1 / 165.0, "AUDUSD": 1 / 1.1}
# Nozionale in EUR di 1 unità (conversione della valuta base in EUR).
NOTIONAL_PER_UNIT = {"EURUSD": 1.0, "GBPUSD": 1.18, "USDJPY": 1 / 1.1, "AUDUSD": 0.59}


def market(
    spec: InstrumentSpec = EURUSD,
    *,
    bid: float | None = None,
    spread_ticks: int = 2,
    quote_ts_ns: int = WED_NOON_NS,
    gap_ticks: int = 50,
    events: tuple[NewsEvent, ...] = (),
    **overrides: object,
) -> MarketContext:
    bid = PRICE[spec.instrument] if bid is None else bid
    bid = round(round(bid / spec.price_increment) * spec.price_increment, 10)  # quote sulla griglia dei tick
    m = MarketContext(
        spec=spec,
        bid=bid,
        ask=round(bid + spread_ticks * spec.price_increment, 10),
        quote_ts_ns=quote_ts_ns,
        value_per_unit=VALUE_PER_UNIT[spec.instrument],
        notional_per_unit=NOTIONAL_PER_UNIT[spec.instrument],
        gap=gap_ticks * spec.price_increment,
        events=events,
    )
    return replace(m, **overrides) if overrides else m


def snapshot(
    equity: float = 2000.0,
    *,
    state: RiskState = RiskState.NORMALE,
    positions: tuple[OpenPosition, ...] = (),
    ts_ns: int = WED_NOON_NS,
    **overrides: object,
) -> AccountSnapshot:
    s = AccountSnapshot(
        ts_ns=ts_ns,
        equity=equity,
        balance=equity,
        hwm=equity,
        floor=equity * (1 - CFG.cppi.k),
        day_start_equity=equity,
        week_start_equity=equity,
        margin_used=0.0,
        positions=positions,
        state=state,
        pause_kind=PauseKind.PERF if state is RiskState.PAUSA else None,
    )
    return replace(s, **overrides) if overrides else s


def proposal(
    m: MarketContext,
    *,
    side: Side = Side.LONG,
    stop_ticks: int = 800,
    tp_ticks: int | None = None,
    proposal_id: str = "p-1",
    instrument: str | None = None,
) -> TradeProposal:
    tick = m.spec.price_increment
    entry = m.ask if side is Side.LONG else m.bid
    sign = 1 if side is Side.LONG else -1
    return TradeProposal(
        proposal_id=proposal_id,
        source="test",
        instrument=instrument or m.spec.instrument,
        side=side,
        reference_price=entry,
        stop_price=round(entry - sign * stop_ticks * tick, 10),
        take_profit_price=None if tp_ticks is None else round(entry + sign * tp_ticks * tick, 10),
        ts_ns=m.quote_ts_ns,
    )


def position(
    spec: InstrumentSpec = EURUSD,
    *,
    side: Side = Side.LONG,
    quantity: int = 1_000,
    stop_ticks: int | None = 500,
    mark: float | None = None,
    gap_ticks: int = 50,
    weekend_gap_ticks: int = 200,
    opened_ts_ns: int = WED_NOON_NS - DAY_NS,
) -> OpenPosition:
    tick = spec.price_increment
    mark = PRICE[spec.instrument] if mark is None else mark
    sign = 1 if side is Side.LONG else -1
    return OpenPosition(
        instrument=spec.instrument,
        base_currency=spec.base_currency,
        quote_currency=spec.quote_currency,
        side=side,
        quantity=quantity,
        mark_price=mark,
        stop_price=None if stop_ticks is None else round(mark - sign * stop_ticks * tick, 10),
        gap=gap_ticks * tick,
        weekend_gap=weekend_gap_ticks * tick,
        value_per_unit=VALUE_PER_UNIT[spec.instrument],
        opened_ts_ns=opened_ts_ns,
    )


# --- strategie hypothesis -----------------------------------------------------------------------------

ENTRY_STATES = (RiskState.NORMALE, RiskState.DIFENSIVO)


@st.composite
def positions_st(
    draw: st.DrawFn, max_size: int = 3, exclude: str | None = None, naked: bool = True
) -> tuple[OpenPosition, ...]:
    names = sorted(n for n in SPECS if n != exclude)
    instruments = draw(st.lists(st.sampled_from(names), max_size=max_size, unique=True))
    out = []
    for i, name in enumerate(instruments):
        spec = SPECS[name]
        # Negativo: il prezzo ha già superato lo SL. None: posizione scoperta (solo se naked=True).
        stop_ticks = draw(st.integers(-50, 2000))
        if naked and draw(st.integers(0, 19)) == 0:
            stop_ticks = None
        out.append(
            position(
                spec,
                side=draw(st.sampled_from(Side)),
                quantity=draw(st.integers(1, 30)) * spec.step_volume,
                stop_ticks=stop_ticks,
                mark=PRICE[name] * draw(st.floats(0.97, 1.03)),
                gap_ticks=draw(st.integers(0, 300)),
                weekend_gap_ticks=draw(st.integers(0, 1000)),
                opened_ts_ns=WED_NOON_NS - (i + 1) * HOUR_NS,
            )
        )
    return tuple(out)


@st.composite
def decision_inputs(
    draw: st.DrawFn, states: tuple[RiskState, ...] = ENTRY_STATES, *, adversarial: bool = False
) -> tuple[TradeProposal, AccountSnapshot, MarketContext]:
    """Proposta, snapshot e mercato plausibili, in un giorno feriale fuori dal blocco del venerdì.

    Di default i controlli d'ingresso passano quasi sempre (quote fresche, esecuzione pronta, SL dal lato
    giusto, nessuna posizione sullo stesso strumento), così le proprietà sulle approvazioni vengono
    esercitate davvero. Con `adversarial=True` gli intervalli includono casi non validi: serve per le
    invarianti che devono valere sempre.
    """
    spec = SPECS[draw(st.sampled_from(sorted(SPECS)))]
    min_stop_ticks = draw(st.integers(0, 50))
    spec = replace(spec, min_stop_distance=min_stop_ticks * spec.price_increment)
    ts = WED_NOON_NS + draw(st.integers(-2 * 24, 24)) * HOUR_NS  # da lunedì a giovedì, a mezzogiorno UTC
    spread_ticks = draw(st.integers(0, 30))
    max_age_s = 40 if adversarial else 25
    m = market(
        spec,
        bid=PRICE[spec.instrument] * draw(st.floats(0.9, 1.1)),
        spread_ticks=spread_ticks,
        quote_ts_ns=ts - draw(st.integers(0, max_age_s)) * NS,
        gap_ticks=draw(st.integers(0, 500)),
        value_per_unit=VALUE_PER_UNIT[spec.instrument] * draw(st.floats(0.8, 1.25)),
    )
    equity = draw(st.floats(200.0, 200_000.0))
    state = draw(st.sampled_from(states))
    snap = snapshot(
        equity,
        state=state,
        positions=draw(
            positions_st(max_size=3 if adversarial else 2, exclude=None if adversarial else spec.instrument)
        ),
        ts_ns=ts,
        floor=equity * draw(st.floats(0.0, 1.05)),
        day_start_equity=equity * draw(st.floats(0.95, 1.05)),
        week_start_equity=equity * draw(st.floats(0.9, 1.1)),
        margin_used=equity * draw(st.floats(0.0, 0.25)),
        execution_ready=draw(st.booleans()) if adversarial else True,
        ramp_active=draw(st.booleans()),
        pause_kind=draw(st.sampled_from(PauseKind)) if state is RiskState.PAUSA else None,
    )
    if adversarial:
        stop_ticks = draw(st.integers(-10, 5000))
    else:
        stop_ticks = spread_ticks + max(1, min_stop_ticks) + draw(st.integers(0, 3000))
    tp = draw(st.one_of(st.none(), st.integers(-10 if adversarial else max(1, min_stop_ticks), 10_000)))
    p = proposal(m, side=draw(st.sampled_from(Side)), stop_ticks=stop_ticks, tp_ticks=tp)
    return p, snap, m
