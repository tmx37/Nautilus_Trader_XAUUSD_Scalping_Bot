"""La config di esempio si carica e i vincoli fra parametri sono applicati (PIANO §2.3, ADR 0004)."""

import copy
from pathlib import Path

import pytest
import yaml

from riskgov.core.config import R_NORMALE_TETTO, ConfigError, load_risk_config, parse_risk_config
from riskgov.core.types import RiskState

EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "risk.example.yaml"


@pytest.fixture
def raw() -> dict:
    with EXAMPLE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _broken(raw: dict, path: str, value) -> dict:
    data = copy.deepcopy(raw)
    *parents, last = path.split(".")
    node = data
    for key in parents:
        node = node[key]
    node[last] = value
    return data


def test_example_config_loads():
    cfg = load_risk_config(EXAMPLE)
    assert cfg.r_state[RiskState.NORMALE] <= R_NORMALE_TETTO
    assert cfg.r_state[RiskState.PAUSA] == 0
    assert cfg.limits.allow_adds is False
    assert cfg.limits.day_boundary_tz.key == "America/New_York"


def test_risk_per_trade_never_increases_with_worse_state():
    cfg = load_risk_config(EXAMPLE)
    order = [RiskState.NORMALE, RiskState.DIFENSIVO, RiskState.PAUSA, RiskState.ARRESTO]
    values = [cfg.r_state[s] for s in order]
    assert values == sorted(values, reverse=True)


def test_kill_switch_fires_before_floor():
    cfg = load_risk_config(EXAMPLE)
    d_kill = cfg.regime.arresto_enter_dd
    assert cfg.cppi.k >= d_kill
    assert cfg.cppi.lam <= 1 - d_kill
    # HWM − F >= D_kill·HWM per ogni HWM >= E0 (verifica numerica della relazione dell'ADR 0004)
    e0 = cfg.account.cap_iniziale
    for hwm in (e0, 1.2 * e0, 1.4 * e0, 2 * e0, 5 * e0):
        floor = e0 * (1 - cfg.cppi.k) + cfg.cppi.lam * (hwm - e0)
        assert hwm - floor >= d_kill * hwm - 1e-9


@pytest.mark.parametrize(
    ("path", "value", "fragment"),
    [
        ("risk.r_state.NORMALE", 0.02, "r_state.NORMALE"),
        ("risk.r_state.PAUSA", 0.001, "r_state.PAUSA"),
        ("risk.r_state.DIFENSIVO", 0.011, "r_state.DIFENSIVO"),
        ("risk.limits.allow_adds", True, "allow_adds"),
        ("risk.cppi.K", 0.10, "cppi.K"),
        ("risk.cppi.lambda", 0.9, "cppi.lambda"),
        ("risk.regime.difensivo.exit_dd", 0.07, "isteresi"),
        ("risk.regime.pausa.enter_dd", 0.20, "isteresi"),
        ("risk.limits.daily.NORMALE", 0.01, "limits.daily"),
        ("risk.watchdog.hard_dd", 0.15, "watchdog.hard_dd"),
        ("risk.f4_ramp.r_normale", 0.02, "f4_ramp"),
        ("risk.regime.cusum.w_r", 6.0, "cusum"),  # avviso non prima dell'allarme
        ("risk.regime.cusum.w_r", 0.0, "cusum"),
    ],
)
def test_constraint_violations_are_rejected(raw, path, value, fragment):
    with pytest.raises(ConfigError) as exc:
        parse_risk_config(_broken(raw, path, value))
    assert any(fragment in e for e in exc.value.errors), exc.value.errors


def test_unknown_key_is_an_error(raw):
    data = copy.deepcopy(raw)
    data["risk"]["limits"]["max_position"] = 5  # refuso di max_positions
    with pytest.raises(ConfigError, match="chiave sconosciuta"):
        parse_risk_config(data)


def test_missing_key_is_an_error(raw):
    data = copy.deepcopy(raw)
    del data["risk"]["regime"]["arresto"]["enter_dd"]
    with pytest.raises(ConfigError, match="chiave mancante"):
        parse_risk_config(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "0.01", True, None])
def test_non_numeric_values_are_rejected(raw, value):
    with pytest.raises(ConfigError, match="numero finito"):
        parse_risk_config(_broken(raw, "risk.r_state.NORMALE", value))


def test_bad_timezone_is_rejected(raw):
    with pytest.raises(ConfigError, match="fuso orario"):
        parse_risk_config(_broken(raw, "risk.limits.day_boundary", "17:00 Mars/Olympus"))
