"""Invarianti del sizing (PIANO §6, n. 1, 2, 3, 15, 16, 18). Da implementare con hypothesis in F1."""

import pytest

pytestmark = pytest.mark.skip(reason="F0: riskgov.core.sizing è uno stub, implementazione in F1")


def test_size_times_unit_risk_never_exceeds_budget():
    """1. quantità × rischio unitario <= budget, e quantità >= 0."""


def test_below_min_volume_is_rejected_never_rounded_up():
    """2. Se la quantità calcolata è sotto il volume minimo la decisione è RIFIUTO (mai max(min, q))."""


def test_risk_bounded_by_state_cppi_and_cap():
    """3. Rischio <= min(r_stato·E, m·(E − F), R_NORMALE_TETTO·E)."""


def test_loss_or_worse_state_never_increases_size():
    """15. Equity più bassa o stato peggiore non aumentano mai la quantità approvata (niente martingala)."""


def test_fail_closed_on_invalid_inputs():
    """16. NaN, infinito, valori negativi o tasso FX mancante → RIFIUTO."""


def test_cap_iniziale_never_enters_sizing():
    """18. Cambiare E0 a parità di equity e floor non cambia la quantità (R1.2)."""
