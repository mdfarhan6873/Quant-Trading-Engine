"use client";

import React, { useState } from "react";
import {
  Layers, ChevronDown, ChevronRight, Search,
  Newspaper, Zap, Database
} from "lucide-react";
import { MarketStateData, LLMDecisionContract } from "@/types/market";
import { findNearestATMOptions } from "@/utils/healthEvaluator";

interface LeftCategorizedDataProps {
  marketState?: MarketStateData | null;
  lastDecision?: LLMDecisionContract | null;
}

export function LeftCategorizedData({ marketState }: LeftCategorizedDataProps) {
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({
    A: false,
    B: false,
    C: false,
    D: false,
    E: false,
  });

  const toggleCategory = (cat: string) => {
    setCollapsed((prev) => ({ ...prev, [cat]: !prev[cat] }));
  };

  const ms = marketState;
  const ind = ms?.indices;
  const nifty = ind?.NIFTY50;
  const bank = ind?.BANKNIFTY;
  const it = ind?.NIFTYIT;
  const vix = ind?.INDIAVIX;
  const fl = ms?.orderflow;
  const opt = ms?.options_data;
  const hw = ms?.heavyweights || {};
  const macro = ms?.macro || {};
  const inst = ms?.institutional;
  const prevOHLC = ms?.prev_ohlc;
  const breakingNews = ms?.breaking_news || [];
  const indianNews = ms?.indian_news || [];
  const combinedNews = breakingNews.length > 0 ? breakingNews : indianNews;

  const multiDay = ms?.multi_day_memory;
  const anchors = multiDay?.anchors;
  const engineExp = multiDay?.engine_experience;

  const niftySpot = nifty?.ltp || 0;
  const niftyVwap = nifty?.vwap || 0;
  const vwapSpread = niftySpot > 0 && niftyVwap > 0 ? niftySpot - niftyVwap : null;

  // Find true closest ATM Call & Put strikes
  const niftyChain = opt?.chain?.NIFTY || {};
  const { ceKey: atmCEKey, peKey: atmPEKey, ce: optCE, pe: optPE } = findNearestATMOptions(niftyChain, niftySpot);

  // Order book imbalance & spread directly from ATM options
  const tbqTotal = (optCE?.tbq || 0) + (optPE?.tbq || 0);
  const tsqTotal = (optCE?.tsq || 0) + (optPE?.tsq || 0);
  const atmObi = tsqTotal > 0 ? tbqTotal / tsqTotal : null;
  const atmSpread = optCE?.bid_ask_spread ?? optPE?.bid_ask_spread ?? null;

  const fiiCash = inst?.fii_net_crores ?? inst?.fii_cash ?? null;
  const pdh = prevOHLC?.NIFTY50?.pdh ?? prevOHLC?.NIFTY50?.high ?? null;
  const pdl = prevOHLC?.NIFTY50?.pdl ?? prevOHLC?.NIFTY50?.low ?? null;

  const fmt = (n?: number | null, dec = 2) =>
    n !== undefined && n !== null && !isNaN(n)
      ? n.toLocaleString("en-IN", { minimumFractionDigits: dec, maximumFractionDigits: dec })
      : "—";

  const matchesSearch = (text: string) => {
    if (!search.trim()) return true;
    return text.toLowerCase().includes(search.toLowerCase());
  };

  // Dynamic Analytical Synthesis Messages (computed strictly from real values)
  const catASynthesis = (() => {
    if (!niftySpot) return "Awaiting live Nifty 50 & Futures quote ingestion...";
    const vwapDir = vwapSpread !== null ? (vwapSpread >= 0 ? `above VWAP (+${vwapSpread.toFixed(1)} pts)` : `below VWAP (${vwapSpread.toFixed(1)} pts)`) : "tracking VWAP";
    const basisTxt = nifty?.futures_premium !== undefined ? `Futures basis at ${nifty.futures_premium >= 0 ? "+" : ""}${nifty.futures_premium.toFixed(1)} pts` : "basis pending";
    return `NIFTY spot at ₹${fmt(niftySpot, 2)} trading ${vwapDir}; ${basisTxt}.`;
  })();

  const catBSynthesis = (() => {
    if (!optCE && !optPE) return "Awaiting Option Chain & Black-Scholes Greeks sync...";
    const ceDoi = optCE?.delta_oi || 0;
    const peDoi = optPE?.delta_oi || 0;
    const ceAction = ceDoi < 0 ? "Call short-covering" : ceDoi > 0 ? "Call writing" : "flat Call OI";
    const peAction = peDoi > 0 ? "Put writing" : peDoi < 0 ? "Put unwinding" : "flat Put OI";
    const ivTxt = optCE?.iv ? `ATM IV ${optCE.iv.toFixed(1)}%` : "IV syncing";
    return `${atmCEKey || "ATM"} shows ${ceAction} (${ceDoi >= 0 ? "+" : ""}${ceDoi.toLocaleString()}) with ${peAction} (${peDoi >= 0 ? "+" : ""}${peDoi.toLocaleString()}). ${ivTxt}, PCR ${(fl?.NIFTY_PCR || 0).toFixed(2)}.`;
  })();

  const catCSynthesis = (() => {
    const cvdVal = fl?.NIFTY_CVD ?? 0;
    const obiStr = atmObi !== null ? `${atmObi.toFixed(2)}x Bid/Ask ratio` : "depth syncing";
    const spreadStr = atmSpread !== null ? `ATM spread ${atmSpread.toFixed(2)} pts` : "spread pending";
    return `CVD at ${cvdVal >= 0 ? "+" : ""}${cvdVal.toLocaleString()} contracts | ${obiStr} | ${spreadStr}.`;
  })();

  const catDSynthesis = (() => {
    const adTxt = fl?.AD_RATIO ? `Breadth A/D ${fl.AD_RATIO.toFixed(2)} (${fl.AD_ADVANCES ?? "?"}/${fl.AD_DECLINES ?? "?"})` : "Breadth syncing";
    const vixTxt = vix?.ltp ? `India VIX ${vix.ltp.toFixed(2)}` : "VIX syncing";
    const bPct = bank?.day_change_pct;
    const itPct = it?.day_change_pct;
    const divTxt =
      bPct !== undefined && itPct !== undefined
        ? Math.sign(bPct) !== Math.sign(itPct) && Math.abs(bPct - itPct) > 0.5
          ? "Sectoral divergence (Bank vs IT) detected"
          : "Sectors aligned"
        : "Sector tracking active";
    return `${adTxt} | ${vixTxt} | ${divTxt}.`;
  })();

  const catESynthesis = (() => {
    const gift = macro?.GIFT_NIFTY ? `GIFT Nifty ₹${fmt(macro.GIFT_NIFTY, 1)}` : "GIFT Nifty pending";
    const fiiStr = fiiCash !== null ? `FII cash ${fiiCash >= 0 ? "+" : ""}₹${fmt(fiiCash, 1)} Cr` : "FII cash pending";
    const crStr = macro?.CRUDE ? `Brent $${macro.CRUDE.toFixed(2)}` : "Brent pending";
    return `${gift} | ${fiiStr} | ${crStr} | DXY ${macro?.DXY ? macro.DXY.toFixed(2) : "—"}.`;
  })();

  return (
    <aside className="w-full flex flex-col bg-[#0D121D] border-r border-[#1E2638] h-full overflow-hidden select-none font-mono">
      {/* Top Header of Left Sidebar */}
      <div className="p-2.5 border-b border-[#1E2638] bg-[#0A0E17] flex flex-col gap-2 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-slate-200 text-xs font-bold tracking-wider">
            <Layers size={13} className="text-cyan-400" />
            <span>32 MARKET DIMENSIONS</span>
          </div>
          <span className="text-[10px] text-cyan-400/80 bg-cyan-950/40 border border-cyan-800/40 px-1.5 py-0.5 rounded">
            5 CATEGORIES
          </span>
        </div>

        <div className="relative">
          <Search size={11} className="absolute left-2.5 top-2 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search metric, strike, heavyweight..."
            className="w-full bg-[#131926] border border-[#1F2A3F] rounded text-[11px] text-slate-200 pl-7 pr-2 py-1 placeholder:text-slate-500 outline-none focus:border-cyan-500 transition-colors"
          />
        </div>
      </div>

      {/* Scrollable Categories List */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-2 text-xs divide-y divide-[#1A2234]">

        {/* ══════════ MULTI-DAY AUCTION CONTINUITY ══════════ */}
        <div className="bg-[#0A0F1A] border border-cyan-900/40 rounded p-2.5 space-y-2 mb-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold text-cyan-300 tracking-wider flex items-center gap-1.5">
              <Database size={12} className="text-cyan-400" />
              MULTI-DAY AUCTION CONTINUITY
            </span>
            <span className="text-[9px] px-1 py-0.2 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-800/40 font-bold">
              3-DAY ROLLING
            </span>
          </div>

          <div className="grid grid-cols-2 gap-1.5 text-[10px]">
            <div className="bg-[#101624] p-1.5 rounded border border-[#1C2538]">
              <span className="text-[8px] text-slate-400 block">3-DAY HIGH (RESISTANCE)</span>
              <span className="font-bold text-rose-400 text-[11px]">
                {anchors?.nifty_3d_high ? `₹${fmt(anchors.nifty_3d_high, 1)}` : "—"}
              </span>
            </div>

            <div className="bg-[#101624] p-1.5 rounded border border-[#1C2538]">
              <span className="text-[8px] text-slate-400 block">3-DAY LOW (SUPPORT)</span>
              <span className="font-bold text-emerald-400 text-[11px]">
                {anchors?.nifty_3d_low ? `₹${fmt(anchors.nifty_3d_low, 1)}` : "—"}
              </span>
            </div>

            <div className="bg-[#101624] p-1.5 rounded border border-[#1C2538]">
              <span className="text-[8px] text-slate-400 block">5D SESSION BENCHMARK</span>
              <span className="font-bold text-amber-300 text-[11px]">
                {anchors?.nifty_weekly_vwap ? `₹${fmt(anchors.nifty_weekly_vwap, 1)}` : "—"}
              </span>
            </div>

            <div className="bg-[#101624] p-1.5 rounded border border-[#1C2538]">
              <span className="text-[8px] text-slate-400 block">FII NET CASH FLOW</span>
              <span className={`font-bold text-[11px] ${(anchors?.fii_3d_net_crores ?? fiiCash ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {(anchors?.fii_3d_net_crores ?? fiiCash) !== null && (anchors?.fii_3d_net_crores ?? fiiCash) !== undefined
                  ? `${(anchors?.fii_3d_net_crores ?? fiiCash)! >= 0 ? "+" : ""}₹${fmt(anchors?.fii_3d_net_crores ?? fiiCash, 1)} Cr`
                  : "—"}
              </span>
            </div>
          </div>

          <div className="p-1 rounded bg-[#101624] border border-cyan-800/30 text-[9px] text-cyan-200">
            <span className="text-slate-400 font-semibold">BIAS: </span>
            <span className="font-bold">{multiDay?.structural_bias || "SYNCING_AUCTION_CONTEXT"}</span>
          </div>

          {ms?.quant_rag_context && (
            <div className="p-2 rounded bg-[#0E1524] border border-indigo-800/40 space-y-1">
              <div className="flex items-center justify-between text-[9px]">
                <span className="font-bold text-indigo-300 flex items-center gap-1">
                  <Zap size={10} className="text-indigo-400" />
                  QUANT RAG ARCHETYPE
                </span>
                <span className="text-indigo-300 font-bold bg-indigo-950/80 px-1.5 py-0.2 rounded border border-indigo-800/50">
                  {ms.quant_rag_context.similarity_score}% MATCH
                </span>
              </div>
              <div className="text-[10px] text-slate-100 font-bold truncate">
                {ms.quant_rag_context.matched_archetype}
              </div>
              <div className="text-[9px] text-amber-300/90 leading-tight">
                <span className="text-slate-400">DIRECTIVE: </span>
                {ms.quant_rag_context.quant_directive}
              </div>
            </div>
          )}

          {engineExp && (
            <div className="p-1.5 rounded bg-emerald-950/20 border border-emerald-800/30 text-[9px] text-emerald-300 leading-tight">
              <span className="font-bold text-emerald-400">EPISODIC LESSON: </span>
              {engineExp.key_lesson || "Maintaining Patience Protocol."}
            </div>
          )}
        </div>

        {/* ══════════ CATEGORY A: SPOT & FUTURES DYNAMICS ══════════ */}
        {(matchesSearch("spot") || matchesSearch("futures") || matchesSearch("vwap") || matchesSearch("basis")) && (
          <div className="pt-2">
            <button
              onClick={() => toggleCategory("A")}
              className="w-full flex items-center justify-between text-left py-1 text-slate-300 hover:text-cyan-400 group"
            >
              <div className="flex items-center gap-1.5 font-bold text-[11px] tracking-wider text-cyan-400">
                {collapsed.A ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                <span>CAT A: SPOT & FUTURES DYNAMICS</span>
              </div>
              <span className="text-[9px] px-1 py-0.2 rounded bg-[#161F30] text-slate-400">1–5</span>
            </button>

            {!collapsed.A && (
              <div className="mt-1.5 space-y-1.5 pl-3 border-l-2 border-cyan-500/30">
                {/* 1. Spot Prices */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold">1. INDEX SPOT PRICES</span>
                    <span className={`font-bold ${niftySpot > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {niftySpot > 0 ? (nifty?.source || "LIVE").toUpperCase() : "OFFLINE"}
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between mt-1">
                    <span className="text-slate-200 font-bold text-[12px]">
                      NIFTY: {niftySpot > 0 ? `₹${fmt(niftySpot, 2)}` : "—"}
                    </span>
                    <span className="text-slate-300 text-[11px]">
                      BANK: {bank?.ltp ? `₹${fmt(bank.ltp, 2)}` : "—"}
                    </span>
                  </div>
                </div>

                {/* 2 & 3. Futures LTP, Volume & Basis */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold">2 & 3. FUTURES & BASIS</span>
                    <span className="text-cyan-400 font-bold">
                      {nifty?.futures_ltp ? `FUT ₹${fmt(nifty.futures_ltp, 1)}` : "CURR EXPIRY"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-slate-200 font-bold">
                      Basis: {nifty?.futures_premium !== undefined ? `${nifty.futures_premium >= 0 ? "+" : ""}${nifty.futures_premium.toFixed(1)} pts` : "—"}
                    </span>
                    <span className="text-slate-400 text-[10px]">
                      Vol: {nifty?.volume ? `${(nifty.volume / 100000).toFixed(1)}L` : "—"}
                    </span>
                  </div>
                </div>

                {/* 4. VWAP & Distance */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold">4. VWAP BENCHMARK & DISTANCE</span>
                    <span className={vwapSpread === null ? "text-slate-500" : vwapSpread >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {vwapSpread === null ? "—" : vwapSpread >= 0 ? "▲ ABOVE VWAP" : "▼ BELOW VWAP"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-slate-200 font-bold">
                      VWAP: {niftyVwap > 0 ? `₹${fmt(niftyVwap, 1)}` : "—"}
                    </span>
                    <span className={`font-bold text-[11px] ${vwapSpread !== null && vwapSpread >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {vwapSpread !== null ? `${vwapSpread >= 0 ? "+" : ""}${vwapSpread.toFixed(1)} pts` : "—"}
                    </span>
                  </div>
                </div>

                {/* 5. Volume Delta */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold">5. VOLUME DELTA</span>
                    <span className="text-amber-400 font-bold">
                      {ms?.is_market_open ? "TICK DELTA" : "STATIC CLOSED"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-slate-200 font-bold">
                      Δ Vol: {nifty?.delta_volume !== undefined ? `${nifty.delta_volume >= 0 ? "+" : ""}${nifty.delta_volume.toLocaleString()}` : "—"}
                    </span>
                    <span className="text-cyan-400 font-bold text-[10px]">
                      1m ΔP: {nifty?.delta_price_1m !== undefined ? `${nifty.delta_price_1m >= 0 ? "+" : ""}${nifty.delta_price_1m.toFixed(1)}` : "—"}
                    </span>
                  </div>
                </div>

                <div className="p-1.5 rounded bg-cyan-950/20 border border-cyan-800/30 text-[10px] text-cyan-300/90 leading-tight">
                  <span className="font-bold text-cyan-400">CAT A SYNTHESIS:</span> {catASynthesis}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══════════ CATEGORY B: OPTIONS & GREEKS DYNAMICS ══════════ */}
        {(matchesSearch("option") || matchesSearch("greek") || matchesSearch("delta") || matchesSearch("pcr") || matchesSearch("gex")) && (
          <div className="pt-2">
            <button
              onClick={() => toggleCategory("B")}
              className="w-full flex items-center justify-between text-left py-1 text-slate-300 hover:text-purple-400 group"
            >
              <div className="flex items-center gap-1.5 font-bold text-[11px] tracking-wider text-purple-400">
                {collapsed.B ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                <span>CAT B: OPTIONS & GREEKS (ATM ±20)</span>
              </div>
              <span className="text-[9px] px-1 py-0.2 rounded bg-[#161F30] text-slate-400">6–16</span>
            </button>

            {!collapsed.B && (
              <div className="mt-1.5 space-y-1.5 pl-3 border-l-2 border-purple-500/30">
                {/* 6, 7 & 8: Closest ATM Call & Put */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold">6–8. ATM CE / PE & ΔOI</span>
                    <span className="text-purple-400 font-bold">{Object.keys(niftyChain).length} CONTRACTS</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mt-1.5">
                    <div className="bg-[#090D14] p-1.5 rounded border border-emerald-900/30">
                      <span className="text-[9px] text-emerald-400 font-bold block">{atmCEKey || "ATM CALL"}</span>
                      <span className="text-[11px] font-bold text-slate-100">
                        {optCE?.ltp !== undefined ? `₹${optCE.ltp.toFixed(2)}` : "—"}
                      </span>
                      <div className="text-[9px] text-slate-400 mt-0.5">
                        ΔOI:{" "}
                        <span className={(optCE?.delta_oi || 0) < 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                          {optCE?.delta_oi !== undefined
                            ? `${optCE.delta_oi >= 0 ? "+" : ""}${(optCE.delta_oi / 1000).toFixed(1)}k (${optCE.delta_oi < 0 ? "Cover" : optCE.delta_oi > 0 ? "Write" : "Flat"})`
                            : "—"}
                        </span>
                      </div>
                    </div>

                    <div className="bg-[#090D14] p-1.5 rounded border border-rose-900/30">
                      <span className="text-[9px] text-rose-400 font-bold block">{atmPEKey || "ATM PUT"}</span>
                      <span className="text-[11px] font-bold text-slate-100">
                        {optPE?.ltp !== undefined ? `₹${optPE.ltp.toFixed(2)}` : "—"}
                      </span>
                      <div className="text-[9px] text-slate-400 mt-0.5">
                        ΔOI:{" "}
                        <span className={(optPE?.delta_oi || 0) > 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                          {optPE?.delta_oi !== undefined
                            ? `${optPE.delta_oi >= 0 ? "+" : ""}${(optPE.delta_oi / 1000).toFixed(1)}k (${optPE.delta_oi > 0 ? "Write" : optPE.delta_oi < 0 ? "Unwind" : "Flat"})`
                            : "—"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 9–13: Greeks Matrix */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                    <span className="font-semibold">9–13. BLACK-SCHOLES GREEKS</span>
                    <span className="text-cyan-400 text-[9px]">{optCE?.delta ? "VOLLIB SOLVED" : "PENDING"}</span>
                  </div>
                  <div className="grid grid-cols-4 gap-1 text-center">
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">DELTA (Δ)</span>
                      <span className="text-[10px] font-bold text-cyan-400">{optCE?.delta ? optCE.delta.toFixed(2) : "—"}</span>
                    </div>
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">GAMMA (Γ)</span>
                      <span className="text-[10px] font-bold text-purple-400">{optCE?.gamma ? optCE.gamma.toFixed(4) : "—"}</span>
                    </div>
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">THETA (Θ)</span>
                      <span className="text-[10px] font-bold text-rose-400">{optCE?.theta ? optCE.theta.toFixed(1) : "—"}</span>
                    </div>
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">IV (%)</span>
                      <span className="text-[10px] font-bold text-amber-400">{optCE?.iv ? `${optCE.iv.toFixed(1)}%` : "—"}</span>
                    </div>
                  </div>
                </div>

                {/* 14–16: PCR, GEX & Max Pain */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                    <span className="font-semibold">14–16. PCR, GEX & MAX PAIN</span>
                    <span className={`text-[9px] font-bold ${(fl?.NIFTY_PCR || 0) >= 1.0 ? "text-emerald-400" : "text-amber-400"}`}>
                      {(fl?.NIFTY_PCR || 0) >= 1.2 ? "BULLISH OI" : (fl?.NIFTY_PCR || 0) > 0 && (fl?.NIFTY_PCR || 0) < 0.8 ? "BEARISH OI" : "BALANCED OI"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-[9px] text-slate-400 block">TOTAL PCR</span>
                      <span className="text-[12px] font-bold text-slate-100">{fl?.NIFTY_PCR ? fl.NIFTY_PCR.toFixed(2) : "—"}</span>
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-400 block">NET GEX</span>
                      <span className={`text-[12px] font-bold ${(opt?.NIFTY_GEX || 0) >= 0 ? "text-cyan-400" : "text-rose-400"}`}>
                        {opt?.NIFTY_GEX !== undefined && opt.NIFTY_GEX !== 0
                          ? `${opt.NIFTY_GEX > 0 ? "+" : ""}${(opt.NIFTY_GEX / 10000000).toFixed(2)} Cr`
                          : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-400 block">MAX PAIN</span>
                      <span className="text-[12px] font-bold text-amber-300">
                        {opt?.NIFTY_MAXPAIN ? `₹${fmt(opt.NIFTY_MAXPAIN, 0)}` : "—"}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="p-1.5 rounded bg-purple-950/20 border border-purple-800/30 text-[10px] text-purple-300/90 leading-tight">
                  <span className="font-bold text-purple-400">CAT B SYNTHESIS:</span> {catBSynthesis}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══════════ CATEGORY C: ORDER FLOW & MICROSTRUCTURE ══════════ */}
        {(matchesSearch("orderflow") || matchesSearch("cvd") || matchesSearch("depth") || matchesSearch("imbalance")) && (
          <div className="pt-2">
            <button
              onClick={() => toggleCategory("C")}
              className="w-full flex items-center justify-between text-left py-1 text-slate-300 hover:text-emerald-400 group"
            >
              <div className="flex items-center gap-1.5 font-bold text-[11px] tracking-wider text-emerald-400">
                {collapsed.C ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                <span>CAT C: ORDER FLOW & MICROSTRUCTURE</span>
              </div>
              <span className="text-[9px] px-1 py-0.2 rounded bg-[#161F30] text-slate-400">17–20</span>
            </button>

            {!collapsed.C && (
              <div className="mt-1.5 space-y-1.5 pl-3 border-l-2 border-emerald-500/30">
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold">19. CUMULATIVE VOLUME DELTA (CVD)</span>
                    <span className={(fl?.NIFTY_CVD || 0) >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                      {fl?.NIFTY_CVD ? (fl.NIFTY_CVD > 0 ? "BUY FLOW" : "SELL FLOW") : "NEUTRAL"}
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between mt-1">
                    <span className={`font-bold text-[14px] ${(fl?.NIFTY_CVD || 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {fl?.NIFTY_CVD !== undefined ? `${fl.NIFTY_CVD >= 0 ? "+" : ""}${fl.NIFTY_CVD.toLocaleString()}` : "—"}
                    </span>
                    <span className="text-slate-400 text-[10px]">
                      BN CVD: {fl?.BANKNIFTY_CVD !== undefined ? `${fl.BANKNIFTY_CVD >= 0 ? "+" : ""}${fl.BANKNIFTY_CVD.toLocaleString()}` : "—"}
                    </span>
                  </div>
                </div>

                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-[9px] text-slate-400 block">18. OPTION OBI RATIO</span>
                      <span className={`font-bold text-[11px] ${(atmObi || 1) >= 1 ? "text-emerald-400" : "text-rose-400"}`}>
                        {atmObi !== null ? `${atmObi.toFixed(2)}x Bid/Ask` : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-400 block">20. ATM BID-ASK SPREAD</span>
                      <span className="text-cyan-400 font-bold text-[11px]">
                        {atmSpread !== null ? `${atmSpread.toFixed(2)} pts` : "—"}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="p-1.5 rounded bg-emerald-950/20 border border-emerald-800/30 text-[10px] text-emerald-300/90 leading-tight">
                  <span className="font-bold text-emerald-400">CAT C SYNTHESIS:</span> {catCSynthesis}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══════════ CATEGORY D: BREADTH & HEAVYWEIGHT FLOWS ══════════ */}
        {(matchesSearch("breadth") || matchesSearch("heavyweight") || matchesSearch("hdfc") || matchesSearch("reliance") || matchesSearch("vix")) && (
          <div className="pt-2">
            <button
              onClick={() => toggleCategory("D")}
              className="w-full flex items-center justify-between text-left py-1 text-slate-300 hover:text-amber-400 group"
            >
              <div className="flex items-center gap-1.5 font-bold text-[11px] tracking-wider text-amber-400">
                {collapsed.D ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                <span>CAT D: BREADTH & HEAVYWEIGHTS</span>
              </div>
              <span className="text-[9px] px-1 py-0.2 rounded bg-[#161F30] text-slate-400">21–26</span>
            </button>

            {!collapsed.D && (
              <div className="mt-1.5 space-y-1.5 pl-3 border-l-2 border-amber-500/30">
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538] space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold">21 & 22. TOP INDEX DRIVERS</span>
                    <span className="text-slate-400 text-[9px]">LTP • OBI</span>
                  </div>
                  {["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY"].map((sym) => {
                    const item = hw[sym];
                    return (
                      <div key={sym} className="flex items-center justify-between text-[10px] py-0.5 border-b border-[#1A2234] last:border-0">
                        <span className="font-bold text-slate-200">{sym}</span>
                        <span className="text-slate-300">
                          {item?.ltp ? `₹${fmt(item.ltp, 1)}` : "—"}
                          {item?.day_change_pct !== undefined && (
                            <span className={`ml-1 text-[9px] ${item.day_change_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              ({item.day_change_pct >= 0 ? "+" : ""}{item.day_change_pct.toFixed(1)}%)
                            </span>
                          )}
                        </span>
                        <span className={`font-bold ${item && item.imbalance >= 1.2 ? "text-emerald-400" : "text-slate-400"}`}>
                          OBI: {item?.imbalance !== undefined ? `${item.imbalance.toFixed(2)}x` : "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>

                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="grid grid-cols-2 gap-2 text-[10px]">
                    <div>
                      <span className="text-[9px] text-slate-400 block">23. A/D RATIO</span>
                      <span className={`font-bold ${(fl?.AD_RATIO || 0) >= 1 ? "text-emerald-400" : "text-rose-400"}`}>
                        {fl?.AD_RATIO ? `${fl.AD_RATIO.toFixed(2)} (${fl.AD_ADVANCES ?? "?"} / ${fl.AD_DECLINES ?? "?"})` : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-400 block">24. SECTOR SYNERGY</span>
                      <span className="text-cyan-400 font-bold">
                        {bank?.day_change_pct !== undefined && it?.day_change_pct !== undefined
                          ? `BN ${bank.day_change_pct >= 0 ? "+" : ""}${bank.day_change_pct.toFixed(1)}% | IT ${it.day_change_pct >= 0 ? "+" : ""}${it.day_change_pct.toFixed(1)}%`
                          : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-400 block">25. INDIA VIX</span>
                      <span className="text-amber-400 font-bold">
                        {vix?.ltp
                          ? `${vix.ltp.toFixed(2)} (${(vix.delta_vix || 0) >= 0 ? "+" : ""}${(vix.delta_vix || 0).toFixed(2)})`
                          : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-400 block">26. PDH / PDL LEVELS</span>
                      <span className="text-slate-200 font-bold">
                        {pdh && pdl ? `${fmt(pdh, 0)} / ${fmt(pdl, 0)}` : "—"}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="p-1.5 rounded bg-amber-950/20 border border-amber-800/30 text-[10px] text-amber-300/90 leading-tight">
                  <span className="font-bold text-amber-400">CAT D SYNTHESIS:</span> {catDSynthesis}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══════════ CATEGORY E: GLOBAL MACRO & LIVE NEWS ══════════ */}
        {(matchesSearch("macro") || matchesSearch("news") || matchesSearch("crude") || matchesSearch("dxy") || matchesSearch("fii") || matchesSearch("gift")) && (
          <div className="pt-2">
            <button
              onClick={() => toggleCategory("E")}
              className="w-full flex items-center justify-between text-left py-1 text-slate-300 hover:text-blue-400 group"
            >
              <div className="flex items-center gap-1.5 font-bold text-[11px] tracking-wider text-blue-400">
                {collapsed.E ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                <span>CAT E: GLOBAL MACRO & LIVE NEWS</span>
              </div>
              <span className="text-[9px] px-1 py-0.2 rounded bg-[#161F30] text-slate-400">27–32</span>
            </button>

            {!collapsed.E && (
              <div className="mt-1.5 space-y-1.5 pl-3 border-l-2 border-blue-500/30">
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="grid grid-cols-4 gap-1 text-center">
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">27. GIFT</span>
                      <span className="text-[10px] font-bold text-cyan-300">{macro?.GIFT_NIFTY ? fmt(macro.GIFT_NIFTY, 0) : "—"}</span>
                    </div>
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">28. DXY</span>
                      <span className="text-[10px] font-bold text-slate-200">{macro?.DXY ? macro.DXY.toFixed(2) : "—"}</span>
                    </div>
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">29. BRENT</span>
                      <span className="text-[10px] font-bold text-slate-200">{macro?.CRUDE ? `$${macro.CRUDE.toFixed(1)}` : "—"}</span>
                    </div>
                    <div className="bg-[#090D14] p-1 rounded">
                      <span className="text-[8px] text-slate-400 block">30. US 10Y</span>
                      <span className="text-[10px] font-bold text-slate-200">{macro?.BOND_10Y ? `${macro.BOND_10Y.toFixed(2)}%` : "—"}</span>
                    </div>
                  </div>
                </div>

                {/* 31. Live News Headlines */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538] space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold flex items-center gap-1">
                      <Newspaper size={11} className="text-cyan-400" />
                      31. LIVE MARKET NEWS ({combinedNews.length})
                    </span>
                    <span className="text-cyan-400 text-[9px] font-bold">RSS STREAM</span>
                  </div>
                  {combinedNews.length > 0 ? (
                    combinedNews.slice(0, 2).map((item, idx) => {
                      const title = typeof item === "object" ? item?.title || item?.headline : item;
                      return (
                        <div key={idx} className="p-1 rounded bg-[#090D14] text-[10px] text-slate-300 truncate" title={title}>
                          • {title}
                        </div>
                      );
                    })
                  ) : (
                    <div className="p-1 rounded bg-[#090D14] text-[10px] text-slate-500 italic">
                      Awaiting RSS headlines...
                    </div>
                  )}
                </div>

                {/* 32. Institutional Flow */}
                <div className="bg-[#111724] p-2 rounded border border-[#1C2538]">
                  <div className="flex items-center justify-between text-[10px]">
                    <div>
                      <span className="text-[9px] text-slate-400 block">32. FII NET CASH ({inst?.date || "EOD"})</span>
                      <span className={`font-bold ${(fiiCash ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {fiiCash !== null ? `${fiiCash >= 0 ? "+" : ""}₹${fmt(fiiCash, 2)} Cr` : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="text-[9px] text-slate-400 block">DII NET CASH</span>
                      <span className={`font-bold ${(inst?.dii_net_crores ?? inst?.dii_cash ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {(inst?.dii_net_crores ?? inst?.dii_cash) !== null && (inst?.dii_net_crores ?? inst?.dii_cash) !== undefined
                          ? `${(inst?.dii_net_crores ?? inst?.dii_cash)! >= 0 ? "+" : ""}₹${fmt(inst?.dii_net_crores ?? inst?.dii_cash, 2)} Cr`
                          : "—"}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="p-1.5 rounded bg-blue-950/20 border border-blue-800/30 text-[10px] text-blue-300/90 leading-tight">
                  <span className="font-bold text-blue-400">CAT E SYNTHESIS:</span> {catESynthesis}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
