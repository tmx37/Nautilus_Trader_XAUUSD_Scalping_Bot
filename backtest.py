import pandas as pd
import matplotlib.pyplot as plt

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import BacktestVenueConfig
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType

from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators.averages import ExponentialMovingAverage
from nautilus_trader.indicators.atr import AverageTrueRange
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.objects import Quantity


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
def run_backtest():

    df = pd.read_csv("data/XAUUSD_M1.csv")

    engine = BacktestEngine()

    venue = BacktestVenueConfig(
        name="SIM",
        oms_type="HEDGING",
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=["10000 USD"],
    )

    engine.add_venue(venue)

    instrument_id = InstrumentId.from_str("XAUUSD.SIM")

    strategy = XAUEMAStrategy(instrument_id)
    engine.add_strategy(strategy)

    # =========================
    # CONVERT CSV -> BAR
    # =========================
    bars = []

    for i in range(len(df)):

        ts = pd.to_datetime(df["timestamp"][i])

        bar = Bar(
            bar_type=BarType.from_str("XAUUSD.SIM-1-MINUTE-LAST-EXTERNAL"),
            open=df["open"][i],
            high=df["high"][i],
            low=df["low"][i],
            close=df["close"][i],
            volume=df["volume"][i],
            ts_event=int(ts.timestamp() * 1e9),
            ts_init=int(ts.timestamp() * 1e9),
        )

        bars.append(bar)

    engine.add_data(bars)

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
    run_backtest()