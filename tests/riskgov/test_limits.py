"""Invarianti dei limiti (PIANO §6, n. 8, 9, 10, 11) e regole su notizie, weekend e valute."""

import math
from dataclasses import replace

import pytest
from factories import (
    CFG,
    EURUSD,
    GBPUSD,
    NS,
    USDJPY,
    WED_NOON_NS,
    decision_inputs,
    market,
    position,
    proposal,
    snapshot,
    utc_ns,
)
from hypothesis import given

from riskgov.core.governor import decide
from riskgov.core.limits import (
    committed_loss,
    currency_exposure,
    open_heat,
    position_risk,
    weekend_closures,
    weekend_entry_block,
)
from riskgov.core.types import DecisionKind, NewsEvent, RiskState, Side

# Tolleranza relativa per i confronti fatti con un'espressione diversa da quella del governor.
REL = 1e-12


def _within(value: float, limit: float) -> bool:
    return value <= limit + REL * abs(limit) + 1e-12


def _per_state(ps, state):
    return ps.difensivo if state is RiskState.DIFENSIVO else ps.normale


def _new_gap_risk(d, m):
    return d.quantity * ((d.stop_distance + m.gap) * m.value_per_unit)


@given(decision_inputs())
def test_heat_after_approval_within_state_cap(inputs):
    """8. Dopo ogni approvazione la heat corretta per i gap è <= heat_cap dello stato."""
    p, snap, m = inputs
    d = decide(p, snap, m, CFG)
    if d.kind is DecisionKind.REJECTED:
        return
    heat = open_heat(snap.positions) + _new_gap_risk(d, m)
    assert _within(heat, _per_state(CFG.limits.heat_cap, snap.state) * snap.equity)


@given(decision_inputs())
def test_committed_loss_plus_new_risk_within_daily_and_weekly(inputs):
    """9. Perdita impegnata + nuovo rischio <= limite giornaliero e settimanale."""
    p, snap, m = inputs
    d = decide(p, snap, m, CFG)
    if d.kind is DecisionKind.REJECTED:
        return
    heat, new = open_heat(snap.positions), _new_gap_risk(d, m)
    day = committed_loss(snap.day_start_equity, snap.equity, heat) + new
    week = committed_loss(snap.week_start_equity, snap.equity, heat) + new
    assert _within(day, _per_state(CFG.limits.daily, snap.state) * snap.day_start_equity)
    assert _within(week, _per_state(CFG.limits.weekly, snap.state) * snap.week_start_equity)


@given(decision_inputs(adversarial=True))
def test_position_count_one_per_instrument_no_adds(inputs):
    """10. Numero massimo di posizioni, una per strumento, nessuna aggiunta né mediazione."""
    p, snap, m = inputs
    d = decide(p, snap, m, CFG)
    if d.kind is DecisionKind.REJECTED:
        return
    assert all(pos.instrument != p.instrument for pos in snap.positions)
    assert len(snap.positions) < _per_state(CFG.limits.max_positions, snap.state)


@pytest.mark.parametrize("side", list(Side))
def test_adding_to_an_open_position_is_rejected_in_both_directions(side):
    m = market(EURUSD)
    snap = snapshot(positions=(position(EURUSD, side=Side.LONG),))
    d = decide(proposal(m, side=side), snap, m, CFG)
    assert d.kind is DecisionKind.REJECTED and "one_per_instrument" in d.reason


@given(decision_inputs())
def test_projected_margin_within_cap(inputs):
    """11. Margine usato proiettato <= margin_used_cap × E."""
    p, snap, m = inputs
    d = decide(p, snap, m, CFG)
    if d.kind is DecisionKind.REJECTED:
        return
    margin = snap.margin_used + d.quantity * (m.notional_per_unit * m.spec.margin_rate)
    assert _within(margin, CFG.limits.margin_used_cap * snap.equity)


@given(decision_inputs())
def test_currency_net_risk_within_cap_or_not_worse(inputs):
    """Rischio netto per valuta <= cap·E dopo il trade, oppure non peggiore di prima (posizioni estranee)."""
    p, snap, m = inputs
    d = decide(p, snap, m, CFG)
    if d.kind is DecisionKind.REJECTED:
        return
    before = currency_exposure(snap.positions)
    new = _new_gap_risk(d, m)
    sign = 1.0 if p.side is Side.LONG else -1.0
    cap = CFG.limits.currency_net_risk * snap.equity
    for ccy, direction in ((m.spec.base_currency, sign), (m.spec.quote_currency, -sign)):
        old = before.get(ccy, 0.0)
        assert _within(abs(old + direction * new), max(cap, abs(old)))


def test_correlated_usd_exposure_is_capped():
    """Long EURUSD aperto con rischio ~1%: un long GBPUSD è limitato dal rischio netto in USD (1,5%)."""
    eur = position(EURUSD, side=Side.LONG, quantity=2_000, stop_ticks=1_000, gap_ticks=0)  # €18,2
    m = market(GBPUSD, gap_ticks=0)
    snap = snapshot(2000.0, positions=(eur,), day_start_equity=1900.0, week_start_equity=1900.0)  # in utile
    d = decide(proposal(m, stop_ticks=800), snap, m, CFG)
    # Senza il limite per valuta: 0,02 lot (€14,5).
    # Con il limite: spazio in USD = 30 − 18,2 = €11,8 → 0,01 lot.
    assert d.kind is DecisionKind.REDUCED
    assert d.quantity == 1_000
    assert "currency_net_risk_USD" in d.reason


def test_naked_position_blocks_every_entry():
    """Una posizione senza SL ha rischio infinito: nessun nuovo ingresso finché non è coperta."""
    naked = position(USDJPY, stop_ticks=None)
    assert math.isinf(position_risk(naked))
    m = market(EURUSD)
    d = decide(proposal(m), snapshot(positions=(naked,)), m, CFG)
    assert d.kind is DecisionKind.REJECTED
    assert all(not math.isnan(c.value) and not math.isnan(c.limit) for c in d.checks)


def test_position_risk_past_stop_is_only_the_gap():
    pos = position(EURUSD, side=Side.LONG, stop_ticks=-20, gap_ticks=50, quantity=10_000)
    assert position_risk(pos) == pytest.approx(10_000 * 50 * 1e-5 / 1.1)


def test_position_risk_short():
    pos = position(EURUSD, side=Side.SHORT, stop_ticks=300, gap_ticks=50, quantity=10_000)
    assert position_risk(pos) == pytest.approx(10_000 * 350 * 1e-5 / 1.1)


@pytest.mark.parametrize(
    ("offset_min", "currencies", "blocked"),
    [
        (10, {"USD"}, True),  # evento USD fra 10 minuti
        (-29, {"EUR"}, True),  # evento EUR 29 minuti fa
        (31, {"USD"}, False),  # fuori finestra
        (-31, {"USD"}, False),
        (0, {"JPY"}, False),  # valuta non coinvolta
    ],
)
def test_no_entries_in_news_blackout(offset_min, currencies, blocked):
    ev = NewsEvent(WED_NOON_NS + offset_min * 60 * NS, frozenset(currencies), "NFP")
    m = market(EURUSD, events=(ev,))
    d = decide(proposal(m), snapshot(), m, CFG)
    assert (d.kind is DecisionKind.REJECTED) is blocked
    if blocked:
        assert "news_blackout" in d.reason and "NFP" in d.reason


@pytest.mark.parametrize(
    ("ts", "blocked"),
    [
        (utc_ns(2026, 10, 23, 15, 59), False),  # venerdì 15:59
        (utc_ns(2026, 10, 23, 16, 0), True),  # venerdì 16:00
        (utc_ns(2026, 10, 24, 12, 0), True),  # sabato
        (utc_ns(2026, 10, 25, 22, 0), True),  # domenica sera, riapertura
        (utc_ns(2026, 10, 26, 0, 0), False),  # lunedì 00:00
        (utc_ns(2026, 10, 22, 23, 59), False),  # giovedì
    ],
)
def test_no_entries_after_friday_cutoff(ts, blocked):
    assert weekend_entry_block(ts, CFG.gaps.no_entry_after_fri_utc) is blocked
    m = market(EURUSD, quote_ts_ns=ts)
    d = decide(proposal(m), snapshot(ts_ns=ts), m, CFG)
    assert (d.kind is DecisionKind.REJECTED) is blocked


def test_weekend_closures_newest_first_until_under_cap():
    """Heat del weekend > 1,5%·E: si chiude dalla posizione più recente finché si rientra (PIANO §2.3)."""
    old = position(EURUSD, quantity=10_000, stop_ticks=100, weekend_gap_ticks=100, opened_ts_ns=1)  # €18,2
    mid = position(GBPUSD, quantity=10_000, stop_ticks=100, weekend_gap_ticks=100, opened_ts_ns=2)  # €18,2
    new = position(USDJPY, quantity=1_000, stop_ticks=100, weekend_gap_ticks=100, opened_ts_ns=3)  # €1,2
    # Cap = 1,5% di €2.000 = €30: servono due chiusure, prima USDJPY (più recente) poi GBPUSD.
    assert weekend_closures((mid, new, old), 2000.0, CFG) == ("USDJPY", "GBPUSD")
    assert weekend_closures((old,), 2000.0, CFG) == ()


def test_weekend_closures_fail_closed():
    pos = position(EURUSD)
    assert weekend_closures((pos,), float("nan"), CFG) == ("EURUSD",)
    assert weekend_closures((replace(pos, stop_price=None),), 1e9, CFG) == ("EURUSD",)
