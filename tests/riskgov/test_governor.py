"""Invarianti del governor (PIANO §6, n. 4, 5, 6, 7, 17)."""

import math
import pickle
from dataclasses import replace

import pytest
from factories import (
    CFG,
    EURUSD,
    SPECS,
    USDJPY,
    WED_NOON_NS,
    decision_inputs,
    market,
    position,
    proposal,
    snapshot,
)
from hypothesis import given
from hypothesis import strategies as st

from riskgov.core.governor import decide, decide_exit, decide_stop_update
from riskgov.core.types import (
    DecisionKind,
    ExitProposal,
    RiskState,
    Side,
    StopUpdateProposal,
)

ALL_STATES = tuple(RiskState)


@given(decision_inputs(states=(RiskState.PAUSA, RiskState.ARRESTO), adversarial=True))
def test_pausa_and_arresto_never_approve_entries(inputs):
    """4. In PAUSA e in ARRESTO nessun ingresso viene approvato."""
    d = decide(*inputs, CFG)
    assert d.kind is DecisionKind.REJECTED and d.quantity == 0 and d.risk_amount == 0


@given(decision_inputs(states=ALL_STATES, adversarial=True), st.sampled_from([1.0, math.nan, math.inf, -5.0]))
def test_exits_are_always_approved(inputs, equity):
    """5. Le uscite sono sempre approvate, in qualsiasi stato e anche con dati non validi."""
    _, snap, _ = inputs
    ex = ExitProposal("x-1", "test", "EURUSD", "trailing", WED_NOON_NS)
    d = decide_exit(ex, replace(snap, equity=equity))
    assert d.kind is DecisionKind.APPROVED


@given(decision_inputs(states=ALL_STATES, adversarial=True))
def test_every_entry_has_stop_on_correct_side(inputs):
    """6. Ogni ingresso approvato ha lo SL dal lato giusto e a distanza >= minimo del broker.

    Lo SL effettivo è prezzo d'ingresso ∓ distanza relativa; il broker lo confronta con il prezzo di
    chiusura (bid per un long, ask per uno short).
    """
    p, snap, m = inputs
    d = decide(p, snap, m, CFG)
    if d.kind is DecisionKind.REJECTED:
        assert d.quantity == 0 and d.stop_distance is None
        return
    tick = m.spec.price_increment
    assert d.quantity > 0 and d.stop_distance > 0
    if p.side is Side.LONG:
        stop = m.ask - d.stop_distance
        dist_close = round((m.bid - stop) / tick)
    else:
        stop = m.bid + d.stop_distance
        dist_close = round((stop - m.ask) / tick)
    assert dist_close >= max(1, math.ceil(m.spec.min_stop_distance / tick - 1e-9))
    # La distanza inviata è un multiplo esatto del tick (l'adapter la converte in unità da 1e-5).
    assert abs(d.stop_distance / tick - round(d.stop_distance / tick)) < 1e-6
    if d.take_profit_distance is not None:
        assert d.take_profit_distance > 0


@given(decision_inputs(states=ALL_STATES, adversarial=True))
def test_checks_are_journal_safe(inputs):
    """Nessun NaN nei controlli: il journal è JSON e ogni decisione dice quale controllo l'ha determinata."""
    d = decide(*inputs, CFG)
    assert d.checks
    assert all(not math.isnan(c.value) and not math.isnan(c.limit) for c in d.checks)
    if d.kind is DecisionKind.REJECTED:
        assert any(not c.passed for c in d.checks)
    else:
        assert all(c.passed for c in d.checks)


stop_moves = st.tuples(
    st.sampled_from(sorted(SPECS)),
    st.sampled_from(Side),
    st.one_of(st.none(), st.integers(1, 2000)),  # SL attuale in tick dal prezzo (None = scoperta)
    st.integers(-3000, 3000),  # nuovo SL in tick dal prezzo, verso il guadagno se positivo
    st.integers(0, 50),  # distanza minima in tick
    st.integers(0, 20),  # spread in tick
)


@given(stop_moves)
def test_stop_updates_are_monotone(move):
    """7. Lo SL di un long non scende mai, quello di uno short non sale mai; resta a distanza >= minimo."""
    name, side, cur_ticks, new_ticks, min_ticks, spread = move
    spec = replace(SPECS[name], min_stop_distance=min_ticks * SPECS[name].price_increment)
    m = market(spec, spread_ticks=spread)
    tick = spec.price_increment
    close = m.bid if side is Side.LONG else m.ask
    sign = 1 if side is Side.LONG else -1
    pos = replace(
        position(spec, side=side, mark=close),
        stop_price=None if cur_ticks is None else round(close - sign * cur_ticks * tick, 10),
    )
    # new_ticks > 0: lo SL nuovo è (cur − new_ticks) tick dal prezzo, cioè più vicino al prezzo.
    base = cur_ticks if cur_ticks is not None else 2000
    new_stop = round(close - sign * (base - new_ticks) * tick, 10)
    d = decide_stop_update(StopUpdateProposal("s-1", "test", name, new_stop, WED_NOON_NS), pos, m)
    if d.kind is DecisionKind.REJECTED:
        assert d.stop_price is None
        return
    if pos.stop_price is not None:
        assert (d.stop_price > pos.stop_price) if side is Side.LONG else (d.stop_price < pos.stop_price)
    dist = round(sign * (close - d.stop_price) / tick)
    assert dist >= max(1, min_ticks)


def test_stop_update_without_position_is_rejected():
    m = market(EURUSD)
    d = decide_stop_update(StopUpdateProposal("s-1", "test", "EURUSD", 1.09, WED_NOON_NS), None, m)
    assert d.kind is DecisionKind.REJECTED


def test_stop_update_through_price_is_rejected():
    """Uno SL oltre il prezzo corrente scatterebbe subito: si rifiuta (il segnale può proporre un'uscita)."""
    m = market(EURUSD)
    pos = position(EURUSD, side=Side.LONG, mark=m.bid)
    d = decide_stop_update(StopUpdateProposal("s-1", "test", "EURUSD", m.bid + 0.0001, WED_NOON_NS), pos, m)
    assert d.kind is DecisionKind.REJECTED


@given(decision_inputs(states=ALL_STATES, adversarial=True))
def test_decide_is_pure_and_survives_persist_restore(inputs):
    """17. decide() è deterministica e non dipende dall'identità degli oggetti: stessi valori dopo un ciclo
    di serializzazione → stessa decisione. (Il ripristino della macchina a stati è in test_regime.)"""
    p, snap, m = inputs
    first = decide(p, snap, m, CFG)
    assert decide(p, snap, m, CFG) == first
    restored = pickle.loads(pickle.dumps((p, snap, m)))
    assert decide(*restored, CFG) == first


def test_proposal_for_another_instrument_is_rejected():
    m = market(EURUSD)
    d = decide(proposal(m, instrument="GBPUSD"), snapshot(), m, CFG)
    assert d.kind is DecisionKind.REJECTED and "strumento" in d.reason


@pytest.mark.parametrize("age_s", [31, -31])
def test_stale_or_future_quote_is_rejected(age_s):
    m = market(EURUSD, quote_ts_ns=WED_NOON_NS - age_s * 1_000_000_000)
    d = decide(proposal(m), snapshot(), m, CFG)
    assert d.kind is DecisionKind.REJECTED and "quote_age_s" in d.reason


def test_not_ready_after_disconnection_is_rejected():
    m = market(EURUSD)
    d = decide(proposal(m), snapshot(execution_ready=False), m, CFG)
    assert d.kind is DecisionKind.REJECTED and "execution_ready" in d.reason


def test_stop_inside_spread_is_rejected():
    """Con lo spread di 20 tick uno SL a 15 tick dall'ask sarebbe sopra il bid: scatterebbe subito."""
    m = market(EURUSD, spread_ticks=20)
    d = decide(proposal(m, stop_ticks=15), snapshot(), m, CFG)
    assert d.kind is DecisionKind.REJECTED and "stop_side_ticks" in d.reason


def test_jpy_pair_stop_distance_is_in_its_own_ticks():
    m = market(USDJPY)
    d = decide(proposal(m, side=Side.SHORT, stop_ticks=600, tp_ticks=1200), snapshot(5000.0), m, CFG)
    assert d.kind is DecisionKind.APPROVED
    assert d.stop_distance == pytest.approx(0.6) and d.take_profit_distance == pytest.approx(1.2)
