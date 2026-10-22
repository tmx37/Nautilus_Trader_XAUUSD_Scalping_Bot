"""Invarianti del floor a cricchetto (PIANO §6, n. 12). Da implementare con hypothesis in F1."""

import pytest

pytestmark = pytest.mark.skip(reason="F0: riskgov.core.floor è uno stub, implementazione in F1")


def test_hwm_and_floor_never_decrease():
    """12a. Su qualsiasi percorso di equity senza prelievi, HWM e floor non scendono mai."""


def test_floor_stays_below_hwm():
    """12b. F < HWM sempre."""


def test_floor_locks_initial_capital_after_enough_profit():
    """Con K=0.20 e λ=0.5, HWM >= 1.4·E0 ⇒ F >= E0."""


def test_withdrawal_rescales_without_triggering_drawdown():
    """Un prelievo riscala HWM ed F in proporzione: il DD resta invariato."""
