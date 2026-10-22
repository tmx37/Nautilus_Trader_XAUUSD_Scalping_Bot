"""Client asyncio nativo per cTrader Open API (protobuf su TLS, porta 5035).

Nessuna dipendenza da NautilusTrader né dal resto del sistema (contratto import-linter): lo usano sia
l'adapter `nt_ctrader` sia il watchdog. Decisione: ADR 0001.

Da implementare in F1 (PIANO §2.1):
- framing (4 byte di lunghezza + ProtoMessage) e connessione TLS a demo/live.ctraderapi.com;
- heartbeat ogni 10 s e timeout di inattività in ingresso;
- correlazione richiesta/risposta per clientMsgId;
- token bucket 50 req/s e 5 req/s per lo storico, con gestione di retryAfter;
- riconnessione con backoff e jitter, ri-autenticazione app/account;
- refresh del token OAuth con scrittura atomica (il refresh invalida la coppia precedente);
- conversioni di unità: prezzi ×1e5, volumi in centesimi di unità, denaro ×10^moneyDigits.
"""
