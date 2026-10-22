"""Core puro del gestore del rischio: sizing, floor, macchina a stati, limiti, riconciliazione.

Nessuna dipendenza da NautilusTrader (contratto import-linter), così lo stesso codice gira nei test basati
su proprietà, nel Monte Carlo di calibrazione e nel nodo live.
"""
