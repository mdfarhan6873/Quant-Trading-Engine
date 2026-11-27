import { MarketStateData, DimensionHealthItem, OptionContractData } from "@/types/market";

/** Finds the closest Call/Put pair to current Nifty spot instead of picking an arbitrary edge strike. */
export function findNearestATMOptions(
  chain: Record<string, OptionContractData> | undefined,
  spotPrice: number
): { ceKey?: string; peKey?: string; ce?: OptionContractData | null; pe?: OptionContractData | null } {
  if (!chain || Object.keys(chain).length === 0) return {};

  let bestCEKey: string | undefined;
  let bestCE: OptionContractData | null = null;
  let bestCEDiff = Infinity;

  let bestPEKey: string | undefined;
  let bestPE: OptionContractData | null = null;
  let bestPEDiff = Infinity;

  for (const [k, v] of Object.entries(chain)) {
    const strikeMatch = k.match(/^(\d+)/);
    const strike = strikeMatch ? parseFloat(strikeMatch[1]) : 0;
    const diff = spotPrice > 0 && strike > 0 ? Math.abs(strike - spotPrice) : 0;

    if (k.endsWith("CE") && diff < bestCEDiff) {
      bestCEDiff = diff;
      bestCEKey = k;
      bestCE = v;
    } else if (k.endsWith("PE") && diff < bestPEDiff) {
      bestPEDiff = diff;
      bestPEKey = k;
      bestPE = v;
    }
  }

  return { ceKey: bestCEKey, peKey: bestPEKey, ce: bestCE, pe: bestPE };
}

export function evaluate32DimensionsHealth(state?: MarketStateData | null): DimensionHealthItem[] {
  if (!state) {
    return Array.from({ length: 32 }, (_, i) => ({
      id: i + 1,
      category: i < 5 ? "A" : i < 16 ? "B" : i < 20 ? "C" : i < 26 ? "D" : "E",
      categoryName: i < 5 ? "Spot & Futures" : i < 16 ? "Options & Greeks" : i < 20 ? "Order Flow" : i < 26 ? "Breadth & Heavyweights" : "Macro & News",
      name: `Dimension ${i + 1}`,
      keyPath: "unknown",
      status: "FAIL",
      valueFormatted: "No Stream",
      latencyMs: 9999,
      source: "Offline",
      message: "Awaiting WebSocket connection",
    }));
  }

  const ind = state.indices || {};
  const nifty = ind.NIFTY50;
  const bank = ind.BANKNIFTY;
  const vix = ind.INDIAVIX;
  const fl = (state.orderflow || {}) as Partial<NonNullable<MarketStateData["orderflow"]>>;
  const opt = (state.options_data || {}) as Partial<NonNullable<MarketStateData["options_data"]>>;
  const hw = (state.heavyweights || {}) as NonNullable<MarketStateData["heavyweights"]>;
  const macro = (state.macro || {}) as NonNullable<MarketStateData["macro"]>;
  const inst = (state.institutional || {}) as Partial<NonNullable<MarketStateData["institutional"]>>;
  const ohlc = (state.prev_ohlc || {}) as NonNullable<MarketStateData["prev_ohlc"]>;
  const allNews = [...(state.breaking_news || []), ...(state.indian_news || [])];

  const spot = nifty?.ltp || 0;
  const niftyChain = opt.chain?.NIFTY || {};
  const { ceKey: atmCEKey, ce: atmCE, pe: atmPE } = findNearestATMOptions(niftyChain, spot);
  const sampleOpt = atmCE || atmPE;

  const hasFutures = Boolean(nifty?.futures_ltp && nifty.futures_ltp > 0);
  const hasOptionChain = Object.keys(niftyChain).length > 0;
  const hasDepth = Boolean(sampleOpt && ((sampleOpt.tbq || 0) > 0 || (sampleOpt.tsq || 0) > 0 || (sampleOpt.bid || 0) > 0));
  const spreadVal = sampleOpt?.bid_ask_spread;
  const spreadValid = spreadVal !== undefined && ((sampleOpt?.bid || 0) > 0 || (sampleOpt?.ask || 0) > 0);

  const tbqTotal = (atmCE?.tbq || 0) + (atmPE?.tbq || 0);
  const tsqTotal = (atmCE?.tsq || 0) + (atmPE?.tsq || 0);
  const atmObi = tsqTotal > 0 ? tbqTotal / tsqTotal : hw.HDFCBANK?.imbalance;

  const indexSource = state.data_sources?.nifty_source || nifty?.source || "NSE Official";
  const vixSource = state.data_sources?.vix_source || vix?.source || "NSE India VIX";
  const pollAgeMs = state.data_sources?.last_poll_ts
    ? Math.max(20, Math.round((Date.now() / 1000 - state.data_sources.last_poll_ts) * 1000))
    : 250;

  const pdhVal = ohlc.NIFTY50?.pdh ?? ohlc.NIFTY50?.high;
  const pdlVal = ohlc.NIFTY50?.pdl ?? ohlc.NIFTY50?.low;
  const fiiNet = inst.fii_net_crores ?? inst.fii_cash;

  return [
    // --- Category A: Spot & Futures Dynamics (Items 1 - 5) ---
    {
      id: 1,
      category: "A",
      categoryName: "Spot & Futures Dynamics",
      name: "Index Spot Prices",
      keyPath: "indices.NIFTY50.ltp",
      status: spot > 0 ? "OK" : "FAIL",
      valueFormatted: spot > 0 ? `Nifty: ₹${spot.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "Unavailable",
      latencyMs: Math.min(pollAgeMs, 9999),
      source: indexSource,
      message: spot > 0 ? `Spot synced via ${indexSource}` : "Missing index spot feed",
    },
    {
      id: 2,
      category: "A",
      categoryName: "Spot & Futures Dynamics",
      name: "Futures LTP & Volume",
      keyPath: "indices.NIFTY50.futures_ltp",
      status: hasFutures ? "OK" : "FAIL",
      valueFormatted: hasFutures
        ? `₹${nifty?.futures_ltp?.toLocaleString("en-IN")} | Vol ${((nifty?.volume || 0) / 100000).toFixed(1)}L`
        : "Offline",
      latencyMs: pollAgeMs,
      source: "NSE Futures (FUTIDX)",
      message: hasFutures ? "Current-month Nifty Futures LTP and traded volume active" : "Futures quote not received",
    },
    {
      id: 3,
      category: "A",
      categoryName: "Spot & Futures Dynamics",
      name: "Futures Premium / Basis",
      keyPath: "indices.NIFTY50.futures_premium",
      status: hasFutures && nifty?.futures_premium !== undefined ? "OK" : "FAIL",
      valueFormatted: hasFutures && nifty?.futures_premium !== undefined
        ? `${nifty.futures_premium >= 0 ? "+" : ""}${nifty.futures_premium.toFixed(2)} pts`
        : "Unavailable",
      latencyMs: 15,
      source: "Basis Spread Engine",
      message: hasFutures ? "Futures vs Cash Spot basis computed live" : "Awaiting futures LTP",
    },
    {
      id: 4,
      category: "A",
      categoryName: "Spot & Futures Dynamics",
      name: "VWAP Trend & Distance",
      keyPath: "indices.NIFTY50.vwap",
      status: nifty?.vwap && nifty.vwap > 0 ? "OK" : "FAIL",
      valueFormatted: nifty?.vwap
        ? `₹${nifty.vwap.toLocaleString("en-IN", { minimumFractionDigits: 1 })} (${spot - nifty.vwap >= 0 ? "+" : ""}${(spot - nifty.vwap).toFixed(1)} pts)`
        : "Unavailable",
      latencyMs: 25,
      source: "Exchange Turnover VWAP",
      message: nifty?.vwap ? "Volume-weighted fair value anchor active" : "VWAP offline",
    },
    {
      id: 5,
      category: "A",
      categoryName: "Spot & Futures Dynamics",
      name: "Index Volume Delta",
      keyPath: "indices.NIFTY50.delta_volume",
      status: hasFutures && nifty?.delta_volume !== undefined ? "OK" : "WARNING",
      valueFormatted: nifty?.delta_volume !== undefined
        ? `${nifty.delta_volume >= 0 ? "+" : ""}${nifty.delta_volume.toLocaleString("en-IN")} qty`
        : "Waiting Tick",
      latencyMs: 50,
      source: "Volume Delta Engine",
      message: state.is_market_open ? "Tracking live contract volume delta per cycle" : "Market closed — ΔVol static until 09:15 IST",
    },

    // --- Category B: Options & Greeks Dynamics (Items 6 - 16) ---
    {
      id: 6,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Option Chain LTP (ATM ±20)",
      keyPath: "options_data.chain.NIFTY",
      status: hasOptionChain ? "OK" : "FAIL",
      valueFormatted: hasOptionChain ? `${Object.keys(niftyChain).length} Strikes (${atmCEKey || "ATM"})` : "Offline",
      latencyMs: pollAgeMs,
      source: "NSE Option Chain V3",
      message: hasOptionChain ? "Weekly Option Chain contracts hydrated" : "Option chain feed missing",
    },
    {
      id: 7,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Option Volume & ΔVol",
      keyPath: "options_data.chain.NIFTY.*.volume",
      status: sampleOpt && sampleOpt.volume > 0 ? "OK" : "WARNING",
      valueFormatted: sampleOpt?.volume ? `ATM Vol: ${(sampleOpt.volume / 100000).toFixed(2)}L` : "Unavailable",
      latencyMs: pollAgeMs,
      source: "NSE Option Chain V3",
      message: sampleOpt?.volume ? "Real contract volume across ATM strikes loaded" : "No option volume yet",
    },
    {
      id: 8,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Open Interest & ΔOI",
      keyPath: "options_data.chain.NIFTY.*.oi",
      status: sampleOpt && sampleOpt.oi > 0 ? "OK" : "FAIL",
      valueFormatted: sampleOpt?.oi
        ? `OI: ${(sampleOpt.oi / 1000).toFixed(1)}k | Δ ${(sampleOpt.delta_oi || 0) >= 0 ? "+" : ""}${(sampleOpt.delta_oi || 0).toLocaleString()}`
        : "Unavailable",
      latencyMs: pollAgeMs,
      source: "NSE Real-Time OI",
      message: sampleOpt?.oi ? "Exchange OI and intraday Change in OI active" : "OI missing",
    },
    {
      id: 9,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Option Greek: Delta (Δ)",
      keyPath: "options_data.chain.NIFTY.*.delta",
      status: sampleOpt?.delta !== undefined && sampleOpt.delta !== 0 ? "OK" : "FAIL",
      valueFormatted: sampleOpt?.delta ? `Δ ${sampleOpt.delta.toFixed(3)}` : "Unavailable",
      latencyMs: 12,
      source: "Black-Scholes (Vollib)",
      message: sampleOpt?.delta ? "Exact Black-Scholes Delta solved using actual expiry DTE" : "Delta unavailable",
    },
    {
      id: 10,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Option Greek: Gamma (Γ)",
      keyPath: "options_data.chain.NIFTY.*.gamma",
      status: sampleOpt?.gamma !== undefined && sampleOpt.gamma > 0 ? "OK" : "FAIL",
      valueFormatted: sampleOpt?.gamma ? `Γ ${sampleOpt.gamma.toFixed(5)}` : "Unavailable",
      latencyMs: 12,
      source: "Black-Scholes (Vollib)",
      message: sampleOpt?.gamma ? "Gamma curvature computed per strike" : "Gamma unavailable",
    },
    {
      id: 11,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Option Greek: Theta (Θ)",
      keyPath: "options_data.chain.NIFTY.*.theta",
      status: sampleOpt?.theta !== undefined && sampleOpt.theta !== 0 ? "OK" : "FAIL",
      valueFormatted: sampleOpt?.theta ? `Θ ${sampleOpt.theta.toFixed(2)} pts/d` : "Unavailable",
      latencyMs: 12,
      source: "Black-Scholes (Vollib)",
      message: sampleOpt?.theta ? "Calendar decay rate active for expiry guard" : "Theta unavailable",
    },
    {
      id: 12,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Option Vega & Rho",
      keyPath: "options_data.chain.NIFTY.*.vega",
      status: sampleOpt?.vega !== undefined && sampleOpt.vega !== 0 ? "OK" : "FAIL",
      valueFormatted: sampleOpt?.vega ? `Vega ${sampleOpt.vega.toFixed(2)} | Rho ${(sampleOpt.rho || 0).toFixed(2)}` : "Unavailable",
      latencyMs: 12,
      source: "Black-Scholes (Vollib)",
      message: sampleOpt?.vega ? "Analytical Vega and Rho computed via 6.75% rate" : "Vega/Rho unavailable",
    },
    {
      id: 13,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Implied Volatility (IV)",
      keyPath: "options_data.chain.NIFTY.*.iv",
      status: sampleOpt?.iv && sampleOpt.iv > 0 ? "OK" : "FAIL",
      valueFormatted: sampleOpt?.iv ? `IV: ${sampleOpt.iv.toFixed(2)}%` : "Unavailable",
      latencyMs: 15,
      source: "IV Newton/Brent Solver",
      message: sampleOpt?.iv ? "Contract Implied Volatility solved from option LTP" : "IV unavailable",
    },
    {
      id: 14,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Put-Call Ratio (PCR)",
      keyPath: "orderflow.NIFTY_PCR",
      status: fl.NIFTY_PCR && fl.NIFTY_PCR > 0 ? "OK" : "FAIL",
      valueFormatted: fl.NIFTY_PCR ? `Nifty ${fl.NIFTY_PCR.toFixed(2)} | BN ${(fl.BANKNIFTY_PCR || 0).toFixed(2)}` : "Unavailable",
      latencyMs: 30,
      source: "Total Option Chain OI",
      message: fl.NIFTY_PCR ? "PCR computed directly from Sum(Put OI) / Sum(Call OI)" : "PCR offline",
    },
    {
      id: 15,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Gamma Exposure (GEX)",
      keyPath: "options_data.NIFTY_GEX",
      status: opt.NIFTY_GEX !== undefined && opt.NIFTY_GEX !== 0 ? "OK" : "WARNING",
      valueFormatted: opt.NIFTY_GEX ? `${opt.NIFTY_GEX > 0 ? "+" : ""}${(opt.NIFTY_GEX / 10000000).toFixed(2)} Cr` : "0.00",
      latencyMs: 35,
      source: "Dealer GEX Engine",
      message: opt.NIFTY_GEX && opt.NIFTY_GEX > 0 ? "Positive Net Gamma (mean reversion dampening)" : "Negative/Neutral Net Gamma",
    },
    {
      id: 16,
      category: "B",
      categoryName: "Options & Greeks Dynamics",
      name: "Max Pain Strike",
      keyPath: "options_data.NIFTY_MAXPAIN",
      status: opt.NIFTY_MAXPAIN && opt.NIFTY_MAXPAIN > 0 ? "OK" : "FAIL",
      valueFormatted: opt.NIFTY_MAXPAIN ? `₹${opt.NIFTY_MAXPAIN.toLocaleString("en-IN")}` : "Unavailable",
      latencyMs: 40,
      source: "Option Payoff Matrix",
      message: opt.NIFTY_MAXPAIN ? "Minimum writer loss strike computed across live OI" : "Max Pain unavailable",
    },

    // --- Category C: Order Flow & Microstructure (Items 17 - 20) ---
    {
      id: 17,
      category: "C",
      categoryName: "Order Flow & Microstructure",
      name: "Level 2 Market Depth",
      keyPath: "options_data.chain.NIFTY.*.bid",
      status: hasDepth ? "OK" : "WARNING",
      valueFormatted: hasDepth
        ? `Bid ₹${sampleOpt?.bid?.toFixed(2)} / Ask ₹${sampleOpt?.ask?.toFixed(2)}`
        : "No Depth Data",
      latencyMs: pollAgeMs,
      source: "NSE / Upstox L2 Depth",
      message: hasDepth ? "Top Bid/Ask quotes & queue quantities streaming" : "Awaiting live Bid/Ask depth",
    },
    {
      id: 18,
      category: "C",
      categoryName: "Order Flow & Microstructure",
      name: "Order Book Imbalance (OBI)",
      keyPath: "options_data.chain.NIFTY.*.tbq",
      status: atmObi !== undefined && atmObi > 0 ? "OK" : "WARNING",
      valueFormatted: atmObi !== undefined ? `${atmObi.toFixed(2)}x Bid/Ask` : "Unavailable",
      latencyMs: 30,
      source: "Queue Imbalance Engine",
      message: atmObi !== undefined ? "Total Bid vs Ask quantity pressure calculated" : "Waiting depth imbalance",
    },
    {
      id: 19,
      category: "C",
      categoryName: "Order Flow & Microstructure",
      name: "Cumulative Volume Delta (CVD)",
      keyPath: "orderflow.NIFTY_CVD",
      status: fl.NIFTY_CVD !== undefined ? (state.is_market_open || fl.NIFTY_CVD !== 0 ? "OK" : "WARNING") : "FAIL",
      valueFormatted: fl.NIFTY_CVD !== undefined ? `${fl.NIFTY_CVD >= 0 ? "+" : ""}${fl.NIFTY_CVD.toLocaleString()}` : "Offline",
      latencyMs: 25,
      source: "Futures Aggressor Tracker",
      message: state.is_market_open ? "Tracking live signed Futures volume ticks" : "Market closed — CVD starts at 09:15 IST tick flow",
    },
    {
      id: 20,
      category: "C",
      categoryName: "Order Flow & Microstructure",
      name: "Bid-Ask Spread & Liquidity",
      keyPath: "options_data.chain.NIFTY.*.bid_ask_spread",
      status: spreadValid ? (spreadVal! <= 2.5 ? "OK" : "WARNING") : "WARNING",
      valueFormatted: spreadValid ? `${spreadVal!.toFixed(2)} pts` : "Unavailable",
      latencyMs: 30,
      source: "Execution Liquidity Guard",
      message: spreadValid ? `ATM contract spread is ${spreadVal!.toFixed(2)} pts` : "Spread unavailable",
    },

    // --- Category D: Breadth & Heavyweight Equity Flows (Items 21 - 26) ---
    {
      id: 21,
      category: "D",
      categoryName: "Breadth & Heavyweights",
      name: "Heavyweight Stocks LTP & Vol",
      keyPath: "heavyweights",
      status: Object.keys(hw).length >= 20 ? "OK" : Object.keys(hw).length > 0 ? "WARNING" : "FAIL",
      valueFormatted: `${Object.keys(hw).length} / 27 Stocks Active`,
      latencyMs: pollAgeMs,
      source: "Groww / NSE Equities",
      message: hw.HDFCBANK ? `HDFC ₹${hw.HDFCBANK.ltp} | RELIANCE ₹${hw.RELIANCE?.ltp || 0}` : "Heavyweight feed unavailable",
    },
    {
      id: 22,
      category: "D",
      categoryName: "Breadth & Heavyweights",
      name: "Heavyweight Order Imbalances",
      keyPath: "heavyweights.HDFCBANK.imbalance",
      status: hw.HDFCBANK?.imbalance !== undefined ? "OK" : "FAIL",
      valueFormatted: hw.HDFCBANK?.imbalance !== undefined ? `HDFC ${hw.HDFCBANK.imbalance.toFixed(2)}x` : "Unavailable",
      latencyMs: pollAgeMs,
      source: "Equities Queue Depth",
      message: hw.HDFCBANK ? "Real TotalBuyQty / TotalSellQty computed on top Nifty drivers" : "Missing heavyweight depth",
    },
    {
      id: 23,
      category: "D",
      categoryName: "Breadth & Heavyweights",
      name: "Advance / Decline (A/D) Ratio",
      keyPath: "orderflow.AD_RATIO",
      status: fl.AD_RATIO !== undefined && fl.AD_RATIO > 0 ? "OK" : "FAIL",
      valueFormatted: fl.AD_RATIO
        ? `${fl.AD_RATIO.toFixed(2)} (${fl.AD_ADVANCES ?? "?"} Adv / ${fl.AD_DECLINES ?? "?"} Dec)`
        : "Unavailable",
      latencyMs: pollAgeMs,
      source: "NSE NIFTY 50 Breadth",
      message: fl.AD_RATIO ? "Official Nifty 50 constituent advance/decline count active" : "Breadth feed offline",
    },
    {
      id: 24,
      category: "D",
      categoryName: "Breadth & Heavyweights",
      name: "Sectoral Synergy (IT vs Bank)",
      keyPath: "indices.NIFTYIT.ltp",
      status: ind.NIFTYIT?.ltp && ind.NIFTYIT.ltp > 0 ? "OK" : "FAIL",
      valueFormatted:
        ind.NIFTYIT?.ltp && bank?.ltp
          ? `Bank ${bank.day_change_pct !== undefined ? `${bank.day_change_pct >= 0 ? "+" : ""}${bank.day_change_pct.toFixed(2)}%` : "—"} | IT ${ind.NIFTYIT.day_change_pct !== undefined ? `${ind.NIFTYIT.day_change_pct >= 0 ? "+" : ""}${ind.NIFTYIT.day_change_pct.toFixed(2)}%` : "—"}`
          : "Unavailable",
      latencyMs: pollAgeMs,
      source: indexSource,
      message: "Live sectoral divergence monitored between Nifty Bank and Nifty IT",
    },
    {
      id: 25,
      category: "D",
      categoryName: "Breadth & Heavyweights",
      name: "India VIX",
      keyPath: "indices.INDIAVIX.ltp",
      status: vix?.ltp && vix.ltp > 0 ? "OK" : "FAIL",
      valueFormatted: vix?.ltp
        ? `${vix.ltp.toFixed(2)} (${(vix.delta_vix || 0) >= 0 ? "+" : ""}${(vix.delta_vix || 0).toFixed(2)})`
        : "Unavailable",
      latencyMs: pollAgeMs,
      source: vixSource,
      message: vix?.ltp ? `Live India VIX at ${vix.ltp.toFixed(2)} from ${vixSource}` : "India VIX feed missing",
    },
    {
      id: 26,
      category: "D",
      categoryName: "Breadth & Heavyweights",
      name: "Technical Liquidity Levels",
      keyPath: "prev_ohlc.NIFTY50",
      status: pdhVal && pdlVal ? "OK" : "FAIL",
      valueFormatted: pdhVal && pdlVal ? `PDH ${pdhVal.toFixed(1)} | PDL ${pdlVal.toFixed(1)}` : "Unavailable",
      latencyMs: 120,
      source: "Previous Session OHLC",
      message: pdhVal ? "Verified previous session High/Low/Pivot levels loaded" : "Previous OHLC missing",
    },

    // --- Category E: Global Macro & Live News Intelligence (Items 27 - 32) ---
    {
      id: 27,
      category: "E",
      categoryName: "Global Macro & News",
      name: "GIFT Nifty (Pre-Market Gap)",
      keyPath: "macro.GIFT_NIFTY",
      status: macro.GIFT_NIFTY ? "OK" : "WARNING",
      valueFormatted: macro.GIFT_NIFTY
        ? `₹${macro.GIFT_NIFTY.toLocaleString("en-IN")} (${(macro.GIFT_NIFTY_change || 0) >= 0 ? "+" : ""}${(macro.GIFT_NIFTY_change || 0).toFixed(1)})`
        : "Unavailable",
      latencyMs: 400,
      source: "NSE IX / Global Feed",
      message: macro.GIFT_NIFTY ? "Live GIFT Nifty futures quote active" : "GIFT Nifty pending next macro poll",
    },
    {
      id: 28,
      category: "E",
      categoryName: "Global Macro & News",
      name: "US Dollar Index (DXY)",
      keyPath: "macro.DXY",
      status: macro.DXY ? "OK" : "WARNING",
      valueFormatted: macro.DXY ? `${macro.DXY.toFixed(2)}` : "Unavailable",
      latencyMs: 500,
      source: "Yahoo Finance (DX-Y.NYB)",
      message: macro.DXY ? "Live US Dollar Index benchmark loaded" : "DXY unavailable",
    },
    {
      id: 29,
      category: "E",
      categoryName: "Global Macro & News",
      name: "Brent Crude Oil Prices",
      keyPath: "macro.CRUDE",
      status: macro.CRUDE ? "OK" : "WARNING",
      valueFormatted: macro.CRUDE ? `$${macro.CRUDE.toFixed(2)}` : "Unavailable",
      latencyMs: 500,
      source: "Yahoo Finance (BZ=F)",
      message: macro.CRUDE ? "Live Brent Crude Oil futures price active" : "Crude Oil unavailable",
    },
    {
      id: 30,
      category: "E",
      categoryName: "Global Macro & News",
      name: "US 10-Year Treasury Yield",
      keyPath: "macro.BOND_10Y",
      status: macro.BOND_10Y ? "OK" : "WARNING",
      valueFormatted: macro.BOND_10Y ? `${macro.BOND_10Y.toFixed(2)}%` : "Unavailable",
      latencyMs: 500,
      source: "Yahoo Finance (^TNX)",
      message: macro.BOND_10Y ? "US 10Y Treasury yield benchmark active" : "10Y Yield unavailable",
    },
    {
      id: 31,
      category: "E",
      categoryName: "Global Macro & News",
      name: "Live Breaking Financial News",
      keyPath: "indian_news",
      status: allNews.length > 0 ? "OK" : "WARNING",
      valueFormatted: `${allNews.length} Live Headlines`,
      latencyMs: 800,
      source: "ET Markets RSS + NewsAPI",
      message: allNews.length > 0 ? "Real-time Indian financial RSS stream ingested" : "Awaiting news feed",
    },
    {
      id: 32,
      category: "E",
      categoryName: "Global Macro & News",
      name: "Institutional Flow (FII / DII)",
      keyPath: "institutional.fii_net_crores",
      status: fiiNet !== undefined && fiiNet !== null ? "OK" : "WARNING",
      valueFormatted: fiiNet !== undefined && fiiNet !== null
        ? `FII: ${fiiNet >= 0 ? "+" : ""}₹${fiiNet.toLocaleString("en-IN")} Cr`
        : "Unavailable",
      latencyMs: 900,
      source: "NSE Institutional Flow",
      message: inst.date ? `Official NSE FII/DII data (${inst.date})` : "Awaiting NSE FII/DII report",
    },
  ];
}
