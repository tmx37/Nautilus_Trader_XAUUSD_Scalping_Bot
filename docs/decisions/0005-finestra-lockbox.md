# ADR 0005 — Finestra lockbox per le ipotesi FX di F2

- **Stato:** accettata (2026-10-24, dall'utente, prima di qualsiasi backtest FX).
- **Fase:** F0 · **Sostituisce:** — · **Sostituita da:** —
- **Collegati:** PIANO §2.4 punto 4, §4 (F0, F2); `experiments/prereg/TEMPLATE.yaml`; ADR 0003 (EXP-0000).

## Contesto
- Il lockbox è l'ultima difesa contro la sovra-ottimizzazione (rischio T13; evidenza legacy: correlazione di rango IS/forward −0,47). Funziona solo se i dati della finestra non sono mai stati guardati durante lo sviluppo, e se la finestra è fissata **prima** di vedere qualsiasi risultato.
- Il PIANO propone: walk-forward rolling 36/6/6 mesi sul periodo 2010–2023 (finestre OOS dal 2013-01-01 al 2023-12-31), lockbox 2024-01-01 → 2026-06-30.
- Il PIANO (§2.4) dice "usato una sola volta **per ipotesi**", `CLAUDE.md` dice "used once": le due formulazioni vanno rese coerenti.
- Al 2026-10-24 nessun backtest FX è stato eseguito: il catalog è vuoto e il registro contiene solo EXP-0000 (XAUUSD, MT5, 2024). EXP-0000 cade nel 2024 ma riguarda un altro strumento e un'altra ipotesi: non contamina i parametri delle ipotesi FX.
- Volume atteso nella finestra proposta (30 mesi): circa 150–250 trade per S1 e 375–625 per S2, con le stime [DA VERIFICARE] di PIANO §3. Basta per un controllo di segno (expectancy > 0, PF ≥ 1), non per una stima precisa.

## Opzioni considerate
| Opzione | Pro | Contro |
|---|---|---|
| A. Lockbox fisso 2024-01-01 → 2026-06-30, aperto una volta per ipotesi | Proposta del PIANO; 30 mesi recenti, con regimi diversi (tassi alti, tagli 2024–2025); fine fissa → riproducibile | Ogni apertura rivela qualcosa sul periodo a chi progetta le ipotesi successive |
| B. Lockbox fisso, aperto **una sola volta in assoluto** (tutte le ipotesi insieme) | Nessuna fuga d'informazione fra ipotesi | Obbliga a finire tutte le ipotesi prima di guardare: blocca S1 se S2 è in ritardo |
| C. Lockbox "mobile" fino alla data di F2 | Più dati | Fine non fissata → non riproducibile; tentazione di spostarla |
| D. Nessun lockbox, solo walk-forward | Più dati per il WF | Il WF da solo è già stato aggirato in passato (−0,47): serve un controllo mai toccato |

## Decisione
Opzione **A**, con regole che limitano la fuga d'informazione:
1. **Finestre fissate**: sviluppo e walk-forward su dati con timestamp < 2024-01-01 (WF 2010-01-01 → 2023-12-31, OOS 2013-01-01 → 2023-12-31); lockbox **2024-01-01 00:00 UTC → 2026-06-30 23:59:59 UTC**, uguale per tutti gli strumenti FX.
2. **Dati dopo il 2026-06-30**: non usati in F2. Restano di riserva; un eventuale uso richiede un nuovo ADR.
3. **Un'apertura per ipotesi**: solo con parametri congelati, solo dopo che tutti gli altri criteri di F2 sono soddisfatti, come EXP separato (`kind: lockbox`) pre-registrato e committato. Ogni apertura è una riga del registro e conta nei tentativi.
4. **Esito senza appello**: un lockbox che non soddisfa i criteri porta l'ipotesi a SCARTATO (`LOCKBOX_NEGATIVE`), mai a DA RITARARE. Non si itera su un'ipotesi dopo averne aperto il lockbox.
5. **Ipotesi contaminate**: un'ipotesi pre-registrata **dopo** la prima apertura del lockbox non può usarlo come prova; serve un nuovo ADR con un'altra finestra (per esempio i dati di riserva del punto 2 più la demo).
6. **Nessuna ispezione**: sulla finestra lockbox si producono solo controlli di qualità dei dati (conteggi, buchi, duplicati), mai statistiche di rendimento, grafici di prezzo o indicatori per la ricerca.
7. **Guardia nel codice (F2)**: l'esecutore degli esperimenti rifiuta di leggere dati con timestamp ≥ 2024-01-01 se il prereg non è di tipo `lockbox`, e rifiuta un secondo EXP `lockbox` per la stessa ipotesi.

`CLAUDE.md` è allineato: il lockbox si apre una sola volta per ipotesi (ADR 0005).

## Motivazione
- A tiene la proposta del PIANO e la rende verificabile: finestra fissa, aperture registrate, guardia nel codice.
- B è più pulita ma accoppia i tempi di S1 e S2 senza un vantaggio proporzionato, perché le due ipotesi sono pre-registrate prima di qualsiasi apertura (punto 5): le loro regole e griglie non possono più cambiare in base a quanto visto nel lockbox.
- C e D tolgono proprio la garanzia che il lockbox deve dare.

## Conseguenze
- `experiments/prereg/TEMPLATE.yaml` usa già queste finestre.
- Il report di qualità dei dati di F0 copre anche il lockbox, ma solo con metriche di qualità (punto 6).
- In F2: guardia dell'esecutore (punto 7) con test; il verdetto (`research/verdict.py`) mappa un lockbox negativo su SCARTATO.
- Rischio residuo: chi progetta le ipotesi conosce a grandi linee i mercati 2024–2026 (tassi, trend del dollaro). Non è eliminabile; è il motivo per cui il lockbox è un controllo di segno e non la base della stima.

## Prove
- PIANO §2.4 punto 4; `experiments/registry.jsonl` (solo EXP-0000 al 2026-10-24).
- Bailey, Borwein, López de Prado, Zhu (2014), "The Probability of Backtest Overfitting": motivazione per un campione mai toccato.

## Condizioni di revisione
- Un'ipotesi va valutata dopo che il lockbox è già stato aperto (punto 5).
- I dati Dukascopy della finestra risultano inutilizzabili (qualità < soglie di F0).
- Il numero di trade attesi nel lockbox, misurato sul WF, è troppo basso per un controllo di segno (meno di 50 per un'ipotesi).

## Scartato
- B: accoppia i tempi delle ipotesi; la fuga d'informazione è già limitata dalla pre-registrazione.
- C: fine mobile, non riproducibile.
- D: nessun controllo indipendente dal walk-forward.
