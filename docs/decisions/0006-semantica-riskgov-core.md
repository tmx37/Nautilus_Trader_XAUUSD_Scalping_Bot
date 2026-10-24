# ADR 0006 — Semantica di `riskgov.core` dove il PIANO non la fissa

- **Stato:** accettata (2026-10-24, dall'utente). Implementata in `src/riskgov/core/` con i test delle invarianti. Fissa la semantica, non i **valori**: restano quelli iniziali dell'ADR 0004, da calibrare in F2.
- **Fase:** F0/F1 · **Sostituisce:** — · **Sostituita da:** —
- **Collegati:** ADR 0004 (architettura del gestore del rischio), PIANO §2.3 e §6; `tests/riskgov/`.

## Contesto
Implementando `riskgov.core` sono emersi punti che il PIANO (§2.3) e l'ADR 0004 lasciano aperti o rendono contraddittori. Il più serio è un difetto della macchina a stati come scritta:
- la PAUSA (PERF) scatta con DD ≥ 10%; in PAUSA non si opera, quindi il DD non recupera;
- dopo 10–20 giorni si torna in DIFENSIVO con il DD ancora ≥ 10%, che rifà scattare subito la PAUSA;
- una seconda PAUSA entro 60 giorni porta in ARRESTO.

Quindi una PAUSA per DD finirebbe in ARRESTO automatico ogni volta che le posizioni rimaste aperte non recuperano il DD da sole durante la pausa, cioè nel caso normale. La regola di rientro non avrebbe senso. Inoltre:
- "avviso CUSUM → DIFENSIVO" non ha una soglia in config (c'è solo l'allarme `h_r`);
- non è definito su quale equity si misurano i limiti giornaliero e settimanale;
- dopo un prelievo la formula del floor con E0 fisso porta F sopra l'equity (es. metà conto prelevata → ARRESTO immediato);
- "nessun ingresso dopo le 16:00 UTC di venerdì" non dice fino a quando.

## Opzioni considerate (punto principale: rientro dalla PAUSA)
| Opzione | Pro | Contro |
|---|---|---|
| A. Trigger della PAUSA per DD "a fronte": dopo una PAUSA si riarma solo quando il DD torna sotto `difensivo.enter_dd` | Il rientro funziona come previsto; restano attivi ARRESTO al 15% e CUSUM; un solo booleano persistito | Dopo il rientro si può scendere dal 10% al 15% senza un'altra PAUSA |
| B. Ribasare l'HWM all'uscita dalla PAUSA | Semplice | Azzera il DD, quindi anche la distanza dall'ARRESTO: un sistema in perdita potrebbe perdere un altro 15% |
| C. Soglia di PAUSA relativa al DD al momento del rientro | Fine | Più stato, più casi limite, più difficile da calibrare |

## Decisione
Si adotta **A** e le regole seguenti; ognuna ha un test in `tests/riskgov/`.

**Macchina a stati** (`regime.py`):
1. La PAUSA ha due motivi indipendenti: PERF (si chiude da sola) e OPS (solo con `manual_confirm_ops`). Lo stato è PAUSA finché uno dei due è attivo; nel `pause_kind` OPS prevale. Confermare OPS durante una PAUSA (PERF) riporta in PAUSA (PERF), non in DIFENSIVO.
2. Trigger della PAUSA per DD a fronte (opzione A). Si disarma all'ingresso in qualsiasi PAUSA (PERF) e si riarma con DD < `difensivo.enter_dd`.
3. CUSUM sugli R dei trade reali chiusi in NORMALE o DIFENSIVO: `S = max(0, S + k − R)`. Nuova chiave `regime.cusum.w_r` (valore iniziale 4,0, con 0 < w_r < h_r): S > w_r → DIFENSIVO; S > h_r → PAUSA (PERF). S si azzera all'ingresso in PAUSA.
4. Da DIFENSIVO a NORMALE servono: DD ≤ `exit_dd`, almeno `min_trades` trade in DIFENSIVO **e** S ≤ w_r. Senza l'ultima condizione l'avviso CUSUM riporterebbe subito in DIFENSIVO.
5. Il limite settimanale "toccato" che porta in DIFENSIVO è: perdita dall'inizio settimana (realizzata + latente) ≥ `limits.weekly.NORMALE`.
6. I giorni di PAUSA (`min_days`, `max_days`) sono giorni di borsa, contati dalle chiusure delle 17:00 di New York. La finestra della seconda PAUSA (`repeat_pausa_days`) è in giorni di calendario, fra un ingresso in PAUSA e l'altro.
7. I trade reali che si chiudono durante una PAUSA (aperti prima) non contano né per il CUSUM né per il rientro: per il rientro contano solo i trade ombra.
8. Dopo ogni PAUSA il livello è DIFENSIVO con il conteggio dei trade azzerato: da PAUSA a NORMALE non si passa mai in un solo evento.
9. Lo stato è un `RegimeState` immutabile, serializzabile in JSON senza perdite. Le transizioni (con il motivo) si leggono con `pop_transitions()` per il journal.

**Riferimenti di equity** (`floor.py`):

10. Un prelievo riscala E0, HWM ed F per lo stesso fattore `E_dopo/E_prima`: DD ed E/F restano invariati.
11. Lo sblocco dall'ARRESTO ribasa HWM all'equity corrente e mantiene F. Se E ≤ F lo sblocco è impossibile: il capitale sotto il floor non si rischia più, e ripartire richiede un ADR con nuovi parametri.

**Decisione sugli ingressi** (`governor.py`, `limits.py`, `sizing.py`):

12. Il core calcola tutti i rischi dai fatti grezzi (quantità, prezzi, SL, gap, conversioni FX): l'integrazione non passa mai un rischio già calcolato.
13. La distanza dello SL è relativa al prezzo eseguibile (ask per un long, bid per uno short) e arrotondata al tick. È quella che l'adapter invia ed è quella usata per il sizing. Lo SL deve stare ad almeno `max(1 tick, distanza minima del broker)` dal prezzo di chiusura (bid per un long, ask per uno short). I confronti si fanno in tick interi.
14. Tutti i limiti sono vincoli lineari sulla quantità q (`usato + q·consumo_unitario ≤ limite`):
    - rischio per stato e CPPI sono misurati in R (distanza dello SL);
    - heat, giornaliero, settimanale e per valuta sono misurati sul rischio corretto per i gap;
    - il margine è misurato sul nozionale × aliquota di margine.

    q è il minimo dei massimi, arrotondato per difetto al passo; una verifica finale con lo stesso prodotto toglie l'errore di virgola mobile.
15. I limiti giornaliero e settimanale sono frazioni dell'equity **d'inizio periodo** (soglia fissa per il periodo); gli altri sono frazioni dell'equity corrente.
16. Rischio netto per valuta: con segno (un long è lungo la base e corto la quotata). Se l'esposizione supera già il cap (posizione estranea) sono ammessi solo trade che la riducono.
17. Blocco del weekend: da venerdì 16:00 UTC a lunedì 00:00 UTC. Copre anche la riapertura della domenica sera, quando gli spread sono più larghi.
18. Rampa di F4: con `ramp_active` il rischio di **ogni** stato è `min(r_stato, f4_ramp.r_normale)`, così uno stato peggiore non dà mai più rischio. Toglierla è un cambio di config, quindi un ADR, ammesso solo dopo almeno `f4_ramp.trades` trade.
19. REDUCED = quantità approvata inferiore a quella data dal solo rischio per stato. Una decisione rifiutata per quantità mostra nel journal i controlli valutati al volume minimo.
20. Fail-closed asimmetrico:
    - ingresso con input non validi (NaN, infiniti, negativi, tasso FX mancante, specifiche di volume incoerenti) → rifiuto;
    - uscita → sempre approvata;
    - modifica dello SL non valida o non monotona → rifiuto (resta lo SL attuale);
    - una posizione senza SL ha rischio infinito e blocca ogni ingresso.

## Motivazione
- A è l'unica opzione che rende utilizzabile la regola di rientro del PIANO senza togliere protezione: l'ARRESTO al 15% resta fisso rispetto allo stesso HWM. B lo sposterebbe in basso, C aggiungerebbe complessità da calibrare senza un beneficio chiaro.
- I punti 10–11 evitano due ARRESTI spuri (prelievo, sblocco) e mantengono la promessa del floor: non scende mai.
- I punti 12–14 rendono le invarianti del PIANO §6 verificabili in modo esatto: i test basati su proprietà controllano i limiti con le stesse grandezze che il governor usa.

## Conseguenze
- `config/risk.example.yaml` e `riskgov.core.config` hanno la chiave `regime.cusum.w_r`. Lo schema in PIANO §2.3 è aggiornato.
- Firme cambiate rispetto agli stub di F0:
  - `decide(proposal, snapshot, market, cfg)`;
  - nuovi `decide_exit` e `decide_stop_update`;
  - `rescale_on_withdrawal(marks, …)`;
  - `RiskStateMachine(cfg, RegimeState)`.

  `AccountSnapshot` contiene le posizioni (`OpenPosition`) al posto dei totali precalcolati.
- Il governor Nautilus (F1) dovrà chiamare:
  - `on_equity` a ogni aggiornamento;
  - `on_day_close` + `floor.on_daily_close` alle 17:00 di New York;
  - `on_trade_closed` per i trade reali e per quelli ombra;
  - `weekend_closures` il venerdì prima del blocco.
- Restano da fare in F1: `reconcile.classify` (dipende dai report reali di cTrader) e il journal.
- Rischio residuo del punto 2: dopo una PAUSA per DD il sistema può operare (a rischio DIFENSIVO) fra il 10% e il 15% di DD. È voluto, ma va considerato nella calibrazione Monte Carlo di F2.

## Prove
- `tests/riskgov/test_regime.py::test_dd_trigger_rearms_only_below_difensivo` mostra il difetto evitato.
- `tests/riskgov/test_floor.py::test_large_withdrawal_without_rescaling_e0_would_kill` mostra l'ARRESTO spurio evitato dal punto 10.
- `uv run pytest tests/riskgov`: le 18 invarianti del PIANO §6 sono coperte da test basati su proprietà.

## Condizioni di revisione
- La calibrazione Monte Carlo di F2 mostra che il punto 2 lascia troppo spazio fra PAUSA e ARRESTO.
- I report reali di cTrader (F1) mostrano che una delle grandezze del punto 12 non è disponibile o non è affidabile.
- La distanza minima dello SL di cTrader risulta misurata da un prezzo diverso da quello di chiusura [DA VERIFICARE in F1].

## Scartato
- B: ribasare l'HWM all'uscita dalla PAUSA sposta in basso la soglia di ARRESTO.
- C: soglia di PAUSA relativa al rientro; complessità senza beneficio dimostrato.
- Avviso CUSUM fissato a h/2 nel codice: un parametro nascosto è peggio di una chiave di config validata.
