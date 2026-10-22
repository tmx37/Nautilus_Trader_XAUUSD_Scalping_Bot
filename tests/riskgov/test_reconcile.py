"""Politica di riconciliazione (PIANO §2.3). La tabella POLICY è già la specifica; classify() è uno stub."""

import pytest

from riskgov.core.reconcile import POLICY, ReconcileCase
from riskgov.core.types import PauseKind, RiskState


def test_policy_covers_every_case():
    assert set(POLICY) == set(ReconcileCase)


def test_cases_that_touch_safety_force_pausa_ops():
    for case in (
        ReconcileCase.KNOWN_WITHOUT_SL,
        ReconcileCase.UNKNOWN_POSITION,
        ReconcileCase.FOREIGN_PENDING_ORDER,
        ReconcileCase.EQUITY_MISMATCH,
    ):
        assert POLICY[case].state is RiskState.PAUSA
        assert POLICY[case].pause_kind is PauseKind.OPS


def test_local_missing_order_is_never_resubmitted():
    assert "mai reinviarlo" in POLICY[ReconcileCase.LOCAL_ORDER_MISSING_AT_BROKER].action


@pytest.mark.skip(reason="F0: classify() è uno stub, implementazione in F1")
def test_classify_matches_broker_reports():
    """Ogni combinazione di report broker + journal produce i casi attesi (fixture registrate in F1)."""
