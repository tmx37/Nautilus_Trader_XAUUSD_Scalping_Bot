# Sistema di trading Pepperstone EU / cTrader Open API su NautilusTrader

Sistema automatico per un conto retail **Pepperstone EU**, collegato tramite un adapter cTrader Open API scritto per NautilusTrader (v2). Gira prima in demo e passa al reale solo dopo il superamento di soglie pre-registrate. Il capitale iniziale è unico e non viene mai integrato. Il rischio è deciso da un componente separato dalle strategie.

> Nessun rendimento è promesso. Il 74,1% dei conti CFD retail di Pepperstone EU perde denaro. Il progetto è costruito per accorgersi presto, e a costo limitato, se una strategia non ha vantaggio.

**Stato:** fase F0 (setup). Il dettaglio è in [`HANDOFF.md`](HANDOFF.md).

## Documenti

| File | Contenuto |
|---|---|
| [`HANDOFF.md`](HANDOFF.md) | Stato attuale, prossimi passi, domande aperte (da leggere per primo) |
| [`docs/PIANO.md`](docs/PIANO.md) | Piano di progetto: fattibilità, architettura, strategie, fasi F0–F5, test, costi |
| [`docs/decisions/`](docs/decisions/README.md) | Decision record (ADR) |
| [`experiments/`](experiments/) | Registro esperimenti append-only, pre-registrazioni, schemi dei report |
| [`legacy/`](legacy/README.md) | Vecchio port XAUUSD da MT5 (archiviato, non funzionante) |

## Setup

Serve [`uv`](https://docs.astral.sh/uv/). L'ambiente viene creato in `.venv` con Python 3.14 (vedi `.python-version`).

```bash
uv sync
uv run pytest
uv run lint-imports
uv run ruff check
```

Per attivare gli hook git (titoli dei commit con riferimento ad ADR/EXP/fase, registro append-only):

```bash
git config core.hooksPath tools/githooks
```

## Licenza

GPL-3.0 (vedi [`LICENSE`](LICENSE)). Progetto indipendente, non affiliato né approvato da Nautech Systems, Spotware o Pepperstone.
