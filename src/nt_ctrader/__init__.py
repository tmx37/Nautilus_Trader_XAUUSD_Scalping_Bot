"""Adapter NautilusTrader (v2, Python Adapter Interface) per cTrader Open API.

Progetto indipendente, non affiliato né approvato da Nautech Systems; il prefisso `nt_` rispetta le
indicazioni sul marchio NautilusTrader. Poggia su `ctrader_async` (ADR 0001) e su nautilus_trader 2.0.0rc7
(ADR 0002).

Da implementare in F1 (PIANO §2.1):
- InstrumentProvider: ProtoOASymbol → CurrencyPair con le specifiche del broker;
- MarketDataClient: spot → QuoteTick, trendbar;
- ExecutionClient: bracket Nautilus → un solo ProtoOANewOrderReq con SL/TP relativi; modifica dello SL
  figlio → ProtoOAAmendPositionSLTPReq; mass status per la riconciliazione; OMS HEDGING con
  venue_position_id; rifiuto fail-closed di ogni ingresso senza SL.
"""
