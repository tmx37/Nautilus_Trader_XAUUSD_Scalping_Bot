# HANDOFF — leggere per primo

**Aggiornato:** 2026-10-22 · **Fase:** F0 (setup) · **Branch:** develop

## Obiettivo
Sistema automatico su un conto **Pepperstone EU** (cTrader Open API, adapter nostro per NautilusTrader).
Prima demo, reale solo dopo soglie pre-registrate. Capitale unico CAP_INIZIALE (€1–5k), mai integrato.
Il rischio è deciso da un componente separato (`riskgov`) che ha l'ultima parola.
**Nessun rendimento è promesso né assunto.**

## Leggere in quest'ordine
1. Questo file
2. `docs/PIANO.md`
3. `docs/decisions/README.md`
4. `experiments/registry.jsonl`
5. `CLAUDE.md`

## Stato attuale
- Repo ristrutturato (scaffolding F0). Il codice XAUUSD legacy è in `legacy/`: non funziona, serve solo
  come riferimento.
- EXP-0000 (EMA crossover XAUUSD M15, MT5, 2024) → **SCARTATO**: correlazione di rango IS/forward −0,47,
  0 passaggi su 148 profittevoli in entrambi i periodi.
- Pacchetti `ctrader_async`, `nt_ctrader`, `riskgov`, `tradingsys` creati come stub. Sono implementati solo
  `riskgov.core.config` (caricamento e vincoli di `config/risk.example.yaml`) e la tabella `POLICY` di `riskgov.core.reconcile`.

## Cosa funziona
- `uv sync` (Python 3.14.8 di sistema, `nautilus_trader==2.0.0rc7`, protobuf 7.36.2)
- `uv run pytest`: 37 test verdi (config del rischio, tabella di riconciliazione, schemi, registro, regola append-only); 27 test delle invarianti del rischio presenti ma in skip (stub)
- `uv run lint-imports`: `riskgov.core` e `ctrader_async` non importano `nautilus_trader`
- Hook git attivi (`core.hooksPath = tools/githooks`, impostazione locale: va ripetuta su ogni clone): registro append-only e titoli dei commit con `[ADR-NNNN]`, `[EXP-NNNN]` o `[F<n>]`

## Cosa non funziona / non esiste ancora
- Nessuna connessione a cTrader
- Catalog dei dati vuoto
- Nessuna strategia e nessun backtest

## Prossimi passi
1. [utente] Aprire un demo cTrader (Razor, EUR) su **Pepperstone EU**. Verificare nel contratto: entità
   Pepperstone EU Ltd (CySEC 388/20), classe retail, protezione dal saldo negativo, leva ESMA. [DA VERIFICARE]
2. [utente] Registrare l'app su openapi.ctrader.com (approvazione manuale) e chiedere al supporto
   Pepperstone EU se l'Open API è abilitata sui conti retail.
3. ADR 0005: congelare la finestra lockbox (proposta: 2024-01-01 → 2026-06-30) **prima** di qualsiasi
   backtest.
4. Pipeline Dukascopy → ParquetDataCatalog, con manifest sha256 e report di qualità.
5. Implementare `riskgov.core` togliendo gli skip dei test uno alla volta.
6. Spike F1 di `ctrader_async`: pre-registrare l'EXP, poi connessione, autenticazione e spot EURUSD.

## Decisioni
| ADR | Titolo | Stato |
|---|---|---|
| 0001 | Client asyncio nativo per cTrader | accettata |
| 0002 | NautilusTrader v2, RC fissata | accettata con condizione: serve una 2.0.0 stabile prima di F4 |
| 0003 | Archiviazione legacy + EXP-0000 | accettata |
| 0004 | Architettura del gestore del rischio | proposta: soglie da calibrare in F2 |

## Domande aperte
- CAP_INIZIALE esatto. Sotto €2k, con 0,01 lot, lo stato DIFENSIVO di S1 coincide con PAUSA.
- Valuta del conto (EUR consigliato); le commissioni cTrader sono addebitate in USD.
- Ore settimanali disponibili (le stime del PIANO §7 assumono 10–15).
- Fiscalità italiana con un broker estero [DA VERIFICARE con un commercialista].
- Concorrenza di due sessioni sullo stesso conto (nodo + watchdog) [DA VERIFICARE in F1].

## Rischi noti
- Nautilus v2 è una RC (non raccomandata per il live); l'adapter Python non ha cache Redis/Postgres.
- Lo SL non è garantito: gap del weekend e delle notizie.
- Il refresh del token OAuth invalida la coppia precedente: deve rinnovare un solo processo.
- È probabile che le ipotesi vengano scartate: il 74,1% dei conti CFD retail Pepperstone EU perde denaro.

## Convenzioni rapide
- Commit con `[ADR-NNNN]`, `[EXP-NNNN]` o `[F<n>]` nel titolo.
- `registry.jsonl` è append-only. Il prereg si committa prima dell'esecuzione; i criteri non si cambiano.
- Identificatori in inglese; commenti, log e documenti in italiano.
