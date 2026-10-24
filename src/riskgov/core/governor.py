"""Decisione finale su ogni proposta (PIANO §2.3, ADR 0004).

Le funzioni sono pure e deterministiche: stessi input, stessa decisione. Così il Monte Carlo di
calibrazione e il nodo live usano esattamente la stessa logica, e uno snapshot ripristinato dopo un
riavvio produce le stesse decisioni.

Asimmetria voluta del fail-closed:
- ingresso con input non validi → RIFIUTO;
- uscita → sempre APPROVATA, in qualsiasi stato e con qualsiasi input (chiudere riduce il rischio);
- modifica dello SL non valida → RIFIUTO (resta lo SL attuale, che è già al broker).

Lo SL d'ingresso è convertito in distanza relativa dal prezzo eseguibile (ask per un long, bid per uno
short), arrotondata al tick: è la distanza che l'adapter invia nel ProtoOANewOrderReq ed è quella usata
per il sizing. I confronti fra prezzi si fanno in tick interi, così l'errore di virgola mobile non può
spostare uno SL dal lato sbagliato o sotto la distanza minima.
"""

from __future__ import annotations

import math

from riskgov.core.config import PerState, RiskConfig
from riskgov.core.limits import (
    Capacity,
    committed_loss,
    currency_capacity,
    currency_exposure,
    news_blackout,
    open_heat,
    weekend_entry_block,
)
from riskgov.core.sizing import risk_fraction, round_down_volume, shrink_until, volume_spec_ok
from riskgov.core.types import (
    AccountSnapshot,
    Check,
    Decision,
    DecisionKind,
    ExitProposal,
    MarketContext,
    OpenPosition,
    RiskState,
    Side,
    StopUpdateProposal,
    TradeProposal,
)

_NS_PER_S = 1_000_000_000
_ENTRY_STATES = (RiskState.NORMALE, RiskState.DIFENSIVO)


def decide(
    proposal: TradeProposal, snapshot: AccountSnapshot, market: MarketContext, cfg: RiskConfig
) -> Decision:
    """Approva, riduce o rifiuta una proposta d'ingresso. Le uscite passano da `decide_exit`."""
    invalid = _invalid_inputs(proposal, snapshot, market)
    if invalid:
        return _reject(proposal, (Check("inputs_valid", 0.0, 1.0, False),), f"input non validi: {invalid}")

    spec, state = market.spec, snapshot.state
    tick = spec.price_increment
    entry = market.ask if proposal.side is Side.LONG else market.bid
    stop_ticks = _ticks(_toward_loss(proposal.side, entry, proposal.stop_price), tick)
    spread_ticks = _ticks(market.ask - market.bid, tick)
    min_ticks = max(1, math.ceil(spec.min_stop_distance / tick - 1e-9))
    # Distanza dello SL dal prezzo di chiusura (bid per un long, ask per uno short): è quella che il
    # broker confronta con lo SL.
    stop_close_ticks = stop_ticks - spread_ticks
    tp_ticks = (
        None
        if proposal.take_profit_price is None
        else _ticks(_toward_loss(proposal.side, proposal.take_profit_price, entry), tick)
    )
    quote_age_s = (snapshot.ts_ns - market.quote_ts_ns) / _NS_PER_S
    blackout = news_blackout(
        snapshot.ts_ns,
        (spec.base_currency, spec.quote_currency),
        market.events,
        cfg.news.before_min,
        cfg.news.after_min,
    )
    entry_state = state in _ENTRY_STATES
    held = any(p.instrument == proposal.instrument for p in snapshot.positions)
    max_pos = _per_state(cfg.limits.max_positions, state) if entry_state else 0

    gates = (
        _flag("state_allows_entry", entry_state),
        _flag("execution_ready", snapshot.execution_ready),
        Check(
            "quote_age_s",
            quote_age_s,
            cfg.execution.stale_quote_s,
            abs(quote_age_s) <= cfg.execution.stale_quote_s,
        ),
        _flag("weekend_cutoff", not weekend_entry_block(snapshot.ts_ns, cfg.gaps.no_entry_after_fri_utc)),
        _flag("news_blackout", blackout is None),
        _flag("one_per_instrument", not held),
        Check(
            "max_positions",
            float(len(snapshot.positions) + 1),
            float(max_pos),
            len(snapshot.positions) < max_pos,
        ),
        Check("stop_side_ticks", float(stop_close_ticks), 1.0, stop_close_ticks >= 1),
        Check(
            "stop_min_distance_ticks",
            float(stop_close_ticks),
            float(min_ticks),
            stop_close_ticks >= min_ticks,
        ),
    )
    if tp_ticks is not None:
        gates += (Check("take_profit_ticks", float(tp_ticks), float(min_ticks), tp_ticks >= min_ticks),)
    failed = [g for g in gates if not g.passed]
    if failed:
        reason = f"rifiutata: {', '.join(g.name for g in failed)}"
        if blackout is not None:
            reason += f" (evento {blackout.name})"
        return _reject(proposal, gates, reason)

    stop_distance = _price(stop_ticks, tick)
    tp_distance = None if tp_ticks is None else _price(tp_ticks, tick)
    capacities = _capacities(proposal.side, stop_distance, snapshot, market, cfg)
    by_name = {c.name: c for c in capacities}

    q_cap = min(c.max_units() for c in capacities)
    q = round_down_volume(q_cap, spec.min_volume, spec.step_volume, spec.max_volume)
    q = shrink_until(
        q, spec.step_volume, spec.min_volume, lambda u: all(c.check(u).passed for c in capacities)
    )
    binding = min(capacities, key=lambda c: c.max_units()).name

    if q == 0:
        # Controlli valutati al volume minimo: mostrano quale vincolo impedisce anche il lotto più piccolo.
        checks = gates + tuple(c.check(spec.min_volume) for c in capacities)
        return _reject(
            proposal, checks, f"rifiutata: quantità sotto il minimo del broker (vincolo {binding})"
        )

    checks = gates + tuple(c.check(q) for c in capacities)
    risk_amount = q * (stop_distance * market.value_per_unit)  # stesso prodotto del controllo risk_state
    q_state = round_down_volume(
        by_name["risk_state"].max_units(), spec.min_volume, spec.step_volume, spec.max_volume
    )
    kind = DecisionKind.REDUCED if q < q_state else DecisionKind.APPROVED
    reason = f"{'ridotta' if kind is DecisionKind.REDUCED else 'approvata'}: vincolo determinante {binding}"
    return Decision(
        proposal_id=proposal.proposal_id,
        kind=kind,
        quantity=q,
        risk_amount=risk_amount,
        checks=checks,
        reason=reason,
        stop_distance=stop_distance,
        take_profit_distance=tp_distance,
    )


def decide_exit(proposal: ExitProposal, snapshot: AccountSnapshot) -> Decision:
    """Le uscite sono sempre approvate, in qualsiasi stato: chiudono tutta la posizione."""
    del snapshot  # firma uniforme con decide(); l'uscita non dipende dallo stato
    return Decision(
        proposal_id=proposal.proposal_id,
        kind=DecisionKind.APPROVED,
        quantity=0,
        risk_amount=0.0,
        checks=(),
        reason=f"uscita approvata: {proposal.reason}",
    )


def decide_stop_update(
    proposal: StopUpdateProposal, position: OpenPosition | None, market: MarketContext
) -> Decision:
    """Approva un nuovo SL solo se va verso il guadagno (o mette uno SL mancante) e resta valido.

    Vale in ogni stato: stringere lo SL riduce sempre il rischio.
    """
    tick = market.spec.price_increment
    positive = (proposal.new_stop_price, market.bid, market.ask, tick)
    if position is None or position.instrument != proposal.instrument:
        return _reject(proposal, (_flag("position_exists", False),), "rifiutata: nessuna posizione aperta")
    if (
        not all(math.isfinite(x) and x > 0 for x in positive)
        or not (math.isfinite(market.spec.min_stop_distance) and market.spec.min_stop_distance >= 0)
        or market.ask < market.bid
    ):
        return _reject(proposal, (_flag("inputs_valid", False),), f"input non validi: {positive}")

    new_ticks = _ticks(proposal.new_stop_price, tick)
    new_stop = _price(new_ticks, tick)
    min_ticks = max(1, math.ceil(market.spec.min_stop_distance / tick - 1e-9))
    close = market.bid if position.side is Side.LONG else market.ask
    dist_ticks = _ticks(_toward_loss(position.side, close, new_stop), tick)
    if position.stop_price is None or not math.isfinite(position.stop_price):
        # Posizione senza SL: qualsiasi SL valido è un miglioramento (nel journal il limite è 0).
        improves, current = True, 0.0
    else:
        cur_ticks = _ticks(position.stop_price, tick)
        current = position.stop_price
        improves = new_ticks > cur_ticks if position.side is Side.LONG else new_ticks < cur_ticks
    checks = (
        Check("stop_monotone", new_stop, current, improves),
        Check("stop_min_distance_ticks", float(dist_ticks), float(min_ticks), dist_ticks >= min_ticks),
    )
    if not all(c.passed for c in checks):
        return _reject(proposal, checks, f"rifiutata: {', '.join(c.name for c in checks if not c.passed)}")
    return Decision(
        proposal_id=proposal.proposal_id,
        kind=DecisionKind.APPROVED,
        quantity=position.quantity,
        risk_amount=0.0,
        checks=checks,
        reason="nuovo SL approvato",
        stop_price=new_stop,
    )


def _capacities(
    side: Side, stop_distance: float, snapshot: AccountSnapshot, market: MarketContext, cfg: RiskConfig
) -> tuple[Capacity, ...]:
    """Vincoli lineari sulla quantità del nuovo trade (in R il budget, corretti per i gap gli altri)."""
    e, state, lim = snapshot.equity, snapshot.state, cfg.limits
    r_unit = stop_distance * market.value_per_unit
    gap_unit = (stop_distance + market.gap) * market.value_per_unit
    heat = open_heat(snapshot.positions)
    net = currency_exposure(snapshot.positions)
    direction = 1.0 if side is Side.LONG else -1.0
    ccy_cap = lim.currency_net_risk * e
    return (
        Capacity("risk_state", 0.0, risk_fraction(state, cfg, snapshot.ramp_active) * e, r_unit),
        Capacity("cppi", 0.0, cfg.cppi.m * (e - snapshot.floor), r_unit),
        Capacity("heat", heat, _per_state(lim.heat_cap, state) * e, gap_unit),
        Capacity(
            "daily_loss",
            committed_loss(snapshot.day_start_equity, e, heat),
            _per_state(lim.daily, state) * snapshot.day_start_equity,
            gap_unit,
        ),
        Capacity(
            "weekly_loss",
            committed_loss(snapshot.week_start_equity, e, heat),
            _per_state(lim.weekly, state) * snapshot.week_start_equity,
            gap_unit,
        ),
        Capacity(
            "margin",
            snapshot.margin_used,
            lim.margin_used_cap * e,
            market.notional_per_unit * market.spec.margin_rate,
        ),
        currency_capacity(market.spec.base_currency, direction, net, ccy_cap, gap_unit),
        currency_capacity(market.spec.quote_currency, -direction, net, ccy_cap, gap_unit),
    )


def _invalid_inputs(proposal: TradeProposal, snapshot: AccountSnapshot, market: MarketContext) -> str:
    """Descrizione del primo input non valido, o stringa vuota. Fail-closed su NaN, infiniti e negativi."""
    spec = market.spec
    positive = {
        "equity": snapshot.equity,
        "day_start_equity": snapshot.day_start_equity,
        "week_start_equity": snapshot.week_start_equity,
        "bid": market.bid,
        "ask": market.ask,
        "value_per_unit": market.value_per_unit,
        "notional_per_unit": market.notional_per_unit,
        "price_increment": spec.price_increment,
        "margin_rate": spec.margin_rate,
        "reference_price": proposal.reference_price,
        "stop_price": proposal.stop_price,
    }
    non_negative = {
        "floor": snapshot.floor,
        "margin_used": snapshot.margin_used,
        "gap": market.gap,
        "min_stop_distance": spec.min_stop_distance,
    }
    if proposal.take_profit_price is not None:
        positive["take_profit_price"] = proposal.take_profit_price
    for name, v in positive.items():
        if not (math.isfinite(v) and v > 0):
            return f"{name}={v!r}"
    for name, v in non_negative.items():
        if not (math.isfinite(v) and v >= 0):
            return f"{name}={v!r}"
    if market.ask < market.bid:
        return f"ask {market.ask} < bid {market.bid}"
    if proposal.instrument != spec.instrument:
        return (
            f"strumento della proposta {proposal.instrument} diverso da quello di mercato {spec.instrument}"
        )
    if not volume_spec_ok(spec.min_volume, spec.step_volume, spec.max_volume):
        return f"volumi dello strumento non validi: {spec.min_volume}/{spec.step_volume}/{spec.max_volume}"
    return ""


def _toward_loss(side: Side, price: float, stop: float) -> float:
    """Distanza da `price` a `stop` nel verso della perdita (positiva se lo stop è dal lato giusto)."""
    return price - stop if side is Side.LONG else stop - price


def _ticks(distance: float, tick: float) -> int:
    return round(distance / tick)


def _price(ticks: int, tick: float) -> float:
    return round(ticks * tick, 10)


def _per_state[T: (int, float)](ps: PerState[T], state: RiskState) -> T:
    return ps.difensivo if state is RiskState.DIFENSIVO else ps.normale


def _flag(name: str, ok: bool) -> Check:
    return Check(name, 1.0 if ok else 0.0, 1.0, ok)


def _reject(proposal: TradeProposal | StopUpdateProposal, checks: tuple[Check, ...], reason: str) -> Decision:
    return Decision(
        proposal_id=proposal.proposal_id,
        kind=DecisionKind.REJECTED,
        quantity=0,
        risk_amount=0.0,
        checks=checks,
        reason=reason,
    )
