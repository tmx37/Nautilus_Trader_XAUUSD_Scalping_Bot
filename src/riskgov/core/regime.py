"""Macchina a stati del rischio NORMALE → DIFENSIVO → PAUSA → ARRESTO (PIANO §2.3, ADR 0004, ADR 0006).

Regole fisse:
- DD >= arresto.enter_dd oppure equity <= floor portano sempre in ARRESTO;
- da ARRESTO si esce solo con `manual_unlock`, e si va in PAUSA (OPS);
- da PAUSA non si torna mai direttamente a NORMALE: si passa sempre da DIFENSIVO, con il conteggio dei
  trade in DIFENSIVO azzerato;
- una seconda PAUSA (PERF) entro `arresto.repeat_pausa_days` dalla precedente porta in ARRESTO.

Semantica scelta dove il PIANO non la fissa (ADR 0006):
- la PAUSA ha due motivi indipendenti: PERF (si chiude da sola con le condizioni di rientro) e OPS (solo
  con `manual_confirm_ops`); finché uno dei due è attivo lo stato è PAUSA, e OPS prevale nel `pause_kind`;
- il DD che porta in PAUSA è un fronte: dopo una PAUSA (di qualsiasi motivo) il trigger si riarma solo
  quando il DD torna sotto `difensivo.enter_dd`. Senza questo, uscire dalla PAUSA con il DD ancora sopra
  il 10% (in PAUSA non si opera, quindi il DD non recupera) farebbe scattare subito una seconda PAUSA e
  quindi l'ARRESTO. Nel frattempo restano attivi l'ARRESTO al 15% e il CUSUM;
- CUSUM sugli R dei trade reali chiusi in NORMALE o DIFENSIVO: S = max(0, S + k − R); avviso (S > w)
  → DIFENSIVO, allarme (S > h) → PAUSA (PERF). S si azzera all'ingresso in PAUSA;
- per tornare da DIFENSIVO a NORMALE servono DD <= exit_dd, almeno `min_trades` trade in DIFENSIVO e
  S <= w (altrimenti l'avviso CUSUM riporterebbe subito in DIFENSIVO);
- i giorni di PAUSA sono giorni di borsa, contati dalle chiamate a `on_day_close`;
- i trade reali chiusi durante una PAUSA (aperti prima) non contano né per il CUSUM né per il rientro;
  contano solo i trade ombra.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from riskgov.core.config import RiskConfig
from riskgov.core.types import PauseKind, RiskState

_NS_PER_DAY = 86_400 * 1_000_000_000
_ADR_ID = re.compile(r"^[0-9]{4}$")


@dataclass(frozen=True, slots=True)
class RegimeState:
    """Stato persistito della macchina a stati. Solo tipi primitivi: va e torna da JSON senza perdite."""

    # Livello quando non c'è PAUSA né ARRESTO. Dopo ogni PAUSA è DIFENSIVO.
    level: RiskState = RiskState.NORMALE
    perf_pause: bool = False
    ops_reason: str | None = None
    arresto_reason: str | None = None
    pause_days: int = 0
    shadow_trades: int = 0
    shadow_r_sum: float = 0.0
    difensivo_trades: int = 0
    cusum: float = 0.0
    pausa_dd_armed: bool = True
    last_perf_pause_ns: int | None = None
    last_dd: float | None = None

    @property
    def state(self) -> RiskState:
        if self.arresto_reason is not None:
            return RiskState.ARRESTO
        if self.perf_pause or self.ops_reason is not None:
            return RiskState.PAUSA
        return self.level

    @property
    def pause_kind(self) -> PauseKind | None:
        if self.state is not RiskState.PAUSA:
            return None
        return PauseKind.OPS if self.ops_reason is not None else PauseKind.PERF

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["level"] = self.level.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegimeState:
        d = dict(data)
        d["level"] = RiskState(d["level"])
        state = cls(**d)
        if state.level not in (RiskState.NORMALE, RiskState.DIFENSIVO):
            raise ValueError(f"level deve essere NORMALE o DIFENSIVO, trovato {state.level}")
        return state


@dataclass(frozen=True, slots=True)
class Transition:
    """Cambio di stato (o di motivo della PAUSA), da scrivere nel journal."""

    ts_ns: int
    from_state: RiskState
    from_pause_kind: PauseKind | None
    to_state: RiskState
    to_pause_kind: PauseKind | None
    reason: str


class RiskStateMachine:
    """Stato del rischio, aggiornato da equity, trade chiusi, giorni di borsa, eventi operativi e comandi
    manuali. Deterministica: stessa sequenza di eventi, stessi stati e stesse transizioni."""

    def __init__(self, cfg: RiskConfig, state: RegimeState | None = None) -> None:
        self._cfg = cfg
        self._s = state if state is not None else RegimeState()
        self._transitions: list[Transition] = []

    @property
    def state(self) -> RiskState:
        return self._s.state

    @property
    def pause_kind(self) -> PauseKind | None:
        return self._s.pause_kind

    @property
    def regime(self) -> RegimeState:
        """Stato completo da persistere (immutabile)."""
        return self._s

    def pop_transitions(self) -> tuple[Transition, ...]:
        """Transizioni avvenute dall'ultima chiamata, in ordine."""
        out = tuple(self._transitions)
        self._transitions.clear()
        return out

    # --- eventi -------------------------------------------------------------------------------------

    def on_equity(
        self, ts_ns: int, equity: float, hwm: float, floor: float, week_start_equity: float
    ) -> RiskState:
        """Aggiornamento mark-to-market. DD = 1 − E/HWM, con HWM sull'equity di chiusura giornaliera."""
        if self._s.arresto_reason is not None:
            return self.state
        values = (equity, hwm, floor, week_start_equity)
        if not all(math.isfinite(x) for x in values) or hwm <= 0 or week_start_equity <= 0:
            return self.on_ops_anomaly(ts_ns, f"dati di equity non validi: {values}")

        reg = self._cfg.regime
        dd = 1.0 - equity / hwm
        self._set(ts_ns, None, last_dd=dd)
        if dd >= reg.arresto_enter_dd:
            return self._arresto(ts_ns, f"DD {dd:.2%} >= {reg.arresto_enter_dd:.2%}")
        if equity <= floor:
            return self._arresto(ts_ns, f"equity {equity:.2f} <= floor {floor:.2f}")

        if not self._s.pausa_dd_armed and dd < reg.difensivo_enter_dd:
            self._set(ts_ns, None, pausa_dd_armed=True)
        if self._s.pausa_dd_armed and dd >= reg.pausa_enter_dd:
            return self._enter_perf_pause(ts_ns, f"DD {dd:.2%} >= {reg.pausa_enter_dd:.2%}")

        if self.state is RiskState.NORMALE:
            week_loss = 1.0 - equity / week_start_equity
            if dd >= reg.difensivo_enter_dd:
                return self._to_difensivo(ts_ns, f"DD {dd:.2%} >= {reg.difensivo_enter_dd:.2%}")
            if week_loss >= self._cfg.limits.weekly.normale:
                return self._to_difensivo(
                    ts_ns, f"perdita settimanale {week_loss:.2%} >= {self._cfg.limits.weekly.normale:.2%}"
                )
        return self._maybe_exit_difensivo(ts_ns)

    def on_trade_closed(self, ts_ns: int, r_multiple: float, *, shadow: bool = False) -> RiskState:
        """Trade chiuso, con il risultato in multipli di R; `shadow=True` per i trade ombra in PAUSA."""
        if self._s.arresto_reason is not None:
            return self.state
        if not math.isfinite(r_multiple):
            return self.on_ops_anomaly(ts_ns, f"R di un trade chiuso non valido: {r_multiple!r}")
        s = self._s
        if shadow:
            if s.perf_pause:
                self._set(
                    ts_ns,
                    None,
                    shadow_trades=s.shadow_trades + 1,
                    shadow_r_sum=s.shadow_r_sum + r_multiple,
                )
                return self._maybe_exit_perf_pause(ts_ns)
            return self.state
        if self.state is RiskState.PAUSA:
            return self.state

        reg = self._cfg.regime
        cusum = max(0.0, s.cusum + reg.cusum_k_r - r_multiple)
        dif_trades = s.difensivo_trades + 1 if s.level is RiskState.DIFENSIVO else s.difensivo_trades
        self._set(ts_ns, None, cusum=cusum, difensivo_trades=dif_trades)
        if cusum > reg.cusum_h_r:
            return self._enter_perf_pause(ts_ns, f"allarme CUSUM {cusum:.2f} > {reg.cusum_h_r}")
        if self.state is RiskState.NORMALE and cusum > reg.cusum_w_r:
            return self._to_difensivo(ts_ns, f"avviso CUSUM {cusum:.2f} > {reg.cusum_w_r}")
        return self._maybe_exit_difensivo(ts_ns)

    def on_day_close(self, ts_ns: int) -> RiskState:
        """Chiusura di un giorno di borsa (17:00 di New York, da lunedì a venerdì)."""
        if self._s.arresto_reason is not None or not self._s.perf_pause:
            return self.state
        self._set(ts_ns, None, pause_days=self._s.pause_days + 1)
        return self._maybe_exit_perf_pause(ts_ns)

    def on_ops_anomaly(self, ts_ns: int, reason: str) -> RiskState:
        """Anomalia di riconciliazione o di esecuzione, deposito rilevato, dati non validi → PAUSA (OPS).

        Se una PAUSA (OPS) è già attiva il motivo originale resta: le anomalie successive vanno nel journal.
        """
        if self._s.arresto_reason is not None or self._s.ops_reason is not None:
            return self.state
        return self._set(ts_ns, f"anomalia operativa: {reason}", ops_reason=reason, level=RiskState.DIFENSIVO)

    def on_kill(self, ts_ns: int, reason: str) -> RiskState:
        """Evento che porta direttamente in ARRESTO: stop-out del broker (isServerEvent), posizione senza
        SL non correggibile, `ARRESTO.lock` scritto dal watchdog."""
        if self._s.arresto_reason is not None:
            return self.state
        return self._arresto(ts_ns, reason)

    def manual_confirm_ops(self, ts_ns: int, operator: str, note: str) -> RiskState:
        """Conferma manuale che l'anomalia operativa è risolta: si torna in DIFENSIVO, oppure si resta in
        PAUSA (PERF) se anche quella è in corso."""
        if not operator.strip():
            raise ValueError("operatore obbligatorio")
        if self._s.arresto_reason is not None:
            raise ValueError("in ARRESTO serve manual_unlock, non manual_confirm_ops")
        if self._s.ops_reason is None:
            raise ValueError("nessuna PAUSA (OPS) da confermare")
        return self._set(
            ts_ns,
            f"conferma manuale OPS di {operator}: {note}",
            ops_reason=None,
            level=RiskState.DIFENSIVO,
            difensivo_trades=0,
        )

    def manual_unlock(self, ts_ns: int, operator: str, adr_id: str) -> RiskState:
        """Sblocco manuale dell'ARRESTO, con l'ADR di revisione: si va in PAUSA (OPS).

        HWM va ribasato all'equity corrente e il floor resta (`floor.rebase_after_unlock`).
        """
        if not operator.strip():
            raise ValueError("operatore obbligatorio")
        if not _ADR_ID.match(adr_id):
            raise ValueError(f"adr_id deve essere di 4 cifre (es. '0007'), trovato {adr_id!r}")
        if self._s.arresto_reason is None:
            raise ValueError("manual_unlock vale solo in ARRESTO")
        return self._set(
            ts_ns,
            f"sblocco manuale di {operator}, ADR {adr_id}",
            arresto_reason=None,
            perf_pause=False,
            ops_reason=f"sblocco da ARRESTO (ADR {adr_id}, {operator})",
            level=RiskState.DIFENSIVO,
            difensivo_trades=0,
            cusum=0.0,
            pausa_dd_armed=True,
        )

    # --- interni ------------------------------------------------------------------------------------

    def _set(self, ts_ns: int, reason: str | None, **changes: Any) -> RiskState:
        before = (self._s.state, self._s.pause_kind)
        self._s = replace(self._s, **changes)
        after = (self._s.state, self._s.pause_kind)
        if after != before:
            self._transitions.append(Transition(ts_ns, *before, *after, reason or "aggiornamento"))
        return self._s.state

    def _arresto(self, ts_ns: int, reason: str) -> RiskState:
        return self._set(ts_ns, f"ARRESTO: {reason}", arresto_reason=reason, perf_pause=False)

    def _to_difensivo(self, ts_ns: int, reason: str) -> RiskState:
        return self._set(ts_ns, reason, level=RiskState.DIFENSIVO, difensivo_trades=0)

    def _enter_perf_pause(self, ts_ns: int, reason: str) -> RiskState:
        last = self._s.last_perf_pause_ns
        window_ns = self._cfg.regime.arresto_repeat_pausa_days * _NS_PER_DAY
        if last is not None and ts_ns - last <= window_ns:
            return self._arresto(
                ts_ns, f"seconda PAUSA (PERF) entro {window_ns // _NS_PER_DAY} giorni: {reason}"
            )
        return self._set(
            ts_ns,
            f"PAUSA (PERF): {reason}",
            perf_pause=True,
            level=RiskState.DIFENSIVO,
            pause_days=0,
            shadow_trades=0,
            shadow_r_sum=0.0,
            cusum=0.0,
            pausa_dd_armed=False,
            last_perf_pause_ns=ts_ns,
        )

    def _maybe_exit_perf_pause(self, ts_ns: int) -> RiskState:
        s, reg = self._s, self._cfg.regime
        if not s.perf_pause:
            return self.state
        verified = (
            s.pause_days >= reg.pausa_min_days
            and s.shadow_trades >= reg.pausa_shadow_min_trades
            and s.shadow_r_sum >= 0
        )
        if verified:
            reason = f"fine PAUSA (PERF): {s.shadow_trades} trade ombra con ΣR = {s.shadow_r_sum:.2f} >= 0"
        elif s.pause_days >= reg.pausa_max_days:
            reason = f"fine PAUSA (PERF): {s.pause_days} giorni di borsa"
        else:
            return self.state
        return self._set(ts_ns, reason, perf_pause=False, level=RiskState.DIFENSIVO, difensivo_trades=0)

    def _maybe_exit_difensivo(self, ts_ns: int) -> RiskState:
        s, reg = self._s, self._cfg.regime
        if self.state is not RiskState.DIFENSIVO or s.last_dd is None:
            return self.state
        if (
            s.last_dd <= reg.difensivo_exit_dd
            and s.difensivo_trades >= reg.difensivo_min_trades
            and s.cusum <= reg.cusum_w_r
        ):
            return self._set(
                ts_ns,
                f"DD {s.last_dd:.2%} <= {reg.difensivo_exit_dd:.2%}, {s.difensivo_trades} trade in DIFENSIVO",
                level=RiskState.NORMALE,
            )
        return self.state
