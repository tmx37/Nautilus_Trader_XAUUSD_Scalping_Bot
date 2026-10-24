# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

An automated trading system for a **Pepperstone EU** retail account. It connects through a custom NautilusTrader adapter for the cTrader Open API. It runs on demo first and goes live only after pre-registered thresholds are met. The initial capital is deposited once (€1–5k) and never topped up. A separate risk component (`riskgov`) has the final say on every order. No returns are promised or assumed.

**Read `HANDOFF.md` first**: current phase, what works, next steps, open questions. Then read `docs/PIANO.md` (the full plan) and `docs/decisions/` (ADRs). Docs, code comments and log messages are in Italian; identifiers are in English.

The repo started as an XAUUSD EMA-crossover port of an MT5 EA. That code is archived in `legacy/` and does not work. Its hypothesis was rejected as EXP-0000: in-sample vs forward rank correlation −0.47, and 0 of 148 passes were profitable in both periods. Don't build on it. `legacy/README.md` lists its bugs.

## Setup and commands

`uv` manages the venv in `.venv`, using system Python 3.14 (`.python-version`). Python downloads are disabled in the user's uv config.

```bash
uv sync                       # install (nautilus_trader pinned ==2.0.0rc7, see ADR 0002)
uv run pytest                 # tests; demo tests are marked `demo`, run them with -m demo
uv run pytest tests/riskgov/test_config.py::test_example_config_loads   # single test
uv run lint-imports           # component boundary contracts (pyproject [tool.importlinter])
uv run ruff check && uv run ruff format --check
```

Git hooks are in `tools/githooks/` but are only active after `git config core.hooksPath tools/githooks`.

## Layout

- `src/ctrader_async/`: native asyncio cTrader Open API client (ADR 0001). Must never import `nautilus_trader`; the watchdog reuses it.
- `src/nt_ctrader/`: NautilusTrader v2 adapter. Use the `nt_` prefix: third-party packages may not use the `nautilus` name.
- `src/riskgov/core/`: pure, deterministic risk logic. Must never import `nautilus_trader`. `riskgov/nautilus/` holds the `RiskGovernor`, which will be the node's only Strategy.
- `src/tradingsys/`: `signals` (Actors that only *propose* trades), `research`, `reporting`, `datapipe`, `watchdog`, `cli`.
- `config/risk.example.yaml`: risk parameters. `riskgov.core.config` rejects unknown or missing keys and any violated cross-parameter constraint.
- `experiments/`: `registry.jsonl` (append-only), `prereg/`, `schema/`, `reports/`.

## Rules that are easy to break

- **Risk**:
  - Only `RiskGovernor` submits orders; signals publish proposals.
  - Every entry carries a broker-side stop loss. cTrader MARKET orders only accept *relative* SL/TP.
  - Size is always rounded **down**, and the trade is rejected if it falls below the minimum volume. Never round up to the minimum lot (the legacy EA did).
  - Sizing uses current equity, never CAP_INIZIALE.
  - No grid, martingale, averaging down or adding to positions.
  - Nothing may assume or request a deposit.
- **Experiments**:
  - Commit the prereg file *before* running.
  - Criteria never change after results are seen.
  - Never edit existing lines of `registry.jsonl`; append a correcting event instead.
  - At most 3 iterations per hypothesis.
  - The lockbox window (2024-01-01 → 2026-06-30) is opened once per hypothesis, with frozen parameters, as its own prereg'd EXP; a negative result discards the hypothesis (ADR 0005).
- **Decisions**:
  - Every decision gets an ADR in `docs/decisions/` (template there).
  - ADRs are never deleted; they get superseded.
  - Commit titles carry `[ADR-NNNN]`, `[EXP-NNNN]` or `[F0]`…`[F5]`.
- **HANDOFF.md**: update it at the end of every work session.
- **Version**: NautilusTrader v2 is a release candidate and its API differs from v1 (`LiveNode`, `on_quote`, Python Adapter Interface). Check `nautilustrader.io/docs/latest`; don't rely on v1 examples. Changing the pinned version needs an ADR.
- **cTrader units**: prices are in 1e-5, volumes in hundredths of a unit (1 lot EURUSD = 10,000,000), money in 10^moneyDigits. A token refresh invalidates the previous token pair.
- **Secrets**: `config/*.env` and `secrets/` are gitignored. Only `*.example.env` is committed.
