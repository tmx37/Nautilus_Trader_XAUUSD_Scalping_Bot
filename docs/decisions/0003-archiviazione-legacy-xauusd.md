# ADR 0003 — Archiviazione del codice XAUUSD legacy e verdetto EXP-0000

- **Stato:** accettata (2026-10-22)
- **Fase:** F0 · **Sostituisce:** — · **Sostituita da:** —
- **Collegati:** EXP-0000 in `experiments/registry.jsonl`, `legacy/README.md`.

## Contesto
- Il repo nasceva come port su NautilusTrader di un Expert Advisor MT5 (EMA crossover su XAUUSD).
- Nessuno dei file Python legacy funziona (dettagli in `legacy/README.md`): ordini costruiti senza id, firme di indicatori sbagliate, attributi inesistenti, unità errate, spread ignorato, ora server trattata come UTC.
- L'ottimizzazione MT5 di `XAUUSD_EMA_EA_V2` (XAUUSD M15, 2024, server PepperstoneUK-Demo, deposito $1000, leva 1:100) ha prodotto 148 passaggi genetici su EMA_Fast, EMA_Slow, ATR_Multiplier e Min_ATR, con tab forward:
  - correlazione di rango fra profitto in-sample e forward: **−0,47** (Pearson −0,50);
  - passaggi con PF > 1: 58/148 in-sample, 8/148 in forward, **0 in entrambi i periodi**;
  - i 10 migliori in-sample sono tutti in perdita in forward (media −123 $ su 1000 $);
  - il miglior forward ha PF 1,08 (+25,90 $).
  - La data di separazione IS/forward non è nei file; il rapporto dei trade (circa 1,86) suggerisce l'ultimo terzo del 2024 (inferenza).
- L'EA V2 arrotonda la dimensione per eccesso al lotto minimo (`MathMax(minLot, …)`, riga 178): con conti piccoli rischia più della percentuale dichiarata.
- Il nuovo progetto (PIANO) cambia broker di riferimento (Pepperstone EU), connessione (cTrader Open API), strumenti (major FX) e struttura.

## Opzioni considerate
| Opzione | Pro | Contro |
|---|---|---|
| A. Spostare tutto in `legacy/` con `git mv` | Resta consultabile; la storia git dei file è conservata; la radice del repo è pulita | Il nome del repo (XAUUSD Scalping Bot) non descrive più il progetto |
| B. Lasciare i file in radice | Nessuno spostamento | Confonde un modello successivo su cosa è attivo |
| C. Cancellare i file | Repo più snello | Si perde il riferimento immediato a evidenza utile (e a un errore da non ripetere) |

## Decisione
Opzione **A** (scelta dell'utente il 2026-10-22). L'ipotesi legacy viene registrata come **EXP-0000, verdetto SCARTATO**. Il codice legacy non viene portato né corretto.

## Motivazione
- L'evidenza MT5 mostra overfitting tipico: i parametri migliori in-sample sono i peggiori fuori campione. Ritararli sarebbe proprio ciò che R2.5 vieta.
- Tenere i file in `legacy/` conserva il riferimento senza rischio che vengano scambiati per codice attivo.
- Registrare EXP-0000 rende l'evidenza leggibile da un modello successivo senza questa conversazione (R3).

## Conseguenze
- `legacy/` è escluso da lint e test.
- Lo scalping XAUUSD resta fuori dalla fase iniziale. Un ritorno su XAUUSD è una **nuova ipotesi** (nuovo EXP, nuovo prereg) e diventa praticabile solo con equity di circa €6k o più (PIANO §3).
- L'eventuale cambio di nome del repo è una scelta dell'utente (azione esterna, non fatta).

## Prove
- `legacy/old_mt5_test_data/ReportOptimizer-62115380.xml` (sha256 `fa8ee3b090b5ef6ec647e6f4c769cf22826c2d68872730b0a500b7afea2aa5da`)
- `legacy/old_mt5_test_data/ForwardResultsOutput-62115380.xml` (sha256 `7771bf8d5d2822c82597540fcd31be5cf9f2041f6e2ac3e2b9585cf392e773d3`)
- `legacy/old_mt5_test_data/TesterOptgraphReport2026.04.15.png`
- Riga EXP-0000 in `experiments/registry.jsonl`.

## Condizioni di revisione
Nessuna prevista: il verdetto è definitivo per questa ipotesi con questi dati.

## Scartato
- B: ambiguità per chi legge il repo.
- C: perdita di evidenza.
