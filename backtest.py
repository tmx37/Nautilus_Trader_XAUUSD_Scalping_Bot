import sys

import pandas as pd
import matplotlib.pyplot as plt

from pathlib import Path

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.config import BacktestEngineConfig

from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.model.identifiers import TraderId, Venue, InstrumentId
from nautilus_trader.model.data import Bar, BarType

from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators.averages import ExponentialMovingAverage
from nautilus_trader.indicators import AverageTrueRange
from nautilus_trader.model.orders import MarketOrder

from nautilus_trader.persistence.wranglers import BarDataWrangler


# =========================
# STRATEGIA
# =========================
class XAUEMAStrategy(Strategy):

    def __init__(self, instrument_id):
        super().__init__()

        self.instrument_id = instrument_id

        self.ema_fast = ExponentialMovingAverage(20)
        self.ema_slow = ExponentialMovingAverage(50)
        self.ema_htf = ExponentialMovingAverage(200)
        self.atr = AverageTrueRange(14)

        self.last_bar = None

    def on_bar(self, bar):

        # session filter
        if not (8 <= bar.ts_start.hour <= 20):
            return

        self.ema_fast.update_raw(bar.close)
        self.ema_slow.update_raw(bar.close)
        self.atr.update_raw(bar)

        if not self.ema_fast.initialized:
            return

        if self.atr.value is None:
            return

        if self.last_bar == bar.ts_start:
            return

        self.last_bar = bar.ts_start

        trend_up = bar.close > self.ema_htf.value
        trend_down = bar.close < self.ema_htf.value

        cross_up = self.ema_fast.value > self.ema_slow.value
        cross_down = self.ema_fast.value < self.ema_slow.value

        if self.portfolio.net_position(self.instrument_id) != 0:
            return

        if cross_up and trend_up:
            self.submit_order(
                MarketOrder(
                    instrument_id=self.instrument_id,
                    order_side="BUY",
                    quantity=Quantity.from_int(1),
                )
            )

        if cross_down and trend_down:
            self.submit_order(
                MarketOrder(
                    instrument_id=self.instrument_id,
                    order_side="SELL",
                    quantity=Quantity.from_int(1),
                )
            )


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

    instrument_id = InstrumentId.from_str("XAUUSD.SIM")

    strategy = XAUEMAStrategy(instrument_id)
    engine.add_strategy(strategy)

    # =========================
    # CONVERT CSV -> BAR
    # =========================
    bars = []

    # suddivido il dataset in chunks di dati, per ottimizzare il carico
    chunk_size = 1000
    for chunk in pd.read_csv(path_string, chunksize=chunk_size):
        
        # converto le colonne in formato leggibile da nautilus
        chunk.columns = [c.strip("<>") for c in chunk.columns]
        chunk.index = pd.to_datetime(chunk["date"] + " " + chunk["time"])
        chunk = chunk.rename(columns={"tickvol": "volume"})[["open", "high", "low", "close", "volume"]]
        
        wrangler = BarDataWrangler(
            bar_type=BarType.from_str("XAUUSD.SIM-10-MINUTE-LAST-EXTERNAL"),
            instrument=instrument_id,  
        )
        bars_chunk = wrangler.process(chunk)
        engine.add_data(bars_chunk)
    
    # df = pd.read_csv(path_string)
    # print("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    # print(df)
    # print("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")


    ## OLD AI SLOP TO FORMAT CSV DATA 
    # for i in range(len(df)):
    #     print("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    #     print(df["<TIME>"][i])
    #     print("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    #     ts = pd.to_datetime(df["<TIME>"][i])
    #     bar = Bar(
    #         bar_type=BarType.from_str("XAUUSD.SIM-1-MINUTE-LAST-EXTERNAL"),
    #         open=df["open"][i],
    #         high=df["high"][i],
    #         low=df["low"][i],
    #         close=df["close"][i],
    #         volume=df["volume"][i],
    #         ts_event=int(ts.timestamp() * 1e9),
    #         ts_init=int(ts.timestamp() * 1e9),
    #     )
    #     bars.append(bar)
    # engine.add_data(bars)

    # =========================
    # RUN
    # =========================
    engine.run()

    # =========================
    # RESULTS
    # =========================
    portfolio = engine.portfolio

    print("\n===== RESULTS =====")
    print("BALANCE:", portfolio.balance())
    print("EQUITY:", portfolio.equity())
    print("REALIZED PNL:", portfolio.realized_pnl())
    print("MAX DRAWDOWN:", portfolio.max_drawdown())

    # =========================
    # EQUITY CURVE
    # =========================
    equity = portfolio.equity_curve()

    plt.plot(equity.timestamps, equity.values)
    plt.title("XAUUSD EMA Strategy Equity Curve")
    plt.show()


if __name__ == "__main__":
    run_backtest(sys.argv[1])
    