"""Caricamento e validazione della configurazione del rischio (config/risk.*.yaml).

Una config che viola i vincoli fra parametri (PIANO §2.3, ADR 0004) non si carica: il sistema non deve
poter partire con parametri incoerenti. Tutte le chiavi sono obbligatorie e quelle sconosciute sono
errori, così un refuso non diventa un default silenzioso.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from riskgov.core.types import RiskState

# Tetto assoluto del rischio per trade (PIANO §4, F5). Si alza solo con un ADR e una modifica qui.
R_NORMALE_TETTO = 0.01


class ConfigError(ValueError):
    """Config del rischio non valida; `errors` elenca le violazioni trovate."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("config del rischio non valida:\n- " + "\n- ".join(errors))
        self.errors = errors


@dataclass(frozen=True, slots=True)
class PerState[T: (int, float)]:
    """Valore per gli stati in cui si può aprire una posizione."""

    normale: T
    difensivo: T


@dataclass(frozen=True, slots=True)
class AccountConfig:
    currency: str
    cap_iniziale: float  # solo E0 per il floor, mai nel sizing (R1.2)


@dataclass(frozen=True, slots=True)
class F4RampConfig:
    r_normale: float
    trades: int


@dataclass(frozen=True, slots=True)
class CppiConfig:
    k: float
    lam: float
    m: float


@dataclass(frozen=True, slots=True)
class RegimeConfig:
    hwm_basis: str
    difensivo_enter_dd: float
    difensivo_exit_dd: float
    difensivo_min_trades: int
    pausa_enter_dd: float
    pausa_min_days: int
    pausa_shadow_min_trades: int
    pausa_max_days: int
    arresto_enter_dd: float
    arresto_repeat_pausa_days: int
    cusum_k_r: float
    cusum_w_r: float
    cusum_h_r: float


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    day_boundary: time
    day_boundary_tz: ZoneInfo
    daily: PerState[float]
    weekly: PerState[float]
    heat_cap: PerState[float]
    max_positions: PerState[int]
    currency_net_risk: float
    margin_used_cap: float
    allow_adds: bool


@dataclass(frozen=True, slots=True)
class GapsConfig:
    quantile: float
    weekend_heat_cap: float
    no_entry_after_fri_utc: time


@dataclass(frozen=True, slots=True)
class NewsConfig:
    calendar_file: Path
    before_min: int
    after_min: int


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    sl_confirm_s: float
    sl_retries: int
    stale_quote_s: float
    inbound_idle_s: float


@dataclass(frozen=True, slots=True)
class WatchdogConfig:
    poll_s: float
    naked_grace_s: float
    emergency_sl_risk: float
    hard_dd: float


@dataclass(frozen=True, slots=True)
class RiskConfig:
    account: AccountConfig
    r_state: Mapping[RiskState, float]
    f4_ramp: F4RampConfig
    cppi: CppiConfig
    regime: RegimeConfig
    limits: LimitsConfig
    gaps: GapsConfig
    news: NewsConfig
    execution: ExecutionConfig
    max_notional_x_equity: float
    watchdog: WatchdogConfig


def load_risk_config(path: str | Path) -> RiskConfig:
    """Legge un file YAML di config del rischio e lo valida."""
    with Path(path).open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse_risk_config(data)


def parse_risk_config(data: Any) -> RiskConfig:
    """Costruisce e valida una RiskConfig da un mapping già letto (radice con la chiave `risk`)."""
    root = _section(data, "", {"risk"})
    r = _section(
        root["risk"],
        "risk",
        {
            "account",
            "r_state",
            "f4_ramp",
            "cppi",
            "regime",
            "limits",
            "gaps",
            "news",
            "execution",
            "backstop",
            "watchdog",
        },
    )

    acc = _section(r["account"], "risk.account", {"currency", "cap_iniziale"})
    rs = _section(r["r_state"], "risk.r_state", {s.value for s in RiskState})
    ramp = _section(r["f4_ramp"], "risk.f4_ramp", {"r_normale", "trades"})
    cppi = _section(r["cppi"], "risk.cppi", {"K", "lambda", "m"})
    reg = _section(r["regime"], "risk.regime", {"hwm_basis", "difensivo", "pausa", "arresto", "cusum"})
    dif = _section(reg["difensivo"], "risk.regime.difensivo", {"enter_dd", "exit_dd", "min_trades"})
    pau = _section(
        reg["pausa"], "risk.regime.pausa", {"enter_dd", "min_days", "shadow_min_trades", "max_days"}
    )
    arr = _section(reg["arresto"], "risk.regime.arresto", {"enter_dd", "repeat_pausa_days"})
    cus = _section(reg["cusum"], "risk.regime.cusum", {"k_r", "w_r", "h_r"})
    lim = _section(
        r["limits"],
        "risk.limits",
        {
            "day_boundary",
            "daily",
            "weekly",
            "heat_cap",
            "max_positions",
            "currency_net_risk",
            "margin_used_cap",
            "allow_adds",
        },
    )
    gaps = _section(r["gaps"], "risk.gaps", {"quantile", "weekend_heat_cap", "no_entry_after_fri_utc"})
    news = _section(r["news"], "risk.news", {"calendar_file", "before_min", "after_min"})
    ex = _section(
        r["execution"], "risk.execution", {"sl_confirm_s", "sl_retries", "stale_quote_s", "inbound_idle_s"}
    )
    back = _section(r["backstop"], "risk.backstop", {"max_notional_x_equity"})
    wd = _section(r["watchdog"], "risk.watchdog", {"poll_s", "naked_grace_s", "emergency_sl_risk", "hard_dd"})

    boundary_time, boundary_tz = _day_boundary(lim["day_boundary"], "risk.limits.day_boundary")

    cfg = RiskConfig(
        account=AccountConfig(
            currency=_currency(acc["currency"], "risk.account.currency"),
            cap_iniziale=_num(acc["cap_iniziale"], "risk.account.cap_iniziale"),
        ),
        r_state={s: _num(rs[s.value], f"risk.r_state.{s.value}") for s in RiskState},
        f4_ramp=F4RampConfig(
            r_normale=_num(ramp["r_normale"], "risk.f4_ramp.r_normale"),
            trades=_int(ramp["trades"], "risk.f4_ramp.trades"),
        ),
        cppi=CppiConfig(
            k=_num(cppi["K"], "risk.cppi.K"),
            lam=_num(cppi["lambda"], "risk.cppi.lambda"),
            m=_num(cppi["m"], "risk.cppi.m"),
        ),
        regime=RegimeConfig(
            hwm_basis=str(reg["hwm_basis"]),
            difensivo_enter_dd=_num(dif["enter_dd"], "risk.regime.difensivo.enter_dd"),
            difensivo_exit_dd=_num(dif["exit_dd"], "risk.regime.difensivo.exit_dd"),
            difensivo_min_trades=_int(dif["min_trades"], "risk.regime.difensivo.min_trades"),
            pausa_enter_dd=_num(pau["enter_dd"], "risk.regime.pausa.enter_dd"),
            pausa_min_days=_int(pau["min_days"], "risk.regime.pausa.min_days"),
            pausa_shadow_min_trades=_int(pau["shadow_min_trades"], "risk.regime.pausa.shadow_min_trades"),
            pausa_max_days=_int(pau["max_days"], "risk.regime.pausa.max_days"),
            arresto_enter_dd=_num(arr["enter_dd"], "risk.regime.arresto.enter_dd"),
            arresto_repeat_pausa_days=_int(arr["repeat_pausa_days"], "risk.regime.arresto.repeat_pausa_days"),
            cusum_k_r=_num(cus["k_r"], "risk.regime.cusum.k_r"),
            cusum_w_r=_num(cus["w_r"], "risk.regime.cusum.w_r"),
            cusum_h_r=_num(cus["h_r"], "risk.regime.cusum.h_r"),
        ),
        limits=LimitsConfig(
            day_boundary=boundary_time,
            day_boundary_tz=boundary_tz,
            daily=_per_state(lim["daily"], "risk.limits.daily", _num),
            weekly=_per_state(lim["weekly"], "risk.limits.weekly", _num),
            heat_cap=_per_state(lim["heat_cap"], "risk.limits.heat_cap", _num),
            max_positions=_per_state(lim["max_positions"], "risk.limits.max_positions", _int),
            currency_net_risk=_num(lim["currency_net_risk"], "risk.limits.currency_net_risk"),
            margin_used_cap=_num(lim["margin_used_cap"], "risk.limits.margin_used_cap"),
            allow_adds=_bool(lim["allow_adds"], "risk.limits.allow_adds"),
        ),
        gaps=GapsConfig(
            quantile=_num(gaps["quantile"], "risk.gaps.quantile"),
            weekend_heat_cap=_num(gaps["weekend_heat_cap"], "risk.gaps.weekend_heat_cap"),
            no_entry_after_fri_utc=_hhmm(gaps["no_entry_after_fri_utc"], "risk.gaps.no_entry_after_fri_utc"),
        ),
        news=NewsConfig(
            calendar_file=Path(str(news["calendar_file"])),
            before_min=_int(news["before_min"], "risk.news.before_min"),
            after_min=_int(news["after_min"], "risk.news.after_min"),
        ),
        execution=ExecutionConfig(
            sl_confirm_s=_num(ex["sl_confirm_s"], "risk.execution.sl_confirm_s"),
            sl_retries=_int(ex["sl_retries"], "risk.execution.sl_retries"),
            stale_quote_s=_num(ex["stale_quote_s"], "risk.execution.stale_quote_s"),
            inbound_idle_s=_num(ex["inbound_idle_s"], "risk.execution.inbound_idle_s"),
        ),
        max_notional_x_equity=_num(back["max_notional_x_equity"], "risk.backstop.max_notional_x_equity"),
        watchdog=WatchdogConfig(
            poll_s=_num(wd["poll_s"], "risk.watchdog.poll_s"),
            naked_grace_s=_num(wd["naked_grace_s"], "risk.watchdog.naked_grace_s"),
            emergency_sl_risk=_num(wd["emergency_sl_risk"], "risk.watchdog.emergency_sl_risk"),
            hard_dd=_num(wd["hard_dd"], "risk.watchdog.hard_dd"),
        ),
    )
    errors = validate(cfg)
    if errors:
        raise ConfigError(errors)
    return cfg


def validate(cfg: RiskConfig) -> list[str]:
    """Restituisce l'elenco dei vincoli violati (vuoto se la config è coerente)."""
    errors: list[str] = []

    def need(ok: bool, msg: str) -> None:
        if not ok:
            errors.append(msg)

    rs = cfg.r_state
    rn, rd = rs[RiskState.NORMALE], rs[RiskState.DIFENSIVO]
    reg, lim, cppi = cfg.regime, cfg.limits, cfg.cppi

    need(cfg.account.cap_iniziale > 0, "account.cap_iniziale deve essere > 0")
    need(0 < rn <= R_NORMALE_TETTO, f"r_state.NORMALE deve stare in (0, {R_NORMALE_TETTO}]")
    need(0 <= rd <= rn, "r_state.DIFENSIVO deve stare in [0, r_state.NORMALE]")
    need(rs[RiskState.PAUSA] == 0, "r_state.PAUSA deve essere 0 (nessun nuovo ingresso)")
    need(rs[RiskState.ARRESTO] == 0, "r_state.ARRESTO deve essere 0 (nessun nuovo ingresso)")
    need(0 < cfg.f4_ramp.r_normale <= rn, "f4_ramp.r_normale deve stare in (0, r_state.NORMALE]")
    need(cfg.f4_ramp.trades >= 0, "f4_ramp.trades deve essere >= 0")

    need(reg.hwm_basis == "daily_close_equity", "regime.hwm_basis supportato: daily_close_equity")
    need(
        0 < reg.difensivo_exit_dd < reg.difensivo_enter_dd < reg.pausa_enter_dd < reg.arresto_enter_dd < 1,
        "serve 0 < difensivo.exit_dd < difensivo.enter_dd < pausa.enter_dd < arresto.enter_dd < 1 (isteresi)",
    )
    need(reg.difensivo_min_trades >= 1, "regime.difensivo.min_trades deve essere >= 1")
    need(0 < reg.pausa_min_days <= reg.pausa_max_days, "serve 0 < pausa.min_days <= pausa.max_days")
    need(reg.pausa_shadow_min_trades >= 1, "regime.pausa.shadow_min_trades deve essere >= 1")
    need(reg.arresto_repeat_pausa_days >= 1, "regime.arresto.repeat_pausa_days deve essere >= 1")
    need(
        reg.cusum_k_r >= 0 and 0 < reg.cusum_w_r < reg.cusum_h_r,
        "cusum: serve k_r >= 0 e 0 < w_r < h_r (avviso prima dell'allarme)",
    )

    # Con K >= D_kill e lambda <= 1 - D_kill il kill switch scatta sempre prima del floor (ADR 0004).
    need(cppi.k >= reg.arresto_enter_dd, "cppi.K deve essere >= regime.arresto.enter_dd")
    need(0 <= cppi.lam <= 1 - reg.arresto_enter_dd, "cppi.lambda deve stare in [0, 1 - arresto.enter_dd]")
    need(cppi.k < 1, "cppi.K deve essere < 1")
    need(cppi.m > 0, "cppi.m deve essere > 0")

    for name, ps in (("daily", lim.daily), ("weekly", lim.weekly), ("heat_cap", lim.heat_cap)):
        need(0 < ps.difensivo <= ps.normale, f"limits.{name}: serve 0 < DIFENSIVO <= NORMALE")
    need(
        lim.daily.normale >= lim.heat_cap.normale and lim.daily.difensivo >= lim.heat_cap.difensivo,
        "limits.daily deve essere >= limits.heat_cap in ogni stato (altrimenti non si entra mai)",
    )
    need(
        lim.weekly.normale >= lim.daily.normale and lim.weekly.difensivo >= lim.daily.difensivo,
        "limits.weekly deve essere >= limits.daily in ogni stato",
    )
    need(
        lim.heat_cap.normale >= rn and lim.heat_cap.difensivo >= rd,
        "limits.heat_cap deve contenere almeno un trade a rischio pieno dello stato",
    )
    need(
        1 <= lim.max_positions.difensivo <= lim.max_positions.normale,
        "limits.max_positions: serve 1 <= DIFENSIVO <= NORMALE",
    )
    need(
        0 < lim.currency_net_risk <= lim.heat_cap.normale,
        "limits.currency_net_risk deve stare in (0, heat_cap.NORMALE]",
    )
    need(0 < lim.margin_used_cap <= 0.5, "limits.margin_used_cap deve stare in (0, 0.5]")
    need(
        lim.allow_adds is False, "limits.allow_adds deve essere false (niente aggiunte, griglie, martingale)"
    )

    need(0.9 <= cfg.gaps.quantile < 1, "gaps.quantile deve stare in [0.9, 1)")
    need(
        0 < cfg.gaps.weekend_heat_cap <= lim.heat_cap.normale,
        "gaps.weekend_heat_cap deve stare in (0, heat_cap.NORMALE]",
    )
    need(cfg.news.before_min >= 0 and cfg.news.after_min >= 0, "news: finestre di blackout >= 0")
    ex = cfg.execution
    need(
        ex.sl_confirm_s > 0 and ex.sl_retries >= 1 and ex.stale_quote_s > 0 and ex.inbound_idle_s > 0,
        "execution: tempi > 0 e sl_retries >= 1",
    )
    need(cfg.max_notional_x_equity > 0, "backstop.max_notional_x_equity deve essere > 0")

    wd = cfg.watchdog
    need(
        wd.hard_dd > reg.arresto_enter_dd,
        "watchdog.hard_dd deve essere > regime.arresto.enter_dd (il nodo agisce sempre per primo)",
    )
    need(wd.hard_dd < 1, "watchdog.hard_dd deve essere < 1")
    need(
        wd.poll_s > 0 and wd.naked_grace_s > ex.sl_confirm_s,
        "watchdog: poll_s > 0 e naked_grace_s > execution.sl_confirm_s",
    )
    need(
        0 < wd.emergency_sl_risk <= 2 * lim.heat_cap.normale,
        "watchdog.emergency_sl_risk deve stare in (0, 2 * heat_cap.NORMALE]",
    )
    return errors


def _section(data: Any, path: str, keys: set[str]) -> dict[str, Any]:
    where = path or "<radice>"
    if not isinstance(data, Mapping):
        raise ConfigError([f"{where}: atteso un mapping"])
    missing = keys - data.keys()
    extra = data.keys() - keys
    errors = [f"{path}.{k}: chiave mancante".lstrip(".") for k in sorted(missing)]
    errors += [f"{path}.{k}: chiave sconosciuta".lstrip(".") for k in sorted(map(str, extra))]
    if errors:
        raise ConfigError(errors)
    return dict(data)


def _num(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ConfigError([f"{path}: atteso un numero finito, trovato {value!r}"])
    return float(value)


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError([f"{path}: atteso un intero, trovato {value!r}"])
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError([f"{path}: atteso true/false, trovato {value!r}"])
    return value


def _currency(value: Any, path: str) -> str:
    if not (isinstance(value, str) and len(value) == 3 and value.isupper()):
        raise ConfigError([f"{path}: atteso un codice ISO di 3 lettere maiuscole, trovato {value!r}"])
    return value


def _hhmm(value: Any, path: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        raise ConfigError([f"{path}: atteso un orario HH:MM, trovato {value!r}"]) from None


def _day_boundary(value: Any, path: str) -> tuple[time, ZoneInfo]:
    parts = str(value).split()
    if len(parts) != 2:
        raise ConfigError([f"{path}: atteso 'HH:MM Zona/IANA', trovato {value!r}"])
    try:
        tz = ZoneInfo(parts[1])
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError([f"{path}: fuso orario sconosciuto {parts[1]!r}"]) from None
    return _hhmm(parts[0], path), tz


def _per_state[T: (int, float)](data: Any, path: str, conv: Any) -> PerState[T]:
    d = _section(data, path, {"NORMALE", "DIFENSIVO"})
    return PerState(
        normale=conv(d["NORMALE"], f"{path}.NORMALE"), difensivo=conv(d["DIFENSIVO"], f"{path}.DIFENSIVO")
    )
