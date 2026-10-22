"""Invarianti del governor (PIANO §6, n. 4, 5, 6, 7, 17). Da implementare con hypothesis in F1."""

import pytest

pytestmark = pytest.mark.skip(reason="F0: riskgov.core.governor è uno stub, implementazione in F1")


def test_pausa_and_arresto_never_approve_entries():
    """4. In PAUSA e in ARRESTO nessun ingresso viene approvato."""


def test_exits_are_always_approved():
    """5. Le uscite sono sempre approvate, in qualsiasi stato."""


def test_every_entry_has_stop_on_correct_side():
    """6. Ogni ingresso approvato ha lo SL dal lato giusto e a distanza >= minimo del broker."""


def test_stop_updates_are_monotone():
    """7. Lo SL di un long non scende mai, quello di uno short non sale mai."""


def test_decide_is_pure_and_survives_persist_restore():
    """17. decide() è deterministica; persistenza → ripristino dello snapshot dà decisioni identiche."""
