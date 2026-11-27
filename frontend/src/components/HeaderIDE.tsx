"use client";

import React, { useState, useEffect } from "react";
import {
  ShieldAlert, Wifi, WifiOff, Clock,
  Edit3, Check, X, Cpu
} from "lucide-react";
import { MarketStateData, LLMDecisionContract, ExecutionStateSummary } from "@/types/market";

interface HeaderIDEProps {
  connected: boolean;
  marketState?: MarketStateData | null;
  lastSignal?: { action?: string; symbol?: string; confidence?: number; reason?: string };
  lastDecision?: LLMDecisionContract | null;
  tradingMode?: string;
  paperFunds: number;
  executionState?: ExecutionStateSummary | null;
  onUpdateFunds: (newFunds: number) => Promise<void>;
  onToggleMode: (currentMode?: string) => Promise<void>;
  onKillSwitch: () => Promise<void>;
}

export function HeaderIDE({
  connected,
  marketState,
  lastSignal,
  lastDecision,
  tradingMode = "PAPER",
  paperFunds,
  executionState,
  onUpdateFunds,
  onToggleMode,
  onKillSwitch,
}: HeaderIDEProps) {
  const [istTime, setIstTime] = useState("");
  const [isEditingFunds, setIsEditingFunds] = useState(false);
  const [fundValue, setFundValue] = useState(paperFunds.toString());

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setIstTime(
        now.toLocaleTimeString("en-US", {
          timeZone: "Asia/Kolkata",
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }) + " IST"
      );
    };
    updateClock();
    const interval = setInterval(updateClock, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleSaveFunds = async () => {
    const parsed = parseFloat(fundValue);
    if (!isNaN(parsed) && parsed > 0) {
      await onUpdateFunds(parsed);
      setIsEditingFunds(false);
    }
  };

  const ind = marketState?.indices;
  const nifty = ind?.NIFTY50;
  const bank = ind?.BANKNIFTY;
  const vix = ind?.INDIAVIX;

  const action = lastDecision?.action || lastSignal?.action || "OBSERVE";
  const confidence = lastDecision?.confidence || lastSignal?.confidence || 0;
  const isMarketOpen = marketState?.is_market_open ?? false;

  const stateColor =
    action.includes("CALL") || action.includes("BUY")
      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/40"
      : action.includes("PUT") || action.includes("SELL")
        ? "bg-rose-500/15 text-rose-400 border-rose-500/40"
        : action === "HOLD"
          ? "bg-amber-500/15 text-amber-400 border-amber-500/40"
          : "bg-slate-700/30 text-slate-300 border-slate-600/40";

  return (
    <header className="h-11 bg-[#090D14] border-b border-[#1E2638] px-3 flex items-center justify-between text-xs select-none shrink-0 font-mono">
      {/* Left: Brand, Ticker Badges, Market Status */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 pr-3 border-r border-[#1E2638]">
          <div className="w-5 h-5 rounded bg-gradient-to-tr from-cyan-600 to-blue-500 flex items-center justify-center text-[10px] font-bold text-white shadow-sm shadow-cyan-500/20">
            J
          </div>
          <span className="font-bold tracking-wider text-slate-200 text-[11px]">
            JINI<span className="text-cyan-400">_IDE</span>
          </span>
          <span className="text-[9px] px-1 py-0.2 bg-[#161D2C] text-cyan-300 rounded border border-cyan-800/40 font-mono">
            LIVE
          </span>
        </div>

        {/* Live Ticker Badges: NIFTY, BANK NIFTY, INDIA VIX */}
        <div className="hidden lg:flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#111724] border border-[#1A2234]">
            <span className="text-[10px] text-slate-400 font-semibold">NIFTY</span>
            <span className="text-[11px] font-bold text-slate-100">
              {nifty && nifty.ltp > 0 ? `₹${nifty.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"}
            </span>
            {nifty?.day_change !== undefined && nifty.ltp > 0 && (
              <span className={`text-[9px] font-bold ${nifty.day_change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {nifty.day_change >= 0 ? "+" : ""}{nifty.day_change.toFixed(1)} ({nifty.day_change_pct?.toFixed(2)}%)
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#111724] border border-[#1A2234]">
            <span className="text-[10px] text-slate-400 font-semibold">BANKNIFTY</span>
            <span className="text-[11px] font-bold text-slate-100">
              {bank && bank.ltp > 0 ? `₹${bank.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"}
            </span>
            {bank?.day_change !== undefined && bank.ltp > 0 && (
              <span className={`text-[9px] font-bold ${bank.day_change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {bank.day_change >= 0 ? "+" : ""}{bank.day_change.toFixed(1)} ({bank.day_change_pct?.toFixed(2)}%)
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#111724] border border-[#1A2234]">
            <span className="text-[10px] text-slate-400 font-semibold">VIX</span>
            <span className="text-[11px] font-bold text-amber-300">
              {vix && vix.ltp > 0 ? vix.ltp.toFixed(2) : "—"}
            </span>
            {vix?.delta_vix !== undefined && vix.ltp > 0 && (
              <span className={`text-[9px] font-bold ${vix.delta_vix <= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {vix.delta_vix >= 0 ? "+" : ""}{vix.delta_vix.toFixed(2)}
              </span>
            )}
          </div>
        </div>

        {/* Market Open/Closed Status */}
        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#111724] border border-[#1A2234]">
          <span
            className={`w-2 h-2 rounded-full ${isMarketOpen ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
              }`}
          />
          <span className="text-[10px] tracking-wider font-semibold text-slate-300">
            {isMarketOpen ? "MARKET OPEN" : "MARKET CLOSED"}
          </span>
        </div>
      </div>

      {/* Center: Live Clock & AI State Machine Indicator */}
      <div className="flex items-center gap-3">
        <div className={`flex items-center gap-2 px-2.5 py-0.5 rounded border text-[11px] font-bold ${stateColor}`}>
          <Cpu size={12} />
          <span>{action}</span>
          {confidence > 0 && (
            <span className="text-[9px] px-1 rounded bg-black/30 text-white">
              {confidence}%
            </span>
          )}
        </div>

        <div className="hidden sm:flex items-center gap-1 text-slate-400 text-[11px]">
          <Clock size={12} className="text-cyan-400" />
          <span>{istTime || "--:--:-- IST"}</span>
        </div>
      </div>

      {/* Right: Trading Mode, Paper Funds, WebSocket, Kill Switch */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#111724] border border-[#1A2234]">
          <span className="text-[10px] text-slate-400">CAPITAL:</span>
          {isEditingFunds ? (
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={fundValue}
                onChange={(e) => setFundValue(e.target.value)}
                className="w-16 bg-[#161D2C] border border-cyan-500 text-slate-100 text-[10px] px-1 py-0.2 rounded font-mono outline-none"
              />
              <button onClick={handleSaveFunds} className="text-emerald-400 hover:text-emerald-300">
                <Check size={11} />
              </button>
              <button onClick={() => setIsEditingFunds(false)} className="text-rose-400 hover:text-rose-300">
                <X size={11} />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <span
                className={`text-[11px] font-bold ${
                  paperFunds >= 50000 ? "text-emerald-400" : "text-amber-300"
                }`}
              >
                ₹{paperFunds.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}
              </span>
              {typeof executionState?.realized_pnl_today === "number" &&
                (executionState.realized_pnl_today !== 0 || (executionState.trades_executed_today ?? 0) > 0) && (
                  <span
                    className={`text-[9px] font-bold px-1 rounded ${
                      executionState.realized_pnl_today >= 0
                        ? "bg-emerald-500/15 text-emerald-400"
                        : "bg-rose-500/15 text-rose-400"
                    }`}
                    title="Today's realized trading P&L"
                  >
                    {executionState.realized_pnl_today >= 0 ? "+" : ""}
                    ₹{executionState.realized_pnl_today.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </span>
                )}
              <button
                onClick={() => {
                  setFundValue(paperFunds.toString());
                  setIsEditingFunds(true);
                }}
                className="text-slate-500 hover:text-slate-300 transition-colors"
                title="Edit paper capital"
              >
                <Edit3 size={10} />
              </button>
            </div>
          )}
        </div>

        <button
          onClick={() => onToggleMode(tradingMode)}
          className={`px-2 py-0.5 rounded border text-[10px] font-bold tracking-wider transition-all ${tradingMode === "LIVE"
            ? "bg-rose-500/20 text-rose-300 border-rose-500/50 hover:bg-rose-500/30"
            : "bg-cyan-500/15 text-cyan-300 border-cyan-500/40 hover:bg-cyan-500/25"
            }`}
        >
          {tradingMode === "LIVE" ? "● LIVE ROUTE" : "○ PAPER SIM"}
        </button>

        <div
          className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#111724] border border-[#1A2234]"
          title={connected ? "Live Engine Stream Active" : "Stream Disconnected"}
        >
          {connected ? (
            <>
              <Wifi size={11} className="text-emerald-400" />
              <span className="text-[9px] text-emerald-400 font-bold hidden sm:inline">LIVE</span>
            </>
          ) : (
            <>
              <WifiOff size={11} className="text-rose-400 animate-pulse" />
              <span className="text-[9px] text-rose-400 font-bold hidden sm:inline">OFFLINE</span>
            </>
          )}
        </div>

        <button
          onClick={onKillSwitch}
          className="px-2.5 py-1 rounded bg-rose-600/90 hover:bg-rose-600 text-white font-bold text-[10px] tracking-wider flex items-center gap-1 transition-all shadow-sm shadow-rose-900/30 active:scale-95 border border-rose-400/30"
          title="Emergency Stop: Liquidates all open positions and pauses the engine"
        >
          <ShieldAlert size={12} />
          <span className="hidden sm:inline">KILL SWITCH</span>
        </button>
      </div>
    </header>
  );
}
