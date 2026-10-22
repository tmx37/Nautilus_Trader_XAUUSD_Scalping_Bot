# Piano di progetto — sistema di trading Pepperstone EU / cTrader Open API su NautilusTrader

> Versione 1 · 2026-10-22 · Le assunzioni non verificate sono marcate [DA VERIFICARE]. Le decisioni vivono in `docs/decisions/`; lo stato corrente in `HANDOFF.md`.

> Il piano non assume alcun rendimento. L'esito più probabile di un progetto retail di questo tipo è che le ipotesi vengano scartate: il 74,1% dei conti CFD retail di Pepperstone EU perde denaro. Il valore del sistema sta nello scoprirlo presto, in modo economico e senza perdere più di quanto stabilito.

## 1. Verifica di fattibilità

**Verdetto: fattibile tecnicamente, con un rischio principale di prodotto (l'assenza di vantaggio) e tre rischi tecnici seri:**
- la v2 di Nautilus è ancora RC;
- lo SL non è garantito;
- l'adapter va scritto da zero.

| # | Rischio | Prob./Impatto | Mitigazione |
|---|---|---|---|
| T1 | Open API non abilitata sul conto Pepperstone EU (`CHANNEL_IS_BLOCKED`), oppure approvazione dell'app lenta | M/A | Verificarlo nella **prima settimana di F0** con un conto demo e il supporto. Ripiego: pacchetto `MetaTrader5`, solo Windows o Wine (`mt5linux`), con un nuovo ADR. |
| T2 | Nautilus v2 è RC; l'API cambia fra una rc e l'altra; la v1 è congelata | A/M | Versione fissata **esatta**. Logica di protocollo in `ctrader_async`, senza Nautilus; adapter sottile. Gate F4: serve una 2.0.0 stabile, oppure un ADR che accetti esplicitamente la RC. |
| T3 | L'adapter Python in v2 non ha cache Redis/Postgres, quindi al riavvio lo stato va ricostruito | A/A | Mass status completo dal broker (Reconcile, DealList, `avg_px_open`). Il journal locale conserva l'intento (SL voluto, id della proposta). Riavvii testati in F1. |
| T4 | Gli ordini MARKET vogliono lo SL **relativo**; mettere lo SL dopo il fill lascia la posizione scoperta | A/A | Lo SL è sempre relativo e parte con l'ordine. Verifica via Reconcile entro 10 s dal fill. La dimensione si calcola sulla distanza **arrotondata** inviata. L'adapter rifiuta ingressi senza SL. |
| T5 | SL non garantito: gap del weekend o delle notizie oltre lo stop | A/M | Heat corretta per i gap (§2.3), blackout notizie, niente coppie CHF, regole sul weekend. |
| T6 | Rotazione del token OAuth: il refresh invalida la coppia, rischio di restare chiusi fuori | M/A | Scrittura atomica; un solo processo rinnova ciascuna coppia; token o app separati per il watchdog [DA VERIFICARE]. |
| T7 | Storico cTrader limitato (tick 1 settimana per richiesta, barre circa 14k con troncamento silenzioso [DA VERIFICARE], 5 req/s) | A/B | Lo storico lungo viene da Dukascopy; cTrader serve per i controlli incrociati; il registratore di tick è attivo dal giorno 1 di F1. |
| T8 | I dati Dukascopy differiscono da Pepperstone (spread, tick) | A/M | Spread calibrato per ora del giorno sui tick Pepperstone registrati; test di parità in F3. |
| T9 | Backtest a barre ottimista (niente fill all'apertura della barra successiva, SL e TP nella stessa barra risolti con un'euristica) | M/M | Esecuzione su dati M1 bid/ask, o QuoteTick, con segnali su barre aggregate; costi ×1,5 come stress test. |
| T10 | Swap: il modulo FX di Nautilus triplica mercoledì **e** venerdì; la convenzione di Pepperstone è diversa [DA VERIFICARE] | M/M | `SimulationModule` scritto da noi con i `swapLong/Short` registrati ogni giorno dal demo. |
| T11 | Commissione in USD su conto in EUR | A/B | Conversione FX nel modello di costi. |
| T12 | Granularità: 0,01 lot con €1k di capitale | A/M | Tabella in §3. Con meno di circa €2k lo stato DIFENSIVO di S1 coincide di fatto con PAUSA. Raccomandato CAP_INIZIALE ≥ €2k. |
| T13 | Sovra-ottimizzazione (l'evidenza legacy: −0,47) | A/A | Pre-registrazione, conteggio dei tentativi, DSR, lockbox, limite di 3 iterazioni per ipotesi. |
| T14 | Il demo non dimostra il vantaggio (troppi pochi trade); i fill in demo possono essere migliori di quelli reali [DA VERIFICARE] | A/M | Il demo serve per la **parità di esecuzione**; il vantaggio va provato sullo storico più il lockbox. F4 parte con rischio dimezzato. |
| T15 | Due sessioni sullo stesso conto (nodo e watchdog): comportamento non documentato | M/M | Test sul demo in F1 prima di adottare il watchdog con azioni di scrittura. |
| T16 | Aspetti regolatori e fiscali (contratto con l'entità EU, onboarding di residenti italiani, regime dichiarativo con broker estero) | M/M | [DA VERIFICARE]: contratto e commercialista prima di F4. |

## 2. Architettura

### 2.1 Componenti

```
  ┌───────────── processo principale: LiveNode (live) / BacktestEngine (test) — stesso codice strategia+rischio ──────────────┐
  │                                                                                                                       │
  │  tradingsys.signals (Actor)          riskgov.nautilus.RiskGovernor (UNICA Strategy)        nt_ctrader (adapter)       │
  │  S1 Donchian/ATR H4, S2 ORB  ──TradeProposal──►  core puro: sizing, regime,     ──bracket──►  ExecutionClient ──┐     │
  │  (non possono inviare ordini)   publish_message   limiti, floor, riconciliazione  (SL obbl.)  guardia: no SL=deny │     │
  │        ▲  barre/quote                   │  journal JSONL (prima dell'invio)                   DataClient ◄──┐     │     │
  │        └────────── Cache/MessageBus ◄───┴──── Nautilus RiskEngine (backstop: notional, rate) ◄─InstrumentProv│     │     │
  │                                                                                                             │     │     │
  │  tradingsys.datapipe: TickRecorder (Actor) ──► ParquetDataCatalog ◄── import Dukascopy (offline)             │     │     │
  │  tradingsys.reporting: metriche → report JSON → experiments/                                    ctrader_async (asyncio)│
  └─────────────────────────────────────────────────────────────────────────────────────────────────── TLS/protobuf, auth,─┘
                                                                                                     heartbeat, rate limit
                                                                                                             │
  watchdog (processo + host separati, sessione cTrader propria, usa ctrader_async)  ◄──── Reconcile 60 s ────┤
  → alert (Telegram/healthchecks) · SL d'emergenza se manca ≥120 s · chiusura totale se DD ≥ 20%    cTrader Open API (demo/live)
                                                                                                    → Pepperstone: SL lato server
```

| Componente | Responsabilità | Dipende da |
|---|---|---|
| `ctrader_async` | TLS, framing, heartbeat ogni 10 s, timeout di inattività in ingresso (45 s), correlazione `clientMsgId`, token bucket 50/5 req/s, riconnessione con backoff e jitter, auth app/account, refresh del token atomico, conversioni di unità | protobuf (nessun Nautilus) |
| `nt_ctrader` | `InstrumentProvider` (ProtoOASymbol → CurrencyPair con le specifiche del broker), `MarketDataClient` (spot → QuoteTick, trendbar), `ExecutionClient` (**traduce il bracket Nautilus in un `ProtoOANewOrderReq` unico con SL/TP relativi**; modifica dello SL figlio → `AmendPositionSLTP`; eventi sintetici per i figli; mass status per la riconciliazione; OMS HEDGING con `venue_position_id`) | nautilus_trader v2, ctrader_async |
| `riskgov.core` | Logica pura e deterministica: sizing, macchina a stati, floor, limiti, politica di riconciliazione | stdlib, numpy |
| `riskgov.nautilus` | `RiskGovernor(Strategy)`, **l'unico componente che può inviare ordini**; snapshot di stato persistito in modo atomico; `ARRESTO.lock`; journal | riskgov.core, nautilus |
| `tradingsys.signals` | Actor S1 e S2 che pubblicano `TradeProposal`, `ExitProposal` e `StopUpdateProposal` | nautilus |
| `tradingsys.datapipe` | Import Dukascopy → catalog, manifest sha256, controlli di qualità, TickRecorder | nautilus |
| `tradingsys.research` | Esecutore del backtest, walk-forward, baseline, Monte Carlo, DSR, verdetto | reporting |
| `tradingsys.reporting` | Metriche su trade ed equity (stesso codice per backtest, demo e reale), report JSON con schema versionato | numpy |
| `tradingsys.watchdog` | Monitor indipendente (§2.3) | ctrader_async, **non** Nautilus |
| `tradingsys.cli` | `riskctl` (status, unlock), `exp` (prereg, esecuzione, verdetto) | — |

**Decisione: versione di Nautilus (ADR 0002).**

| | v1 1.231.0 | v2 2.0.0rc7 (scelta) |
|---|---|---|
| Pro | Stabile; l'adapter comunitario è già scritto per la v1 | È il futuro (la documentazione `latest` descrive la v2); Python Adapter Interface supportata; `CfdSwapModule`, `publish_message` |
| Contro | Congelata, solo patch di sicurezza per circa 3 mesi; ogni adapter scritto ora andrà portato | RC "non per live"; API mobile; niente Redis/Postgres per gli adapter Python |

Motivazione: il live reale (F4) è lontano 6 mesi o più, e scrivere per la v1 vuol dire riscrivere. Fissiamo `==2.0.0rc7`, aggiorniamo solo con un ADR e chiediamo una 2.0.0 stabile prima di F4.

**Decisione: come garantire che il gestore del rischio abbia l'ultima parola (ADR 0004).**

| Opzione | Pro | Contro |
|---|---|---|
| (a) I segnali sono Actor (non possono gestire ordini) e passano proposte al `RiskGovernor`, unica Strategy **(scelta)** | Garanzia **strutturale**: gli Actor non hanno API d'ordine; limiti di portafoglio in un solo punto | Più messaggi; va provato che `publish_message` si comporti allo stesso modo in backtest [DA VERIFICARE con test] |
| (b) Classe base di Strategy che avvolge `submit_order` | Semplice | Aggirabile da qualsiasi sottoclasse; non è un componente separato |
| (c) Solo il RiskEngine di Nautilus | Già pronto | In v2 è in Rust e non si estende da Python; non conosce equity né drawdown |

Il RiskEngine resta come backstop: `max_notional_per_order` circa 8×equity, limite di frequenza degli invii, `bypass=False`. Un test di CI verifica che la config del nodo contenga **esattamente una** Strategy.

### 2.2 Livelli di difesa indipendenti (R1.3)

1. **Governor**:
   - rischio per trade;
   - limiti giornalieri e settimanali;
   - heat;
   - margine;
   - numero di posizioni;
   - macchina a stati;
   - floor.
2. **Guardia dell'adapter**: rifiuta (fail-closed) qualsiasi ordine di ingresso non reduce-only senza SL; verifica lo SL lato broker dopo il fill.
3. **RiskEngine di Nautilus**: notional massimo per ordine e limiti di frequenza.
4. **Broker**: SL lato server inviato con l'ordine.
5. **Watchdog**: processo e host separati.
6. Ultima istanza, che **non è** un elemento di progetto: lo stop-out ESMA al 50% e la protezione dal saldo negativo.

### 2.3 Gestore del rischio (R1)

**Definizioni.**
- E = equity mark-to-market.
- HWM = massimo storico dell'**equity di chiusura giornaliera**: evita di scattare sui ritracciamenti intraday del trend, ma resta una misura di "massimo di equity".
- DD = 1 − E/HWM.
- Il giorno di trading si chiude alle 17:00 di New York.

**Sizing (R1.2).**
- `budget = min(r_stato·E, m·(E − F), spazio residuo sotto i limiti giornaliero, settimanale e di heat)`.
- `q = floor_step(budget / (distanza_stop_arrotondata × valore_unitario_EUR))`.
- **Se q < volume minimo il trade viene RIFIUTATO e la decisione finisce nel journal**: mai arrotondare per eccesso.
- CAP_INIZIALE non compare mai nel sizing: esiste solo come E0 per il floor.

**Floor a cricchetto (stile CPPI).**
- `F = max(F_prec, E0·(1−K) + λ·(HWM − E0))`, con K = 0,20, λ = 0,5, m = 0,05.
- All'inizio m·K = 1% = r_NORMALE, quindi non c'è uno scalino.
- Con K ≥ D_kill e λ ≤ 1 − D_kill il kill switch scatta **sempre prima** del floor: il floor si sfonda solo con un gap.
- Il floor non è ridondante:
  - con HWM = 1,4·E0 si ha F = E0, cioè il capitale iniziale diventa non più rischiabile;
  - riduce il rischio in modo continuo man mano che il cuscino si assottiglia.
- F non scende mai, nemmeno dopo uno sblocco manuale.

**Macchina a stati.** I valori sono iniziali: vengono **calibrati con il Monte Carlo in F2 e congelati in un ADR prima di F3**.

| Stato | Si entra se (basta una condizione) | Rischio/trade | Heat max (corretta per i gap) | Max posizioni | Si esce |
|---|---|---|---|---|---|
| NORMALE | default | 1,0% (in F4 si parte da 0,5%) | 2,0% | 3 | — |
| DIFENSIVO | DD ≥ 6%; limite settimanale toccato; avviso CUSUM | 0,5% | 1,0% | 2 | → NORMALE se DD ≤ 3% **e** almeno 5 trade in DIFENSIVO (automatico; isteresi 6→3) |
| PAUSA (PERF) | DD ≥ 10%; allarme CUSUM | 0 (solo gestione delle posizioni aperte) | — | — | → DIFENSIVO (**mai** direttamente a NORMALE) dopo ≥ 10 giorni di borsa con ΣR ≥ 0 su almeno 8 trade ombra, oppure dopo 20 giorni |
| PAUSA (OPS) | anomalia di riconciliazione o di esecuzione; deposito rilevato | 0 | — | — | solo con conferma manuale |
| ARRESTO | DD ≥ 15%; E ≤ F; 2ª PAUSA (PERF) entro 60 giorni; stop-out del broker (`isServerEvent`); posizione senza SL non correggibile | chiusura totale | 0 | 0 | solo manuale (`riskctl unlock` più ADR di revisione) → PAUSA (OPS); HWM ribasato, F **mantenuto** |

Perché queste soglie:
- Con un rischio dell'1% e un win rate tipico del trend following intorno al 35%, una serie di circa 10 perdite consecutive è normale: è circa 1,3% di probabilità per sequenza, quindi probabile su 150 trade.
- Il 6% fa entrare in DIFENSIVO dopo circa 6R.
- L'ARRESTO al 15% (circa 20R con il rischio dimezzato) è raggiungibile da un sistema senza vantaggio in tempi ragionevoli, ma raramente da uno con vantaggio.
- Calibrazione: si fa un bootstrap a blocchi settimanali di 10.000 percorsi annuali, passati nello **stesso** `riskgov.core`, sulla distribuzione R dell'OOS **con aspettativa tagliata del 50%**. Obiettivi:
  - P(ARRESTO in 12 mesi) ≤ 10% sulla distribuzione tagliata;
  - P(ARRESTO in 12 mesi) ≥ 50% sotto l'ipotesi nulla (media = −costi).
- I soli DD sono lenti a riconoscere un sistema senza vantaggio, quindi si aggiunge un **CUSUM sugli R**: `S = max(0, S + k − R)`, allarme quando S > h.

**Limiti giornalieri e settimanali (R1.3b).**
- Sono **soglie d'ingresso** calcolate sulla **perdita impegnata**: (E_inizio_periodo − E) + Σ rischio aperto corretto per i gap + rischio del nuovo trade.
- Limiti: giorno 2% (NORMALE) / 1% (DIFENSIVO); settimana 4% / 2%.
- Il limite giornaliero è ≥ della heat cap, altrimenti a inizio giornata non si potrebbe entrare.

**Esposizione (R1.3d).**
- Margine usato ≤ 20% dell'equity (livello di margine ≥ 500%, contro lo stop-out al 50%).
- Una posizione per strumento; rischio netto per valuta ≤ 1,5%.
- **Nessuna aggiunta di posizione, nessuna mediazione, nessuna griglia, nessuna martingala**: la dimensione dipende solo da E, F, stato e distanza dello stop, e una perdita non può mai farla crescere (è un'invariante testata).
- Gli unici ordini di ingresso ammessi sono a mercato. Ogni ordine pendente sul conto è quindi estraneo.

**Gap e notizie (R1.6).**
- Rischio per posizione = q·(|P − SL| + G_i), dove G_i è il quantile 99,5% dei gap storici all'apertura delle barre dello strumento (con un quantile separato per il weekend).
- Nessun ingresso dopo le 16:00 UTC di venerdì.
- S2 chiude sempre entro fine sessione.
- S1 tiene posizioni nel weekend solo se la heat del weekend corretta per i gap è ≤ 1,5%; altrimenti chiude dalla posizione più recente.
- Nessuna coppia CHF.
- `config/events.yaml` è versionato e costruito da fonti ufficiali: BLS ICS (NFP, CPI), FOMC, BCE, BoE, RBA, BoJ. Blackout di ±30 minuti sulle coppie della valuta coinvolta, applicato **anche nei backtest**.

**Riconciliazione (R1.6).** Il broker è la fonte di verità per lo stato; il journal lo è per l'intento.

| Caso | Azione | Stato |
|---|---|---|
| Posizione nota con SL | Riprendere; se lo SL è più largo di quello voluto, riportarlo al valore voluto | invariato (OPS se la modifica fallisce) |
| Posizione nota senza SL | Rimettere lo SL voluto; se il prezzo lo ha già superato, chiudere | PAUSA (OPS) |
| Posizione sconosciuta (senza il nostro prefisso nella `label`) | Mettere uno SL a rischio ≤ r_N·E se manca; contarla nella heat; non chiuderla se lo SL si può mettere | PAUSA (OPS) |
| Ordine locale assente dal broker | Cercare nei deal per `clientOrderId`; se è stato eseguito, trattarlo come posizione nota; altrimenti segnarlo fallito. **Mai reinviarlo** | invariato; da 3 casi in 24 h → OPS |
| Ordine pendente al broker non noto localmente | Cancellarlo (è estraneo) | PAUSA (OPS) |
| Stop-out o differenza di quantità | Adottare il valore del broker | ARRESTO se `isServerEvent` |
| Equity del broker diversa da quella locale oltre lo 0,5% | Fidarsi del broker | PAUSA (OPS) |

Altre regole:
- Dopo una disconnessione, ingressi bloccati fino alla riconciliazione più una barra.
- Quote più vecchie di 30 s: ingressi bloccati.
- Modifica dello SL rifiutata: 3 tentativi, poi chiusura.
- Ordine rifiutato: viene scritto nel journal e non si ritenta in automatico (il segnale nel frattempo è vecchio).

**Ciclo dello stato di trading in Nautilus.**
- NORMALE, DIFENSIVO e PAUSA restano in `ACTIVE`: è il governor a bloccare gli ingressi, e i trailing stop hanno bisogno delle modifiche.
- ARRESTO: `REDUCING` → chiusura con ordini reduce-only → `HALTED` quando si è flat.
- Il modo in cui una Strategy imposta lo stato in v2 è [DA VERIFICARE]. Ripiego: il governor non invia più nulla e la guardia dell'adapter resta attiva.

**Prelievi (ammessi) e depositi (vietati da R1.1).**
- Un evento `DEPOSIT_WITHDRAW` con importo positivo → PAUSA (OPS) e ADR obbligatorio.
- Un prelievo riscala HWM ed F in proporzione, così non viene scambiato per drawdown.
- Non esiste alcuna funzione che chieda, suggerisca o presupponga un versamento.

**Watchdog (minimale, per €1–5k).**
- Fase 1, obbligatoria prima di F3: Reconcile ogni 60 s; healthchecks.io; avviso su Telegram se una posizione non ha SL o manca l'heartbeat del nodo.
- Fase 2, obbligatoria prima di F4: un'unica azione di scrittura. Se una posizione è senza SL da 120 s o più, mette uno SL d'emergenza con rischio ≤ 2%. Non modifica mai uno SL esistente e non apre mai nulla.
- Fase 3: chiusura totale se DD ≥ 20%. La soglia è volutamente più larga del 15% del nodo, così le due logiche non si contendono la posizione.
- Ogni azione del watchdog scrive `ARRESTO.lock`, che il nodo legge all'avvio.
- Gira su un host diverso (circa €4/mese) per evitare guasti correlati.

**Schema `config/risk.example.yaml`.** I nomi delle chiavi sono definitivi, i valori sono quelli iniziali indicati sopra.

```yaml
risk:
  account: {currency: EUR, cap_iniziale: 2000}
  r_state: {NORMALE: 0.010, DIFENSIVO: 0.005, PAUSA: 0, ARRESTO: 0}
  f4_ramp: {r_normale: 0.005, trades: 30}
  cppi: {K: 0.20, lambda: 0.5, m: 0.05}
  regime:
    hwm_basis: daily_close_equity
    difensivo: {enter_dd: 0.06, exit_dd: 0.03, min_trades: 5}
    pausa: {enter_dd: 0.10, min_days: 10, shadow_min_trades: 8, max_days: 20}
    arresto: {enter_dd: 0.15, repeat_pausa_days: 60}
    cusum: {k_r: 0.1, h_r: 6.0}
  limits:
    day_boundary: "17:00 America/New_York"
    daily: {NORMALE: 0.02, DIFENSIVO: 0.01}
    weekly: {NORMALE: 0.04, DIFENSIVO: 0.02}
    heat_cap: {NORMALE: 0.02, DIFENSIVO: 0.01}
    max_positions: {NORMALE: 3, DIFENSIVO: 2}
    currency_net_risk: 0.015
    margin_used_cap: 0.20
    allow_adds: false
  gaps: {quantile: 0.995, weekend_heat_cap: 0.015, no_entry_after_fri_utc: "16:00"}
  news: {calendar_file: config/events.yaml, before_min: 30, after_min: 30}
  execution: {sl_confirm_s: 10, sl_retries: 3, stale_quote_s: 30, inbound_idle_s: 45}
  backstop: {max_notional_x_equity: 8}
  watchdog: {poll_s: 60, naked_grace_s: 120, emergency_sl_risk: 0.02, hard_dd: 0.20}
```

### 2.4 Ciclo di feedback (R2)

**1. Pre-registrazione.**
- `experiments/prereg/EXP-NNNN.yaml` contiene: ipotesi H-xxx, iterazione (1–3), finestre IS/OOS/lockbox, parametri o griglia, metriche con soglie, baseline, conteggio dei tentativi già fatti, hash del manifest dei dati.
- Va **committato prima** dell'esecuzione.
- `exp run` rifiuta di partire se il file non è in HEAD o è modificato, e scrive nel risultato lo sha del prereg. Un criterio cambiato dopo avere visto i risultati diventa così un hash diverso, e quindi visibile.

**2. Report JSON** (`experiments/reports/EXP-NNNN/report.json`, schema versionato). Contiene:
- `kind` (backtest | walkforward | demo | live);
- n. operazioni;
- rendimento netto;
- PF;
- expectancy in R;
- DD massimo e sua durata;
- Sharpe e Sortino (annualizzati sui rendimenti giornalieri);
- win rate;
- esposizione (% del tempo a mercato, heat media);
- costi totali (spread, commissioni, swap, slippage);
- distribuzione per **sessione** (Asia, Londra, NY, sovrapposizione) e per **regime** (terzili di volatilità dal percentile ATR; trend/range dall'efficiency ratio a 20 barre: etichette deterministiche);
- R per strumento;
- tempo passato in ogni stato di rischio;
- numero di decisioni del governor per tipo.

**3. Baseline obbligatorie.**
- (a) **Ingressi casuali**: stessi strumenti, stessa frequenza, direzione e momento casuali, **stessa** uscita e stesso governor; 1.000 semi.
- (b) **Passiva**: liquidità (0%) e buy & hold a esposizione media uguale, swap inclusi.
- Promozione solo con expectancy OOS netta **> 95° percentile** della baseline casuale.

**4. Controlli anti-overfitting.**
- Walk-forward rolling: 36 mesi di training, 6 di test, passo 6 mesi, sul periodo 2010–2023.
- Efficienza del walk-forward (WFE) = rendimento annualizzato OOS / IS, che deve essere ≥ 0,5.
- Almeno il 60% delle finestre OOS deve essere positivo.
- **Stabilità**: tutti i vicini a ±1 passo della griglia devono avere expectancy > 0 e stare entro il 50% del valore scelto (deve essere un altopiano, non un picco).
- **Monte Carlo**: bootstrap a blocchi dell'ordine dei trade; il 95° percentile del DD massimo deve stare sotto 0,8 × la soglia di ARRESTO.
- **DSR** (Sharpe deflazionato di Bailey e López de Prado) con N = tentativi cumulati dal registro: deve essere ≥ 0,95. Implementazione nostra (circa 20 righe), testata sull'esempio del paper; PBO con CSCV è opzionale.
- **Lockbox**: 2024-01-01 → 2026-06-30, usato **una sola volta** per ipotesi, con i parametri congelati. La finestra viene fissata in un ADR in F0, prima di qualsiasi backtest.

**5. Verdetto strutturato** (`research/verdict.py`, a regole, legge prereg e report).
- **SCARTATO**:
  - non batte la baseline casuale;
  - DSR < 0,95;
  - lockbox negativo;
  - 3ª iterazione fallita.
- **DA RITARARE**, con codice di diagnosi:
  - `COSTS_DOMINATE`: lordo > 0, netto ≤ 0;
  - `PARAM_FRAGILE`;
  - `TOO_FEW_TRADES`;
  - `OOS_DEGRADATION`;
  - `DD_EXCEEDS`;
  - `REGIME_CONCENTRATED`: oltre il 70% del P&L in un solo regime.

  Per ogni codice è indicata l'azione ammessa.
- **PROMOSSO**: tutti i criteri soddisfatti.
- Massimo **3 iterazioni per ipotesi**, poi l'ipotesi si abbandona.
- Massimo **4 ipotesi in tutto** sugli stessi dati.

**6. Scarto fra demo/reale e backtest.**
- `parity.json` settimanale:
  - slippage medio e p95 su ingresso e SL;
  - spread reale contro modello, per ora del giorno;
  - latenza invio→fill p50/p95;
  - segnali mancati;
  - tasso di corrispondenza dei segnali con il backtest ombra sui tick registrati dello stesso periodo.
- L'aggiornamento del modello di costi produce un nuovo `config/cost_model.vN.yaml` legato a un EXP; dopo ogni nuovo modello si **riesegue** (senza riottimizzare) l'OOS di F2.

### 2.5 Memoria persistente (R3)

- **ADR** `docs/decisions/NNNN-titolo.md`:
  - contesto, opzioni, decisione, motivazione, prove (link a report o EXP), stato (proposta, accettata, sostituita da NNNN);
  - non si cancella mai nulla; indice in `docs/decisions/README.md`.
- **Registro** `experiments/registry.jsonl`:
  - append-only, una riga per evento (`preregistered`, `completed`, `verdict`);
  - campi: id, data, commit, data_hash, parametri, ipotesi, criteri, sha del prereg, metriche chiave, percorso del report, verdetto, ADR;
  - il pre-commit verifica che la versione in HEAD sia un prefisso del file.
- **Diario operativo** `journal/{demo,live}/AAAA-MM-GG.jsonl`:
  - scritto **prima** dell'invio, con fsync;
  - campi: ts, id della proposta, sorgente, segnale con valori degli indicatori, stato di rischio, snapshot {E, HWM, F, DD, heat, perdita impegnata}, controlli [{nome, valore, limite, esito}], decisione, quantità proposta e approvata, `clientOrderId`;
  - l'id del conto è salvato come hash; commit settimanale.
- **HANDOFF.md** sempre aggiornato: fa parte della "definition of done" di ogni sessione di lavoro.
- **Commit**: `[ADR-NNNN]`, `[EXP-NNNN]` o `[F<n>]` nel titolo, imposti dall'hook `commit-msg`.

## 3. Strategia iniziale

Si parte con due ipotesi pre-registrate e separate, che contano entrambe nel numero dei tentativi.

| | **S1 — Trend following Donchian/ATR, H4** (principale) | **S2 — Breakout del range d'apertura di Londra** (secondaria) |
|---|---|---|
| Logica di mercato | Momentum di serie storica (Moskowitz, Ooi, Pedersen 2012; Hurst, Ooi, Pedersen 2017). Nota onesta: le prove sono più forti su orizzonti mensili e su portafogli diversificati di futures; su 4 coppie FX in H4 sono più deboli | Concentrazione di liquidità e volatilità all'apertura di Londra (Crabel 1990; momentum intraday: Gao et al. 2018 su azioni; FX [DA VERIFICARE]). Prove accademiche più deboli |
| Regole | Long/short quando la chiusura rompe il massimo o minimo di N barre; stop iniziale a 2×ATR(20); trailing chandelier k×ATR; uscita sul trailing | Range fra le 08:00 e le 09:00 di Londra (zoneinfo, ora legale gestita); ingresso a mercato quando la quota supera il range ± 0,1×range; SL sul lato opposto del range; TP k·R oppure uscita alle 16:30 di Londra; un trade al giorno; si salta il giorno se il range è < 0,15 o > 0,8 × ATR(D1) o se c'è un evento in calendario |
| Parametri liberi | N ∈ {20, 55, 100}, k ∈ {2,5, 3, 4} → 9 combinazioni | k ∈ {1, 1,5, 2, solo uscita a tempo} → 4 combinazioni |
| Strumenti | EURUSD, GBPUSD, USDJPY, AUDUSD | EURUSD, GBPUSD |
| Trade attesi | circa 60–100 all'anno in totale [DA VERIFICARE] | circa 150–250 all'anno [DA VERIFICARE] |
| Costo / R | circa 1 pip (commissione 0,6 + spread 0,1–0,3 + slippage) su uno stop di 60–120 pip → **circa 1–2% di R** | circa 1 pip su uno stop di 15–30 pip → **circa 3–7% di R** |
| Rischi | Lunghe serie di perdite; swap; gap del weekend | Costi; dipendenza dal regime; ora legale |

**Granularità per EURUSD** (0,01 lot ≈ €0,09 per pip; si arrotonda sempre per difetto):

| E | Budget all'1% | Stop S1 di 80 pip (≈ €7,3 per 0,01 lot) | Budget allo 0,5% (DIFENSIVO) |
|---|---|---|---|
| €1.000 | €10 | 0,01 lot (0,73%) | €5 → **rifiutato** |
| €2.000 | €20 | 0,02 lot (0,73%) | €10 → 0,01 lot |
| €5.000 | €50 | 0,06 lot (0,88%) | €25 → 0,03 lot |

- XAUUSD (0,01 lot = 1 oz, stop H4 di $40–90) **non è praticabile** sotto i €6k circa con rischio ≤ 1%. È escluso dalla fase iniziale e si potrà rivalutare solo come nuova ipotesi.
- Lo scalping XAUUSD legacy è chiuso come EXP-0000.
- Solo ingressi a mercato con SL relativo. Gli ordini stop pendenti a coppie (OCO) sono esclusi: dopo una disconnessione potrebbero eseguirsi entrambi.

## 4. Fasi e criteri di uscita

Ogni fase ha criteri misurabili. **Una qualsiasi violazione bloccante fa ripartire dalla fase indicata.**

**F0 — Setup e dati** (2–3 settimane)
- Contenuto:
  - ristrutturazione del repo e scaffolding;
  - demo cTrader Razor in EUR su **Pepperstone EU**, con verifica contrattuale di entità, classe retail, protezione dal saldo negativo e leva [DA VERIFICARE];
  - registrazione dell'app Open API;
  - conferma dal supporto che l'Open API è abilitata;
  - barre M1 bid/ask Dukascopy 2010→oggi per 4 coppie, più tick dal 2023 (via `dukascopy-node`, che oggi richiede Chromium, in una cartella isolata; termini d'uso [DA VERIFICARE]);
  - catalog e manifest sha256;
  - ADR della finestra lockbox.
- Uscita:
  - report di qualità dei dati: ≥ 99% dei minuti attesi presenti nelle ore di mercato, buchi documentati, zero duplicati;
  - ADR 0001–0005 accettati;
  - app approvata e login demo riuscito;
  - `pytest` e `lint-imports` verdi.
- **Blocca**: Open API non disponibile → ADR sul ripiego MT5, oppure stop.

**F1 — Adapter in demo** (6–10 settimane)
- Contenuto:
  - `ctrader_async`;
  - `nt_ctrader`;
  - TickRecorder;
  - `riskgov.core` completo, con tutte le invarianti verdi;
  - governor con rischio minimo fisso;
  - watchdog fase 1.
- Uscita:
  - almeno 50 ordini di prova da 0,01 lot, **tutti** con SL verificato al broker entro 10 s;
  - 7 giorni consecutivi, con un weekend, senza eccezioni non gestite e senza discrepanze dopo le riconciliazioni;
  - almeno 20 disconnessioni forzate e almeno 10 kill del processo con posizione aperta, con il 100% di recuperi corretti;
  - almeno 3 refresh del token forzati senza lockout;
  - tutti gli scenari del finto server verdi;
  - latenza p50/p95 misurata.
- **Blocca**: un solo ordine eseguito senza SL e non rilevato → stop, analisi della causa e ADR.

**F2 — Backtest e walk-forward** (4–6 settimane, in parte in parallelo a F1)
- Contenuto:
  - S1 e S2 pre-registrate;
  - walk-forward;
  - baseline;
  - Monte Carlo;
  - DSR;
  - stress sui costi;
  - lockbox;
  - calibrazione delle soglie della macchina a stati, con relativo ADR.
- Uscita con **PROMOSSO** per almeno un'ipotesi. Criteri (se ne possono solo stringere):
  - almeno 200 trade OOS;
  - PF netto ≥ 1,15;
  - expectancy ≥ +0,08R;
  - expectancy > 0 anche con costi ×1,5;
  - batte il 95° percentile della baseline casuale;
  - DSR ≥ 0,95;
  - WFE ≥ 0,5;
  - altopiano dei parametri;
  - P95 del DD MC ≤ 12%;
  - lockbox con expectancy > 0 e PF ≥ 1.
- **Blocca**: tutte le ipotesi SCARTATO entro i limiti di iterazione → stop del progetto (§7).

**F3 — Demo** (almeno 12 settimane **e** almeno 30 trade per ogni strategia promossa, vale la condizione raggiunta più tardi)
- Scopo: **parità di esecuzione e solidità operativa**, non la prova del vantaggio.
- Uscita:
  - almeno il 95% dei segnali coincide con il backtest ombra;
  - trade mancati ≤ 5%;
  - modello di costi aggiornato e OOS di F2 ancora conforme ai criteri;
  - R realizzati dentro la banda MC 5–95%;
  - zero violazioni di regole;
  - zero posizioni senza SL per più di 10 s;
  - almeno 4 settimane consecutive senza incidenti OPS;
  - watchdog fasi 1 e 2 attive;
  - esercitazioni del runbook fatte (kill switch, sblocco dell'ARRESTO, riavvio);
  - Nautilus in versione 2.0.0 stabile, oppure un ADR che accetti la RC.
- **Blocca**: R sotto il 5° percentile MC → SCARTATO o DA RITARARE (si torna a F2).

**F4 — Reale con capitale minimo** (almeno 12 settimane **e** almeno 30 trade)
- Contenuto:
  - commit del tag di fine F3;
  - CAP_INIZIALE versato **una sola volta**;
  - r_NORMALE allo 0,5% per i primi 30 trade, poi all'1% tramite ADR.
- Uscita:
  - costo reale per trade ≤ 1,5 × il modello calibrato in demo;
  - R dentro la banda MC;
  - nessuna violazione;
  - nessun ARRESTO.
- **Blocca**: ARRESTO → stop e revisione completa; posizione senza SL in reale → si torna a F1.

**F5 — Crescita solo tramite profitti** (continua)
- La dimensione cresce da sola con E.
- Il rischio per trade ha un **tetto all'1%**, che si può cambiare solo con un ADR.
- Nessun versamento: un deposito porta in PAUSA (OPS).
- Ogni nuova strategia o nuovo strumento è una nuova ipotesi che ripassa da F2 → F3 → F4, dentro la stessa heat cap globale.
- Report mensile, CUSUM continuo, confronto trimestrale con il backtest.

## 5. Struttura del repository e convenzioni

```
HANDOFF.md  CLAUDE.md  README.md  pyproject.toml  uv.lock  .python-version  .gitignore
docs/PIANO.md   docs/decisions/{README,TEMPLATE,0001..0004}.md   docs/runbooks/ (da F1)
config/{risk.example.yaml, ctrader.example.env, cost_model.v0.yaml, events.yaml (F1)}
experiments/{registry.jsonl, prereg/, reports/, schema/}
journal/{demo,live}/            (da F1)
proto/                          (F1: .proto vendorizzati + ORIGINE.md con commit e licenza)
src/ctrader_async/              client cTrader, senza Nautilus
src/nt_ctrader/                 adapter Nautilus (prefisso nt_ per il marchio)
src/riskgov/{core,nautilus}/    core puro / integrazione
src/tradingsys/{signals,research,reporting,datapipe,watchdog,cli}/
tests/{riskgov,ctrader_async,nt_ctrader,integration,demo,fault}/
tools/{githooks/, check_registry_append_only.py, gen_proto.sh (F1)}
legacy/                         codice XAUUSD e report MT5 (solo riferimento)
data/{raw,catalog}/             ignorata da git; il manifest con gli hash è in experiments/
```

Convenzioni:
- Identificatori in inglese; commenti, log e documenti in italiano, come nel repo attuale.
- Python 3.14 (sistema) con ambiente `.venv` gestito da `uv`, tutto in UTC; le sessioni si calcolano con `zoneinfo`.
- Ruff per lint e formattazione. Contratti `import-linter` per i confini (`riskgov.core` e `ctrader_async` senza `nautilus_trader`).
- Segreti solo in `.env` fuori da git; token in `secrets/`, scritti in modo atomico e con permessi 600.
- Ogni sessione di lavoro si chiude con HANDOFF.md aggiornato.

## 6. Piano di test

**Unitari, gestore del rischio.** Test basati su proprietà con `hypothesis`, più test di mutazione (`mutmut`, punteggio ≥ 80% su `riskgov.core`). Invarianti:
1. dimensione × rischio unitario ≤ budget;
2. sotto il minimo → RIFIUTO, mai arrotondamento per eccesso;
3. rischio ≤ min(r_stato·E, m·(E−F), tetto);
4. PAUSA e ARRESTO non approvano mai un ingresso;
5. le uscite sono sempre approvate;
6. ogni ingresso ha lo SL dal lato giusto e a una distanza ≥ minimo;
7. lo SL si muove in modo monotono (solo verso il guadagno);
8. heat corretta per i gap ≤ cap dello stato;
9. perdita impegnata + nuovo rischio ≤ limiti giornaliero e settimanale;
10. numero di posizioni, una per strumento, nessuna aggiunta;
11. margine proiettato ≤ cap;
12. HWM ed F non scendono mai, ed F < HWM;
13. DD ≥ D_kill oppure E ≤ F ⇒ ARRESTO; si esce dall'ARRESTO solo a mano; da PAUSA non si passa mai direttamente a NORMALE;
14. nessuna oscillazione dentro la banda di isteresi;
15. una perdita o uno stato peggiore non aumentano mai la dimensione;
16. fail-closed: NaN, infinito, valori negativi o tasso FX mancante → RIFIUTO;
17. `decide()` è puro e deterministico, e un ciclo persistenza→ripristino dà decisioni identiche;
18. CAP_INIZIALE non entra nel sizing: cambiare E0 a parità di E e di F non cambia la dimensione.

**Unitari, adapter.**
- Conversioni di prezzi, volumi e denaro.
- Calcolo dello SL relativo e dell'arrotondamento.
- Parsing con fixture protobuf registrate (file golden).
- Traduzione bracket → `NewOrderReq` e modifica dello SL figlio → `AmendPositionSLTP`.

**Integrazione.**
- Finto server cTrader asyncio con TLS, che parla protobuf.
- BacktestEngine: gap oltre lo SL, rifiuto, riavvio; `publish_message` con lo stesso comportamento in backtest e live.
- Determinismo: stessi dati e stessa config → stesso hash del report.
- Demo (`pytest -m demo`, con credenziali): connessione, simboli, spot per 60 s, ordine da 0,01 lot con SL, Reconcile, chiusura, DealList.

**Scenari di guasto** (finto server, poi ripetuti sul demo):
- disconnessione durante l'invio;
- `ExecutionEvent` in ritardo, duplicato o fuori ordine;
- ordine rifiutato;
- `AmendPositionSLTP` rifiutato;
- heartbeat assente;
- token scaduto, o refresh concorrente;
- `CHANNEL_IS_BLOCKED`;
- superamento del limite di frequenza (`retryAfter`);
- kill del processo con posizione aperta e riavvio;
- posizione sconosciuta;
- posizione senza SL;
- ordine pendente estraneo;
- stop-out con `isServerEvent`;
- deposito rilevato;
- quote ferme;
- cambio dell'ora legale;
- gap del weekend;
- watchdog e nodo attivi insieme.

## 7. Tempi, costi, condizioni di stop

**Tempi** (si assumono 10–15 ore a settimana con l'assistenza di Claude Code [DA VERIFICARE la disponibilità reale]):

| Fase | Durata |
|---|---|
| F0 | 2–3 settimane |
| F1 | 6–10 settimane |
| F2 | 4–6 settimane (in parte in parallelo) |
| F3 | ≥ 12 settimane di calendario |
| F4 | ≥ 12 settimane |

→ F4 non prima di aprile 2027 circa, la decisione su F5 non prima dell'estate 2027.

**Costi** (prezzi indicativi, ottobre 2026):

| Voce | Costo |
|---|---|
| VPS Linux (Hetzner, OVH, Contabo) | €5–10 al mese |
| Host del watchdog | circa €4–5 al mese |
| healthchecks.io, Telegram | gratis |
| Dati (Dukascopy, cTrader) | gratis (termini [DA VERIFICARE]) |
| Demo | gratis |
| **Infrastruttura, totale** | **circa €10–15 al mese (€120–180 l'anno)** |

**Nota onesta**: con €2k di capitale l'infrastruttura pesa per il **6–9% l'anno**. Per questo F1–F3 girano in locale o su una VPS minima, e il "rendimento netto" di F4/F5 si valuta anche al netto dell'infrastruttura. Costi di trading: $6 per lotto andata e ritorno (cioè $0,06 per 0,01 lot), più spread e swap.

**Il progetto si ferma se:**
1. l'Open API non è utilizzabile su Pepperstone EU e il ripiego MT5 non è affidabile;
2. F1 non viene superata dopo 12 settimane di lavoro effettivo;
3. tutte le ipotesi (al massimo 4, al massimo 3 iterazioni ciascuna) sono SCARTATO → nessun vantaggio dimostrato, e non si continua a scavare negli stessi dati;
4. i costi reali misurati in F3 rendono l'expectancy ≤ 0;
5. in F4 si raggiunge l'ARRESTO, compare una posizione senza SL o gli R scendono sotto il 5° percentile MC;
6. il rendimento atteso realistico non copre infrastruttura e tempo (valutazione a fine F4);
7. cambiano regole o condizioni del broker o di ESMA, oppure l'Open API viene revocata.
