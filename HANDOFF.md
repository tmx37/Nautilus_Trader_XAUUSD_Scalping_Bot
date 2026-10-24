# HANDOFF — leggere per primo

**Aggiornato:** 2026-10-24 · **Fase:** F0 (setup), con `riskgov.core` di F1 anticipato · **Branch:** develop

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
- **`riskgov.core` implementato** (2026-10-24): sizing, floor a cricchetto, limiti, macchina a stati, governor
  (`decide`, `decide_exit`, `decide_stop_update`). Semantica dei punti aperti del PIANO nell'ADR 0006.
  Manca solo `reconcile.classify`, che dipende dai report reali di cTrader (F1).
- `ctrader_async`: OAuth pronto (2026-10-24), testato solo con un finto endpoint perché l'app non è ancora
  approvata. `oauth` (URL, scambio del codice, refresh HTTP, redirect su loopback), `tokens` (scrittura
  atomica, permessi 600, lock fra processi), `settings` (validazione di `config/ctrader.env`), comando
  `uv run ctrader-login`. Il resto (TLS, framing, protobuf) è da fare nello spike.
- `nt_ctrader`, `riskgov.nautilus` e il resto di `tradingsys` sono ancora stub.
- ADR 0005 (finestra lockbox) e 0006 (semantica di `riskgov.core`) accettati il 2026-10-24, prima di qualsiasi
  backtest FX. Resta in proposta lo 0004: l'uscita da F0 richiede gli ADR 0001–0005 accettati.

## Cosa funziona
- `uv sync` (Python 3.14.8 di sistema, `nautilus_trader==2.0.0rc7`, protobuf 7.36.2)
- `uv run pytest`: 256 test verdi, 1 in skip (`reconcile.classify`). Le 18 invarianti del PIANO §6 sono test
  basati su proprietà (`hypothesis`); le strategie condivise sono in `tests/factories.py`, il finto endpoint OAuth
  in `tests/fake_oauth.py` (`pythonpath = ["tests"]`).
- `uv run lint-imports`: `riskgov.core` e `ctrader_async` non importano `nautilus_trader`
- Hook git attivi (`core.hooksPath = tools/githooks`, impostazione locale: va ripetuta su ogni clone): registro append-only e titoli dei commit con `[ADR-NNNN]`, `[EXP-NNNN]` o `[F<n>]`

## Cosa non funziona / non esiste ancora
- Nessuna connessione a cTrader
- Catalog dei dati vuoto
- Nessuna strategia e nessun backtest

## Prossimi passi
1. [utente] Aprire un demo cTrader (Razor, EUR) su **Pepperstone EU**. Verificare nel contratto: entità
   Pepperstone EU Ltd (CySEC 388/20), classe retail, protezione dal saldo negativo, leva ESMA. [DA VERIFICARE]
2. [utente] App Open API **inviata il 2026-10-24, stato "submitted"** (approvazione manuale di Spotware).
   Permesso "Access your accounts and trade" (solo i conti del cTrader ID che ha registrato l'app: il demo
   Pepperstone va aperto o collegato con lo stesso cTrader ID); redirect `http://localhost:8765/callback`.
   Quando è "Active": compilare `config/ctrader.env` (client ID e secret) ed eseguire `uv run ctrader-login`
   [DA VERIFICARE al primo login: metodo GET dell'endpoint del token, la documentazione è incoerente]. Il trading automatico è ammesso da Pepperstone (utente);
   che l'Open API veda il conto EU retail si verifica al primo login (il conto deve comparire nella lista
   di `ProtoOAGetAccountListByAccessTokenReq`). Se non compare: ADR sul ripiego MT5.
3. Pipeline Dukascopy → ParquetDataCatalog, con manifest sha256 e report di qualità (solo metriche di
   qualità sulla finestra lockbox, ADR 0005 punto 6).
4. Spike F1 di `ctrader_async`: pre-registrare l'EXP, poi connessione, autenticazione e spot EURUSD.
5. `riskgov.nautilus.RiskGovernor` e journal (F1); test di mutazione con `mutmut` su `riskgov.core`
   (obiettivo ≥ 80%, PIANO §6), non ancora eseguito.

## Decisioni
| ADR | Titolo | Stato |
|---|---|---|
| 0001 | Client asyncio nativo per cTrader | accettata |
| 0002 | NautilusTrader v2, RC fissata | accettata con condizione: serve una 2.0.0 stabile prima di F4 |
| 0003 | Archiviazione legacy + EXP-0000 | accettata |
| 0004 | Architettura del gestore del rischio | proposta: soglie da calibrare in F2 |
| 0005 | Finestra lockbox (2024-01-01 → 2026-06-30, una apertura per ipotesi) | accettata |
| 0006 | Semantica di `riskgov.core` (rientro dalla PAUSA, CUSUM `w_r`, prelievi, weekend…) | accettata |

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
