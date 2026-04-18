from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators.averages import ExponentialMovingAverage
from nautilus_trader.indicators.atr import AverageTrueRange
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.objects import Quantity


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

        # filtro sessione
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

        # trend filter semplice
        trend_up = bar.close > self.ema_htf.value
        trend_down = bar.close < self.ema_htf.value

        cross_up = self.ema_fast.value > self.ema_slow.value
        cross_down = self.ema_fast.value < self.ema_slow.value

        if self.portfolio.net_position(self.instrument_id) != 0:
            return

        sl_dist = self.atr.value * 1.5

        if cross_up and trend_up:
            order = MarketOrder(
                instrument_id=self.instrument_id,
                order_side="BUY",
                quantity=Quantity.from_int(1),
            )
            self.submit_order(order)

        if cross_down and trend_down:
            order = MarketOrder(
                instrument_id=self.instrument_id,
                order_side="SELL",
                quantity=Quantity.from_int(1),
            )
            self.submit_order(order)