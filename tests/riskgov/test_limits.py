"""Invarianti dei limiti (PIANO §6, n. 8, 9, 10, 11). Da implementare con hypothesis in F1."""

import pytest

pytestmark = pytest.mark.skip(reason="F0: riskgov.core.limits è uno stub, implementazione in F1")


def test_heat_after_approval_within_state_cap():
    """8. Dopo ogni approvazione la heat corretta per i gap è <= heat_cap dello stato."""


def test_committed_loss_plus_new_risk_within_daily_and_weekly():
    """9. Perdita impegnata + nuovo rischio <= limite giornaliero e settimanale."""


def test_position_count_one_per_instrument_no_adds():
    """10. Numero massimo di posizioni, una per strumento, nessuna aggiunta né mediazione."""


def test_projected_margin_within_cap():
    """11. Margine usato proiettato <= margin_used_cap × E."""


def test_no_entries_in_news_blackout_or_after_friday_cutoff():
    """Nessun ingresso nella finestra di blackout di un evento o dopo il venerdì alle 16:00 UTC."""
