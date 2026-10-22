# legacy/ — codice XAUUSD archiviato (solo riferimento)

Archiviato il 2026-10-22 con l'[ADR 0003](../docs/decisions/0003-archiviazione-legacy-xauusd.md). **Non è codice attivo**: non viene corretto, testato né portato alla v2 di NautilusTrader. Ipotesi registrata come **EXP-0000, verdetto SCARTATO** in `experiments/registry.jsonl`.

## Contenuto

| Percorso | Cosa è |
|---|---|
| `old_mt5_test_data/XAUUSD_EMA_EA.mq5` | EA MT5 V1: EMA 20/50, SL = ATR(14)×1,5, TP = 2R, rischio 1% |
| `old_mt5_test_data/XAUUSD_EMA_EA_V2.mq5` | EA MT5 V2: aggiunge Min_ATR, sessione 08–20 ora server, filtro spread, filtro EMA200 M15, SL + spread, break-even a 1R; rischio 0,5% |
| `old_mt5_test_data/ReportOptimizer-62115380.xml` | Ottimizzazione MT5 (SpreadsheetML), XAUUSD M15 2024, 148 passaggi |
| `old_mt5_test_data/ForwardResultsOutput-62115380.xml` | Tab forward della stessa ottimizzazione |
| `old_mt5_test_data/TesterOptgraphReport2026.04.15.png` | Grafico dell'ottimizzazione ("Balance max") |
| `backtest.py` | Backtest Nautilus v1: **non** implementa la strategia dell'EA |
| `nautilus_xau_strategy.py.py` | Port più vicino all'EA (la doppia estensione è il nome reale) |
| `_strategy.py` | Prima bozza, mai funzionante |
| `data/XAUUSD_M10_202306200550_202312292320.csv` | 18.945 barre M10 da MT5 (TSV, ora server UTC+2/+3, colonna spread in punti da 0,01) |

## Evidenza (perché SCARTATO)

Ottimizzazione genetica su EMA_Fast 15–25, EMA_Slow 40–80, ATR_Multiplier 1,2–2,0, Min_ATR 0,3–0,8 (server PepperstoneUK-Demo, $1000, 1:100):
- correlazione di rango fra in-sample e forward: **−0,47**;
- PF > 1: 58/148 in-sample, 8/148 in forward, **0 in entrambi**;
- i 10 migliori in-sample perdono tutti in forward; il miglior forward ha PF 1,08.

Nota: il demo usato era dell'entità **UK** di Pepperstone, non EU.

## Bug noti (per chi legge il codice)

`nautilus_xau_strategy.py.py`:
- `Currency` usato ma non importato; `sys` importato solo dentro `__main__`.
- Indicatori registrati con `register_indicator_for_bars` **e** aggiornati a mano con `update_raw`: ogni barra conta due volte (e gli aggiornamenti manuali stanno dietro al filtro di sessione).
- `MarketOrder(...)` costruito senza `trader_id`, `client_order_id`, ecc. → `TypeError`; inoltre `_enter_long`/`_enter_short` inviano un ordine a mercato **e** un bracket (due ingressi per segnale).
- `atr.update_raw(bar)` ha la firma sbagliata (vuole high, low, close).
- `prev_value` e `price_increment_value` non esistono in Nautilus.
- Import misti fra layout vecchio e nuovo degli indicatori.
- `on_position_update` (break-even) è uno stub.
- Arrotondamento `max(min_qty, qty)`: stesso sovra-rischio dell'EA.

`backtest.py`:
- Entra su uno stato (`fast − slow > 0,20`), non su un incrocio; rientra subito dopo ogni SL/TP.
- `trade_size=0.1` su un `CurrencyPair` XAU vale 0,1 oz, non 0,1 lotti MT5 (10 oz): P&L circa 100 volte più piccolo.
- Barre etichettate `1-MINUTE` ma i dati sono M10: il `BarType` deve coincidere con quello della config, altrimenti la strategia non riceve barre.

Entrambi:
- Barre `LAST` mentre MT5 esporta barre BID; spread ignorato; nessun modello di fill né di commissioni realistico.
- Ora server trattata come UTC (sfasamento di 2–3 ore, ora legale ignorata).

EA V2 (`XAUUSD_EMA_EA_V2.mq5`, riga 178): `lots = MathMax(minLot, MathMin(maxLot, lots));` arrotonda per eccesso al lotto minimo → con conti piccoli rischia più della percentuale dichiarata. Il nuovo `riskgov` **rifiuta** invece il trade.

## Come eseguirli (sconsigliato)

Usano API Nautilus v1 (`TradingNode`, Cython): non girano con l'ambiente del progetto (v2, ADR 0002). Servirebbe un venv separato con `nautilus_trader==1.231.0`, e anche così falliscono per i bug sopra.
