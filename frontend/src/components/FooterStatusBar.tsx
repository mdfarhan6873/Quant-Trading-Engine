"use client";

import React from "react";
import {
  GitBranch, Database, Cpu, Wifi,
  ShieldCheck, Radio
} from "lucide-react";
import { MarketStateData } from "@/types/market";

interface FooterStatusBarProps {
  connected: boolean;
  tradingMode?: string;
  hasPositions?: boolean;
  marketState?: MarketStateData | null;
}

export function FooterStatusBar({
  connected,
  tradingMode = "PAPER",
  marketState,
}: FooterStatusBarProps) {
  const ds = marketState?.data_sources;
  const redisOnline = ds?.redis_connected ?? false;
  const upstoxConnected = ds?.upstox_ws?.connected ?? false;
  const upstoxTokenValid = ds?.upstox_ws?.token_valid ?? false;
  const llmStatus = ds?.llm_status;
  const feedLabel = upstoxConnected
    ? "FEED: UPSTOX WS (<20ms)"
    : upstoxTokenValid
      ? "FEED: UPSTOX REST + NSE"
      : "FEED: NSE + GROWW + YAHOO";
  const llmLabel = llmStatus?.healthy
    ? `AI BRAIN: ${(llmStatus.active_providers || []).join("+").toUpperCase()} + RAG`
    : llmStatus?.action_required
      ? (llmStatus?.configured_cloud_count || 0) > 0
        ? "AI BRAIN: KEY AUTH ERROR (.ENV)"
        : "AI BRAIN: ADD FREE LLM KEY (.ENV)"
      : llmStatus?.transient_warning
        ? "AI BRAIN: RETRYING PROVIDER"
        : "AI BRAIN: WARMING UP";

  return (
    <footer className="h-6 bg-[#080B12] border-t border-[#1A2234] px-3 flex items-center justify-between text-[10px] text-slate-400 select-none font-mono shrink-0">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1 hover:text-slate-200 cursor-pointer">
          <GitBranch size={11} className="text-cyan-400" />
          <span>main*</span>
        </div>

        <div className="flex items-center gap-1">
          <Radio size={11} className={upstoxConnected ? "text-emerald-400" : "text-amber-400"} />
          <span className={upstoxConnected ? "text-emerald-400" : "text-amber-300"}>{feedLabel}</span>
        </div>

        <div className="flex items-center gap-1">
          <Database size={11} className={redisOnline ? "text-emerald-400" : "text-amber-400"} />
          <span>{redisOnline ? "DOCKER REDIS: ONLINE" : "CACHE: IN-MEMORY"}</span>
        </div>

        <div className="hidden md:flex items-center gap-1">
          <Cpu size={11} className={llmStatus?.healthy ? "text-emerald-400" : "text-amber-400"} />
          <span className={llmStatus?.healthy ? "text-cyan-300" : "text-amber-300"}>{llmLabel}</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
          <span className="font-bold text-slate-300">{tradingMode} MODE</span>
        </div>

        <div className="flex items-center gap-1 text-emerald-400 font-bold">
          <ShieldCheck size={11} />
          <span>RISK GUARDS: ARMED</span>
        </div>

        <div className="flex items-center gap-1">
          <Wifi size={11} className={connected ? "text-emerald-400" : "text-rose-400"} />
          <span>{connected ? "WS: LIVE (1s)" : "WS: OFFLINE"}</span>
        </div>

        <div className="hidden sm:inline text-slate-500">
          IST
        </div>
      </div>
    </footer>
  );
}
