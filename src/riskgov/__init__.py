"""Gestore del rischio: componente separato dalle strategie, con l'ultima parola su ogni ordine (R1.5).

- `riskgov.core`: logica pura e deterministica, senza import di NautilusTrader.
- `riskgov.nautilus`: integrazione (RiskGovernor, unica Strategy del nodo).

Architettura: ADR 0004, PIANO §2.3.
"""
