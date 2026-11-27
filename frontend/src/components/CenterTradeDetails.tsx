"use client";

import React, { useState, useEffect } from "react";
import {
  Briefcase, ShieldCheck, CheckCircle2, Target, XCircle, FileText, PauseCircle
} from "lucide-react";
import { API_CONFIG } from "@/config/api";
import {
  Position,
  LLMDecisionContract,
  MarketStateData,
  TradeLogRow,
  RoundTripTrade,
} from "@/types/market";

interface CenterTradeDetailsProps {
  positions?: Record<string, Position> | null;
  lastDecision?: LLMDecisionContract | null;
  lastSignal?: { action?: string; symbol?: string; confidence?: number; reason?: string };
  marketState?: MarketStateData | null;
  tradingMode?: string;
  onSquareOffPosition?: (symbol: string) => Promise<void>;
}

function formatTs(ts?: string | null): string {
  if (!ts) return "—";
  return ts.slice(0, 19).replace("T", " ");
}

function formatTimeOnly(ts?: string | null): string {
  if (!ts) return "—";
  return ts.slice(11, 19) || ts;
}

function formatDuration(secs?: number | null): string {
  if (typeof secs !== "number" || !Number.isFinite(secs)) return "—";
  const mins = Math.floor(secs / 60);
  const rem = secs % 60;
  return mins > 0 ? `${mins}m ${String(rem).padStart(2, "0")}s` : `${rem}s`;
}

export function CenterTradeDetails({
  positions = {},
  lastDecision,
  lastSignal,
  marketState,
  onSquareOffPosition,
}: CenterTradeDetailsProps) {
  const [activeTab, setActiveTab] = useState<"positions" | "plan" | "orders">("positions");
  const [historyView, setHistoryView] = useState<"journal" | "raw">("journal");
  const [tradeLogs, setTradeLogs] = useState<TradeLogRow[]>([]);
  const [roundTrips, setRoundTrips] = useState<RoundTripTrade[]>([]);

  const posCount = Object.values(positions || {}).filter(
    (p) => Math.abs(p.net_qty ?? p.qty ?? 0) > 0
  ).length;
  const decisionKey = lastDecision?.decision_id || "";

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const res = await fetch(`${API_CONFIG.BASE_URL}/api/trades`);
        if (res.ok) {
          const d = await res.json();
          setTradeLogs(d.trades || []);
          setRoundTrips(d.round_trips || []);
        }
      } catch {
        // Ignore transient offline errors
      }
    };
    fetchTrades();
    const id = setInterval(fetchTrades, 10000);
    return () => clearInterval(id);
  }, [posCount, decisionKey]);

  const action = lastDecision?.action || lastSignal?.action || "OBSERVE";
  const confidence = lastDecision?.confidence || lastSignal?.confidence || 0;
  const reason =
    lastDecision?.reason ||
    lastSignal?.reason ||
    "System evaluating live 32 market dimensions. Entry requires >90% multi-factor alignment.";
  const setup = lastDecision?.setup || "PATIENCE_PROTOCOL";
  const direction = lastDecision?.direction || "NEUTRAL";

  const posEntries = Object.entries(positions || {}).filter(
    ([, p]) => Math.abs(p.net_qty ?? p.qty ?? 0) > 0
  );
  const hasPositions = posEntries.length > 0;

  const ind = marketState?.indices;
  const nifty = ind?.NIFTY50;
  const vix = ind?.INDIAVIX;
  const fl = marketState?.orderflow;
  const llmStatus = marketState?.data_sources?.llm_status;

  return (
    <div className="flex-1 flex flex-col bg-[#0B0F18] overflow-hidden select-none font-mono">
      {/* Tab Header Bar */}
      <div className="h-8 bg-[#090D15] border-b border-[#1E2638] px-3 flex items-center justify-between text-xs shrink-0">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setActiveTab("positions")}
            className={`px-3 py-1 rounded text-[11px] font-bold tracking-wider flex items-center gap-1.5 transition-colors ${
              activeTab === "positions"
                ? "bg-[#161F30] text-cyan-300 border-b-2 border-cyan-400"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Briefcase size={12} />
            <span>ACTIVE POSITIONS ({posEntries.length})</span>
          </button>

          <button
            onClick={() => setActiveTab("plan")}
            className={`px-3 py-1 rounded text-[11px] font-bold tracking-wider flex items-center gap-1.5 transition-colors ${
              activeTab === "plan"
                ? "bg-[#161F30] text-cyan-300 border-b-2 border-cyan-400"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Target size={12} />
            <span>AI TRADE PLAN & REASON</span>
          </button>

          <button
            onClick={() => setActiveTab("orders")}
            className={`px-3 py-1 rounded text-[11px] font-bold tracking-wider flex items-center gap-1.5 transition-colors ${
              activeTab === "orders"
                ? "bg-[#161F30] text-cyan-300 border-b-2 border-cyan-400"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileText size={12} />
            <span>ORDER HISTORY ({tradeLogs.length})</span>
          </button>
        </div>

        <div className="text-[10px] text-slate-400 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span>RISK MONITOR ACTIVE</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 text-xs">
        {/* TAB 1: ACTIVE POSITIONS (NO FAKE TRADES WHEN FLAT!) */}
        {activeTab === "positions" && (
          <div className="space-y-3 h-full">
            {!hasPositions ? (
              <div className="bg-[#101623] border border-[#1E283D] rounded p-5 flex flex-col items-center justify-center text-center gap-2">
                <PauseCircle size={22} className="text-cyan-400" />
                <div className="text-slate-200 font-bold text-xs tracking-wider">
                  NO ACTIVE OPEN POSITIONS (CAPITAL AT RISK: ₹0.00)
                </div>
                <div className="text-[11px] text-slate-400 max-w-md leading-relaxed">
                  Patience Protocol engaged — AI state is <span className="text-cyan-300 font-bold">{action}</span>.
                  Positions appear here only when a live or paper order fills in the execution router.
                </div>
              </div>
            ) : (
              posEntries.map(([symKey, activePosition]) => {
                const qty = activePosition.net_qty ?? activePosition.qty ?? 0;
                const entry = activePosition.avg_price ?? activePosition.entry_price ?? 0;
                const ltp = activePosition.current_ltp ?? entry;
                const pnlPoints = ltp - entry;
                const unrealizedPnL = pnlPoints * qty;
                const pnlPercent = entry > 0 ? ((qty >= 0 ? pnlPoints : -pnlPoints) / entry) * 100 : 0;
                const isProfit = unrealizedPnL >= 0;

                return (
                  <div key={symKey} className="bg-[#101623] border border-[#1E283D] rounded p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-[#1C2538]">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-1.5 py-0.5 rounded border text-[10px] font-bold ${
                            qty >= 0
                              ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40"
                              : "bg-rose-500/20 text-rose-400 border-rose-500/40"
                          }`}
                        >
                          {qty > 0 ? "LONG" : "SHORT"}
                        </span>
                        <span className="text-slate-100 font-bold text-sm">
                          {activePosition.symbol || symKey}
                        </span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#162032] text-cyan-300 border border-cyan-800/40 font-mono">
                          {Math.abs(qty)} Qty
                        </span>
                      </div>

                      <div className="flex items-baseline gap-2">
                        <span className="text-[10px] text-slate-400">UNREALIZED P&L:</span>
                        <span className={`text-base font-extrabold ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                          {isProfit ? "+" : ""}₹{unrealizedPnL.toFixed(2)}
                        </span>
                        <span className={`text-[11px] font-bold ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                          ({isProfit ? "+" : ""}{pnlPercent.toFixed(2)}%)
                        </span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2.5 text-[11px]">
                      <div className="bg-[#090D15] p-2 rounded border border-[#161E2E]">
                        <span className="text-[9px] text-slate-400 block mb-0.5">AVG ENTRY PRICE</span>
                        <span className="font-bold text-slate-200">₹{entry.toFixed(2)}</span>
                      </div>
                      <div className="bg-[#090D15] p-2 rounded border border-[#161E2E]">
                        <span className="text-[9px] text-slate-400 block mb-0.5">CURRENT LTP</span>
                        <span className="font-bold text-cyan-300">₹{ltp.toFixed(2)}</span>
                      </div>
                      <div className="bg-[#090D15] p-2 rounded border border-[#161E2E]">
                        <span className="text-[9px] text-slate-400 block mb-0.5">STOP LOSS</span>
                        <span className="font-bold text-rose-400">
                          {activePosition.stop_loss ? `₹${activePosition.stop_loss.toFixed(2)}` : "TSL Dynamic"}
                        </span>
                      </div>
                      <div className="bg-[#090D15] p-2 rounded border border-[#161E2E]">
                        <span className="text-[9px] text-cyan-400 font-bold block mb-0.5">TRAILING SL</span>
                        <span className="font-bold text-slate-200">
                          {activePosition.trailing_sl ? `₹${activePosition.trailing_sl.toFixed(2)}` : "Armed (+15pt trigger)"}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-end pt-2.5 mt-2 border-t border-[#1C2538] text-[10px]">
                      <button
                        onClick={() => onSquareOffPosition && onSquareOffPosition(activePosition.symbol || symKey)}
                        className="px-3 py-1 rounded bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/40 font-bold tracking-wider flex items-center gap-1 transition-colors"
                      >
                        <XCircle size={11} />
                        <span>CLOSE POSITION (SQUARE OFF)</span>
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* TAB 2: AI TRADE PLAN & REASON */}
        {activeTab === "plan" && (
          <div className="space-y-2.5">
            <div className="bg-[#101623] border border-[#1E283D] rounded p-2.5 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-slate-400 font-semibold">STATE:</span>
                  <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 text-[11px] font-bold">
                    {action}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-slate-400 font-semibold">DIRECTION:</span>
                  <span className="text-cyan-300 font-bold text-[11px]">{direction}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-slate-400 font-semibold">SETUP:</span>
                  <span className="text-amber-300 font-bold text-[11px]">{setup}</span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {lastDecision?.provider && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 font-bold uppercase">
                    {lastDecision.provider}
                  </span>
                )}
                <span className="text-[10px] text-slate-400">CONFIDENCE:</span>
                <span className="text-sm font-extrabold text-cyan-400">{confidence}%</span>
                <ShieldCheck size={14} className="text-emerald-400" />
              </div>
            </div>

            {llmStatus?.action_required && (
              <div className="bg-amber-950/30 border border-amber-500/40 rounded p-2.5 text-[11px] text-amber-200 space-y-1">
                <div className="font-bold text-amber-300 text-[10px] tracking-wider uppercase">
                  LLM PROVIDER CONFIGURATION REQUIRED
                </div>
                <p className="text-[11px] text-amber-100/90 font-sans leading-relaxed">
                  {llmStatus.action_required}
                </p>
              </div>
            )}

            {!llmStatus?.action_required && llmStatus?.transient_warning && (
              <div className="bg-slate-900/80 border border-slate-700/60 rounded px-2.5 py-1.5 text-[10px] text-slate-300 flex items-center justify-between gap-2">
                <span className="text-amber-300 font-bold uppercase shrink-0">LLM RETRY NOTICE:</span>
                <span className="truncate text-slate-300">{llmStatus.transient_warning}</span>
              </div>
            )}

            <div className="bg-[#101623] border border-[#1E283D] rounded p-3 space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-200">
                <span className="flex items-center gap-1.5 text-cyan-400">
                  <CheckCircle2 size={13} className="text-emerald-400" />
                  LIVE FACTOR CONFLUENCE & REASONING
                </span>
                <span className="text-[9px] text-slate-400">TIME: {marketState?.market_time || "--:--:--"} IST</span>
              </div>

              <p className="text-[11px] text-slate-300 leading-relaxed font-sans bg-[#090D15] p-2.5 rounded border border-[#161E2E]">
                {reason}
              </p>

              <div className="flex flex-wrap items-center gap-1.5 pt-1 text-[10px]">
                {nifty && nifty.ltp > 0 && nifty.vwap > 0 && (
                  <span className={`px-2 py-0.5 rounded border ${nifty.ltp >= nifty.vwap ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" : "bg-rose-500/10 text-rose-400 border-rose-500/30"}`}>
                    Spot vs VWAP: {nifty.ltp >= nifty.vwap ? "+" : ""}{(nifty.ltp - nifty.vwap).toFixed(1)} pts
                  </span>
                )}
                {vix && vix.ltp > 0 && (
                  <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                    India VIX: {vix.ltp.toFixed(2)}
                  </span>
                )}
                {fl?.NIFTY_PCR ? (
                  <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                    Nifty PCR: {fl.NIFTY_PCR.toFixed(2)}
                  </span>
                ) : null}
                {fl?.AD_RATIO ? (
                  <span className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/30">
                    A/D Ratio: {fl.AD_RATIO.toFixed(2)}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: TRADE JOURNAL & ORDER HISTORY FROM SQLITE + LIVE OPTION LTP */}
        {activeTab === "orders" && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[10px]">
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setHistoryView("journal")}
                  className={`px-2 py-0.5 rounded border font-bold transition-colors ${
                    historyView === "journal"
                      ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                      : "bg-[#101623] text-slate-400 border-[#1E283D] hover:text-slate-200"
                  }`}
                >
                  TRADE JOURNAL ({roundTrips.length})
                </button>
                <button
                  onClick={() => setHistoryView("raw")}
                  className={`px-2 py-0.5 rounded border font-bold transition-colors ${
                    historyView === "raw"
                      ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                      : "bg-[#101623] text-slate-400 border-[#1E283D] hover:text-slate-200"
                  }`}
                >
                  RAW ORDERS ({tradeLogs.length})
                </button>
              </div>
              <span className="text-slate-400">
                Net PnL includes Paper brokerage (₹60/order) &amp; Live Option LTP
              </span>
            </div>

            {historyView === "journal" ? (
              <div className="space-y-2">
                {roundTrips.length === 0 ? (
                  <div className="bg-[#101623] border border-[#1E283D] rounded py-6 text-center text-slate-500 italic text-[10px]">
                    No executed round-trip trades in SQLite audit ledger yet.
                  </div>
                ) : (
                  roundTrips.map((rt) => {
                    const grossProfit = rt.gross_pnl >= 0;
                    const netProfit = rt.net_pnl >= 0;
                    const ifHeldDiff = rt.if_held_pnl;
                    return (
                      <div key={rt.id} className="bg-[#101623] border border-[#1E283D] rounded p-2.5 space-y-2 text-[10px]">
                        <div className="flex flex-wrap items-center justify-between gap-2 pb-1.5 border-b border-[#182133]">
                          <div className="flex items-center gap-2">
                            <span
                              className={`px-1.5 py-0.5 rounded font-bold border ${
                                rt.status === "OPEN"
                                  ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                                  : "bg-slate-800 text-slate-300 border-slate-700"
                              }`}
                            >
                              {rt.status} · {rt.side}
                            </span>
                            <span className="text-cyan-400 font-bold">{rt.mode}</span>
                            <span className="text-slate-100 font-bold text-xs">{rt.symbol}</span>
                            <span className="text-slate-400">{rt.qty} Qty</span>
                            {rt.hold_seconds !== null && rt.hold_seconds !== undefined && (
                              <span className="px-1.5 py-0.2 rounded bg-[#090D15] border border-[#1B2436] text-amber-300">
                                Held {formatDuration(rt.hold_seconds)}
                              </span>
                            )}
                          </div>

                          <div className="flex flex-wrap items-center gap-2.5">
                            <span>
                              <span className="text-slate-400">GROSS: </span>
                              <span className={`font-bold ${grossProfit ? "text-emerald-400" : "text-rose-400"}`}>
                                {grossProfit ? "+" : ""}₹{rt.gross_pnl.toFixed(2)}
                              </span>
                            </span>
                            <span>
                              <span className="text-slate-400">NET (w/ ₹{rt.brokerage.toFixed(0)} fee): </span>
                              <span className={`font-extrabold ${netProfit ? "text-emerald-400" : "text-rose-400"}`}>
                                {netProfit ? "+" : ""}₹{rt.net_pnl.toFixed(2)}
                              </span>
                            </span>
                            {typeof rt.fund_after === "number" && rt.fund_after > 0 && (
                              <span className="px-1.5 py-0.5 rounded bg-[#090D15] border border-[#1B2436] text-slate-200 font-bold">
                                Bal: ₹{rt.fund_after.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                              </span>
                            )}
                          </div>
                        </div>

                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                          <div className="bg-[#090D15] px-2 py-1.5 rounded border border-[#161E2E]">
                            <div className="text-[9px] text-emerald-400 font-bold">ENTERED</div>
                            <div className="font-bold text-slate-100">
                              {rt.entry_price !== null && rt.entry_price !== undefined ? `₹${rt.entry_price.toFixed(2)}` : "—"}
                            </div>
                            <div className="text-[9px] text-slate-400">{formatTimeOnly(rt.entry_time)} IST</div>
                          </div>

                          <div className="bg-[#090D15] px-2 py-1.5 rounded border border-[#161E2E]">
                            <div className="text-[9px] text-rose-400 font-bold">CLOSED</div>
                            <div className="font-bold text-slate-100">
                              {rt.exit_price !== null && rt.exit_price !== undefined ? `₹${rt.exit_price.toFixed(2)}` : "OPEN"}
                            </div>
                            <div className="text-[9px] text-slate-400">{formatTimeOnly(rt.exit_time)} IST</div>
                          </div>

                          <div className="bg-[#090D15] px-2 py-1.5 rounded border border-[#161E2E]">
                            <div className="text-[9px] text-cyan-400 font-bold">LIVE OPTION LTP</div>
                            <div className="font-bold text-cyan-300">
                              {typeof rt.current_ltp === "number" && rt.current_ltp > 0 ? `₹${rt.current_ltp.toFixed(2)}` : "—"}
                            </div>
                            <div className="text-[9px] text-slate-400">
                              {typeof ifHeldDiff === "number" ? (
                                <span className={ifHeldDiff >= 0 ? "text-emerald-400" : "text-rose-400"}>
                                  If Held: {ifHeldDiff >= 0 ? "+" : ""}₹{ifHeldDiff.toFixed(2)}
                                </span>
                              ) : (
                                "Live quote pending"
                              )}
                            </div>
                          </div>

                          <div className="bg-[#090D15] px-2 py-1.5 rounded border border-[#161E2E]">
                            <div className="text-[9px] text-amber-300 font-bold">EXIT TRIGGER</div>
                            <div className="text-slate-200 truncate" title={rt.exit_reason || rt.entry_reason || ""}>
                              {rt.exit_reason || (rt.status === "OPEN" ? "Position Active" : "—")}
                            </div>
                            <div className="text-[9px] text-slate-500 truncate">{rt.entry_time ? formatTs(rt.entry_time).slice(0, 10) : ""}</div>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            ) : (
              <div className="bg-[#101623] border border-[#1E283D] rounded overflow-x-auto">
                <table className="w-full text-left text-[10px]">
                  <thead className="bg-[#090D15] border-b border-[#1C2538] text-slate-400">
                    <tr>
                      <th className="py-2 px-2.5">TIMESTAMP</th>
                      <th className="py-2 px-2">MODE</th>
                      <th className="py-2 px-2">SYMBOL</th>
                      <th className="py-2 px-2">SIDE</th>
                      <th className="py-2 px-2">QTY</th>
                      <th className="py-2 px-2">FILL PRICE</th>
                      <th className="py-2 px-2">LIVE LTP</th>
                      <th className="py-2 px-2">REALIZED P&amp;L</th>
                      <th className="py-2 px-2.5 text-right">FUND BAL</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#161E2E]">
                    {tradeLogs.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="py-6 text-center text-slate-500 italic">
                          No recorded trades in SQLite audit ledger yet.
                        </td>
                      </tr>
                    ) : (
                      tradeLogs.slice(0, 50).map((t, idx) => (
                        <tr key={t.id || idx} className="hover:bg-[#141C2C] text-slate-300">
                          <td className="py-1.5 px-2.5 font-mono text-slate-400">
                            {formatTs(t.timestamp)}
                          </td>
                          <td className="py-1.5 px-2 text-cyan-400 font-bold">{t.mode}</td>
                          <td className="py-1.5 px-2 font-bold text-slate-100">{t.symbol}</td>
                          <td className={`py-1.5 px-2 font-bold ${t.action === "BUY" ? "text-emerald-400" : "text-rose-400"}`}>
                            {t.action}
                          </td>
                          <td className="py-1.5 px-2">{t.qty}</td>
                          <td className="py-1.5 px-2">₹{t.price?.toFixed(2)}</td>
                          <td className="py-1.5 px-2 text-cyan-300 font-semibold">
                            {typeof t.current_ltp === "number" && t.current_ltp > 0 ? `₹${t.current_ltp.toFixed(2)}` : "—"}
                          </td>
                          <td className={`py-1.5 px-2 font-bold ${(t.pnl || 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                            {t.action === "SELL" ? `${t.pnl >= 0 ? "+" : ""}₹${t.pnl.toFixed(2)}` : "—"}
                          </td>
                          <td className="py-1.5 px-2.5 text-right text-slate-200 font-mono">
                            {typeof t.fund_balance === "number" && t.fund_balance > 0 ? `₹${t.fund_balance.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "—"}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
