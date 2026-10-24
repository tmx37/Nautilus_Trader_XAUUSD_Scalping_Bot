"""Invarianti del floor a cricchetto e dei riferimenti di equity (PIANO §6, n. 12; ADR 0004)."""

import pytest
from factories import CFG
from hypothesis import given
from hypothesis import strategies as st

from riskgov.core.floor import (
    EquityMarks,
    drawdown,
    initial_marks,
    on_daily_close,
    rebase_after_unlock,
    rescale_on_withdrawal,
    update_floor,
)

E0 = CFG.account.cap_iniziale
closes = st.lists(st.floats(0.3, 5.0).map(lambda f: f * E0), max_size=300)


@given(closes)
def test_hwm_and_floor_never_decrease(path):
    """12a. Su qualsiasi percorso di equity senza prelievi, HWM e floor non scendono mai."""
    marks = initial_marks(E0, CFG.cppi)
    for close in path:
        new = on_daily_close(marks, close, CFG.cppi)
        assert new.hwm >= marks.hwm
        assert new.floor >= marks.floor
        assert new.e0 == marks.e0
        marks = new


@given(closes)
def test_floor_stays_below_hwm(path):
    """12b. F < HWM sempre; di più, il kill switch (DD >= D_kill) scatta prima del floor."""
    marks = initial_marks(E0, CFG.cppi)
    d_kill = CFG.regime.arresto_enter_dd
    for close in path:
        marks = on_daily_close(marks, close, CFG.cppi)
        assert marks.floor < marks.hwm
        assert marks.floor <= marks.hwm * (1 - d_kill) * (1 + 1e-12)


def test_floor_locks_initial_capital_after_enough_profit():
    """Con K=0.20 e λ=0.5, HWM >= 1.4·E0 ⇒ F >= E0: il capitale iniziale non è più rischiabile."""
    assert CFG.cppi.k == 0.20 and CFG.cppi.lam == 0.5
    marks = on_daily_close(initial_marks(E0, CFG.cppi), 1.4 * E0, CFG.cppi)
    assert marks.floor == pytest.approx(E0)
    marks = on_daily_close(marks, 1.3 * E0, CFG.cppi)  # ritracciamento: il floor resta
    assert marks.floor == pytest.approx(E0)


def test_initial_cppi_budget_equals_normal_risk():
    """All'inizio m·(E0 − F) = m·K·E0 = r_NORMALE·E0: nessuno scalino fra i due vincoli (PIANO §2.3)."""
    marks = initial_marks(E0, CFG.cppi)
    assert CFG.cppi.m * (E0 - marks.floor) == pytest.approx(CFG.r_state["NORMALE"] * E0)


@given(
    closes,
    st.floats(0.01, 0.99),  # frazione dell'equity che resta dopo il prelievo
    st.floats(0.85, 1.0),  # equity al momento del prelievo, come frazione di HWM
)
def test_withdrawal_rescales_without_triggering_drawdown(path, kept, eq_frac):
    """Un prelievo riscala E0, HWM ed F in proporzione: DD ed E/F restano invariati."""
    marks = initial_marks(E0, CFG.cppi)
    for close in path:
        marks = on_daily_close(marks, close, CFG.cppi)
    before = marks.hwm * eq_frac
    after = before * kept
    new = rescale_on_withdrawal(marks, before, after)
    assert drawdown(after, new.hwm) == pytest.approx(drawdown(before, marks.hwm), abs=1e-12)
    assert after / new.floor == pytest.approx(before / marks.floor)
    assert new.e0 == pytest.approx(marks.e0 * kept)
    # La formula del floor con E0 e HWM riscalati non alza il floor alla chiusura successiva.
    assert on_daily_close(new, after, CFG.cppi).floor == pytest.approx(new.floor)


def test_large_withdrawal_without_rescaling_e0_would_kill():
    """Perché E0 va riscalato: con E0 fisso, metà conto prelevata porterebbe F sopra l'equity."""
    marks = initial_marks(E0, CFG.cppi)
    unscaled = EquityMarks(e0=E0, hwm=E0 / 2, floor=marks.floor / 2)
    assert update_floor(unscaled.floor, unscaled.e0, unscaled.hwm, CFG.cppi) > E0 / 2
    scaled = rescale_on_withdrawal(marks, E0, E0 / 2)
    assert on_daily_close(scaled, E0 / 2, CFG.cppi).floor < E0 / 2


def test_deposit_is_not_a_withdrawal():
    marks = initial_marks(E0, CFG.cppi)
    with pytest.raises(ValueError, match="deposito"):
        rescale_on_withdrawal(marks, E0, E0 * 1.1)


def test_unlock_rebases_hwm_and_keeps_floor():
    marks = on_daily_close(initial_marks(E0, CFG.cppi), 1.2 * E0, CFG.cppi)
    equity = 1.2 * E0 * 0.84  # ARRESTO al 16% di DD
    new = rebase_after_unlock(marks, equity)
    assert new.hwm == equity and new.floor == marks.floor and new.e0 == marks.e0
    assert drawdown(equity, new.hwm) == 0


def test_unlock_below_floor_is_impossible():
    marks = initial_marks(E0, CFG.cppi)
    with pytest.raises(ValueError, match="floor"):
        rebase_after_unlock(marks, marks.floor)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0])
def test_non_positive_or_non_finite_capital_raises(bad):
    marks = initial_marks(E0, CFG.cppi)
    with pytest.raises(ValueError):
        initial_marks(bad, CFG.cppi)
    with pytest.raises(ValueError):
        rescale_on_withdrawal(marks, bad, 1.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_close_raises(bad):
    with pytest.raises(ValueError):
        on_daily_close(initial_marks(E0, CFG.cppi), bad, CFG.cppi)
