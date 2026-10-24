"""Tipi del core del rischio. Immutabili, senza dipendenze da NautilusTrader.

Convenzioni:
- importi nella valuta del conto;
- prezzi come float nella valuta di quotazione;
- quantità in unità intere dello strumento (es. 1.000 unità = 0,01 lot EURUSD), così l'arrotondamento al
  passo è esatto; la conversione dai centesimi di unità di cTrader è compito dell'adapter;
- tempi in nanosecondi UTC dall'epoch, come in NautilusTrader.

Il core calcola tutti i rischi a partire dai fatti grezzi (quantità, prezzi, stop, gap, conversioni):
l'integrazione non passa mai un rischio già calcolato.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class RiskState(StrEnum):
    """Stati della macchina a stati del rischio (PIANO §2.3)."""

    NORMALE = "NORMALE"
    DIFENSIVO = "DIFENSIVO"
    PAUSA = "PAUSA"
    ARRESTO = "ARRESTO"


class PauseKind(StrEnum):
    """Motivo della PAUSA: PERF si chiude da sola con le condizioni di rientro, OPS solo a mano."""

    PERF = "PERF"
    OPS = "OPS"


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class DecisionKind(StrEnum):
    APPROVED = "APPROVED"
    REDUCED = "REDUCED"  # approvata con quantità inferiore a quella del solo rischio per stato
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """Proposta di ingresso pubblicata da un Actor di segnale. Il governor decide la quantità.

    `stop_price` e `take_profit_price` sono livelli assoluti voluti dal segnale; il governor li converte
    in distanze relative dal prezzo eseguibile corrente (cTrader accetta solo SL/TP relativi sui MARKET).
    """

    proposal_id: str
    source: str
    instrument: str
    side: Side
    reference_price: float
    stop_price: float
    take_profit_price: float | None
    ts_ns: int
    indicators: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExitProposal:
    """Proposta di chiusura totale di una posizione. Sempre approvata (PIANO §6, n. 5)."""

    proposal_id: str
    source: str
    instrument: str
    reason: str
    ts_ns: int


@dataclass(frozen=True, slots=True)
class StopUpdateProposal:
    """Nuovo livello assoluto dello SL di una posizione aperta (trailing). Solo verso il guadagno."""

    proposal_id: str
    source: str
    instrument: str
    new_stop_price: float
    ts_ns: int


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """Evento del calendario (config/events.yaml): blackout sugli strumenti delle valute coinvolte."""

    ts_ns: int
    currencies: frozenset[str]
    name: str


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Specifiche di negoziazione del broker (da ProtoOASymbol), già convertite in unità dello strumento."""

    instrument: str
    base_currency: str
    quote_currency: str
    price_increment: float
    min_volume: int
    step_volume: int
    max_volume: int
    # Distanza minima dello SL dal prezzo, in unità di prezzo (0 se il broker non ne impone una).
    min_stop_distance: float
    # Margine richiesto per unità di nozionale (es. 1/30 con la leva ESMA sulle major).
    margin_rate: float


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Dati di mercato e conversioni per lo strumento della proposta, al momento della decisione."""

    spec: InstrumentSpec
    bid: float
    ask: float
    quote_ts_ns: int
    # Valore nella valuta del conto di un movimento di 1,0 di prezzo per 1 unità (conversione quote→conto).
    value_per_unit: float
    # Nozionale di 1 unità nella valuta del conto (conversione base→conto).
    notional_per_unit: float
    # G_i: quantile dei gap all'apertura delle barre, in unità di prezzo (PIANO §2.3, R1.6).
    gap: float
    events: tuple[NewsEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class OpenPosition:
    """Posizione aperta al broker, con i dati per calcolarne il rischio corretto per i gap."""

    instrument: str
    base_currency: str
    quote_currency: str
    side: Side
    quantity: int
    # Prezzo corrente dal lato di chiusura: bid per un long, ask per uno short.
    mark_price: float
    # None = posizione senza SL al broker (anomalia: rischio infinito, nessun nuovo ingresso).
    stop_price: float | None
    gap: float
    weekend_gap: float
    value_per_unit: float
    opened_ts_ns: int


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Stato del conto e del rischio al momento della decisione.

    CAP_INIZIALE non compare: il sizing usa solo l'equity corrente e il floor (R1.2).
    """

    ts_ns: int
    equity: float
    balance: float
    hwm: float
    floor: float
    # Equity all'inizio del giorno e della settimana di trading (confine alle 17:00 di New York).
    day_start_equity: float
    week_start_equity: float
    margin_used: float
    positions: tuple[OpenPosition, ...]
    state: RiskState
    pause_kind: PauseKind | None = None
    # False dopo una disconnessione, finché non sono passate la riconciliazione e una barra (PIANO §2.3).
    execution_ready: bool = True
    # True in F4 finché un ADR non toglie la rampa: rischio NORMALE limitato a f4_ramp.r_normale.
    ramp_active: bool = False


@dataclass(frozen=True, slots=True)
class Check:
    """Esito di un singolo controllo, scritto nel journal insieme alla decisione.

    Per i controlli sì/no `value` e `limit` valgono 1.0 (vero) o 0.0 (falso).
    """

    name: str
    value: float
    limit: float
    passed: bool


@dataclass(frozen=True, slots=True)
class Decision:
    """Risposta del governor a una proposta.

    - Ingresso: `quantity` approvata, `risk_amount` = quantità × distanza dello SL × valore unitario,
      `stop_distance`/`take_profit_distance` relative da inviare al broker.
    - Uscita: sempre APPROVED, chiude tutta la posizione; `quantity` non è usata.
    - Modifica dello SL: `stop_price` assoluto, arrotondato al tick, da inviare con AmendPositionSLTP.
    """

    proposal_id: str
    kind: DecisionKind
    quantity: int
    risk_amount: float
    checks: tuple[Check, ...]
    reason: str
    stop_distance: float | None = None
    take_profit_distance: float | None = None
    stop_price: float | None = None
