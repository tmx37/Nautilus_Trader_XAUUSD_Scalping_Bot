"""Invarianti e scenari della macchina a stati (PIANO §6, n. 13, 14, 17; ADR 0006)."""

import json
import random

import pytest
from factories import CFG, DAY_NS, HOUR_NS, WED_NOON_NS
from hypothesis import given
from hypothesis import strategies as st

from riskgov.core.floor import initial_marks, on_daily_close
from riskgov.core.regime import RegimeState, RiskStateMachine
from riskgov.core.types import PauseKind, RiskState

E0 = CFG.account.cap_iniziale
REG = CFG.regime
N, D, P, A = RiskState.NORMALE, RiskState.DIFENSIVO, RiskState.PAUSA, RiskState.ARRESTO
EPS = 1e-9  # E = HWM·(1 − dd) in virgola mobile può dare un DD appena sotto la soglia


class Sim:
    """Guida la macchina a stati con eventi astratti, tenendo HWM e floor come farebbe il governor."""

    def __init__(self, state: RegimeState | None = None) -> None:
        self.sm = RiskStateMachine(CFG, state)
        self.marks = initial_marks(E0, CFG.cppi)
        self.equity = E0
        self.week_start = E0
        self.days = 0
        self.ts = WED_NOON_NS
        self.obs = [(self.sm.state, self.sm.pause_kind)]
        self.transitions = []

    def equity_to(self, equity: float) -> RiskState:
        self.equity = equity
        self.ts += HOUR_NS
        return self._observe(
            self.sm.on_equity(self.ts, equity, self.marks.hwm, self.marks.floor, self.week_start)
        )

    def dd_to(self, dd: float) -> RiskState:
        return self.equity_to(self.marks.hwm * (1 - dd))

    def trade(self, r: float, shadow: bool = False) -> RiskState:
        self.ts += HOUR_NS
        return self._observe(self.sm.on_trade_closed(self.ts, r, shadow=shadow))

    def day(self, n: int = 1) -> RiskState:
        for _ in range(n):
            self.ts += DAY_NS
            self.marks = on_daily_close(self.marks, self.equity, CFG.cppi)
            self.days += 1
            if self.days % 5 == 0:
                self.week_start = self.equity
            self._observe(self.sm.on_day_close(self.ts))
        return self.sm.state

    def apply(self, event: tuple[str, float]) -> None:
        kind, x = event
        if kind == "equity":
            self.equity_to(self.equity * (1 + x))
        elif kind == "trade":
            self.trade(x)
        elif kind == "shadow":
            self.trade(x, shadow=True)
        elif kind == "day":
            self.day()
        elif kind == "ops":
            self.ts += HOUR_NS
            self._observe(self.sm.on_ops_anomaly(self.ts, "test"))
        elif kind == "confirm" and self.sm.pause_kind is PauseKind.OPS:
            self.ts += HOUR_NS
            self._observe(self.sm.manual_confirm_ops(self.ts, "operatore", "risolto"))

    def _observe(self, state: RiskState) -> RiskState:
        assert state is self.sm.state
        self.obs.append((self.sm.state, self.sm.pause_kind))
        self.transitions.extend(self.sm.pop_transitions())
        return state


def _path(seed: int, drift: float, n: int) -> list[tuple[str, float]]:
    """Percorso casuale lungo con una tendenza: con drift negativo equity e R scendono fino a PAUSA e ARRESTO.

    Hypothesis genera seme, tendenza e lunghezza; il percorso nasce da un generatore con seme, perché le
    liste lunghe generate elemento per elemento restano quasi sempre corte e vicine a zero.
    """
    rng = random.Random(seed)
    kinds = ("equity", "trade", "shadow", "day", "ops", "confirm")
    weights = (40, 25, 10, 22, 1, 2)
    out = []
    for kind in rng.choices(kinds, weights, k=n):
        if kind == "equity":
            out.append((kind, rng.gauss(drift, 0.015)))
        elif kind in ("trade", "shadow"):
            out.append((kind, min(5.0, max(-1.5, rng.gauss(100 * drift, 1.5)))))
        else:
            out.append((kind, 0.0))
    return out


events = st.builds(
    _path,
    st.integers(0, 2**32),
    st.sampled_from([-0.01, -0.005, -0.002, 0.0, 0.002, 0.005]),
    st.integers(0, 600),
)


@given(events)
def test_kill_conditions_always_lead_to_arresto(evs):
    """13a. DD >= arresto.enter_dd oppure equity <= floor ⇒ ARRESTO dopo l'aggiornamento."""
    sim = Sim()
    for ev in evs:
        sim.apply(ev)
        if ev[0] == "equity":
            dd = 1 - sim.equity / sim.marks.hwm
            if dd >= REG.arresto_enter_dd or sim.equity <= sim.marks.floor:
                assert sim.sm.state is A


@given(events)
def test_arresto_is_left_only_manually(evs):
    """13b. Nessuna sequenza di equity, trade, giorni o anomalie fa uscire da ARRESTO."""
    sim = Sim()
    for ev in evs:
        sim.apply(ev)
    states = [s for s, _ in sim.obs]
    if A in states:
        assert all(s is A for s in states[states.index(A) :])


@given(events)
def test_pausa_never_returns_directly_to_normale(evs):
    """13c. Da PAUSA si passa solo a DIFENSIVO, ARRESTO o a un altro motivo di PAUSA."""
    sim = Sim()
    for ev in evs:
        sim.apply(ev)
    for (before, _), (after, _) in zip(sim.obs, sim.obs[1:], strict=False):
        assert not (before is P and after is N)
    assert not any(t.from_state is P and t.to_state is N for t in sim.transitions)


@given(events)
def test_transitions_match_observations(evs):
    """Ogni cambio di stato osservato ha una transizione nel journal, con il motivo."""
    sim = Sim()
    for ev in evs:
        sim.apply(ev)
    changes = [(a, b) for a, b in zip(sim.obs, sim.obs[1:], strict=False) if a != b]
    logged = [((t.from_state, t.from_pause_kind), (t.to_state, t.to_pause_kind)) for t in sim.transitions]
    assert logged == changes
    assert all(t.reason for t in sim.transitions)


@given(events, st.integers(0, 400))
def test_persist_restore_gives_identical_future(evs, cut):
    """17. Persistenza (JSON) → ripristino a metà sequenza: stessi stati e transizioni del percorso intero."""
    full = Sim()
    for ev in evs:
        full.apply(ev)

    first = Sim()
    for ev in evs[:cut]:
        first.apply(ev)
    saved = json.loads(json.dumps(first.sm.regime.to_dict()))
    second = Sim(RegimeState.from_dict(saved))
    for attr in ("marks", "equity", "week_start", "days", "ts"):
        setattr(second, attr, getattr(first, attr))
    for ev in evs[cut:]:
        second.apply(ev)

    assert first.obs + second.obs[1:] == full.obs
    assert first.transitions + second.transitions == full.transitions


def test_no_chatter_inside_hysteresis_band():
    """14. Un'equity che oscilla dentro la banda exit_dd–enter_dd non provoca transizioni."""
    sim = Sim()
    sim.week_start = E0 * 0.9  # isola la banda del DD dal limite settimanale
    for i in range(200):  # NORMALE: DD fra 0 e appena sotto enter_dd
        sim.dd_to(REG.difensivo_enter_dd * (0.999 if i % 2 else 0.01))
    assert sim.transitions == []

    sim.dd_to(REG.difensivo_enter_dd + EPS)
    assert sim.sm.state is D
    sim.sm.pop_transitions()
    sim.transitions.clear()
    for i in range(200):  # DIFENSIVO: DD fra appena sopra exit_dd e appena sotto pausa
        sim.dd_to(REG.difensivo_exit_dd * 1.001 if i % 2 else REG.pausa_enter_dd * 0.999)
        sim.trade(0.5)
    assert sim.sm.state is D
    assert sim.transitions == []


def test_difensivo_exit_needs_dd_and_trades():
    sim = Sim()
    sim.dd_to(0.07)
    assert sim.sm.state is D
    sim.dd_to(0.02)  # DD rientrato ma 0 trade in DIFENSIVO
    assert sim.sm.state is D
    for _ in range(REG.difensivo_min_trades - 1):
        sim.trade(0.2)
    assert sim.sm.state is D
    sim.trade(0.2)
    assert sim.sm.state is N


def test_weekly_loss_triggers_difensivo():
    sim = Sim()
    sim.day()
    sim.equity_to(E0 * 1.10)
    sim.day(5)  # nuova settimana con HWM = 1,10·E0
    sim.week_start = sim.equity
    sim.equity_to(sim.week_start * (1 - CFG.limits.weekly.normale))
    assert sim.sm.state is D
    assert "settimanale" in sim.transitions[-1].reason


def test_cusum_warning_then_alarm():
    """S = max(0, S + k − R): avviso (S > w) → DIFENSIVO, allarme (S > h) → PAUSA (PERF)."""
    sim = Sim()
    s = 0.0
    while True:
        s = max(0.0, s + REG.cusum_k_r + 1.0)
        state = sim.trade(-1.0)
        if s > REG.cusum_h_r:
            assert state is P and sim.sm.pause_kind is PauseKind.PERF
            break
        assert state is (D if s > REG.cusum_w_r else N)
    assert sim.sm.regime.cusum == 0.0  # azzerato all'ingresso in PAUSA


def test_cusum_ignores_trades_closed_during_pausa():
    sim = Sim()
    sim.sm.on_ops_anomaly(sim.ts, "test")
    for _ in range(50):
        sim.trade(-1.0)
    assert sim.sm.regime.cusum == 0.0 and sim.sm.state is P


def test_pausa_exit_with_shadow_verification():
    sim = Sim()
    sim.dd_to(REG.pausa_enter_dd + EPS)
    assert sim.sm.state is P and sim.sm.pause_kind is PauseKind.PERF
    for _ in range(REG.pausa_shadow_min_trades):
        sim.trade(0.1, shadow=True)
    sim.day(REG.pausa_min_days - 1)
    assert sim.sm.state is P
    sim.day()
    assert sim.sm.state is D


def test_pausa_exit_by_max_days_with_negative_shadow():
    sim = Sim()
    sim.dd_to(REG.pausa_enter_dd + EPS)
    for _ in range(REG.pausa_shadow_min_trades):
        sim.trade(-1.0, shadow=True)
    sim.day(REG.pausa_max_days - 1)
    assert sim.sm.state is P
    sim.day()
    assert sim.sm.state is D


def test_dd_trigger_rearms_only_below_difensivo():
    """Uscita dalla PAUSA con DD ancora sopra pausa.enter_dd: niente seconda PAUSA immediata (ADR 0006).

    Senza il riarmo a fronte, la PAUSA ripartirebbe subito e diventerebbe ARRESTO per ripetizione.
    """
    sim = Sim()
    sim.dd_to(0.11)
    assert sim.sm.state is P
    sim.day(REG.pausa_max_days)
    sim.dd_to(0.11)  # DD invariato: in PAUSA non si opera
    assert sim.sm.state is D
    sim.dd_to(0.12)
    assert sim.sm.state is D
    sim.dd_to(REG.arresto_enter_dd + EPS)  # l'ARRESTO resta sempre attivo
    assert sim.sm.state is A


def test_second_pausa_within_window_leads_to_arresto():
    """Seconda PAUSA (PERF) entro repeat_pausa_days ⇒ ARRESTO."""
    sim = Sim()
    sim.dd_to(0.11)
    sim.day(REG.pausa_max_days)
    sim.dd_to(0.05)  # riarmo del trigger: DD sotto difensivo.enter_dd
    sim.dd_to(0.105)  # entro 60 giorni dalla prima PAUSA
    assert sim.sm.state is A
    assert "seconda PAUSA" in sim.sm.regime.arresto_reason


def test_second_pausa_after_window_is_just_pausa():
    sim = Sim()
    sim.dd_to(0.11)
    sim.day(REG.pausa_max_days)
    sim.dd_to(0.05)
    sim.ts += REG.arresto_repeat_pausa_days * DAY_NS
    sim.dd_to(0.105)
    assert sim.sm.state is P


def test_floor_breach_leads_to_arresto():
    sim = Sim()
    sim.marks = sim.marks.__class__(e0=E0, hwm=E0, floor=E0 * 0.9)  # floor alzato (es. dopo molti profitti)
    sim.equity_to(E0 * 0.9)
    assert sim.sm.state is A and "floor" in sim.sm.regime.arresto_reason


def test_ops_pause_only_manual():
    sim = Sim()
    sim.sm.on_ops_anomaly(sim.ts, "posizione sconosciuta")
    assert sim.sm.state is P and sim.sm.pause_kind is PauseKind.OPS
    sim.day(100)
    for _ in range(20):
        sim.trade(1.0, shadow=True)
    sim.dd_to(0.0)
    assert sim.sm.state is P and sim.sm.pause_kind is PauseKind.OPS
    sim.sm.manual_confirm_ops(sim.ts, "operatore", "posizione chiusa a mano")
    assert sim.sm.state is D  # mai direttamente NORMALE


def test_ops_on_top_of_perf_returns_to_perf_after_confirmation():
    sim = Sim()
    sim.dd_to(0.11)
    sim.sm.on_ops_anomaly(sim.ts, "equity diversa dal broker")
    assert sim.sm.pause_kind is PauseKind.OPS
    sim.sm.manual_confirm_ops(sim.ts, "operatore", "ok")
    assert sim.sm.state is P and sim.sm.pause_kind is PauseKind.PERF


def test_manual_unlock_goes_to_pausa_ops():
    sim = Sim()
    sim.dd_to(0.16)
    assert sim.sm.state is A
    with pytest.raises(ValueError, match="manual_unlock"):
        sim.sm.manual_confirm_ops(sim.ts, "operatore", "x")
    with pytest.raises(ValueError, match="adr_id"):
        sim.sm.manual_unlock(sim.ts, "operatore", "ADR-7")
    assert sim.sm.manual_unlock(sim.ts, "operatore", "0007") is P
    assert sim.sm.pause_kind is PauseKind.OPS


def test_manual_unlock_outside_arresto_is_an_error():
    with pytest.raises(ValueError, match="solo in ARRESTO"):
        RiskStateMachine(CFG).manual_unlock(0, "operatore", "0007")


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_invalid_equity_goes_to_ops_pause(bad):
    sm = RiskStateMachine(CFG)
    assert sm.on_equity(0, bad, E0, E0 * 0.8, E0) is P
    assert sm.pause_kind is PauseKind.OPS


def test_regime_state_rejects_pause_as_level():
    data = RegimeState().to_dict()
    data["level"] = "PAUSA"
    with pytest.raises(ValueError):
        RegimeState.from_dict(data)
