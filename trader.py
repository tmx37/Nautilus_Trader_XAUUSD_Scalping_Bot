from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.indicators.averages import ExponentialMovingAverage
from nautilus_trader.indicators.atr import AverageTrueRange
from nautilus_trader.model.data import BarType
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.objects import Quantity, Price


class XAUEMAStrategy(Strategy):

    def __init__(
        self,
        instrument_id: InstrumentId,
        ema_fast=20,
        ema_slow=50,
        ema_htf=200,
        atr_period=14,
        atr_mult=1.5,
        rr_ratio=2.0,
        risk_pct=0.005,
        min_atr=0.5,
    ):
        super().__init__()

        self.instrument_id = instrument_id

        # Indicators (LTF)
        self.ema_fast = ExponentialMovingAverage(ema_fast)
        self.ema_slow = ExponentialMovingAverage(ema_slow)
        self.atr = AverageTrueRange(atr_period)

        # HTF trend filter
        self.ema_htf = ExponentialMovingAverage(ema_htf)

        # Params
        self.atr_mult = atr_mult
        self.rr_ratio = rr_ratio
        self.risk_pct = risk_pct
        self.min_atr = min_atr

        self.last_bar = None

    # ---------------------------
    # Data update
    # ---------------------------
    def on_bar(self, bar):

        if bar.bar_type.is_instrument() is False:
            return

        # session filter (London + NY)
        if not (8 <= bar.ts_start.hour <= 20):
            return

        self.ema_fast.update_raw(bar.close)
        self.ema_slow.update_raw(bar.close)
        self.atr.update_raw(bar)

        # need enough data
        if not self.ema_fast.initialized or not self.ema_slow.initialized:
            return

        if self.atr.value is None or self.atr.value < self.min_atr:
            return

        # avoid multiple signals per bar
        if self.last_bar == bar.ts_start:
            return
        self.last_bar = bar.ts_start

        # trend filter (HTF EMA)
        htf = self.ema_htf.value
        price = bar.close

        trend_up = price > htf
        trend_down = price < htf

        # crossover logic
        fast_prev = self.ema_fast.value
        slow_prev = self.ema_slow.value

        if self.ema_fast.prev_value is None:
            return

        cross_up = self.ema_fast.prev_value < self.ema_slow.prev_value and fast_prev > slow_prev
        cross_down = self.ema_fast.prev_value > self.ema_slow.prev_value and fast_prev < slow_prev

        if self.portfolio.net_position(self.instrument_id) != 0:
            return

        sl_distance = self.atr.value * self.atr_mult

        # ---------------------------
        # LONG
        # ---------------------------
        if cross_up and trend_up:
            self._enter_long(bar, sl_distance)

        # ---------------------------
        # SHORT
        # ---------------------------
        if cross_down and trend_down:
            self._enter_short(bar, sl_distance)

    # ---------------------------
    # Execution
    # ---------------------------
    def _enter_long(self, bar, sl_distance):

        entry = bar.close
        sl = entry - sl_distance
        tp = entry + sl_distance * self.rr_ratio

        qty = self._calc_position_size(sl_distance)

        order = MarketOrder(
            instrument_id=self.instrument_id,
            order_side="BUY",
            quantity=Quantity.from_int(qty),
        )

        self.submit_order(order)

        self.attach_bracket(order, sl=sl, tp=tp)

    def _enter_short(self, bar, sl_distance):

        entry = bar.close
        sl = entry + sl_distance
        tp = entry - sl_distance * self.rr_ratio

        qty = self._calc_position_size(sl_distance)

        order = MarketOrder(
            instrument_id=self.instrument_id,
            order_side="SELL",
            quantity=Quantity.from_int(qty),
        )

        self.submit_order(order)

        self.attach_bracket(order, sl=sl, tp=tp)

    # ---------------------------
    # Risk management
    # ---------------------------
    def _calc_position_size(self, sl_distance):

        equity = self.portfolio.account_balance().total
        risk_amount = equity * self.risk_pct

        instrument = self.cache.instrument(self.instrument_id)

        # value per price unit
        value_per_point = instrument.price_increment_value

        risk_per_lot = sl_distance * value_per_point

        if risk_per_lot <= 0:
            return 0

        qty = risk_amount / risk_per_lot

        return max(1, int(qty))

    # ---------------------------
    # Break-even logic
    # ---------------------------
    def on_position_update(self, position):

        if position.unrealized_pnl <= 0:
            return

        entry = position.avg_px_open
        current = position.mark_price

        risk = abs(entry - position.sl_price)

        if abs(current - entry) >= risk:
            new_sl = entry
            self.modify_position_stop_loss(position, new_sl)