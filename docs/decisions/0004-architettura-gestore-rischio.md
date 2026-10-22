# ADR 0004 — Architettura del gestore del rischio (`riskgov`)

- **Stato:** proposta (2026-10-22). Struttura accettabile da subito; **i valori delle soglie vanno calibrati con il Monte Carlo in F2** e congelati in un nuovo ADR prima di F3.
- **Fase:** F0 · **Sostituisce:** — · **Sostituita da:** —
- **Collegati:** PIANO §2.1–§2.3, §6; `config/risk.example.yaml`; ADR 0002.

## Contesto
- R1.5: il gestore del rischio è un componente separato dalla strategia e ha sempre l'ultima parola.
- R1.3: servono più livelli di difesa indipendenti (per trade, giorno e settimana, drawdown totale, esposizione).
- R1.4: macchina a stati NORMALE → DIFENSIVO → PAUSA → ARRESTO con isteresi; valutare un floor a cricchetto.
- In NautilusTrader v2 (verificato sulla documentazione corrente):
  - gli Actor "do not manage orders": non possono inviare ordini;
  - `publish_message(topic, obj)` e `subscribe_topic(...)` passano oggetti Python nello stesso processo, in modo sincrono;
  - il RiskEngine è in Rust, controlla precisione, quantità, `max_notional_per_order`, frequenza degli invii e stato di trading, ma **non** equity né drawdown;
  - `TradingState`: REDUCING nega liste di ordini e modifiche; HALTED nega anche le chiusure reduce-only.
- Il legacy MT5 arrotondava la dimensione per eccesso al lotto minimo (ADR 0003): errore da escludere per costruzione.

## Opzioni considerate
| Opzione | Pro | Contro |
|---|---|---|
| A. Segnali come Actor che pubblicano `TradeProposal`; un solo `RiskGovernor(Strategy)` possiede tutti gli ordini | Garanzia strutturale (gli Actor non hanno API d'ordine); limiti di portafoglio in un solo punto; stesso codice in backtest e live | Più messaggi; comportamento di `publish_message` in backtest da provare con un test [DA VERIFICARE] |
| B. Classe base di Strategy che avvolge `submit_order` con un controllo | Semplice | Aggirabile da ogni sottoclasse; i limiti di portafoglio richiedono comunque uno stato condiviso; non è un componente separato |
| C. Solo RiskEngine di Nautilus | Già pronto | Non estendibile da Python in v2; non conosce equity, drawdown né stati |

## Decisione
Opzione **A**, con il RiskEngine di Nautilus come ulteriore livello (backstop):
- `riskgov.core`: logica **pura** e deterministica, senza import di `nautilus_trader` (contratto `import-linter`). Contiene tipi, sizing, floor, macchina a stati, limiti e politica di riconciliazione.
- `riskgov.nautilus.RiskGovernor`: unica Strategy del nodo. Riceve le proposte, chiama `riskgov.core`, scrive il journal **prima** dell'invio, invia bracket con SL obbligatorio.
- Livelli indipendenti: governor; guardia dell'adapter (rifiuta ingressi senza SL); RiskEngine (`max_notional_per_order` circa 8×equity, limite di frequenza, `bypass=False`); SL lato broker; watchdog in un processo e su un host separati.
- Sizing: `budget = min(r_stato·E, m·(E − F), spazio residuo sotto i limiti)`; quantità arrotondata **per difetto**; sotto il minimo → **rifiuto**.
- Floor a cricchetto: `F = max(F_prec, E0·(1−K) + λ·(HWM − E0))`; con K ≥ D_kill e λ ≤ 1 − D_kill il kill switch scatta sempre prima del floor.
- Mappatura su Nautilus: NORMALE, DIFENSIVO e PAUSA restano `ACTIVE` (il governor blocca gli ingressi); ARRESTO = `REDUCING` → chiusura reduce-only → `HALTED`.

Valori iniziali (da calibrare): rischio per trade 1,0% / 0,5% / 0 / 0; DD dal massimo di equity di chiusura giornaliera 6% → DIFENSIVO (uscita al 3%), 10% → PAUSA, 15% → ARRESTO; K = 0,20, λ = 0,5, m = 0,05; limiti giornalieri 2% / 1%, settimanali 4% / 2%; heat cap 2% / 1%; margine usato ≤ 20%. Tabella completa in PIANO §2.3.

## Motivazione
- A è l'unica opzione in cui la regola "la strategia propone, il gestore decide" è imposta dalla struttura e non da una convenzione.
- Un core puro permette test basati su proprietà (PIANO §6, 18 invarianti) e un Monte Carlo che usa **lo stesso** codice delle decisioni reali.
- Il floor dà una cosa che il solo kill switch non dà: oltre un certo profitto (HWM ≥ 1,4·E0 con questi valori) il capitale iniziale non è più rischiabile, e il rischio cala in modo continuo man mano che il cuscino si assottiglia.

## Conseguenze
- La config del nodo deve contenere esattamente una Strategy (test di CI).
- I limiti giornalieri e settimanali sono calcolati sulla **perdita impegnata** (realizzata + rischio aperto corretto per i gap + nuovo trade), non sul solo realizzato.
- Il modo in cui una Strategy imposta `TradingState` in v2 è [DA VERIFICARE]; ripiego: il governor smette di inviare e la guardia dell'adapter resta attiva.
- Il watchdog va provato sul demo con due sessioni contemporanee sullo stesso conto [DA VERIFICARE].

## Prove
- https://nautilustrader.io/docs/latest/concepts/actors
- https://nautilustrader.io/docs/latest/concepts/message_bus
- https://nautilustrader.io/docs/latest/concepts/execution
- `legacy/old_mt5_test_data/XAUUSD_EMA_EA_V2.mq5` riga 178 (arrotondamento per eccesso da evitare).
- Calibrazione: EXP di F2 ancora da pre-registrare.

## Condizioni di revisione
- Dopo la calibrazione Monte Carlo di F2 → nuovo ADR con i valori congelati.
- Se un test mostra che `publish_message` si comporta diversamente in backtest e in live → rivedere il trasporto delle proposte.

## Scartato
- B: aggirabile.
- C da solo: non copre equity, drawdown né stati.
