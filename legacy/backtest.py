import sys

import pandas as pd
import matplotlib.pyplot as plt
import string 
from decimal import Decimal

from pathlib import Path

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.config import StrategyConfig

from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.currencies import USD, Currency
from nautilus_trader.model.objects import Money, Quantity, Price, Currency
from nautilus_trader.model.identifiers import TraderId, Venue, InstrumentId, Symbol
from nautilus_trader.model.data import Bar, BarType

from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators.averages import ExponentialMovingAverage
from nautilus_trader.indicators import AverageTrueRange
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.instruments import CurrencyPair

# =========================
# STRATEGIA
# =========================
class XAUEMAStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    ema_fast: int = 21
    ema_slow: int = 50
    ema_trend: int = 200        # ✅ filtro trend H1
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    trade_size: float = 0.1
    min_ema_diff: float = 0.20
    session_start: int = 8      # ✅ solo ore 08:00-17:00 UTC (Londra + NY)
    session_end: int = 17

class XAUEMAStrategy(Strategy):
    def __init__(self, config: XAUEMAStrategyConfig):
        super().__init__(config)
        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.ema_fast = ExponentialMovingAverage(config.ema_fast)
        self.ema_slow = ExponentialMovingAverage(config.ema_slow)
        self.ema_trend = ExponentialMovingAverage(config.ema_trend)  # ✅
        self.atr = AverageTrueRange(config.atr_period)
        self.instrument = None

    def on_start(self):
        self.instrument = self.cache.instrument(self.instrument_id)
        self.register_indicator_for_bars(self.bar_type, self.ema_fast)
        self.register_indicator_for_bars(self.bar_type, self.ema_slow)
        self.register_indicator_for_bars(self.bar_type, self.ema_trend)
        self.register_indicator_for_bars(self.bar_type, self.atr)
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar):
        if not self.ema_fast.initialized or not self.ema_slow.initialized \
                or not self.ema_trend.initialized or not self.atr.initialized:
            return

        # ✅ Filtro sessione: solo Londra + NY
        hour = bar.ts_event // 1_000_000_000  # ns -> s
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(bar.ts_event / 1e9, tz=timezone.utc)
        if not (self.config.session_start <= dt.hour < self.config.session_end):
            return

        fast  = self.ema_fast.value
        slow  = self.ema_slow.value
        trend = self.ema_trend.value
        diff  = fast - slow

        # Chiudi posizione contraria
        if self.portfolio.is_net_long(self.instrument_id) and diff < -self.config.min_ema_diff:
            self.close_all_positions(self.instrument_id)
        elif self.portfolio.is_net_short(self.instrument_id) and diff > self.config.min_ema_diff:
            self.close_all_positions(self.instrument_id)

        if not self.portfolio.is_flat(self.instrument_id):
            return

        close = float(bar.close)

        # ✅ Entra SOLO in direzione del trend EMA200
        if diff > self.config.min_ema_diff and close > trend:
            self._enter(OrderSide.BUY, bar.close)
        elif diff < -self.config.min_ema_diff and close < trend:
            self._enter(OrderSide.SELL, bar.close)

    def _enter(self, side: OrderSide, close: Price):
        atr     = self.atr.value
        sl_dist = atr * self.config.sl_atr_mult
        tp_dist = atr * self.config.tp_atr_mult
        price   = float(close)

        if side == OrderSide.BUY:
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist

        bracket = self.order_factory.bracket(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(self.config.trade_size),
            sl_trigger_price=Price.from_str(f"{sl:.2f}"),
            tp_price=Price.from_str(f"{tp:.2f}"),
        )
        self.submit_order_list(bracket)

    def on_stop(self):
        self.close_all_positions(self.instrument_id)
        self.unsubscribe_bars(self.bar_type)

# =========================
# BACKTEST ENGINE
# =========================
def run_backtest(input):
    
    path_string = Path(input)
    
    engine = BacktestEngine(
        config=BacktestEngineConfig(trader_id=TraderId("BACKTESTER-001"))
    )

    venue = Venue("SIM")
    engine.add_venue(
        venue = venue,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN, 
        base_currency=USD,
        starting_balances=[Money(1_000, USD)],
    )

    instrument = CurrencyPair(
        instrument_id=InstrumentId(Symbol("XAUUSD"), venue),
        raw_symbol=Symbol("XAUUSD"),
        base_currency=Currency.from_str("XAU"),
        quote_currency=USD,
        price_precision=2,
        size_precision=2,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.01"),
        lot_size=None,
        max_quantity=None,
        min_quantity=Quantity.from_str("0.01"),
        max_notional=None,
        min_notional=None,
        max_price=None,
        min_price=None,
        margin_init=Decimal("0.02"),
        margin_maint=Decimal("0.01"),
        maker_fee=Decimal("0.0"),
        taker_fee=Decimal("0.0"),
        ts_event=0,
        ts_init=0,
    )
    engine.add_instrument(instrument)

    # instrument_id = instrument.id
    # strategy = XAUEMAStrategy(instrument_id)
    # engine.add_strategy(strategy)
    
    bar_type = BarType.from_str("XAUUSD.SIM-1-MINUTE-LAST-EXTERNAL")
    strategy = XAUEMAStrategy(config=XAUEMAStrategyConfig(
        instrument_id=InstrumentId.from_str("XAUUSD.SIM"),
        bar_type=bar_type,
        ema_fast=9,
        ema_slow=21,
        trade_size=0.1,
    ))
    engine.add_strategy(strategy)

    # =========================
    # CONVERT CSV -> BAR
    # =========================
    bars = []
    df = pd.read_csv(path_string, sep='\t')
    
    # combinare le due colonne in un unico timestamp
    df["<TIMESTAMP>"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"])
    
    for i in range(len(df)):
        ts = df["<TIMESTAMP>"][i]
        ts_ns = int(ts.timestamp() * 1e9)
        
        o = round(float(df["<OPEN>"][i]), 2)
        h = round(float(df["<HIGH>"][i]), 2)
        l = round(float(df["<LOW>"][i]), 2)
        c = round(float(df["<CLOSE>"][i]), 2)

        if not (l <= o <= h) or not (l <= c <= h):
            print(f"[SKIP] Row {i}: O={o} H={h} L={l} C={c}")
            continue

        h = max(o, h, l, c)
        l = min(o, l, h, c)
        
        bar = Bar(
            bar_type=BarType.from_str("XAUUSD.SIM-1-MINUTE-LAST-EXTERNAL"),
            open=Price.from_str(f"{o:.2f}"),
            high=Price.from_str(f"{h:.2f}"),
            low=Price.from_str(f"{l:.2f}"),
            close=Price.from_str(f"{c:.2f}"),
            volume=Quantity.from_str(f"{df["<TICKVOL>"][i]:.2f}"),
            ts_event=ts_ns,
            ts_init=ts_ns,
        )
        
        bars.append(bar)
        
    engine.add_data(bars)
    engine.run()
    
    # Statistiche generali
    print("\n===== RESULTS =====")
    stats = engine.get_result()
    print(stats)  # stampa tutto il summary

    # Oppure accedi ai singoli valori
    for stat in engine.trader.generate_account_report(Venue("SIM")):
        print(stat)

    # Recupera gli account events
    portfolio = engine.trader.generate_account_report(Venue("SIM"))
    print(portfolio)

    # Equity curve tramite gli order fills
    fills = engine.trader.generate_order_fills_report()
    print(fills)

    # PnL per trade
    trades = engine.trader.generate_positions_report()
    print(trades)

if __name__ == "__main__":
    run_backtest(sys.argv[1])
    