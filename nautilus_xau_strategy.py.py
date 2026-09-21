import pandas as pd
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money, Quantity, Price
from nautilus_trader.model.identifiers import TraderId, Venue, InstrumentId, Symbol
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators.averages import ExponentialMovingAverage
from nautilus_trader.indicators.atr import AverageTrueRange
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.orders import MarketOrder

# ==========================================
# CONFIGURAZIONE STRATEGIA
# ==========================================
class XAUEMAStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    ema_fast: int = 20
    ema_slow: int = 50
    ema_htf: int = 200       # Filtro trend
    atr_period: int = 14
    atr_mult: float = 1.5    # Moltiplicatore per SL
    rr_ratio: float = 2.0    # Risk/Reward
    risk_pct: float = 0.005  # Rischio per trade (0.5%)
    min_atr: float = 0.5     # Volatilità minima accettabile
    session_start: int = 8   # UTC
    session_end: int = 20    # UTC

class XAUEMAStrategy(Strategy):
    def __init__(self, config: XAUEMAStrategyConfig):
        super().__init__(config)
        self.config = config
        self.instrument = None
        
        # Indicatori
        self.ema_fast = ExponentialMovingAverage(config.ema_fast)
        self.ema_slow = ExponentialMovingAverage(config.ema_slow)
        self.ema_htf = ExponentialMovingAverage(config.ema_htf)
        self.atr = AverageTrueRange(config.atr_period)
        
        self.last_bar_ts = None

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Strumento {self.config.instrument_id} non trovato nel cache!")
            self.stop()
            return

        # Registrazione indicatori
        self.register_indicator_for_bars(self.config.bar_type, self.ema_fast)
        self.register_indicator_for_bars(self.config.bar_type, self.ema_slow)
        self.register_indicator_for_bars(self.config.bar_type, self.ema_htf)
        self.register_indicator_for_bars(self.config.bar_type, self.atr)
        
        self.subscribe_bars(self.config.bar_type)
        self.log.info(f"Strategia avviata su {self.config.instrument_id}")

    def on_bar(self, bar: Bar):
        # 1. Filtro Sessione (UTC)
        dt = datetime.fromtimestamp(bar.ts_init // 1_000_000_000, tz=timezone.utc)
        if not (self.config.session_start <= dt.hour < self.config.session_end):
            return

        # 2. Aggiornamento Indicatori
        self.ema_fast.update_raw(bar.close)
        self.ema_slow.update_raw(bar.close)
        self.ema_htf.update_raw(bar.close) # Semplificazione: uso close barra corrente per HTF
        self.atr.update_raw(bar)

        # 3. Check Inizializzazione
        if not (self.ema_fast.initialized and self.ema_slow.initialized and 
                self.ema_htf.initialized and self.atr.initialized):
            return

        # 4. Check Volatilità Minima
        if self.atr.value < self.config.min_atr:
            return

        # 5. Evita segnali multipli sulla stessa barra
        if self.last_bar_ts == bar.ts_init:
            return
        self.last_bar_ts = bar.ts_init

        # 6. Check Posizione Aperta (No Pyramiding)
        if self.portfolio.net_position(self.config.instrument_id) != 0:
            return

        # 7. Logica di Trading
        price = float(bar.close)
        htf_val = self.ema_htf.value
        
        # Trend Filter
        trend_up = price > htf_val
        trend_down = price < htf_val

        # Crossover Logic (Incrocio appena avvenuto)
        # Confronto tra valore precedente e attuale
        fast_prev = self.ema_fast.prev_value
        slow_prev = self.ema_slow.prev_value
        fast_curr = self.ema_fast.value
        slow_curr = self.ema_slow.value

        if fast_prev is None or slow_prev is None:
            return

        cross_up = (fast_prev <= slow_prev) and (fast_curr > slow_curr)
        cross_down = (fast_prev >= slow_prev) and (fast_curr < slow_curr)

        sl_distance = self.atr.value * self.config.atr_mult

        if cross_up and trend_up:
            self._enter_long(bar, sl_distance)
        elif cross_down and trend_down:
            self._enter_short(bar, sl_distance)

    def _enter_long(self, bar, sl_distance):
        entry = float(bar.close)
        sl = entry - sl_distance
        tp = entry + (sl_distance * self.config.rr_ratio)
        
        qty = self._calculate_qty(sl_distance)
        if qty <= 0:
            return

        order = MarketOrder(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_float(qty, precision=self.instrument.size_precision),
        )
        self.submit_order(order)
        # Nota: Nautilus non ha attach_bracket nativo su MarketOrder submit diretto in tutte le versioni
        # Si usa solitamente un OrderList (Bracket) creato tramite order_factory
        self._submit_bracket(OrderSide.BUY, qty, entry, sl, tp)

    def _enter_short(self, bar, sl_distance):
        entry = float(bar.close)
        sl = entry + sl_distance
        tp = entry - (sl_distance * self.config.rr_ratio)
        
        qty = self._calculate_qty(sl_distance)
        if qty <= 0:
            return

        order = MarketOrder(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=Quantity.from_float(qty, precision=self.instrument.size_precision),
        )
        self.submit_order(order)
        self._submit_bracket(OrderSide.SELL, qty, entry, sl, tp)

    def _submit_bracket(self, side, qty, entry, sl, tp):
        try:
            bracket = self.order_factory.bracket(
                instrument_id=self.config.instrument_id,
                order_side=side,
                quantity=Quantity.from_float(qty, precision=self.instrument.size_precision),
                sl_trigger_price=Price.from_str(f"{sl:.2f}"),
                tp_price=Price.from_str(f"{tp:.2f}"),
            )
            self.submit_order_list(bracket)
        except Exception as e:
            self.log.error(f"Errore creazione bracket: {e}")

    def _calculate_qty(self, sl_distance):
        # Recupero equilibrio account
        account = self.portfolio.account(self.config.instrument_id.venue)
        if not account:
            return 0
        
        equity = account.balance_total(USD) # Assumendo USD come base
        risk_amount = equity * self.config.risk_pct
        
        # Calcolo valore per punto (dipende dallo strumento)
        # Per XAUUSD standard: 1 lotto = 100 once. Movimento 1.00$ = 100$
        # Nautilus gestisce questo tramite instrument specifications
        value_per_point = self.instrument.price_increment_value * (1 / self.instrument.price_increment)
        
        # Rischio per lotto unitario
        risk_per_unit = sl_distance * value_per_point
        
        if risk_per_unit <= 0:
            return 0
            
        qty = risk_amount / risk_per_unit
        
        # Arrotondamento alla precisione dello strumento
        min_qty = float(self.instrument.min_quantity)
        step = float(self.instrument.size_increment)
        
        calculated_qty = max(min_qty, qty)
        # Arrotonda al passo più vicino
        final_qty = round(calculated_qty / step) * step
        
        return final_qty

    def on_position_update(self, position):
        # Logica Break-Even
        if position.is_closed:
            return
            
        if position.unrealized_pnl(USD) > 0:
            entry = float(position.avg_px_open)
            current = float(position.mark_price)
            
            # Calcola rischio iniziale (distanza entry - SL originale)
            # Nota: recuperare lo SL originale da Nautilus può richiedere di salvarlo in un dict
            # Qui usiamo una logica semplificata: se PnL > Rischio Iniziale stimato
            # Per una gestione precisa, salva lo SL iniziale in self.position_sl[position.id]
            
            # Implementazione semplificata BE: se prezzo ha corso di 1x Rischio
            # Serve recuperare lo SL iniziale. Se non salvato, stimiamo:
            # (Questa parte richiede di salvare lo SL al momento dell'ingresso per essere precisa)
            pass 

    def on_stop(self):
        self.close_all_positions(self.config.instrument_id)
        self.unsubscribe_bars(self.config.bar_type)

# ==========================================
# ESECUZIONE BACKTEST
# ==========================================
def run_backtest(csv_path: str):
    path = Path(csv_path)
    if not path.exists():
        print(f"File non trovato: {csv_path}")
        return

    # Setup Engine
    engine = BacktestEngine(
        config=BacktestEngineConfig(trader_id=TraderId("BACKTESTER-001"))
    )

    venue = Venue("SIM")
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(10_000, USD)], # Capitale iniziale aumentato per test seri
    )

    # Definizione Strumento XAUUSD
    instrument = CurrencyPair(
        instrument_id=InstrumentId(Symbol("XAUUSD"), venue),
        raw_symbol=Symbol("XAUUSD"),
        base_currency=Currency.from_str("XAU"), # Nautilus richiede base/quote corretti
        quote_currency=USD,
        price_precision=2,
        size_precision=2,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.01"),
        min_quantity=Quantity.from_str("0.01"),
        margin_init=Decimal("0.02"), # 2% margine iniziale (leverage 50x)
        margin_maint=Decimal("0.01"),
        maker_fee=Decimal("0.0001"), # 0.01% fee realistica
        taker_fee=Decimal("0.0002"), # 0.02% fee realistica
        ts_event=0,
        ts_init=0,
    )
    engine.add_instrument(instrument)

    # Configurazione Strategia
    bar_type = BarType.from_str("XAUUSD.SIM-10-MINUTE-LAST-EXTERNAL") # Impostato su M10 come richiesto
    
    strategy_config = XAUEMAStrategyConfig(
        instrument_id=InstrumentId.from_str("XAUUSD.SIM"),
        bar_type=bar_type,
        ema_fast=20,
        ema_slow=50,
        ema_htf=200,
        atr_period=14,
        atr_mult=1.5,
        rr_ratio=2.0,
        risk_pct=0.01, # 1% rischio per trade
        min_atr=0.8,   # Adatta per M10
        session_start=8,
        session_end=20,
    )
    
    strategy = XAUEMAStrategy(config=strategy_config)
    engine.add_strategy(strategy)

    # Caricamento Dati CSV
    print("Caricamento dati CSV...")
    df = pd.read_csv(path, sep='\t') # Assicurati che il separatore sia corretto
    
    # Parsing Timestamp
    # Assumendo colonne: <DATE>, <TIME>, <OPEN>, <HIGH>, <LOW>, <CLOSE>, <TICKVOL>
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"])
    df = df.sort_values("datetime")
    
    bars = []
    for _, row in df.iterrows():
        ts_ns = int(row["datetime"].timestamp() * 1e9)
        
        o = round(float(row["<OPEN>"]), 2)
        h = round(float(row["<HIGH>"]), 2)
        l = round(float(row["<LOW>"]), 2)
        c = round(float(row["<CLOSE>"]), 2)
        v = float(row["<TICKVOL>"])

        # Sanity Check Prezzi
        if not (l <= o <= h) or not (l <= c <= h):
            continue
            
        bar = Bar(
            bar_type=bar_type,
            open=Price.from_str(f"{o:.2f}"),
            high=Price.from_str(f"{h:.2f}"),
            low=Price.from_str(f"{l:.2f}"),
            close=Price.from_str(f"{c:.2f}"),
            volume=Quantity.from_float(v, precision=2),
            ts_event=ts_ns,
            ts_init=ts_ns,
        )
        bars.append(bar)

    print(f"Aggiunte {len(bars)} barre al motore.")
    engine.add_data(bars)
    
    # Esecuzione
    engine.run()
    
    # Risultati
    print("\n===== RISULTATI BACKTEST =====")
    print(engine.trader.generate_account_report(venue))
    print("\n--- Posizioni ---")
    print(engine.trader.generate_positions_report())
    print("\n--- Ordini ---")
    print(engine.trader.generate_orders_report())

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_backtest(sys.argv[1])
    else:
        print("Usage: python nautilus_xau_strategy.py <path_to_csv>")