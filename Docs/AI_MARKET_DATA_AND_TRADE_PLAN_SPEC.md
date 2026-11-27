 # AI Market Data, LLM Integration & Trade Plan Execution Specification

> **Target Instruments:** NIFTY 50 & BANK NIFTY (Intraday Index Futures & 0DTE/Weekly Options)  
> **Architecture:** Decoupled Fast Loop (Execution in Milliseconds) & Slow Loop (LLM Intelligence in Seconds)  
> **Status:** Production Specification & Architecture Blueprint  

---

## 1. The 32 Core Market Data Dimensions & Impact on Indian Markets

To achieve consistent institutional-grade scalping on the National Stock Exchange of India (NSE), the trading engine continuously tracks 32 distinct data dimensions across 5 categories. Below is the comprehensive breakdown of each metric, what it measures, and exactly how it impacts **Nifty 50** and **Bank Nifty**.

```
                           ┌────────────────────────────────────────┐
                           │      32 MARKET DATA DIMENSIONS         │
                           └──────────────────┬─────────────────────┘
                                              │
         ┌──────────────────┬─────────────────┼──────────────────┬──────────────────┐
         ▼                  ▼                 ▼                  ▼                  ▼
   1. Spot & Fut      2. Options &      3. Order Flow &    4. Breadth &       5. Global Macro
     Dynamics            Greeks          Microstructure     Heavyweights          & News
   (Items 1–5)        (Items 6–16)       (Items 17–20)      (Items 21–26)      (Items 27–32)
```

---

### Category A: Spot & Futures Dynamics

#### 1. Index Spot Prices (`NIFTY 50`, `BANKNIFTY`, `NIFTY IT`)
* **What it is:** The real-time, volume-weighted underlying cash index value calculated from the constituent stocks.
* **How it affects Nifty & BankNifty:** Spot price serves as the absolute anchor for strike selection (determining At-The-Money [ATM], In-The-Money [ITM], and Out-of-The-Money [OTM]). All option strike payouts, intrinsic values, and settlement obligations derive directly from spot.

#### 2. Futures LTP & Volume (`NIFTY:CURR`, `BANKNIFTY:CURR`)
* **What it is:** The Last Traded Price (LTP) and cumulative transaction volume of current-month and next-month index futures traded on the NSE.
* **How it affects Nifty & BankNifty:** Futures reflect leveraged institutional commitments. Breakouts on the spot index that lack volume on futures contracts are high-probability bull/bear traps. Volume surges on futures precede large directional runs.

#### 3. Futures Premium / Discount (Basis Spread)
* **What it is:** The mathematical spread: $\text{Basis} = \text{Futures LTP} - \text{Spot LTP}$.
* **How it affects Nifty & BankNifty:** In a healthy bull market, futures trade at a standard premium due to the cost of carry. A sudden **collapse in futures premium** (or flipping into a deep discount) is a leading warning that institutional desks are dumping long futures or shorting aggressively—this warning typically surfaces **15 to 45 seconds before** the spot index begins dropping.

#### 4. Volume Weighted Average Price (VWAP)
* **What it is:** The intraday average price weighted by cumulative volume:  
  $$\text{VWAP} = \frac{\sum (\text{Typical Price} \times \text{Volume})}{\sum \text{Volume}}$$  
  Reset daily at 09:15:00 IST.
* **How it affects Nifty & BankNifty:** Institutional execution algorithms (TWAP/VWAP engines) use VWAP as their fair-value benchmark.
  * **Above VWAP:** Institutional buyers are in control; aggressive shorting is forbidden.
  * **Below VWAP:** Institutional sellers dominate; buying call options is forbidden.

#### 5. Index Volume Delta / Spikes
* **What it is:** The rate of change in volume between consecutive tick/time intervals ($\Delta \text{Vol} = \text{Vol}_t - \text{Vol}_{t-1}$).
* **How it affects Nifty & BankNifty:** Options scalping relies on momentum surges. A breakout candle accompanied by a 3x–5x volume spike validates genuine buyer/seller participation, whereas low-volume breakouts almost always retrace into chop.

---

### Category B: Option Chain & Greeks Dynamics

#### 6. Option Chain LTP (ATM $\pm$ 20 Strikes for CE and PE)
* **What it is:** Real-time premiums of Call Options (CE) and Put Options (PE) across 41 strikes (20 OTM, 1 ATM, 20 ITM) for both weekly and monthly expiries.
* **How it affects Nifty & BankNifty:** Provides the exact cost basis for trades and monitors the rate of premium expansion/contraction.

#### 7. Option Volume & Delta Volume
* **What it is:** Real-time contracts traded per individual strike and the delta change per minute.
* **How it affects Nifty & BankNifty:** High volume concentration identifies where retail and institutional liquidity is actively battling. Sudden spikes in volume on out-of-the-money puts/calls often highlight institutional block hedging.

#### 8. Open Interest (OI) & Change in Open Interest (COI / $\Delta$OI)
* **What it is:** The total number of outstanding, unsettled derivative contracts and its intraday rate of change.
* **How it affects Nifty & BankNifty:** Option writers (sellers) are predominantly institutional desks due to high margin requirements.
  * **Call $\Delta$OI Dropping sharply:** Call writers are panicking and covering shorts $\rightarrow$ Explosive upward short squeeze.
  * **Put $\Delta$OI Dropping sharply:** Put writers are being forced to liquidate $\rightarrow$ Free-fall long unwinding breakdown.

#### 9. Option Greek: Delta ($\Delta$)
* **What it is:** The rate of change of option price per 1-point move in the underlying index:  
  $$\Delta = \frac{\partial V}{\partial S}$$
* **How it affects Nifty & BankNifty:** Scalpers require quick premium expansion. Buying OTM strikes with Delta $< 0.40$ is unprofitable during quick scalps because the index must move significantly for minimal premium gain. The system selects strikes with $\Delta \in [0.50, 0.70]$ (ATM to ITM_1/ITM_2).

#### 10. Option Greek: Gamma ($\Gamma$)
* **What it is:** The rate of change of Delta per 1-point move in the index ($\Gamma = \frac{\partial \Delta}{\partial S}$).
* **How it affects Nifty & BankNifty:** Gamma is the engine of **0DTE "Hero-or-Zero" expiry day moves**. Near expiry, ATM strikes experience explosive Gamma expansion; a rapid 30-point index move can double or triple option premiums within seconds.

#### 11. Option Greek: Theta ($\Theta$)
* **What it is:** The rate of premium decay over time:  
  $$\Theta = \frac{\partial V}{\partial t}$$
* **How it affects Nifty & BankNifty:** On Indian weekly expiries (Wednesday for Bank Nifty, Thursday for Nifty), Theta decay accelerates exponentially after 13:00 IST. If a trade stays stagnant for more than 3 minutes during sideways chop, Theta consumes the premium.

#### 12. Option Greek: Vega ($\mathcal{V}$) & Rho ($\rho$)
* **What it is:** Sensitivity of the option price to changes in Implied Volatility (Vega) and interest rates (Rho).
* **How it affects Nifty & BankNifty:** Vega measures how much option premium increases when panic/volatility rises. Buying options during high Vega environments leaves the trader vulnerable to sudden volatility contraction.

#### 13. Implied Volatility (IV) & IV Rank / Percentile (IV Crush)
* **What it is:** The market's forward-looking volatility priced into option premiums compared against the 30-day historical range.
* **How it affects Nifty & BankNifty:** Before high-impact scheduled events (e.g., Union Budget, RBI MPC, election results), option sellers price in immense fear, inflating IV. The moment the event concludes, IV collapses (IV Crush)—causing buyers of both CE and PE to lose money even if the market moves in their predicted direction.

#### 14. Put-Call Ratio (PCR)
* **What it is:** The ratio of Total Put Open Interest (or Volume) to Total Call Open Interest:  
  $$\text{PCR} = \frac{\sum \text{Put Volume / OI}}{\sum \text{Call Volume / OI}}$$
* **How it affects Nifty & BankNifty:**
  * $\text{PCR} > 1.3$: Heavily bullish or nearing overbought territory.
  * $\text{PCR} < 0.7$: Heavily bearish or nearing an oversold reversal bounce.
  * Rapid intraday shift from $0.8 \rightarrow 1.1$ signals aggressive put writing and an imminent upward ramp.

#### 15. Gamma Exposure (GEX) & The "Gamma Flip"
* **What it is:** The aggregate net gamma positioned by options dealers and market makers:  
  $$\text{Total GEX} = \sum (\Gamma_{\text{Call}} \times \text{OI}_{\text{Call}} \times S^2 \times 0.01) - \sum (\Gamma_{\text{Put}} \times \text{OI}_{\text{Put}} \times S^2 \times 0.01)$$
* **How it affects Nifty & BankNifty:**
  * **Positive GEX (+GEX):** Market makers trade counter to the trend (buying dips, selling rips) to stay delta-neutral $\rightarrow$ Creates range-bound, low-volatility mean reversion.
  * **Negative GEX (-GEX):** Market makers trade in the direction of the market (selling falling markets, buying rising markets) $\rightarrow$ Amplifies volatility, producing cascading liquidations and runaway breakout trends.
  * **Gamma Flip Level:** The exact index level where GEX transitions from positive to negative; acts as the primary intraday inflection pivot.

#### 16. Max Pain Strike & Expiry Pinning
* **What it is:** The specific strike price where the cumulative intrinsic value of all open Call and Put options is minimized (i.e., where option writers pocket the maximum premium).
* **How it affects Nifty & BankNifty:** In the final 2 hours of expiry day (13:30 to 15:30 IST), institutional writers deploy massive capital to pin the index price near the Max Pain strike, grinding out remaining extrinsic premium.

---

### Category C: Order Flow & Microstructure

#### 17. Level 2 Market Depth (Top 5 Bid/Ask Quantities)
* **What it is:** The live queue of limit buy orders (Bids) and limit sell orders (Asks) resting on the exchange order book.
* **How it affects Nifty & BankNifty:** Reveals immediate supply and demand walls. Paper trading engines use depth to simulate realistic slippage rather than executing fills against unrealizable LTPs.

#### 18. Order Book Imbalance (OBI)
* **What it is:** The ratio of total pending bid volume versus total pending ask volume:  
  $$\text{OBI} = \frac{\sum \text{Bid Quantity}}{\sum \text{Ask Quantity}}$$
* **How it affects Nifty & BankNifty:** If Asks outweigh Bids by $3:1$ ($\text{OBI} < 0.33$), heavy resting liquidity is resisting upward price movement. The algorithm immediately pauses bullish triggers to prevent buying directly into institutional supply blocks.

#### 19. Cumulative Volume Delta (CVD)
* **What it is:** The running cumulative sum of market orders hitting the Ask (aggressive buyers) minus market orders hitting the Bid (aggressive sellers):  
  $$\text{CVD}_t = \text{CVD}_{t-1} + (\text{Vol}_{\text{Ask}} - \text{Vol}_{\text{Bid}})$$
* **How it affects Nifty & BankNifty:** The premier institutional indicator for spotting fake breakouts:
  * **Price makes Higher High + CVD makes Lower High:** Exhaustion / Fakeout. The rally is driven by passive limit absorption rather than aggressive buying $\rightarrow$ Imminent rejection.
  * **Price breaks resistance + CVD spikes upward:** Confirmed breakout with aggressive institutional participation.

#### 20. Bid-Ask Spread & Liquidity Assessment
* **What it is:** The difference between the lowest ask price and the highest bid price ($\text{Spread} = \text{Ask}_{\text{best}} - \text{Bid}_{\text{best}}$).
* **How it affects Nifty & BankNifty:** Deep ITM strikes or illiquid contracts often develop wide spreads. If the spread exceeds 1.5–2 points on Nifty, immediate execution slippage erodes scalp profitability. The system verifies spread tightness before firing orders.

---

### Category D: Market Breadth & Heavyweight Stock Flow

#### 21. Heavyweight Stocks Live Prices & Volumes (Top 27 Equities)
* **What it is:** Tick-by-tick monitoring of the heavyweight stocks that govern the weightage of Indian indices:
  * **Bank Nifty Drivers:** HDFC Bank (~29%), ICICI Bank (~23%), Axis Bank, Kotak Bank, SBI.
  * **Nifty 50 Drivers:** Reliance Industries (~10%), HDFC Bank, ICICI Bank, Infosys, TCS, L&T, ITC.
* **How it affects Nifty & BankNifty:** **Nifty cannot rally sustainably if Reliance and HDFC Bank are falling.** Bank Nifty cannot break out if HDFC Bank and ICICI Bank diverge. The engine verifies heavyweight alignment before confirming any index trade.

#### 22. Heavyweight Order Book Imbalances
* **What it is:** Bid-to-Ask liquidity ratio measured directly on HDFC Bank, Reliance, and ICICI Bank.
* **How it affects Nifty & BankNifty:** If HDFC Bank's order book shows 80% pending ask quantities, any bounce on Bank Nifty is artificial and will be snuffed out as soon as market sell orders hit HDFC Bank.

#### 23. Advance / Decline (A/D) Ratio (Nifty 50 Breadth)
* **What it is:** The count of Nifty 50 constituent stocks trading above their previous day's close versus those trading below:  
  $$\text{A/D Ratio} = \frac{\text{Advancing Stocks}}{\text{Declining Stocks}}$$
* **How it affects Nifty & BankNifty:**
  * **Healthy Rally:** $\text{A/D Ratio} > 2.0$ (35+ stocks advancing).
  * **Narrow Rally Divergence:** Nifty 50 prints new intraday highs, but the A/D ratio is $< 0.5$ (only 12–15 stocks green, driven by single-stock manipulation like Reliance). The engine flags this as a trap and vetoes long trades.

#### 24. Sectoral Synergy (Nifty IT vs. Nifty Bank)
* **What it is:** Cross-sector correlation tracking between the Banking pack (high beta, domestic credit) and the IT pack (export, dollar-sensitive).
* **How it affects Nifty & BankNifty:** When Nifty Bank and Nifty IT move in opposite directions (e.g., Bank up +1.2%, IT down -1.5%), they cancel each other out, locking Nifty 50 into a frustrating, theta-bleeding chop zone. Directional scalps are disabled during sectoral divergence.

#### 25. India VIX (Volatility Index)
* **What it is:** The annualized expected volatility over the next 30 calendar days, computed by the NSE from Nifty out-of-the-money option order books.
* **How it affects Nifty & BankNifty:**
  * $\text{VIX} < 12$: Low volatility; option premiums are cheap, moves are sluggish; targets must be tighter (15–25 points).
  * $\text{VIX} \in [13, 17]$: Optimal scalping regime with predictable follow-through.
  * $\text{VIX} > 20$: High fear regime; wild swings, wide spreads, requiring halved position sizes and wider stop losses.

#### 26. Technical Liquidity Levels (PDH, PDL, PDC & Daily Pivots)
* **What it is:** Previous Day High (PDH), Previous Day Low (PDL), Previous Day Close (PDC), and Classic Floor Pivots:
  $$\text{Pivot} = \frac{\text{PDH} + \text{PDL} + \text{PDC}}{3}, \quad R_1 = 2 \times \text{Pivot} - \text{PDL}, \quad S_1 = 2 \times \text{Pivot} - \text{PDH}$$
* **How it affects Nifty & BankNifty:** Retail stop losses cluster heavily directly above PDH and below PDL. Institutional algorithms hunt these pools of resting liquidity. A sweep of PDH followed by an immediate close back below signals an institutional liquidity grab and a prime shorting opportunity.

---

### Category E: Global Macro & Live News Intelligence

#### 27. GIFT Nifty (Pre-Market Gap Analysis)
* **What it is:** The Nifty derivative contract traded on the NSE International Exchange (NSE IX) at GIFT City, operating nearly 21 hours daily.
* **How it affects Nifty & BankNifty:** Quoted at 09:00 IST to predict the opening gap on the NSE cash market at 09:15 IST. Gaps $> 150$ points trigger "Gap-Day Protocol," forcing the engine to wait 15 minutes for initial opening auction equilibrium.

#### 28. US Dollar Index (DXY)
* **What it is:** The value of the USD relative to a basket of six foreign reserve currencies.
* **How it affects Nifty & BankNifty:** Inversely correlated with Indian equities. A spiking DXY signals capital flight from Emerging Markets back into US assets, triggering Foreign Institutional Investor (FII) selling in Indian banking stocks.

#### 29. Brent Crude Oil Prices
* **What it is:** Global oil price benchmark ($USD per barrel).
* **How it affects Nifty & BankNifty:** India imports $> 80\%$ of its crude oil requirements. Rising crude oil devalues the Indian Rupee (INR), increases domestic inflation expectations, and disproportionately hurts oil-marketing companies and banking credit metrics.

#### 30. US 10-Year Treasury Yield (`^TNX`)
* **What it is:** Benchmark yield on US government sovereign debt.
* **How it affects Nifty & BankNifty:** Rising US bond yields narrow the yield spread between US risk-free assets and Indian risk assets, accelerating foreign institutional outflows from large-cap Nifty holdings.

#### 31. Live Breaking Financial News (Indian & Global Feeds)
* **What it is:** Automated NLP parsing of live headlines via Moneycontrol/Economic Times RSS feeds and NewsAPI.
* **How it affects Nifty & BankNifty:** Technical charts cannot foresee sudden geopolitical skirmishes, unexpected regulatory actions (e.g., RBI tightening unsecured lending rules), or flash management resignations. News sentiment analysis provides an emergency override circuit.

#### 32. Institutional Positioning & Economic Blackout Calendar
* **What it is:** 
  1. Daily Foreign Institutional Investors (FII) and Domestic Institutional Investors (DII) net cash and derivative positions (Bhavcopy).
  2. Scheduled high-impact blackout events (RBI Policy statements, US Fed FOMC interest rate announcements, US CPI releases).
* **How it affects Nifty & BankNifty:** Establishes the overarching macro bias before market open. During scheduled monetary policy announcement windows, options spreads widen artificially; the system activates a **trading blackout** 15 minutes before and after statements.

---

## 2. What We Send to the LLM (State Builder, Stateful Redis Memory & Prompting)

### 2.1 The Two-Speed Architecture & Division of Cognitive Roles

The core architectural foundation of this system is a strict **separation of concerns** between human-like cognitive synthesis and deterministic machine execution:

#### 1. The LLM as the Primary Decision-Maker & Market Interpreter
* **Contextual Synthesis over Rigid Rules:** Python does **not** replace market analysis with rigid, hardcoded technical rules (e.g., simplistic thresholds like "if RSI > 70 do not buy" or "if CVD > 80k buy"). Financial markets are non-stationary; rigid indicator rules produce curve-fitted algorithms that fail when volatility regimes shift.
* **Holistic Interpretation:** The LLM acts as the **Senior Quantitative Trader**. It evaluates the complete market landscape simultaneously: cross-referencing option chain liquidity, Greeks evolution, order flow absorption (CVD), spot-to-VWAP relationships, heavyweight equity order book imbalances, and breaking macroeconomic news.
* **Signal Generation Authority:** The LLM is the sole originator of trading signals:
  $$\text{Action Space} \in \{\text{ENTER\_CALL}, \text{ENTER\_PUT}, \text{HOLD}, \text{EXIT}, \text{NO\_TRADE}, \text{REDUCE}\}$$

#### 2. Python as the Fast Computational, Monitoring & Independent Safety Layer
* **No Subjective Judgment:** Python does not attempt to "understand" or predict the market like a trader.
* **Deterministic Computation (<10ms):** Ingests sub-second tick streams, normalizes timestamps, calculates derived features (VWAP, CVD, Order Book Imbalance), computes Black-Scholes Greeks with mathematical precision, and packages clean, token-efficient state payloads.
* **Independent Safety & Risk Execution:** Python independently enforces hard risk boundaries (daily loss ceilings, max drawdowns, position limits, NSE freeze limit order slicing, trailing stop-losses, and emergency liquidations). **Python never blocks on the LLM to enforce protective exits.**

#### 3. Continuous Market Understanding vs. Continuous Trading (The "Patience Protocol")
A fundamental difference between amateur retail algorithms and institutional hedge fund engines:
* **Amateur bots overtrade:** They execute 30–50 trades a day on minor indicator flickers, generating heavy broker commissions, severe slippage, and death-by-a-thousand-cuts during choppy consolidation.
* **Our Institutional AI Engine observes continuously and strikes selectively:** The system evaluates every 60 seconds to build, calibrate, and maintain an ongoing **Market Narrative**, but it only commits capital 1 to 3 times per day (or ZERO times if conditions lack institutional confluence).

The action space is formally defined as:
$$\text{Action Space} \in \{\text{OBSERVE}, \text{ENTER\_CALL}, \text{ENTER\_PUT}, \text{HOLD}, \text{REDUCE}, \text{EXIT}, \text{NO\_TRADE}\}$$

* **The Baseline Default is `OBSERVE` (High Burden of Proof):** In 95% of 1-minute cycles, the model outputs `OBSERVE` or `NO_TRADE`. An entry requires an overwhelming burden of proof: $\ge 25$ of 32 factors in active alignment, zero critical factor conflicts, and a minimum asymmetric Risk-to-Reward ratio of $1:2.5$.
* **The 5 Cognitive Market States:**
  1. **`OBSERVE_MAPPING` (~60% of Day):** Tracking VWAP formation, measuring opening drive strength, mapping resting liquidity pools (PDH/PDL sweeps). Capital at risk: ₹0.
  2. **`SETUP_DEVELOPING` (~25% of Day):** An institutional thesis is identified (e.g. Call writers are absorbing bids at 22,150; CVD divergence forming). The AI monitors the setup patiently without jumping the gun. Capital at risk: ₹0.
  3. **`SURGICAL_TRIGGER` (1 to 3 times/Day max):** Factor confluence reaches $> 90\%$, CVD surges, Call short-covering confirmed, heavyweights aligned. Fast bracket order placed with hard exchange-side stops.
  4. **`PATIENT_HARVEST` (Active Trade):** Position is open and profitable. The AI trails stops deterministically and resists the urge to micro-manage or panic-exit prematurely.
  5. **`PRESERVE_CAPITAL` (Chop / Blackout):** Market is in a positive-GEX equilibrium pin, sectors diverge, high-impact macro news is imminent, or daily profit/loss limits have been achieved. Trading locked.

#### 4. The Between-Decision Execution Timeline
A real-world operational cycle unfolds as follows:
* **T = 10:15:00 (Signal Generation):** The LLM synthesizes the 32 factors and outputs `ENTER_CALL` on `OPT:NIFTY:22150CE` (2 Lots) with 95% confidence.
* **T = 10:15:01 (Risk & Execution):** Python independently verifies capital headroom, daily loss limit, and blackout status, resolves dynamic contract size ($2 \times 75 = 150$), and fires the bracket order to the broker in $<10\text{ms}$.
* **T = 10:15:01 to 10:15:59 (Fast Monitoring):** Python monitors every incoming WebSocket tick (every 100ms). It tracks P&L, moves trailing stops, and guards against Theta decay. **If an acute flash-crash occurs, Python instantly liquidates the position at market without waiting for the LLM.**
* **T = 10:16:00 (Next Scheduled Audit):** The LLM receives the updated 32-factor state, exact previous decision, verified broker position, and live unrealized P&L. The LLM re-evaluates whether the thesis holds, outputting `HOLD` (to ride momentum), `REDUCE` (to take partial profit), or `EXIT` (if order flow reveals institutional exhaustion).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   FAST EXECUTION LOOP (<10ms)                          │
│  [NSE Tick Stream] ──► [Python Asyncio Engine] ──► [Docker Redis In-Memory State]      │
│                                                          ▲                │            │
│                                    Order Fills / PnL     │                │ Raw Feed   │
│                                                          │                ▼            │
│  [Broker API / DMA] ◄── [Deterministic Risk Engine] ◄────┴─────── [StateBuilder]       │
└───────────────────────────────────────────────▲───────────────────────────┬────────────┘
                                                │                           │
                                                │ New Decision              │ Tripartite
                                                │ (All 32 Factors Audited)  │ Request
                                                │                           ▼
                                    ┌───────────────────────────────────────────┐
                                    │         SLOW COGNITIVE LOOP (1-5s)        │
                                    │    [LLM Brain: Dual-Brain Consensus]      │
                                    │   (Anthropic Claude 3.5 + Gemini Flash)   │
                                    └───────────────────────────────────────────┘
```

---

### 2.2 Docker Redis Stateful Decision Memory Architecture
To avoid "decision amnesia" and erratic 1-minute whipsaws, the trading engine does not treat each cycle as an isolated prompt. Every decision generated by the LLM is stored in **Docker Redis** with strict key structures:

#### Redis Key Schema for Stateful Continuity
1. **`DECISION:LATEST` (Hash / JSON String):**
   * Stores the exact, immutable previous decision returned by the LLM.
   * Fields: `decision_id`, `timestamp`, `action`, `direction`, `setup`, `confidence`, `symbol`, `lots`, `reason`, and the complete array of all 32 evaluated factors (`factor_audit`).
2. **`DECISION:HISTORY:{decision_id}` (JSON String with TTL):**
   * Persisted with a 24-hour TTL (`EXPIRE 86400`) to store the immutable sequence of all daily cycles for post-session trade debriefs and model calibration.
3. **`DECISION:TIMELINE:{YYYY-MM-DD}` (Redis Sorted Set):**
   * Stores `score = unix_timestamp`, `member = decision_id`. Enables sequential temporal range queries (`ZRANGEBYSCORE`) to track the exact evolution of the LLM's bias across the trading day.
4. **`EXECUTION:STATE:LATEST` (Hash):**
   * Independent ground truth of active broker positions, filled lots, average fill price, current unrealized PnL, pending orders, and remaining daily loss allowance.

#### The Continuity Feedback Loop
```
  Cycle (t-1):
  [LLM Output] ──► [Python Validator] ──► Store into Redis:
                                           ├─ DECISION:LATEST
                                           ├─ DECISION:HISTORY:{id}
                                           └─ DECISION:TIMELINE:{date}
                                                     │
  Cycle (t):                                         ▼
  [StateBuilder] ◄──────────────────────── Read DECISION:LATEST
        │
        ├─ Pull current market ticks & order flow from Redis
        ├─ Calculate explicit mathematical deltas (ΔCVD, ΔPrice, ΔOI, ΔTime)
        ├─ Pull real-time portfolio ground truth from EXECUTION:STATE:LATEST
        │
        ▼
  [Construct Tripartite Prompt: Part A + Part B + Part C + Part D] ──► [LLM Brain]
```

---

### 2.3 Super-Intelligent Multi-Day Memory & Indian Market Auction Continuity Engine

A core failure mode of algorithmic trading bots is **intra-session amnesia**: treating each trading day as an isolated, random event. In the National Stock Exchange of India (NSE), derivatives auctions carry profound multi-day structural continuity.

The engine implements a **3-Tier Multi-Day Episodic Memory System** ([`strategy_engine/multi_day_memory.py`](file:///d:/projects/Trading_Algorithm_Software/strategy_engine/multi_day_memory.py)) stored in Docker Redis under `MEMORY:ROLLING_SESSIONS` and `MEMORY:MULTI_DAY_ANCHORS`:

#### 1. Multi-Day Technical Anchors & Swing Liquidity Pools
* **3-Day High / Low Extremes:** Identifies where multi-day retail stop-losses and institutional supply/demand clusters rest. If Nifty breaks out at 22,180 but the 3-day high is 22,215, the model recognizes limited upside headroom ($<35$ pts) and vetoes premature calls.
* **Weekly Developing VWAP (W-VWAP):** Cumulative volume-weighted benchmark anchored from Monday 09:15:00 IST open. Acts as the primary macro institutional balance line for the week.

#### 2. Institutional Flow Trajectory (FII/DII Multi-Day Posture)
* Tracks cumulative **3-Day Net FII/DII Cash Flow** and the **FII Index Futures Long:Short Ratio**.
* *Contrarian Crowding Rule:* If FII Index Futures Long % drops below 20% (crowded shorts) and Nifty tests 3-day support with positive CVD divergence, the engine primes for an explosive, violent short-covering squeeze.

#### 3. Weekly Expiry OI Fortress Mapping
* Weekly options on NSE (Bank Nifty on Wednesday, Nifty on Thursday) build margin walls across 3 to 4 days.
* The memory tracks the **Call Wall** (heavy institutional call writing ceiling) and **Put Wall** (heavy institutional put writing floor), preventing the model from buying options directly into major multi-day seller defense strikes.

#### 4. Engine Self-Reflection & Episodic Experience
* Queries the SQLite audit log (`trading_records.db`) across the last 3 sessions:
  * Number of trades executed, win rate, and realized PnL.
  * Setup-specific expectancy: logs which setups succeeded (e.g. CVD Breakouts above PDH) and which failed (e.g. mid-day chop).
  * Automatically injects a qualitative rule: *"Do not commit capital between 11:30 and 13:00 IST unless CVD spike > 2.5x."*

---

### 2.4 The Tripartite Request Structure (Sent on Every Cycle)
Every prompt delivered to the LLM Slow Loop contains four explicit, decoupled blocks:

* **Part A: `previous_decision` (Immutable Historical Context):**
  Fetched directly from Redis `DECISION:LATEST`. It tells the model its exact stance 60 seconds ago, including its prior confidence, rationale, and all 32 factor ratings.
* **Part B: `current_market_state` (Live Metrics + Pre-Calculated Deltas):**
  The current readings across all 32 dimensions, supplemented with **Python-computed mathematical deltas** ($\Delta\text{Price}$, $\Delta\text{CVD}$, $\Delta\text{OI}$, $\Delta\text{Time}$).
* **Part C: `current_execution_state` (Independent Portfolio Ground Truth):**
  The real-world portfolio status from the broker/paper engine (`open_positions`, `entry_price`, `unrealized_pnl`, `daily_loss_limit_remaining`). This prevents assumption drift—the LLM never guesses whether an order filled; it observes verified portfolio ground truth.
* **Part D: `cognitive_instructions` (Analytical Rules & Anti-Anchoring):**
  Direct instructions forcing the model to compare $t-1$ factors against $t$ factors, assess whether momentum is accelerating or dying, and dynamically adjust without psychological anchoring bias.

---

### 2.4 Why Python Pre-Calculates All Numeric Deltas (Deterministic Arithmetic vs. Semantic Synthesis)
Large Language Models are probabilistic token predictors, not microsecond arithmetic logic units. When asked to subtract large numbers like Cumulative Volume Delta ($81,450 - 64,200$) or evaluate micro-changes in option delta under tight latency, LLMs frequently suffer from arithmetic hallucinations, sign reversals, or magnitude drift.

The architecture enforces a strict division of labor:
1. **Python Fast Loop Does 100% of the Mathematics Deterministically:**
   * **Price Velocity:** $\Delta\text{Price} = \text{Spot}_t - \text{Spot}_{t-1}$
   * **CVD Acceleration:** $\Delta\text{CVD} = \text{CVD}_t - \text{CVD}_{t-1}$
   * **Volume Surge Ratio:** $\text{Relative Volume Spike} = \frac{\text{Volume}_{1m}}{\text{SMA}(\text{Volume}_{1m}, 10)}$
   * **Distance to VWAP Delta:** $\Delta\text{VWAP\_spread} = (\text{Price}_t - \text{VWAP}_t) - (\text{Price}_{t-1} - \text{VWAP}_{t-1})$
   * **Option OI Shift:** $\Delta\text{OI}_{\text{strike, type}} = \text{OI}_t - \text{OI}_{t-1}$
   * **Elapsed Cycle Time:** $\Delta t = \text{UnixTime}_t - \text{UnixTime}_{t-1}$ (in seconds)
2. **The LLM Focuses Exclusively on Multi-Factor Synthesis & Regime Classification:**
   With all deltas cleanly pre-computed, the LLM applies qualitative reasoning: Is $\Delta\text{CVD} > 0$ validating $\Delta\text{Price} > 0$? Is Call OI unwinding while Put OI surges? Is the breakout genuine or an institutional trap?

---

### 2.5 Option Chain Structuring & Greeks Selection Policy

Transmitting a raw option chain with all 41 strikes (20 OTM + ATM + 20 ITM for CE and PE = 82 total contracts) can consume excessive tokens if formatted carelessly. The engine implements a **Dual-Tier Representation Policy** to deliver maximum analytical fidelity within an optimal latency and token budget:

#### 1. Tier 1: Active Scalping Corridor (ATM $\pm$ 3 Strikes — 14 Contracts Total)
* **Role:** Immediate execution and tight momentum tracking.
* **Fields Transmitted:** Complete microstructure and Greeks:
  * `ltp`, `delta_ltp_1m`, `bid`, `ask`, `bid_ask_spread`
  * `volume`, `delta_volume_1m`, `oi`, `delta_oi_1m`
  * `iv`, `delta`, `gamma`, `theta`, `vega`
* **Selection Guarantee:** The Active Corridor is **never pruned or truncated**, ensuring 100% data fidelity for contracts the engine would actually trade.

#### 2. Tier 2: Broad Structural Chain (Remaining ATM $\pm$ 20 Strikes)
* **Role:** Macro liquidity mapping, Max Pain calculation, and institutional Gamma Exposure (GEX) analysis.
* **Fields Transmitted:** Compact structural fields:
  * `strike`, `type` (CE/PE), `ltp`, `volume`, `oi`, `delta_oi_1m`, `iv`
* **Pruning & Selection Policy:** If token constraints or API rate limits require compaction:
  * Strikes with zero traded volume and zero open interest change are filtered out.
  * Strikes with heavy institutional concentration ($\text{OI} > 10,000$ contracts or large $\Delta\text{OI}$ spikes) are strictly prioritized.
  * The engine never silently drops strikes; any pruned strikes are accounted for in the aggregate PCR and GEX totals.

---

### 2.6 Greeks Calculation & Validation Standard (Deterministic In-House Engine)

Broker-provided Greeks are frequently delayed, missing, or calculated using inconsistent dividend or interest rate assumptions. The trading system never relies on unverified broker Greeks.

Instead, the **Python Fast Loop Greeks Engine** ([`data_ingestion/greeks_engine.py`](file:///d:/projects/Trading_Algorithm_Software/data_ingestion/greeks_engine.py)) calculates all Greeks in real-time using a deterministic Black-Scholes-Merton model with synchronized inputs:

1. **Underlying Spot Price ($S$):** The live NSE cash index price, timestamp-synchronized with the option tick ($<10\text{ms}$ skew).
2. **Time to Expiry ($T$):** Calculated down to the exact second:
   $$T = \frac{\text{Remaining Seconds until 15:30:00 on Expiry Date}}{365 \times 24 \times 3600}$$
3. **Risk-Free Rate ($r$):** The prevailing 91-Day Indian Treasury Bill (T-Bill) yield ($\approx 6.75\%$).
4. **Implied Volatility ($\sigma$):** Solved iteratively from the option market price using the Newton-Raphson method with Brent's bisection fallback.
5. **Analytic Greeks:** Computed directly from closed-form partial derivatives:
   * **Delta ($\Delta$):** Rate of premium change with respect to underlying price.
   * **Gamma ($\Gamma$):** Rate of delta change with respect to underlying price.
   * **Theta ($\Theta$):** 1-day calendar decay of premium.
   * **Vega ($\mathcal{V}$):** Sensitivity per 1% change in Implied Volatility.
   * **Rho ($\rho$):** Sensitivity per 1% change in domestic interest rates.

---

### 2.7 The Exact JSON Request Payload Fed to the Model
Below is the complete, schema-compliant JSON payload constructed by `StateBuilder` and delivered to the LLM on every decision cycle:

```json
{
  "request_id": "REQ_20261029_101600_NIFTY",
  "request_timestamp": "2026-10-29T10:16:00+05:30",
  "instrument": "NIFTY",
  "timeframe": "1m",

  "part_a_previous_decision": {
    "decision_id": "DEC_20261029_101500_NIFTY",
    "timestamp": "2026-10-29T10:15:00+05:30",
    "action": "HOLD",
    "direction": "BULLISH",
    "setup": "MOMENTUM_BREAKOUT",
    "confidence": 78,
    "summary_metrics": {
      "total_factors_evaluated": 32,
      "supporting_count": 18,
      "conflicting_count": 5,
      "neutral_count": 9,
      "unavailable_count": 0
    },
    "reason": "Price crossed PDH (22130) but CVD (+64,200) was below the +80,000 threshold and HDFC Bank showed neutral imbalance. Awaiting volume acceleration.",
    "key_factor_snapshots": {
      "1_spot_price": 22135.0,
      "4_vwap": 22120.0,
      "14_cvd": 64200,
      "8_call_atm_oi": 1935000,
      "8_put_atm_oi": 2308000
    }
  },

  "part_b_current_market_state": {
    "timestamp": "2026-10-29T10:16:00+05:30",
    "market_phase": "REGULAR_TRADING",
    "indices": {
      "NIFTY50": {
        "ltp": 22145.5,
        "delta_price_1m": 10.5,
        "volume": 2450000,
        "delta_volume_1m": 35000,
        "vwap": 22120.0,
        "dist_to_vwap": 25.5,
        "delta_dist_to_vwap": 10.5,
        "futures_premium": 18.5,
        "delta_premium": 2.0
      },
      "BANKNIFTY": {
        "ltp": 47650.0,
        "delta_price_1m": 65.0,
        "volume": 1890000,
        "delta_volume_1m": 42000,
        "vwap": 47590.0,
        "dist_to_vwap": 60.0,
        "futures_premium": 32.0
      },
      "NIFTYIT": { "ltp": 36820.0, "delta_price_1m": 45.0 },
      "INDIAVIX": { "ltp": 13.85, "delta_vix_1m": -0.15 }
    },
    "orderflow": {
      "NIFTY_PCR": 1.18,
      "BANKNIFTY_PCR": 1.25,
      "NIFTY_CVD": 81450,
      "delta_nifty_cvd_1m": 17250,
      "BANKNIFTY_CVD": 98200,
      "delta_banknifty_cvd_1m": 8700,
      "AD_RATIO": 2.4
    },
    "options_data": {
      "NIFTY_GEX": 1850000.0,
      "NIFTY_MAXPAIN": 22100.0,
      "BANKNIFTY_GEX": -420000.0,
      "BANKNIFTY_MAXPAIN": 47500.0,
      "chain": {
        "NIFTY": {
          "22150CE": {
            "ltp": 112.5,
            "delta_ltp_1m": 14.0,
            "volume": 420000,
            "delta_volume_1m": 12000,
            "oi": 1850000,
            "delta_oi_1m": -85000,
            "iv": 13.8,
            "delta": 0.52,
            "gamma": 0.0028,
            "theta": -14.2,
            "bid_ask_spread": 0.15
          },
          "22150PE": {
            "ltp": 88.0,
            "delta_ltp_1m": -12.5,
            "volume": 310000,
            "delta_volume_1m": 4500,
            "oi": 2450000,
            "delta_oi_1m": 142000,
            "iv": 14.1,
            "delta": -0.48,
            "gamma": 0.0026,
            "theta": -13.5,
            "bid_ask_spread": 0.15
          }
        }
      }
    },
    "heavyweights": {
      "HDFCBANK": { "ltp": 1465.0, "delta_ltp_1m": 2.5, "volume": 1250000, "delta_vol_1m": 18000, "imbalance": 2.45 },
      "RELIANCE": { "ltp": 2995.0, "delta_ltp_1m": 4.0, "volume": 850000, "delta_vol_1m": 14500, "imbalance": 1.85 },
      "ICICIBANK": { "ltp": 1110.0, "delta_ltp_1m": 1.8, "volume": 620000, "delta_vol_1m": 9200, "imbalance": 2.10 }
    },
    "macro": {
      "DXY": 103.85,
      "CRUDE": 81.20,
      "BOND_10Y": 4.18
    },
    "institutional": {
      "fii_net_crores": 1450.8,
      "dii_net_crores": 890.2
    },
    "prev_ohlc": {
      "NIFTY50": { "close": 22080.0, "pdh": 22130.0, "pdl": 21980.0 },
      "BANKNIFTY": { "close": 47450.0, "pdh": 47700.0, "pdl": 47200.0 }
    },
    "breaking_news": [
      { "headline": "US Fed hints at steady rate trajectory", "source": "NewsAPI", "sentiment": "POSITIVE" }
    ],
    "indian_news": [
      { "headline": "Auto sales surge 18% in monthly metrics", "source": "ET", "sentiment": "BULLISH" }
    ]
  },

  "part_c_current_execution_state": {
    "open_positions": [],
    "pending_orders": [],
    "realized_pnl_today": 3450.0,
    "unrealized_pnl": 0.0,
    "capital_available": 500000.0,
    "margin_utilized_pct": 0.0,
    "daily_loss_limit_remaining": 15000.0,
    "trades_executed_today": 3,
    "active_lot_size_nifty": 75,
    "active_lot_size_banknifty": 30
  },

  "part_d_cognitive_instructions": [
    "Treat part_a_previous_decision as immutable historical context recorded at t-1.",
    "Evaluate all 32 market data factors using part_b_current_market_state.",
    "Compare previous factor values with current values using the pre-calculated numeric deltas.",
    "Identify strengthening signals (e.g. CVD surging from +64k to +81k, Call short-covering accelerating to -85k).",
    "Identify conflicting signals (e.g. heavyweights diverging, spreads widening, IV spiking).",
    "Anti-Anchoring Protocol: Do NOT anchor to the prior action. If previously HOLD awaiting CVD confirmation, and CVD has now decisively confirmed with zero critical conflicts, transition to BUY. If technicals fail, downgrade or EXIT immediately.",
    "Strict Risk Separation: Specify order sizing strictly in 'lots' (integer). The Python execution engine enforces broker lot multiplication (e.g., 2 lots = 150 units) and checks SEBI freeze limits independently.",
    "Output MUST conform strictly to Contract 1 (Complete 32-Factor Audited JSON Schema) with NO markdown fences, NO conversational preamble, and NO omitted factor IDs."
  ]
}
```

---

### 2.8 The System Prompt Rules Fed to the Model
The system prompt establishes immutable mathematical and logical constraints:
1. **Periodic Re-Evaluation Without Overtrading:** The 60-second timer is an audit interval, NOT a signal-generation mandate. `HOLD` (maintaining position or bias) and `NO_TRADE` (waiting for institutional confluence) are the expected, safe baseline responses. The model must NEVER feel compelled to generate an entry signal merely because the evaluation timer ticked.
2. **Action Space Definition:**
   * `ENTER_CALL` / `BUY`: Long call momentum setup with verified institutional confirmation.
   * `ENTER_PUT` / `BUY`: Long put momentum breakdown setup with verified institutional confirmation.
   * `HOLD`: Position is active and progressing favorably, or neutral market regime awaiting setup.
   * `EXIT` / `SELL`: Momentum stalled, adverse order flow detected, or profit target reached.
   * `NO_TRADE`: Choppy or conflicting factor conditions; capital preservation mode.
   * `REDUCE`: Partial profit taking (scale out lots ahead of major technical resistance/support).
3. **Price-Volume-CVD Confirmation Rule:** A spot breakout without aggressive CVD expansion ($\Delta\text{CVD} > 0$) and heavyweight volume surge is classified as an institutional trap $\rightarrow$ **VETO trade (`NO_TRADE` / `HOLD`)**.
4. **VWAP Boundary Law:** Never BUY calls if spot price is below VWAP; never BUY puts if spot price is above VWAP.
5. **Delta OI Confirmation:** Bullish entries require Call $\Delta\text{OI}$ contraction (short-covering) or aggressive Put $\Delta\text{OI}$ expansion (floor support). Bearish entries require Put $\Delta\text{OI}$ contraction or Call $\Delta\text{OI}$ addition.
6. **Active Trade Management Priority:** If `current_execution_state.open_positions` is not empty, the model's sole priority is managing the active position (`HOLD` to ride the trend, `REDUCE` to take partial profits, or `EXIT` if adverse delta emerges). It must NEVER recommend opening a new position while an active position is open.
7. **Anti-Hallucination Discount:** If any confirmation factor in the 32 dimensions is unaligned, apply an automatic $-30\%$ confidence deduction.
8. **Confidence Barrier:** Any final confidence score $< 95\%$ for new entries forces an immediate output of **`HOLD`** or **`NO_TRADE`**.
9. **Complete 32-Factor Enumeration:** All 32 factors must be explicitly evaluated in `factors[0..31]`. Missing data must be assigned `status: "UNAVAILABLE"` and `value: null`. Never invent missing values.
10. **Dynamic Lot Sizing:** Sizing must be given in `lots` (integer), never raw quantity shares. Sizing is governed by the daily risk budget and SEBI contract specifications.

---

## 3. What We Expect from the LLM (Response Contracts)

The engine enforces strict, machine-readable JSON schemas with no markdown commentary, markdown fences, or conversational filler.

### Contract 1: Live Market Trading Decision Schema (Complete 32-Factor Audited JSON)

To ensure full institutional auditability and eliminate "black box" decisions, the LLM must return a structured evaluation of **all 32 market data dimensions** individually. Each factor is tagged with its measured value, status, structural weight, analytical note, and decision impact.

#### Core Structural Principles:
1. **Mandatory 32-Factor Enumeration:** All 32 factors must always be present. If data for a factor is absent, the model assigns `status: "UNAVAILABLE"` and `value: null`. It must never hallucinate values or skip factor IDs.
2. **Fixed Evidence Status Enum:** `SUPPORTING`, `CONFLICTING`, `NEUTRAL`, `WARNING`, or `UNAVAILABLE`.
3. **Fixed Decision Impact Enum:** `SUPPORTS`, `CONFLICTS`, `NEUTRAL`, `RISK`, or `UNKNOWN`.
4. **Predefined Structural Weights:** `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`.
5. **Separation of Analysis from Execution Authorization:** The LLM produces the qualitative/quantitative audit and trading recommendation. The Python execution engine calculates the summary metrics independently and enforces hard risk controls before any order is dispatched.

```json
{
  "decision_id": "DEC_20261029_101532_NIFTY",
  "timestamp": "2026-10-29T10:15:32+05:30",
  "instrument": "NIFTY",
  "timeframe": "1m",

  "action": "ENTER_CALL | ENTER_PUT | HOLD | EXIT | NO_TRADE | REDUCE",
  "direction": "BULLISH | BEARISH | NEUTRAL",
  "setup": "MOMENTUM_BREAKOUT | MEAN_REVERSION | EXPIRY_PIN | NONE",
  "symbol": "OPT:NIFTY:22150CE",
  "lots": 2,
  "confidence": 95,

  "factor_audit": {
    "summary_metrics": {
      "total_factors_required": 32,
      "total_factors_evaluated": 32,
      "supporting_count": 21,
      "conflicting_count": 3,
      "warning_count": 1,
      "neutral_count": 7,
      "unavailable_count": 0,
      "critical_failures": [],
      "net_alignment_pct": 87.5,
      "win_probability": null
    },

    "factors": [
      {
        "factor_id": 1,
        "name": "Index Spot Prices",
        "value": "22145.50",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Spot made a clean breakout above the 22130 opening range resistance on expanding candle size.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 2,
        "name": "Futures LTP and Volume",
        "value": "LTP: 22164.00, Vol: 2,450,000",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Futures trading with strong volume participation, confirming genuine institutional flow.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 3,
        "name": "Futures Premium or Discount",
        "value": "+18.50 pts (Expanding)",
        "status": "SUPPORTING",
        "weight": "MEDIUM",
        "analysis": "Futures premium expanding over spot indicates sustained buyer aggression rather than passive absorption.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 4,
        "name": "VWAP Trend",
        "value": "Spot 22145.5 > VWAP 22120.0",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Price firmly established above institutional fair-value benchmark with positive upward slope.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 5,
        "name": "Index Volume Spikes",
        "value": "+35,000 delta volume (3.2x relative spike)",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Breakout candle accompanied by a 3.2x volume surge compared to the 10-minute baseline.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 6,
        "name": "Option Chain LTP",
        "value": "22150CE LTP 112.50 (+14% in 1m)",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "ATM Call option exhibiting aggressive premium expansion with rapid follow-through.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 7,
        "name": "Option Volume and Delta Volume",
        "value": "22150CE Vol: 420,000, Delta Vol: +12,000",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Heavy concentration of transaction volume entering the ATM call strike.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 8,
        "name": "Open Interest and Change in OI",
        "value": "22150CE -85,000 / 22150PE +142,000",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Significant Call writer short-covering combined with massive aggressive Put writing support.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 9,
        "name": "Option Delta",
        "value": "0.52 (ATM)",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Contract Delta falls within optimal scalp sensitivity zone [0.50, 0.70] for 1:1 price tracking.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 10,
        "name": "Option Gamma",
        "value": "0.0028",
        "status": "SUPPORTING",
        "weight": "MEDIUM",
        "analysis": "Healthy positive Gamma provides accelerated premium expansion on further spot moves.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 11,
        "name": "Option Theta",
        "value": "-14.20 pts/day",
        "status": "NEUTRAL",
        "weight": "MEDIUM",
        "analysis": "Intraday Theta decay is manageable during morning momentum phase (10:15 IST).",
        "decision_impact": "NEUTRAL"
      },
      {
        "factor_id": 12,
        "name": "Vega and Rho",
        "value": "Vega: 0.18, Rho: 0.04",
        "status": "NEUTRAL",
        "weight": "LOW",
        "analysis": "Minor sensitivity to implied volatility swings; minimal macro interest rate impact.",
        "decision_impact": "NEUTRAL"
      },
      {
        "factor_id": 13,
        "name": "IV and IV Rank or Percentile",
        "value": "IV: 13.8%, IV Rank: 28%",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Low IV Rank indicates premiums are not artificially inflated, eliminating IV Crush risk.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 14,
        "name": "Put-Call Ratio (PCR)",
        "value": "1.18 (Shifted from 0.95 at open)",
        "status": "SUPPORTING",
        "weight": "MEDIUM",
        "analysis": "Rising PCR confirms shifting intraday sentiment toward bullish put writing.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 15,
        "name": "Gamma Exposure (GEX) and Gamma Flip",
        "value": "-420,000 (Negative GEX Zone)",
        "status": "SUPPORTING",
        "weight": "MEDIUM",
        "analysis": "Dealers positioned in negative gamma; dealer hedging activity amplifies trend continuation.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 16,
        "name": "Max Pain and Expiry Pinning",
        "value": "Max Pain: 22100.00",
        "status": "NEUTRAL",
        "weight": "LOW",
        "analysis": "Current price 22145 is 45 pts above Max Pain; expiry pinning forces only activate post 13:30 IST.",
        "decision_impact": "NEUTRAL"
      },
      {
        "factor_id": 17,
        "name": "Level 2 Market Depth",
        "value": "Top 5 Bids 145,000 vs Asks 85,000",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Strong resting limit bid depth providing support underneath the market.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 18,
        "name": "Order Book Imbalance",
        "value": "1.71 (Bid/Ask)",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Bids outweigh asks by 1.71:1, well clear of the 0.33 threshold that pauses bullish triggers.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 19,
        "name": "Cumulative Volume Delta (CVD)",
        "value": "+64,200 contracts",
        "status": "SUPPORTING",
        "weight": "CRITICAL",
        "analysis": "Aggressive market buy orders dominating the tape; validates genuine breakout.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 20,
        "name": "Bid-Ask Spread and Liquidity",
        "value": "Spread: 0.25 pts (112.35 x 112.60)",
        "status": "SUPPORTING",
        "weight": "CRITICAL",
        "analysis": "Tight spread well below the 1.50 pt maximum threshold; minimal execution slippage.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 21,
        "name": "Heavyweight Prices and Volumes",
        "value": "HDFCBANK +1.2%, RELIANCE +0.8%, ICICIBANK +1.1%",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Top 3 index heavyweights advancing in unison with volume, providing solid backing.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 22,
        "name": "Heavyweight Order Book Imbalances",
        "value": "HDFCBANK OBI: 2.45, RELIANCE OBI: 1.85",
        "status": "SUPPORTING",
        "weight": "MEDIUM",
        "analysis": "Heavyweight order books show thick bid support absorbing all passive selling.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 23,
        "name": "Advance-Decline Ratio",
        "value": "2.40 (35 Advances / 15 Declines)",
        "status": "SUPPORTING",
        "weight": "MEDIUM",
        "analysis": "Broad market participation confirms rally is index-wide, not an isolated single-stock trap.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 24,
        "name": "Sectoral Synergy",
        "value": "Nifty Bank +0.80% vs Nifty IT +0.10%",
        "status": "WARNING",
        "weight": "MEDIUM",
        "analysis": "IT sector is flat/lagging while banking surges; slight cross-sector drag reduces scalp target.",
        "decision_impact": "RISK"
      },
      {
        "factor_id": 25,
        "name": "India VIX",
        "value": "13.85 (Flat / Mild Drop)",
        "status": "WARNING",
        "weight": "MEDIUM",
        "analysis": "Subdued VIX limits probability of extended 50+ pt runs; target capped at conservative 30 pts.",
        "decision_impact": "RISK"
      },
      {
        "factor_id": 26,
        "name": "PDH, PDL, PDC and Daily Pivots",
        "value": "Cleared PDH (22130) by 15.5 pts",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Breakout has cleared previous day high, triggering resting buy-stop liquidity.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 27,
        "name": "GIFT Nifty",
        "value": "Settled (+110 pts at open)",
        "status": "NEUTRAL",
        "weight": "LOW",
        "analysis": "Pre-market gap has been absorbed into regular trading session; low predictive value now.",
        "decision_impact": "NEUTRAL"
      },
      {
        "factor_id": 28,
        "name": "US Dollar Index (DXY)",
        "value": "103.85 (Flat)",
        "status": "NEUTRAL",
        "weight": "LOW",
        "analysis": "DXY trading sideways; no acute macro currency pressure on Indian markets.",
        "decision_impact": "NEUTRAL"
      },
      {
        "factor_id": 29,
        "name": "Brent Crude Oil",
        "value": "$81.20 / bbl (-0.4%)",
        "status": "SUPPORTING",
        "weight": "LOW",
        "analysis": "Mild softness in crude oil is supportive of Indian Rupee and banking credit health.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 30,
        "name": "US 10-Year Treasury Yield",
        "value": "4.18% (Stable)",
        "status": "NEUTRAL",
        "weight": "LOW",
        "analysis": "US bond yields stable; no risk of sudden foreign capital flight today.",
        "decision_impact": "NEUTRAL"
      },
      {
        "factor_id": 31,
        "name": "Breaking Financial News",
        "value": "Auto sales surge 18%; Fed hints at rate pause",
        "status": "SUPPORTING",
        "weight": "HIGH",
        "analysis": "Domestic and global news flow is positive with no adverse regulatory headlines.",
        "decision_impact": "SUPPORTS"
      },
      {
        "factor_id": 32,
        "name": "FII/DII Positioning and Economic Calendar",
        "value": "FII Net: +₹1,450 Cr; Blackout: Clear",
        "status": "SUPPORTING",
        "weight": "MEDIUM",
        "analysis": "Positive institutional cash flow carryover from prior session; no RBI/Fed blackout events.",
        "decision_impact": "SUPPORTS"
      }
    ]
  },

  "reason": "HIGH PROBABILITY BULLISH SCALP: 21 of 32 factors actively support long entry (87.5% net alignment). Core confluence: Spot above VWAP, positive CVD (+64.2k contracts), Call short-covering (-85k Delta OI), and strong heavyweight support (HDFC Bank & Reliance OBI > 1.8). The 2 warning factors (subdued VIX, lagging IT) are mitigated by scaling target to 30 points with a strict 15-point stop loss.",

  "risk_controls": {
    "data_quality_passed": true,
    "critical_checks_passed": true,
    "daily_loss_limit_passed": true,
    "position_size_validated": true,
    "broker_state_reconciled": true,
    "execution_authorized": false
  }
}
```

---

### Contract 1 Field Definitions & Schema Rules

| Field / Object | Type | Rules & Constraints |
| :--- | :--- | :--- |
| `decision_id` | `string` | Unique identifier formatted as `DEC_{YYYYMMDD}_{HHMMSS}_{INSTRUMENT}` to trace input snapshot, LLM audit, broker orders, and fills. |
| `timestamp` | `string` | ISO 8601 formatted timestamp with IST timezone offset (`+05:30`). |
| `instrument` | `string` | Target market (`NIFTY` or `BANKNIFTY`). |
| `timeframe` | `string` | Analysis timeframe (strictly `1m` for the scalping loop). |
| `action` | `string` | Enum: `ENTER_CALL`, `ENTER_PUT`, `HOLD`, `EXIT`, `NO_TRADE`, `REDUCE` (fully backwards-compatible with `BUY`, `SELL`, `HOLD`, `CLOSE_ALL`). |
| `direction` | `string` | Enum: `BULLISH`, `BEARISH`, `NEUTRAL`. |
| `setup` | `string` | Strategy classification: `MOMENTUM_BREAKOUT`, `MEAN_REVERSION`, `EXPIRY_PIN`, `NONE`. |
| `symbol` | `string` | Explicit target token (e.g. `OPT:NIFTY:22150CE`) or `null` if action is `HOLD` / `CLOSE_ALL`. |
| `lots` | `integer` | Target lots to trade ($0$ if `HOLD` / `CLOSE_ALL`). Actual quantity is dynamically resolved via broker scrip master. |
| `confidence` | `integer` | Probabilistic confidence score (0 to 100). Must be $\ge 90$ for live execution. |
| `factor_audit.factors` | `array` | Exactly **32 items**, indexed from `factor_id: 1` through `factor_id: 32`. |
| `factors[].status` | `string` | Strict Enum: `SUPPORTING`, `CONFLICTING`, `NEUTRAL`, `WARNING`, `UNAVAILABLE`. |
| `factors[].decision_impact` | `string` | Strict Enum: `SUPPORTS`, `CONFLICTS`, `NEUTRAL`, `RISK`, `UNKNOWN`. |
| `factors[].weight` | `string` | Predefined criticality: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`. |
| `risk_controls` | `object` | Independent Python execution flags. `execution_authorized` is set to `true` **only by the Python engine**, never by the LLM. |

---

### Python-Side Validation Rules for Contract 1

1. **Independent Metric Recalculation:** The Python execution engine must recalculate `supporting_count`, `conflicting_count`, `warning_count`, `unavailable_count`, and `net_alignment_pct` directly from the array of 32 factors. It must never trust self-reported LLM counts.
2. **Critical Failure Rule:** If any factor with `weight: "CRITICAL"` (e.g. Factor 19: CVD or Factor 20: Bid-Ask Spread) has `status: "CONFLICTING"` or `"UNAVAILABLE"`, execution is blocked immediately regardless of the overall alignment percentage.
3. **Missing Data Handling:** If a required feed disconnects, the missing factor is marked `UNAVAILABLE`. Missing core market feeds (Greeks, Depth, Spot) automatically force `data_quality_passed = false` and action defaults to `HOLD`.
4. **Execution Authorization Lock:** The field `risk_controls.execution_authorized` remains `false` until the Python risk engine verifies:
   * Cumulative daily loss $<$ Daily Loss Ceiling.
   * Consecutive loss counter $< 3$.
   * No active RBI/Fed policy blackout window.
   * Order quantity within NSE Freeze Quantity (or sliced into child orders).
   * Broker session authenticated and matching engine responding.

---

### Contract 2: Dual-Brain Consensus Engine
To prevent catastrophic model hallucinations or single-model bias, [`strategy_engine/llm_client.py`](file:///d:/projects/Trading_Algorithm_Software/strategy_engine/llm_client.py) queries **Anthropic Claude 3.5 Sonnet** and **Google Gemini Pro** concurrently using `asyncio.gather()`:

```
                          ┌──────────────────────┐
                          │ Market State Payload │
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
         [ Claude 3.5 Sonnet ]               [ Gemini 1.5/2.5 Pro ]
                    │                                 │
                    ▼                                 ▼
            Decision A (JSON)                 Decision B (JSON)
                    │                                 │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │    Dual-Brain Consensus Engine  │
                    │   • Actions Must Match          │
                    │   • Symbols Must Match          │
                    │   • Average Confidence >= 90%   │
                    └────────────────┬────────────────┘
                                     │
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
             [ Approved Trade ]               [ Default to HOLD ]
```

* **Consensus Rule:** A trade executes **only if** $\text{Action}_A == \text{Action}_B$ AND $\text{Symbol}_A == \text{Symbol}_B$ AND $\frac{\text{Conf}_A + \text{Conf}_B}{2} \ge 90\%$.
* **Disagreement Rule:** If Claude recommends `BUY` but Gemini recommends `HOLD` (or vice-versa), the system instantly defaults to **`HOLD`**.
* **Safety Override Rule:** If **either** brain outputs `CLOSE_ALL` (due to an acute news/macro event), the system ignores consensus and immediately triggers total position liquidation.

---

## 4. How the LLM Response is Processed into an Executable Trade Plan

The LLM is the **strategic brain (Slow Loop)**, but the **Python Execution Engine (Fast Loop)** converts that decision into a concrete, risk-managed order plan executed in sub-10 milliseconds.

```
 [LLM Response] ──► [Risk Pre-Checks] ──► [Dynamic Strike Mapper] ──► [Bracket Order Assembly] ──► [Broker Router]
```

---

### Step 1: Pre-Execution Risk Gatekeepers & Anti-Overtrading Shield
Before any order packet is dispatched to a broker:
1. **Daily Trade Quota Ceiling (Anti-Overtrading Shield):** A hard limit of **maximum 3 trades per day** (configurable 1–3). Amateurs churn 50 trades and lose capital to slippage; our system executes with extreme selectivity. Once 3 trades are completed, order dispatch is locked until the next session.
2. **Post-Trade Mandatory Observation Lockout (20 Minutes):** Following the closure of any trade (win or loss), the execution engine enforces an automatic **20-minute mandatory observation cooldown**. New order signals are strictly blocked during this window to eliminate revenge trading and prevent re-entering immediate post-breakout consolidation.
3. **Chop Zone Execution Veto (Positive GEX + Divergence):** If Nifty GEX is strongly positive ($\text{Net GEX} > +1,500,000$) and sectoral breadth is divergent (e.g. Bank Nifty advancing but IT declining), the engine triggers an automatic **Chop Veto**, overriding LLM entry signals with `NO_TRADE`.
4. **Daily Loss Ceiling:** If cumulative daily loss reaches the configured threshold (e.g., ₹5,000), the execution engine locks trading and cancels all resting orders.
5. **Consecutive Loss Cooldown:** If 2 consecutive losses occur, trading is paused for 45 minutes to allow market regime recalibration.
6. **Blackout Window Check:** Verifies current time against scheduled high-impact events (RBI MPC statements, US Fed rate cuts) and enforces a 15-minute trading blackout before and after.
7. **NSE Circuit Breaker Guard:** Confirms index is within normal operational price bands.

---

### Step 2: Dynamic Strike & Instrument Mapping
If the LLM recommends `BUY OPT:NIFTY:ATM_CE`:
1. The Fast Loop reads the latest spot price from Redis (e.g., `22,145.5`).
2. Calculates exact ATM strike:  
   $$\text{ATM Strike} = \text{round}\left(\frac{22145.5}{50}\right) \times 50 = 22,150$$
3. Maps token to weekly expiry contract: `NIFTY26OCT22150CE`.
4. Validates real-time Greeks for the contract:
   * Confirms $\Delta \ge 0.50$.
   * Confirms Bid-Ask spread $\le 1.5$ points.

---

### Step 3: Dynamic Lot-to-Quantity Resolution (SEBI Revisions & Freeze Limits)
The strategy and AI engine strictly reason in **Lots**, never hardcoded share quantities. Because SEBI periodically revises derivative contract lot sizes (e.g. Nifty changing between 50, 25, and 75; Bank Nifty changing between 25, 15, and 30):

1. **Daily Broker Scrip Master Ingestion:** At 08:30 AM IST, the execution engine ingests the broker's security master file (Shoonya/Dhan/Upstox contract master) into Redis, extracting the active `lot_size` and `freeze_quantity` for every instrument token.
2. **Dynamic Quantity Calculation:**
   $$\text{Order Quantity} = \text{Strategy Lots} \times \text{Broker Current Lot Size}$$
   *Example:* If the strategy targets `2 Lots` of Nifty:
   * If Nifty lot size is 75 $\rightarrow \text{Quantity} = 2 \times 75 = 150$.
   * If Nifty lot size is 25 $\rightarrow \text{Quantity} = 2 \times 25 = 50$.
3. **NSE Freeze Limit Slicing:** If the computed quantity exceeds the exchange freeze quantity (e.g., maximum 1,800 units on Nifty), the execution router automatically slices the order into multiple parallel child orders to avoid broker RMS rejection (`RMS: Freeze Limit Exceeded`).

---

### Step 4: Dynamic Risk-Budgeted Lot Sizing
Lot sizing scales with predefined Rupee Risk ($R$), stop distance, and dual-brain confidence:
$$\text{Max Allowed Lots} = \left\lfloor \frac{\text{Predefined Max Rupee Risk (e.g. ₹2,000)}}{\text{Stop Loss Points} \times \text{Broker Lot Size}} \right\rfloor$$

* **Confidence 90% – 92% (Base Setup):** 1 Lot (Conservative probe).
* **Confidence 93% – 95% (Strong Setup):** 2–3 Lots (bounded by Max Allowed Lots).
* **Confidence 96% – 100% (A+ Institutional Setup):** Maximum allowed risk allocation (never exceeding daily risk limit).

---

### Step 5: Bracket Order Assembly (Entry + Stop Loss + Take Profit)
Orders are never entered naked without protective stops. The execution engine constructs a comprehensive bracket order:

```json
{
  "order_type": "LIMIT",
  "symbol": "NIFTY26OCT22150CE",
  "lots": 2,
  "quantity": 150,
  "limit_price": 112.50,
  "stop_loss": {
    "trigger_price": 97.50,
    "limit_price": 96.00,
    "points": 15.0
  },
  "take_profit": {
    "limit_price": 142.50,
    "points": 30.0
  },
  "trailing_stop": {
    "activation_threshold": 15.0,
    "trail_distance": 10.0
  },
  "max_holding_time_seconds": 180
}
```

---

### Step 6: Execution Routing & Sub-Millisecond Failover
The execution router employs a **multi-broker decoupled failover architecture**:
* **Primary Route:** **Shoonya (Finvasia)** — Dispatched via asynchronous REST API to achieve zero brokerage.
* **Failover Route:** If Shoonya times out ($> 500\text{ ms}$), returns an HTTP 5xx, or rejects due to broker infrastructure failure, the failover router immediately reroutes the exact bracket order to **DhanHQ** or **Fyers**.

---

### Step 7: Active Trade Lifecycle & Continuous Between-Decision Monitoring

Once a position is opened, management splits into two distinct, non-interfering loops:

#### 1. The Fast Execution Loop (Sub-10ms Tick Monitoring & Independent Safety)
Between 60-second LLM cycles, the Python Fast Loop monitors position health on every single incoming WebSocket tick (every 50–100ms) and independently enforces risk controls without waiting for LLM approval:
* **Dynamic Trailing Stop Protection:** When option premium gains $+15$ points, the stop-loss automatically ratchets upward, locking in break-even, and subsequently trails 10 points below the high watermark.
* **Emergency Protective Exit:** If an unexpected flash crash occurs, or the underlying index violently moves $> 0.5\%$ against the position in seconds, Python executes an immediate emergency market liquidation. **It never blocks or waits for an LLM response to enforce protective stops.**
* **Time-Based Theta Decay Guard:** If the option price fluctuates within a narrow 4-point range for $> 3$ minutes without directional momentum, Python market-exits the trade to prevent theta decay.
* **Exchange-Side Bracket Persistence & Deadman Switch:** Protective stop-loss legs are placed directly on the broker's order book. If the local engine loses power or internet connectivity, exchange-side orders protect against catastrophic drawdown.

#### 2. The Slow Cognitive Loop (60-Second Re-Evaluation & Strategic Direction)
At the next 60-second boundary (e.g., at 10:16:00), the LLM receives the updated market state, its own previous decision, and verified broker portfolio ground truth:
* **`HOLD`:** Momentum continues to build; $\Delta\text{CVD}$ is accelerating, heavyweights remain aligned $\rightarrow$ Ride the scalp toward the take-profit target.
* **`REDUCE`:** Target resistance approached or momentum decelerating $\rightarrow$ Scale out 50% of active lots to bank profits while holding remainder risk-free.
* **`EXIT`:** Factor deterioration detected (e.g., Call short-covering abruptly turns into aggressive Call writing, or CVD shows bearish divergence) $\rightarrow$ Close position immediately at market.

#### 3. Out-of-Band Event Interrupt Protocol
While the default re-evaluation interval is 60 seconds, an asynchronous **Emergency LLM Interrupt** is triggered if:
* An acute breaking news headline with extreme negative sentiment is ingested.
* India VIX spikes $> 15\%$ within a 30-second window.
* Index Spot breaches the Gamma Flip inflection level.  
*When an interrupt fires, the LLM is prompted out-of-band to reassess macro bias, while Python enforces stops deterministically in the interim.*

---

## 5. Architectural Summary & Codebase Traceability

| Component | Codebase Implementation | Role |
| :--- | :--- | :--- |
| **Real-Time Data Ingestion** | [`data_ingestion/primary_node.py`](file:///d:/projects/Trading_Algorithm_Software/data_ingestion/primary_node.py) | Dhan / TrueData tick-by-tick WebSocket streaming to Redis. |
| **Greeks Engine** | [`data_ingestion/greeks_engine.py`](file:///d:/projects/Trading_Algorithm_Software/data_ingestion/greeks_engine.py) | Black-Scholes calculation of Delta, Theta, Gamma, IV, GEX, and Max Pain. |
| **Order Flow Engine** | [`data_ingestion/orderflow_engine.py`](file:///d:/projects/Trading_Algorithm_Software/data_ingestion/orderflow_engine.py) | Real-time computation of CVD, Order Book Imbalance, and VWAP. |
| **Macro & News Node** | [`data_ingestion/macro_node.py`](file:///d:/projects/Trading_Algorithm_Software/data_ingestion/macro_node.py) | Ingestion of DXY, Crude, 10Y Yields, and live RSS/NewsAPI headlines. |
| **Decision Memory & State Storage** | [`core/redis_client.py`](file:///d:/projects/Trading_Algorithm_Software/core/redis_client.py) / [`strategy_engine/brain.py`](file:///d:/projects/Trading_Algorithm_Software/strategy_engine/brain.py) | Persistence of `DECISION:LATEST`, `DECISION:HISTORY`, and timeline sets for sequential continuity. |
| **State Builder** | [`strategy_engine/state_builder.py`](file:///d:/projects/Trading_Algorithm_Software/strategy_engine/state_builder.py) | Construction of the Tripartite Prompt payload (Parts A, B, C, D) with pre-computed deltas. |
| **Dual-Brain AI Client** | [`strategy_engine/llm_client.py`](file:///d:/projects/Trading_Algorithm_Software/strategy_engine/llm_client.py) | Concurrent execution of Claude 3.5 Sonnet & Gemini with consensus filtering. |
| **Risk Management Guard** | [`strategy_engine/risk_manager.py`](file:///d:/projects/Trading_Algorithm_Software/strategy_engine/risk_manager.py) | Enforcement of daily loss limits, trailing stops, and circuit breakers. |
| **Execution Routers** | [`execution_engine/shoonya_router.py`](file:///d:/projects/Trading_Algorithm_Software/execution_engine/shoonya_router.py) | Low-latency order placement with automatic multi-broker failover. |
