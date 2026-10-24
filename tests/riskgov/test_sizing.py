"""Invarianti del sizing (PIANO §6, n. 1, 2, 3, 15, 16, 18)."""

from dataclasses import replace

import pytest
from factories import CFG, EURUSD, USDJPY, decision_inputs, market, position, proposal, snapshot
from hypothesis import given
from hypothesis import strategies as st

from riskgov.core.config import R_NORMALE_TETTO, AccountConfig
from riskgov.core.governor import decide
from riskgov.core.sizing import position_size, risk_budget, risk_fraction, round_down_volume
from riskgov.core.types import DecisionKind, RiskState

volumes = st.tuples(st.integers(1, 100), st.integers(1, 10), st.integers(1, 10_000)).map(
    lambda t: (t[0] * t[1], t[0], t[0] * t[1] * t[2])  # (minimo, passo, massimo) coerenti
)


@given(
    budget=st.floats(0.0, 1e6),
    stop=st.floats(1e-6, 100.0),
    vpu=st.floats(1e-4, 10.0),
    vol=volumes,
)
def test_size_times_unit_risk_never_exceeds_budget(budget, stop, vpu, vol):
    """1. quantità × rischio unitario <= budget, e quantità >= 0, multipla del passo, <= massimo."""
    min_v, step, max_v = vol
    q = position_size(budget, stop, vpu, min_v, step, max_v)
    assert q >= 0
    assert q * (stop * vpu) <= budget
    if q:
        assert q % step == 0 and min_v <= q <= max_v


@given(budget=st.floats(0.0, 1e4), stop=st.floats(1e-6, 1.0), vpu=st.floats(1e-4, 10.0), vol=volumes)
def test_below_min_volume_is_rejected_never_rounded_up(budget, stop, vpu, vol):
    """2. Se la quantità calcolata è sotto il volume minimo la decisione è RIFIUTO (mai max(min, q))."""
    min_v, step, max_v = vol
    q = position_size(budget, stop, vpu, min_v, step, max_v)
    if budget / (stop * vpu) < min_v:
        assert q == 0


def test_below_min_volume_example_from_piano():
    """PIANO §3: con €1.000 in DIFENSIVO e stop di 80 pip il budget è €5 → rifiutato (0,01 lot ≈ €7,3)."""
    m = market(EURUSD)
    d = decide(proposal(m, stop_ticks=800), snapshot(1000.0, state=RiskState.DIFENSIVO), m, CFG)
    assert d.kind is DecisionKind.REJECTED and d.quantity == 0
    assert "minimo" in d.reason


@pytest.mark.parametrize(
    ("equity", "state", "lots"),
    [
        (1000.0, RiskState.NORMALE, 0.01),
        (2000.0, RiskState.NORMALE, 0.02),
        (2000.0, RiskState.DIFENSIVO, 0.01),
        (5000.0, RiskState.NORMALE, 0.06),
        (5000.0, RiskState.DIFENSIVO, 0.03),
    ],
)
def test_granularity_table_of_piano(equity, state, lots):
    """PIANO §3, tabella della granularità per EURUSD con stop S1 di 80 pip."""
    m = market(EURUSD, spread_ticks=0)
    d = decide(proposal(m, stop_ticks=800), snapshot(equity, state=state), m, CFG)
    assert d.kind is DecisionKind.APPROVED
    assert d.quantity == round(lots * 100_000)


@given(decision_inputs())
def test_risk_bounded_by_state_cppi_and_cap(inputs):
    """3. Rischio <= min(r_stato·E, m·(E − F), R_NORMALE_TETTO·E)."""
    p, snap, m = inputs
    d = decide(p, snap, m, CFG)
    if d.kind is DecisionKind.REJECTED:
        return
    e = snap.equity
    assert d.risk_amount <= risk_fraction(snap.state, CFG, snap.ramp_active) * e
    assert d.risk_amount <= CFG.cppi.m * (e - snap.floor)
    assert d.risk_amount <= R_NORMALE_TETTO * e
    assert d.risk_amount <= risk_budget(snap, CFG)
    if snap.ramp_active:
        assert d.risk_amount <= CFG.f4_ramp.r_normale * e


@given(decision_inputs(), st.floats(0.05, 1.0))
def test_loss_never_increases_size(inputs, factor):
    """15a. A parità di tutto il resto, meno equity non aumenta mai la quantità (niente martingala)."""
    p, snap, m = inputs
    high = decide(p, snap, m, CFG)
    low = decide(p, replace(snap, equity=snap.equity * factor), m, CFG)
    assert low.quantity <= high.quantity


@given(decision_inputs(states=(RiskState.NORMALE,)), st.sampled_from(list(RiskState)[1:]))
def test_worse_state_never_increases_size(inputs, worse):
    """15b. Uno stato peggiore non aumenta mai la quantità."""
    p, snap, m = inputs
    base = decide(p, snap, m, CFG)
    assert decide(p, replace(snap, state=worse), m, CFG).quantity <= base.quantity


@given(decision_inputs(states=(RiskState.NORMALE,)))
def test_ramp_never_increases_size(inputs):
    p, snap, m = inputs
    off = decide(p, replace(snap, ramp_active=False), m, CFG)
    on = decide(p, replace(snap, ramp_active=True), m, CFG)
    assert on.quantity <= off.quantity


BAD = [float("nan"), float("inf"), float("-inf"), -1.0]


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("snapshot", "equity"),
        ("snapshot", "floor"),
        ("snapshot", "day_start_equity"),
        ("snapshot", "week_start_equity"),
        ("snapshot", "margin_used"),
        ("market", "bid"),
        ("market", "ask"),
        ("market", "value_per_unit"),  # tasso FX mancante o sbagliato
        ("market", "notional_per_unit"),
        ("market", "gap"),
        ("proposal", "stop_price"),
        ("proposal", "reference_price"),
        ("proposal", "take_profit_price"),
    ],
)
def test_fail_closed_on_invalid_inputs(target, field, bad):
    """16. NaN, infinito, valori negativi o tasso FX mancante → RIFIUTO."""
    m = market(EURUSD)
    p = proposal(m, tp_ticks=1600)
    s = snapshot()
    assert decide(p, s, m, CFG).kind is DecisionKind.APPROVED  # il caso base passa
    objs = {"snapshot": s, "market": m, "proposal": p}
    objs[target] = replace(objs[target], **{field: bad})
    d = decide(objs["proposal"], objs["snapshot"], objs["market"], CFG)
    assert d.kind is DecisionKind.REJECTED and d.quantity == 0


@pytest.mark.parametrize("field", ["value_per_unit", "notional_per_unit", "bid", "ask"])
def test_zero_conversion_or_price_is_rejected(field):
    m = market(EURUSD)
    d = decide(proposal(m), snapshot(), replace(m, **{field: 0.0}), CFG)
    assert d.kind is DecisionKind.REJECTED


@pytest.mark.parametrize(
    "spec_change",
    [{"min_volume": 0}, {"step_volume": 0}, {"min_volume": 1500, "step_volume": 1000}, {"max_volume": 10}],
)
def test_invalid_volume_spec_is_rejected(spec_change):
    m = market(replace(EURUSD, **spec_change))
    assert decide(proposal(m), snapshot(), m, CFG).kind is DecisionKind.REJECTED


@given(decision_inputs(), st.floats(1.0, 1e6))
def test_cap_iniziale_never_enters_sizing(inputs, e0):
    """18. Cambiare E0 (CAP_INIZIALE) a parità di equity e floor non cambia la decisione (R1.2)."""
    p, snap, m = inputs
    other = replace(CFG, account=AccountConfig(currency="EUR", cap_iniziale=e0))
    assert decide(p, snap, m, other) == decide(p, snap, m, CFG)


def test_reduced_when_a_limit_binds_below_state_budget():
    """Con la heat quasi piena la quantità scende sotto quella del solo rischio per stato: REDUCED."""
    m = market(EURUSD)
    big = position(USDJPY, quantity=20_000, stop_ticks=1_000)  # circa €127 di heat su €200 di cap
    snap = snapshot(10_000.0, positions=(big,), day_start_equity=9_500.0)
    d = decide(proposal(m, stop_ticks=300), snap, m, CFG)
    assert d.kind is DecisionKind.REDUCED
    assert "heat" in d.reason


def test_round_down_volume_basic_cases():
    assert round_down_volume(2999.9, 1000, 1000, 10_000) == 2000
    assert round_down_volume(999.9, 1000, 1000, 10_000) == 0
    assert round_down_volume(50_000, 1000, 1000, 10_500) == 10_000
    assert round_down_volume(float("nan"), 1000, 1000, 10_000) == 0
    assert round_down_volume(float("inf"), 1000, 1000, 10_000) == 10_000
