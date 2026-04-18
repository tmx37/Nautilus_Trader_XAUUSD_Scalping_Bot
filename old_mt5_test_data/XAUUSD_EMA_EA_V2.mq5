//+------------------------------------------------------------------+
//|  XAUUSD_EMA_EA.mq5                                               |
//|  Strategia: EMA 20/50 crossover + ATR stop loss adattivo         |
//|  Simbolo consigliato: XAUUSD  |  Timeframe: M5/M15               |
//|  Versione senza #include — usa OrderSend nativo                  |
//+------------------------------------------------------------------+
#property copyright "Uso personale"
#property version   "1.01"

//--- Parametri configurabili dall'utente
input double RiskPercent    = 0.5;      // Rischio per trade (% del saldo), 0.5 più adatto per 1k$ di budget
input int    EMA_Fast       = 20;       // Periodo EMA veloce
input int    EMA_Slow       = 50;       // Periodo EMA lenta
input int    ATR_Period     = 14;       // Periodo ATR
input double ATR_Multiplier = 1.5;     // Moltiplicatore ATR per SL
input double RR_Ratio       = 2.0;     // Rapporto Risk/Reward
input int    MagicNumber    = 20240001; // ID univoco EA
input int    Slippage       = 30;       // Slippage massimo in punti
input double Min_ATR = 0.5; 

//--- Handle indicatori
int emaFastHandle, emaSlowHandle, atrHandle, emaHTFHandle;

//+------------------------------------------------------------------+
int OnInit()
  {
   emaFastHandle = iMA(_Symbol, PERIOD_CURRENT, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   emaSlowHandle = iMA(_Symbol, PERIOD_CURRENT, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   atrHandle     = iATR(_Symbol, PERIOD_CURRENT, ATR_Period);

   if(emaFastHandle == INVALID_HANDLE ||
      emaSlowHandle == INVALID_HANDLE ||
      atrHandle     == INVALID_HANDLE)
     {
      Print("ERRORE: impossibile creare gli indicatori");
      return INIT_FAILED;
     }
     
   emaHTFHandle = iMA(_Symbol, PERIOD_M15, 200, 0, MODE_EMA, PRICE_CLOSE);
   if(emaHTFHandle == INVALID_HANDLE)
     {
      Print("Errore EMA HTF");
      return INIT_FAILED;
     }

   Print("EA avviato su ", _Symbol, " TF:", EnumToString(Period()));
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(emaFastHandle);
   IndicatorRelease(emaSlowHandle);
   IndicatorRelease(atrHandle);
   IndicatorRelease(emaHTFHandle);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // Filtro per orario di mercato (USD, rientra nella timezone e funziona solo con mercati operativi)
   MqlDateTime timeStruct;
   TimeToStruct(TimeCurrent(), timeStruct);
   int hour = timeStruct.hour;
   if(hour < 8 || hour > 20) return; 
   
   // Filtro x lo spread
   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID)) / _Point;
   if(spread > 50) return; // 50 punti su XAUUSD
  
   ManageBreakEven();
  
   // Esegui solo su nuova candela (evita segnali multipli sulla stessa barra)
   static datetime lastBar = 0;
   datetime currentBar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(currentBar == lastBar) return;
   lastBar = currentBar;

   // Leggi indicatori (indice 0 = candela appena chiusa, 1 = precedente)
   double emaFast[], emaSlow[], atr[];
   ArraySetAsSeries(emaFast, true);
   ArraySetAsSeries(emaSlow, true);
   ArraySetAsSeries(atr,     true);

   if(CopyBuffer(emaFastHandle, 0, 1, 3, emaFast) < 3) return;
   if(CopyBuffer(emaSlowHandle, 0, 1, 3, emaSlow) < 3) return;
   if(CopyBuffer(atrHandle,     0, 1, 3, atr)     < 3) return;

   if(atr[0] < Min_ATR) return; // evita mercato "piatto"

   double emaHTF[];
   ArraySetAsSeries(emaHTF, true);
   
   if(CopyBuffer(emaHTFHandle, 0, 1, 1, emaHTF) < 1) return;
   
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   
   bool trendUp   = price > emaHTF[0];
   bool trendDown = price < emaHTF[0];

   // Segnali crossover
   bool crossUp   = (emaFast[1] < emaSlow[1]) && (emaFast[0] > emaSlow[0]);
   bool crossDown = (emaFast[1] > emaSlow[1]) && (emaFast[0] < emaSlow[0]);

   if(!crossUp && !crossDown) return;
   if(CountOpenPositions() > 0) return;

   double spreadPrice = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double slDistance = (atr[0] * ATR_Multiplier) + spreadPrice;
   
   double lotSize    = CalculateLotSize(slDistance);
   if(lotSize <= 0) return;

   if(crossUp && trendUp) 
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl    = price - slDistance;
      double tp    = price + slDistance * RR_Ratio;
      OpenOrder(ORDER_TYPE_BUY, lotSize, price, sl, tp);
     }

   if(crossDown && trendDown)
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl    = price + slDistance;
      double tp    = price - slDistance * RR_Ratio;
      OpenOrder(ORDER_TYPE_SELL, lotSize, price, sl, tp);
     }
  }

//+------------------------------------------------------------------+
void OpenOrder(ENUM_ORDER_TYPE type, double lots, double price,
               double sl, double tp)
  {
   MqlTradeRequest  req = {};
   MqlTradeResult   res = {};

   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = _Symbol;
   req.volume       = lots;
   req.type         = type;
   req.price        = price;
   req.sl           = NormalizeDouble(sl, _Digits);
   req.tp           = NormalizeDouble(tp, _Digits);
   req.deviation    = Slippage;
   req.magic        = MagicNumber;
   req.comment      = (type == ORDER_TYPE_BUY) ? "EMA BUY" : "EMA SELL";
   req.type_filling = ORDER_FILLING_IOC;

   if(!OrderSend(req, res))
      Print("OrderSend fallito: errore=", GetLastError(), " retcode=", res.retcode);
   else
      Print("Trade aperto: ", EnumToString(type),
            " lots=", lots, " price=", price,
            " SL=", req.sl, " TP=", req.tp);
  }

//+------------------------------------------------------------------+
double CalculateLotSize(double slDistance)
  {
   double balance      = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount   = balance * (RiskPercent / 100.0);

   double tickSize     = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue    = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double lotStep      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot       = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot       = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   if(tickSize == 0 || tickValue == 0) return 0;

   double slValuePerLot = (slDistance / tickSize) * tickValue;
   if(slValuePerLot == 0) return 0;

   double lots = riskAmount / slValuePerLot;
   lots = MathFloor(lots / lotStep) * lotStep;
   lots = MathMax(minLot, MathMin(maxLot, lots));

   return lots;
  }

//+------------------------------------------------------------------+
int CountOpenPositions()
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
         if(PositionGetString(POSITION_SYMBOL)  == _Symbol &&
            PositionGetInteger(POSITION_MAGIC)  == MagicNumber)
            count++;
     }
   return count;
  }
//+------------------------------------------------------------------+
void ManageBreakEven()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;

      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);

      double price;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      else
         price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

      double risk = MathAbs(entry - sl);

      // ✅ evita modifiche inutili
      if(MathAbs(sl - entry) < (_Point * 5)) continue;

      if(MathAbs(price - entry) >= risk)
      {
         MqlTradeRequest req = {};
         MqlTradeResult res = {};

         req.action   = TRADE_ACTION_SLTP;
         req.position = ticket;
         req.sl       = NormalizeDouble(entry, _Digits);
         req.tp       = tp;

         if(!OrderSend(req, res))
            Print("Errore BE: ", GetLastError());
      }
   }
}
//+------------------------------------------------------------------+