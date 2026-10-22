//+------------------------------------------------------------------+
//|  XAUUSD_EMA_EA.mq5                                               |
//|  Strategia: EMA 20/50 crossover + ATR stop loss adattivo         |
//|  Simbolo consigliato: XAUUSD  |  Timeframe: M5                   |
//|  Solo per uso su conto DEMO finché non testato a lungo            |
//+------------------------------------------------------------------+
#property copyright "Uso personale"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>   // libreria ordini standard MT5

//--- Parametri configurabili dall'utente (visibili nel pannello EA)
input double   RiskPercent    = 1.0;   // Rischio per trade (% del saldo)
input int      EMA_Fast       = 20;    // Periodo EMA veloce
input int      EMA_Slow       = 50;    // Periodo EMA lenta
input int      ATR_Period     = 14;    // Periodo ATR per stop loss
input double   ATR_Multiplier = 1.5;   // Moltiplicatore ATR per SL
input double   RR_Ratio       = 2.0;   // Rapporto Risk/Reward (TP = SL x RR)
input int      MagicNumber    = 20240001; // ID univoco di questo EA

//--- Oggetti globali
CTrade trade;
int    emaFastHandle, emaSlowHandle, atrHandle;

//+------------------------------------------------------------------+
//| Inizializzazione: viene chiamata una volta all'avvio              |
//+------------------------------------------------------------------+
int OnInit()
  {
   // Crea gli handle degli indicatori (calcolati da MT5 internamente)
   emaFastHandle = iMA(_Symbol, PERIOD_CURRENT, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   emaSlowHandle = iMA(_Symbol, PERIOD_CURRENT, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   atrHandle     = iATR(_Symbol, PERIOD_CURRENT, ATR_Period);

   if(emaFastHandle == INVALID_HANDLE ||
      emaSlowHandle == INVALID_HANDLE ||
      atrHandle     == INVALID_HANDLE)
     {
      Print("Errore nella creazione degli indicatori. Controlla il simbolo.");
      return INIT_FAILED;
     }

   trade.SetMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30); // slippage massimo accettato

   Print("EA avviato correttamente su ", _Symbol);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Pulizia: chiamata quando l'EA viene rimosso                       |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(emaFastHandle);
   IndicatorRelease(emaSlowHandle);
   IndicatorRelease(atrHandle);
  }

//+------------------------------------------------------------------+
//| OnTick: viene chiamata ad ogni variazione di prezzo               |
//+------------------------------------------------------------------+
void OnTick()
  {
   // Lavoriamo solo sulla chiusura della candela precedente (evita segnali falsi)
   // Controlla se è una nuova candela
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(currentBarTime == lastBarTime) return; // stessa candela, niente da fare
   lastBarTime = currentBarTime;

   // --- Leggi i valori degli indicatori sulle ultime 3 candele ---
   double emaFast[], emaSlow[], atr[];
   ArraySetAsSeries(emaFast, true);
   ArraySetAsSeries(emaSlow, true);
   ArraySetAsSeries(atr,     true);

   // Copia i dati (3 valori: indice 0 = candela appena chiusa, 1 = precedente)
   if(CopyBuffer(emaFastHandle, 0, 1, 3, emaFast) < 3) return;
   if(CopyBuffer(emaSlowHandle, 0, 1, 3, emaSlow) < 3) return;
   if(CopyBuffer(atrHandle,     0, 1, 3, atr)     < 3) return;

   // --- Logica del segnale ---
   // Crossover rialzista: candela precedente EMA fast < EMA slow
   //                      candela attuale  EMA fast > EMA slow
   bool crossUp   = (emaFast[1] < emaSlow[1]) && (emaFast[0] > emaSlow[0]);
   bool crossDown = (emaFast[1] > emaSlow[1]) && (emaFast[0] < emaSlow[0]);

   // --- Conta le posizioni aperte da questo EA ---
   int totalPositions = CountOpenPositions();

   // --- Apertura nuovi trade ---
   double price, sl, tp, lotSize;
   double slDistance = atr[0] * ATR_Multiplier; // SL in punti prezzo

   if(crossUp && totalPositions == 0)
     {
      price   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      sl      = price - slDistance;
      tp      = price + slDistance * RR_Ratio;
      lotSize = CalculateLotSize(slDistance);

      if(lotSize > 0)
        {
         trade.Buy(lotSize, _Symbol, price, sl, tp, "EMA Cross BUY");
         Print("BUY aperto: price=", price, " SL=", sl, " TP=", tp, " lots=", lotSize);
        }
     }

   if(crossDown && totalPositions == 0)
     {
      price   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      sl      = price + slDistance;
      tp      = price - slDistance * RR_Ratio;
      lotSize = CalculateLotSize(slDistance);

      if(lotSize > 0)
        {
         trade.Sell(lotSize, _Symbol, price, sl, tp, "EMA Cross SELL");
         Print("SELL aperto: price=", price, " SL=", sl, " TP=", tp, " lots=", lotSize);
        }
     }
  }

//+------------------------------------------------------------------+
//| Calcola il size del lotto basato sul rischio percentuale          |
//| Formula: lotto = (saldo * rischio%) / (SL in punti * valore pip) |
//+------------------------------------------------------------------+
double CalculateLotSize(double slDistance)
  {
   double balance      = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount   = balance * (RiskPercent / 100.0); // es. 1% di €1000 = €10

   double tickSize     = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue    = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double lotStep      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot       = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot       = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   if(tickSize == 0 || tickValue == 0) return 0;

   // Converti la distanza SL in "numero di tick"
   double slTicks = slDistance / tickSize;

   // Valore monetario di 1 lotto per la distanza SL
   double slValuePerLot = slTicks * tickValue;
   if(slValuePerLot == 0) return 0;

   // Lotti necessari per rischiare esattamente riskAmount
   double lots = riskAmount / slValuePerLot;

   // Arrotonda al lotStep del broker (es. 0.01)
   lots = MathFloor(lots / lotStep) * lotStep;

   // Rispetta i limiti del broker
   lots = MathMax(minLot, MathMin(maxLot, lots));

   return lots;
  }

//+------------------------------------------------------------------+
//| Conta le posizioni aperte da questo EA specifico                  |
//+------------------------------------------------------------------+
int CountOpenPositions()
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
        {
         if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
            PositionGetInteger(POSITION_MAGIC) == MagicNumber)
            count++;
        }
     }
   return count;
  }
//+------------------------------------------------------------------+
