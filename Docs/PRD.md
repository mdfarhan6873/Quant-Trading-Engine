# Product Requirements Document (PRD): AI-Driven Scalping Engine

## 1. Project Overview
**Objective:** Develop a low-latency, automated scalping trading algorithm that utilizes an LLM (Large Language Model) as a strategic brain. The system will initially run in a **Paper Trading (Simulated)** mode using real-time market data from the **Shoonya API** to validate accuracy without financial risk.

## 2. Recommended Tech Stack (The "Super Best" Stack)
To achieve extreme speed while avoiding unnecessary complexity, we do **not** need a separate middle layer like NestJS. Adding NestJS would force us to pass data between Python and Node.js, slowing things down. 

Instead, we will use this highly optimized architecture:

*   **Trading Engine & Backend API:** **Python (FastAPI + `asyncio`)**
    *   *Why:* FastAPI is one of the fastest backend frameworks available (on par with Node.js/Go). Python will handle the complex algorithms, talk to the LLM, execute the trades, AND serve the API for your frontend.
*   **In-Memory State (The Bridge):** **Redis**
    *   *Why:* The Python engine writes live PnL, active trades, and tick data to Redis in microseconds. Your frontend will instantly read this data.
*   **Frontend Dashboard:** **Next.js (React) + Tailwind CSS**
    *   *Why:* Next.js is the absolute best choice for the UI. It will connect to the Python backend via WebSockets to give you a beautiful, live view of exactly what the LLM and trading algorithm are doing in real-time.
*   **Broker API:** **Shoonya (Finvasia) WebSocket & REST API**
    *   *Why:* Zero brokerage, free API, and reliable WebSocket streams.
*   **LLM Provider:** **Anthropic Claude 3.5 Sonnet/Opus** or **Google Gemini 1.5 Pro**
    *   *Why:* Superior context window and advanced logical reasoning required for analyzing complex market data and rule bases.

## 3. System Architecture (The "Hybrid Brain" Approach)
Because LLMs have a latency of 2-10 seconds, the LLM cannot make the final tick-by-tick scalp trigger. The system is split into two independent loops:

### A. The Fast Loop (Execution Engine - Milliseconds)
1.  Connects to the Shoonya WebSocket to receive live price ticks.
2.  Stores the latest prices, volumes, and Option Greeks in Redis.
3.  Evaluates the live price against the *current active strategy parameters* (provided by the Slow Loop).
4.  If conditions are met, it triggers a **Paper Trade** (logs entry price, sets virtual Stop Loss and Target).

### B. The Slow Loop (LLM Strategy Engine - Minutes)
1.  Every 1 to 5 minutes, it pulls the latest market state (last few candles, major OI changes, current VIX) from Redis.
2.  Packages this data along with your "Trading Knowledge Base" into a prompt.
3.  Sends the prompt to the LLM.
4.  The LLM replies with a structured JSON strategy (e.g., `{"bias": "bullish", "trigger_price": 22100, "strike_preference": "ITM_1", "sl": 22080, "target": 22140}`).
5.  Saves this strategy to Redis for the Fast Loop to execute.

## 4. Option Chain & Greeks Management (Strike Selection)
Selecting the correct strike price is critical for scalping Nifty and BankNifty. The system handles this dynamically rather than relying on hardcoded prices.

### A. The Greeks Logic
*   **Delta:** Scalpers need high Delta for momentum. Out-Of-The-Money (OTM) strikes (Delta < 0.4) are ignored because they do not move fast enough. The system prioritizes **At-The-Money (ATM)** or **In-The-Money (ITM)** strikes (Delta 0.5 to 0.7).
*   **Theta (Time Decay):** While scalping is fast, Theta is brutal on Expiry Day (Wednesday/Thursday). The LLM Knowledge Base contains rules to force the engine to choose **Next Week Expiry** or deep ITM strikes during the second half of expiry days to avoid zeroing out.
*   **Liquidity (Bid-Ask Spread):** ITM options can sometimes have wider spreads. The Python engine checks the order book; if the Bid-Ask spread is wider than acceptable limits, it falls back to the highly liquid ATM strike.

### B. How Selection Works in Real-Time
1. The LLM does **not** pick the exact number (e.g., "22100 CE"). Instead, it outputs a dynamic rule: `"strike_preference": "ATM"` or `"strike_preference": "ITM_1"`.
2. When the Fast Loop is triggered to buy, it looks at the live spot price (e.g., Nifty at 22120).
3. It maps `ITM_1` for a Call option to the `22100 CE` strike.
4. It calculates the live Greeks (using `py_vollib` in Python) to verify it meets safety criteria, checks the bid-ask spread, and executes the trade.

## 5. Order Flow & Market Mood Analysis
To accurately predict short-term momentum (1-5 minutes), the system will monitor institutional order flow rather than just price action. The Python engine will extract the following metrics from the Shoonya API and feed them to the LLM:

*   **Change in Open Interest (COI):** Tracking trapped sellers. A sudden drop in Call OI at resistance indicates panic short-covering (a strong bullish signal).
*   **Put-Call Ratio (PCR):** Real-time Intraday Volume PCR. A shift from < 1.0 to > 1.0 within minutes flags an immediate trend reversal.
*   **Order Book Imbalance:** The Fast Loop monitors the top 5 Bid/Ask depths. If Ask Quantities outweigh Bid Quantities by 3x or more, bullish triggers from the LLM are temporarily paused to avoid buying into heavy selling pressure.
*   **Volume Spikes:** Breakouts must be confirmed by a 3x-5x spike in 1-minute option volume to filter out fakeouts.
*   **Cumulative Volume Delta (CVD):** Separates volume into aggressive buys (trades hitting Ask) vs. aggressive sells (trades hitting Bid). If price makes a new high but CVD is dropping, it is a fake breakout — buyers are not aggressive. This is the most powerful divergence signal used by institutional scalpers.
*   **Futures Premium/Discount:** Tracks the spread between Nifty/BankNifty Futures and Spot price. A healthy Futures premium indicates bullish institutional flow. A sudden collapse in premium is a leading indicator of a sell-off — it occurs BEFORE the Spot index drops.

## 6. Advanced Market Context & HFT Alpha Factors (Maximizing Accuracy)
To achieve ultra-high win rates, the LLM will not just look at the index price. It will be fed holistic market context used by professional High-Frequency Trading (HFT) desks to prevent trading in traps. The Python engine will track and feed the following to the LLM:

*   **The "Heavyweights" Principle:** BankNifty is dictated by HDFC Bank and ICICI Bank. Nifty is dictated by Reliance, HDFC, Infosys, and TCS. The LLM will reject index breakouts if the heavyweights do not support the move.
*   **VWAP (Volume Weighted Average Price) Filter:** The ultimate institutional trend line. The system will strictly enforce: **NEVER BUY if price is below VWAP, NEVER SHORT if price is above VWAP.**
*   **Time-of-Day Volatility Windows:** 
    *   *9:15 AM to 10:30 AM:* High volatility (Aggressive Lot Sizing).
    *   *10:30 AM to 1:00 PM:* Theta Decay/Chop Zone (System reduces lot size or halts trading entirely to avoid false breakouts).
    *   *1:00 PM to 3:00 PM:* European Market Open & Second Half trend (High confidence setups).
*   **Technical Liquidity Magnets:** The engine calculates Previous Day High (PDH), Previous Day Low (PDL), and Daily Pivot Points. Breakouts that align with these historical liquidity levels receive an immediate +20% boost to their Confidence Score.
*   **Sectoral Synergy:** The engine tracks the Nifty IT index vs. Nifty Bank index. If they are moving in opposite directions, the LLM will scale down targets.
*   **India VIX & Macro Cues:** Adjusts targets based on VIX and includes a "Blackout Calendar" to halt trading during RBI/Fed policy announcements.
*   **IV Crush Detection:** Before entering any trade, the system compares the specific option's current Implied Volatility (IV) against its historical average (IV Rank / IV Percentile). If IV is abnormally inflated (e.g., before RBI policy or earnings), the system refuses to buy options to avoid the post-event IV Crush where premiums collapse even if direction is correct.
*   **Gamma Exposure (GEX) & The Gamma Flip:** The system estimates Market Maker gamma positioning. On **Positive GEX** days (dealers sell rallies, buy dips), the LLM uses mean-reversion strategies (fade breakouts). On **Negative GEX** days (dealers amplify trends), the LLM switches to aggressive trend-following. The "Gamma Flip" level acts as the critical pivot point for the day.
*   **Max Pain & Expiry Day Pinning:** On expiry days, the system calculates the Max Pain strike (where maximum option buyers lose money). In the last 2 hours of expiry, if the index is near Max Pain, the system avoids new directional bets as the market tends to pin to that strike.
*   **GIFT Nifty & Pre-Market Gap Analysis:** At 9:00 AM, the engine pulls the GIFT Nifty price and compares it to yesterday's Nifty close. If the gap is abnormally large (>200 points), the system enters "Gap Day Mode" — it avoids the chaotic first 15 minutes entirely and waits for price stability before taking any trade.
*   **Advance/Decline Ratio (Market Breadth):** Monitors how many Nifty 50 stocks are advancing vs. declining. If Nifty makes a new high but only 15/50 stocks are green (A/D < 0.5), the LLM flags a "Narrow Rally Divergence" and reduces confidence scores to prevent buying into a reversal trap.

## 7. Live News Sentiment & Global Macros (The NLP Advantage)
While traditional algorithms are blind to real-world events, our LLM-powered system can read and react to the news faster than a human.

*   **Live Headline Parsing:** The Python engine will pull live RSS feeds or News APIs (e.g., Bloomberg, Moneycontrol). Every 1-5 minutes, the LLM reads the latest headlines. If a major breaking news event occurs (e.g., "HDFC Bank reports massive profit drop" or global geopolitical tensions), the LLM will instantly override technical signals and halt buying, or flip the bias to Bearish.
*   **Global Macro Intermarket Analysis:** The LLM will be fed the live status of the **Dollar Index (DXY)**, **US 10-Year Bond Yields**, and **Brent Crude Oil**. (e.g., A sudden spike in Crude Oil prices heavily pressures the Indian Rupee and triggers sell-offs in BankNifty).
*   **FII/DII Data:** The system ingests the previous day's Foreign/Domestic Institutional Investor data to establish the overarching market trend before the opening bell.

## 8. Intelligent Trade Filtering & Dynamic Position Sizing
The market generates hundreds of small signals every day, but 80% of them are traps or low-probability trades. The system uses strict filters to only execute **"A+ Setups"**.

### A. The Confidence Score (Probability Matrix)
When the LLM analyzes the market, it does not just output "BUY" or "SELL". It calculates a **`confidence_score` (0 to 100%)** based on how many Alpha Factors align.
*   **Mediocre Setup (60% Confidence):** Price breaks resistance, but volume is average and Heavyweights (HDFC/Reliance) are flat. -> **ACTION: IGNORE TRADE.**
*   **A+ Setup (90%+ Confidence):** Price breaks resistance + Massive Volume Spike + Heavyweights are flying + Put Writers are panicking (PCR rising). -> **ACTION: EXECUTE.**

### B. Dynamic Lot Sizing
The Python engine dynamically calculates how many lots to buy based on the LLM's confidence score and your total capital.
*   **Base Risk:** Trades with 75% confidence are executed with minimal size (e.g., 1 or 2 lots) to test the waters.
*   **Aggressive Risk:** A+ Setups (90%+ confidence) trigger maximum allowed leverage (e.g., 5 to 10 lots) to maximize profit on the highest probability trades.

### C. Time-Based Auto-Exit (Theta Protection)
In options scalping, *time is risk*. If the trade does not move in our favor immediately, the system kills it. The Fast Loop monitors the **Holding Time**. If a trade is stuck in a 5-point range for more than 3 minutes, the system automatically exits at breakeven or a tiny loss to prevent Theta decay, rather than waiting for the Stop Loss to hit.

### D. Trailing Stop Loss (Profit Protection)
A fixed Target limits profits. Instead, once a trade moves 15+ points in profit, the Stop Loss automatically trails behind the price (e.g., always 10 points behind the current high). This locks in guaranteed profit while letting winners run far beyond the original target.

## 9. Capital Protection & Kill Switch
Individual trade risk management is not enough. The system must protect the entire account from catastrophic drawdowns.

*   **Daily Loss Limit:** A hard-coded maximum daily loss (e.g., ₹5,000). Once hit, the entire system shuts down for the day. No exceptions. No overrides. No revenge trading.
*   **Max Consecutive Losses:** If the system loses 3 trades in a row, it pauses for 30 minutes to let the market regime stabilize before re-entering.
*   **Data Integrity Halt (The "Blindness" Rule):** If *any* critical data stream (Primary WebSocket, Fallback WebSocket, or Macro API) goes offline and its fallback also fails, the system immediately squares off all open positions and halts all new trades. The system is strictly forbidden from trading in the dark.
*   **Kill Switch:** A physical button on the Next.js Dashboard that instantly halts all trading activity, cancels pending orders, and squares off open positions.
*   **Circuit Breaker Awareness:** The system monitors NSE circuit breaker levels (10%, 15%, 20% index moves). If a circuit breaker is triggered, the system immediately exits all positions and halts for the day.

## 10. Paper Trading Module Requirements
To accurately test the system without real money, the Paper Trading module must:
*   Listen to the live order book (Bid/Ask prices).
*   Execute a virtual buy order at the *current Ask price* (simulating real market slippage, not the Last Traded Price).
*   Execute a virtual sell order at the *current Bid price*.
*   Calculate brokerage and taxes (even though Shoonya is 0 brokerage, exchange transaction charges and STT still apply) to calculate Net PnL.
*   Log all trades to a CSV/Database for accuracy analysis.

## 11. Development Phases

### Phase 1: Infrastructure & Data Ingestion (Weeks 1-2)
*   Set up the Python backend with `asyncio`.
*   Integrate Shoonya API (Authentication & Login flow).
*   Establish WebSocket connection and stream live Option Chain data to Redis.

### Phase 2: LLM Integration & Strategy Logic (Weeks 2-3)
*   Create the context-builder module to format live data for the LLM.
*   Integrate the LLM API (Claude/Gemini) with strict JSON output formatting.
*   Establish the communication pipeline between the LLM Output and the Execution Engine.

### Phase 3: Paper Trading Engine (Weeks 3-4)
*   Build the simulated execution environment.
*   Implement Stop Loss (SL), Target, and Trailing SL logic.
*   Run the bot during live market hours and generate end-of-day accuracy reports.

### Phase 4: UI Dashboard (Future)
*   Build a web interface to visualize LLM reasoning, view live paper trades, and analyze historical accuracy.
