# ADR 0002 — NautilusTrader v2 con versione RC fissata esattamente

- **Stato:** accettata (2026-10-22), con condizione: serve una 2.0.0 stabile prima di F4, oppure un ADR che accetti esplicitamente la RC.
- **Fase:** F0 · **Sostituisce:** — · **Sostituita da:** —
- **Collegati:** ADR 0001 (client cTrader), PIANO §1 (rischi T2 e T3), §2.1.

## Contesto
- NautilusTrader è a metà del passaggio dalla v1 alla v2 (verificato il 2026-10-22 su GitHub releases e PyPI).
  - **v1 1.231.0** (2026-08-02): Cython, `TradingNode`, Python 3.12–3.14. Le note di rilascio la indicano come "the final 1.x release with support for the legacy Cython v1 core". Il branch `develop_v1` riceve solo patch di sicurezza per circa 3 mesi dopo il passaggio.
  - **v2 2.0.0rc7** (2026-10-15): Rust + PyO3, `LiveNode`, **Python 3.13–3.14** (rc7 ha tolto la 3.12). Il README la indica come "not recommended for production or live trading".
  - La documentazione `nautilustrader.io/docs/latest` descrive già la v2. `MIGRATION_V2.md`: "V1 Cython adapters need porting".
- In v2 gli adapter Python di terze parti sono supportati tramite la Python Adapter Interface (`nautilus_trader.live.clients`: `DataClient`, `MarketDataClient`, `ExecutionClient` e relative factory). Limite documentato: "Redis/PostgreSQL cache backing is unsupported with custom Python clients".
- La v2 introduce `CfdSwapModule` e `publish_message`/`subscribe_topic`, usati dal piano (swap, proposte al RiskGovernor).
- Il live reale (F4) è previsto non prima di aprile 2027 circa (PIANO §7).

## Opzioni considerate
| Opzione | Pro | Contro |
|---|---|---|
| A. v1 1.231.0 | Stabile; l'adapter comunitario `pash7ka/nautilus-ctrader-adapter` è per la v1 | Congelata; ogni adapter scritto ora va portato alla v2 entro pochi mesi; API diverse dalla documentazione corrente |
| B. v2 con RC fissata esattamente (`==2.0.0rc7`) | Linea futura; documentazione allineata; Python Adapter Interface supportata; `CfdSwapModule`, `publish_message` | API che può cambiare fra una RC e l'altra; ufficialmente non per il live; niente cache Redis/Postgres per adapter Python |
| C. v2 seguendo sempre l'ultima RC | Correzioni subito disponibili | Rottura continua; backtest non riproducibili |

## Decisione
Opzione **B**: `nautilus_trader==2.0.0rc7`, ambiente `.venv` creato da `uv` con il Python di sistema 3.14 (`.python-version`; `requires-python = ">=3.13,<3.15"`). Ogni aggiornamento di versione richiede un ADR. Prima di F4 serve la 2.0.0 stabile, oppure un ADR che accetti la RC con motivazione e prove.

## Motivazione
- Scrivere un adapter per la v1 significa riscriverlo prima ancora di arrivare al reale.
- Il rischio di API mobile è contenuto dall'architettura: la logica di protocollo sta in `ctrader_async` e il rischio in `riskgov.core`, entrambi senza dipendenze da Nautilus (contratti `import-linter`). L'adapter `nt_ctrader` resta sottile.
- Fissare la versione esatta rende i backtest riproducibili (R2): il commit e `uv.lock` identificano l'ambiente.

## Conseguenze
- Il recupero dopo un riavvio non può contare sulla cache persistente di Nautilus: l'adapter deve fornire un mass status completo (Reconcile, DealList, `avg_px_open`) e il journal conserva l'intento (PIANO §2.3, rischio T3).
- Python 3.14: è supportato dalla rc7 ed è già installato (3.14.8). La config di `uv` dell'utente ha i download automatici di Python disattivati, quindi non si scarica una 3.13 a parte. La 3.13 resta compatibile.
- Il codice legacy in `legacy/` usa API v1 e non viene portato (ADR 0003).

## Prove
- https://github.com/nautechsystems/nautilus_trader/releases (tag v1.231.0 e v2.0.0rc7)
- https://pypi.org/project/nautilus-trader/1.231.0/
- https://github.com/nautechsystems/nautilus_trader/blob/develop/MIGRATION_V2.md
- https://nautilustrader.io/docs/latest/developer_guide/python_adapters
- Verifica locale 2026-10-22: `uv sync` risolto con Python 3.14.8, nautilus-trader 2.0.0rc7, protobuf 7.36.2, numpy 2.5.4, scipy 1.18.1 (`uv.lock`); `import nautilus_trader` riuscito.

## Condizioni di revisione
- Uscita della 2.0.0 stabile → ADR di aggiornamento.
- Una RC successiva risolve un bug che blocca F1 → ADR di aggiornamento puntuale.
- La Python Adapter Interface viene ritirata o cambia in modo incompatibile → rivalutare.

## Scartato
- A: vicolo cieco a pochi mesi.
- C: rende impossibile la riproducibilità.
