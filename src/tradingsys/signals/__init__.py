"""Actor di segnale (F2): S1 Donchian/ATR H4, S2 breakout del range d'apertura di Londra.

Gli Actor non possono inviare ordini: pubblicano TradeProposal, ExitProposal e StopUpdateProposal, che
il RiskGovernor approva, riduce o rifiuta (ADR 0004).
"""
