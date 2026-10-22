"""Invarianti della macchina a stati (PIANO §6, n. 13, 14). Da implementare con hypothesis in F1."""

import pytest

pytestmark = pytest.mark.skip(reason="F0: riskgov.core.regime è uno stub, implementazione in F1")


def test_kill_conditions_always_lead_to_arresto():
    """13a. DD >= arresto.enter_dd oppure equity <= floor ⇒ ARRESTO dopo l'aggiornamento."""


def test_arresto_is_left_only_manually():
    """13b. Nessuna sequenza di equity o trade fa uscire da ARRESTO; solo manual_unlock, verso PAUSA (OPS)."""


def test_pausa_never_returns_directly_to_normale():
    """13c. Da PAUSA si passa solo a DIFENSIVO (PERF) o si resta in attesa di conferma (OPS)."""


def test_no_chatter_inside_hysteresis_band():
    """14. Un'equity che oscilla dentro la banda exit_dd–enter_dd non provoca transizioni."""


def test_second_pausa_within_window_leads_to_arresto():
    """Seconda PAUSA (PERF) entro repeat_pausa_days ⇒ ARRESTO."""


def test_cusum_alarm_triggers_pausa():
    """S = max(0, S + k − R) > h ⇒ PAUSA (PERF)."""
