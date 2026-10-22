# Decision record (ADR)

Ogni decisione di progetto è un file `NNNN-titolo.md` scritto partendo da [`TEMPLATE.md`](TEMPLATE.md).

Regole:
- Un ADR non si cancella mai. Per cambiare una decisione si scrive un nuovo ADR e in quello vecchio si aggiorna lo stato in "sostituita da NNNN".
- Stati ammessi: **proposta**, **accettata**, **sostituita da NNNN**.
- I commit che introducono o applicano una decisione hanno `[ADR-NNNN]` nel titolo.
- Le prove sono link a report in `experiments/reports/` o a righe di `experiments/registry.jsonl`.

## Indice

| ADR | Titolo | Stato | Data |
|---|---|---|---|
| [0001](0001-connessione-ctrader-client-asyncio-nativo.md) | Connessione a cTrader Open API con client asyncio nativo | accettata | 2026-10-22 |
| [0002](0002-nautilustrader-v2-rc-fissata.md) | NautilusTrader v2 con RC fissata esattamente | accettata con condizione | 2026-10-22 |
| [0003](0003-archiviazione-legacy-xauusd.md) | Archiviazione del codice XAUUSD legacy e verdetto EXP-0000 | accettata | 2026-10-22 |
| [0004](0004-architettura-gestore-rischio.md) | Architettura del gestore del rischio | proposta | 2026-10-22 |

ADR previsti a breve: 0005 finestra lockbox (F0, prima di qualsiasi backtest); mappatura bracket → SL/TP di posizione nell'adapter (F1); soglie calibrate della macchina a stati (fine F2).
