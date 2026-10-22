"""Integrazione del gestore del rischio con NautilusTrader (F1).

- `RiskGovernor(Strategy)`: unico componente autorizzato a inviare ordini. Riceve le proposte dagli Actor
  di segnale (publish_message), chiama `riskgov.core`, scrive il journal prima dell'invio, invia bracket
  con SL obbligatorio.
- Persistenza atomica dello snapshot di rischio e di `ARRESTO.lock`.
"""
