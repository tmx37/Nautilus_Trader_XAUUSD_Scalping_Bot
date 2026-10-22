"""Watchdog indipendente (processo e host separati, sessione cTrader propria via `ctrader_async`).

Fase 1: Reconcile ogni 60 s e avvisi. Fase 2: SL d'emergenza su posizioni senza SL da oltre 120 s.
Fase 3: chiusura totale se il DD supera la soglia del watchdog, più larga di quella del nodo.
Non importa NautilusTrader (contratto import-linter).
"""
