# ADR 0001 — Connessione a cTrader Open API con client asyncio nativo sui .proto ufficiali

- **Stato:** accettata (2026-10-22). Da rivedere se lo spike di F1 fallisce (vedi "Condizioni di revisione").
- **Fase:** F0 · **Sostituisce:** — · **Sostituita da:** —
- **Collegati:** ADR 0002 (versione di NautilusTrader); prova attesa: EXP dello spike F1.

## Contesto
- NautilusTrader non ha un adapter per cTrader, MT5 o Pepperstone (ADAPTERS.md, ottobre 2026). La FIX di
  Pepperstone richiede circa €160M al mese di volume ed è quindi esclusa.
- cTrader Open API: protobuf su TCP+TLS, porta 5035 (`demo.ctraderapi.com` / `live.ctraderapi.com`,
  una connessione per ambiente).
  - Frame: 4 byte di lunghezza big-endian + `ProtoMessage{payloadType, payload, clientMsgId}`.
  - Heartbeat entro 10 s (la documentazione dice anche 30 s: si usa il valore più stretto).
  - Limiti: 50 req/s, e 5 req/s per lo storico, per connessione.
  - OAuth2: access token di circa 30 giorni; il refresh token invalida la coppia precedente.
- NautilusTrader v2 (ADR 0002) gira su asyncio, con il loop posseduto dal `LiveNode`; la cache
  si usa solo dal thread del nodo; serve Python ≥ 3.13.
- SDK ufficiale `ctrader-open-api` 0.9.2 (giugno 2024): basato su Twisted, con pin rigidi
  (Twisted==24.3.0, protobuf==3.20.1, pyOpenSSL==24.1.0) e classifier fino a Python 3.12.
  - Issue aperte su CVE nelle dipendenze (#43) e su SSL rotto con Python 3.13 (#39).
  - La PR "twisted2asyncio" (#29) non è mai stata unita. Di fatto l'SDK non è mantenuto.
- Esistono client comunitari: `ctrader-api-client` (anyio + betterproto, 0.12.0 di ottobre 2026,
  un solo manutentore) e `pash7ka/nautilus-ctrader-adapter` (MIT, pre-alpha, per Nautilus v1).

## Opzioni considerate
| Opzione | Pro | Contro |
|---|---|---|
| A. SDK ufficiale con `asyncioreactor` di Twisted sul loop di Nautilus | Codice di protocollo già pronto | Pin incompatibili con Python 3.13+ e con lo stack attuale [DA VERIFICARE il conflitto puntuale con le dipendenze di Nautilus]; SSL rotto su 3.13; reactor globale da installare prima di ogni import; compatibilità con uvloop non verificata; SDK abbandonato |
| B. SDK ufficiale in un thread separato, con code thread-safe verso il loop di Nautilus | Isola Twisted | Gli stessi problemi di pin, SSL e CVE; due modelli di concorrenza; ogni evento va passato con `call_soon_threadsafe`; spegnimento, riconnessione e ordinamento degli eventi difficili da testare |
| C. Client asyncio nativo generato dai `.proto` ufficiali (spotware/openapi-proto-messages) | Un solo event loop; nessuna dipendenza abbandonata; pieno controllo su heartbeat, riconnessione, rate limit e correlazione; guasti riproducibili con un finto server; riusabile dal watchdog senza Nautilus | Da scrivere e mantenere (stima 600–900 righe [DA VERIFICARE]); bisogna seguire le evoluzioni dei `.proto` |
| D. Dipendere da un client comunitario | Meno codice all'inizio | Un solo manutentore e bassa maturità proprio sul percorso degli ordini; anyio/betterproto introducono un secondo stile; l'adapter pash7ka è per la v1 |

## Decisione
Opzione **C**.
- Il pacchetto `ctrader_async` (senza import di `nautilus_trader`) implementa il trasporto.
- L'adapter `nt_ctrader` poggia su di esso.
- I `.proto` sono vendorizzati in `proto/`, con commit di origine e licenza [DA VERIFICARE la licenza]
  e uno script di rigenerazione.
- I client comunitari si usano **come riferimento di lettura** per le particolarità del protocollo;
  se se ne riprende codice MIT, lo si cita.

## Motivazione
- Il percorso degli ordini e dello stop loss è il punto più critico del sistema (R1.3a): non deve dipendere da
  una libreria abbandonata né da un ponte fra due event loop.
- Il protocollo è semplice (lunghezza + protobuf su TLS), quindi il costo di C è contenuto e prevedibile;
  A e B ereditano tutti i debiti dell'SDK.
- C è l'unica opzione che permette test deterministici dei guasti richiesti da R1.6 (disconnessioni, eventi
  duplicati o fuori ordine, token scaduto, limite di frequenza).
- Il watchdog indipendente può riusare `ctrader_async` senza dipendere da Nautilus.

## Conseguenze
- In F1:
  - TLS e framing;
  - heartbeat ogni 10 s e timeout di inattività in ingresso a 45 s;
  - correlazione per `clientMsgId`;
  - token bucket 50/5 req/s con gestione di `retryAfter`;
  - riconnessione con backoff e jitter, poi ri-autenticazione e Reconcile;
  - refresh del token con scrittura atomica, eseguito da un solo processo per ogni coppia.
- Conversioni centralizzate e testate: prezzi ×1e5, volumi in centesimi di unità, denaro ×10^moneyDigits.
- Gli ordini MARKET partono sempre con `relativeStopLoss`. La dimensione si calcola sulla distanza
  arrotondata effettivamente inviata.

## Prove
- help.ctrader.com/open-api (connection, proxies-endpoints, account-authentication, messages);
  pypi.org/pypi/ctrader-open-api/json; github.com/spotware/OpenApiPy (issue #39 e #43, PR #29);
  nautilustrader.io/docs/latest/developer_guide/python_adapters.
- La prova sperimentale sarà lo spike di F1 (EXP da pre-registrare).
  - Connessione demo e autenticazione.
  - Spot EURUSD per 1 ora senza buchi superiori a 30 s.
  - 10 ordini da 0,01 lot, tutti con SL verificato via `ProtoOAReconcileReq`.
  - 5 riconnessioni forzate recuperate.

## Condizioni di revisione
Si scrive un nuovo ADR che sostituisce questo se:
- lo spike non raggiunge i criteri entro 3 settimane;
- Spotware pubblica un SDK asyncio mantenuto;
- Pepperstone EU blocca l'Open API (`CHANNEL_IS_BLOCKED`) → si valuta il ripiego `MetaTrader5`
  (solo Windows, oppure Wine con `mt5linux`).

## Scartato
- A e B, per i motivi sopra.
- D come dipendenza: resta solo come riferimento.
