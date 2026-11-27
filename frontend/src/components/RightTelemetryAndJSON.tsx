"use client";

import React, { useState, useMemo } from "react";
import { FileCode, Activity, Copy, Check, Search, Download } from "lucide-react";
import { MarketStateData, LLMDecisionContract } from "@/types/market";
import { evaluate32DimensionsHealth } from "@/utils/healthEvaluator";

interface RightTelemetryAndJSONProps {
  marketState?: MarketStateData | null;
  lastDecision?: LLMDecisionContract | null;
  lastSignal?: { action?: string; symbol?: string; confidence?: number; reason?: string; lots?: number; qty?: number };
}

export function RightTelemetryAndJSON({
  marketState,
  lastDecision,
  lastSignal,
}: RightTelemetryAndJSONProps) {
  const [mainTab, setMainTab] = useState<"health" | "json">("health");
  const [jsonMode, setJsonMode] = useState<"input" | "output">("input");
  const [copied, setCopied] = useState(false);
  const [jsonSearch, setJsonSearch] = useState("");
  const [healthFilter, setHealthFilter] = useState<"ALL" | "OK" | "WARNING" | "FAIL">("ALL");

  const dimensionsHealth = useMemo(() => {
    return evaluate32DimensionsHealth(marketState);
  }, [marketState]);

  const healthyCount = dimensionsHealth.filter((d) => d.status === "OK").length;
  const warningCount = dimensionsHealth.filter((d) => d.status === "WARNING").length;
  const failCount = dimensionsHealth.filter((d) => d.status === "FAIL").length;

  const filteredDimensions = dimensionsHealth.filter((d) => {
    if (healthFilter !== "ALL" && d.status !== healthFilter) return false;
    return true;
  });

  // Never fabricate fake ENTER_CALL JSON; display real lastDecision or clean telemetry status
  const outputJson = useMemo(() => {
    if (lastDecision && Object.keys(lastDecision).length > 0) {
      return lastDecision;
    }
    return {
      status: "AWAITING_DECISION",
      action: lastSignal?.action || "OBSERVE",
      confidence: lastSignal?.confidence || 0,
      reason:
        marketState?.data_sources?.llm_status?.action_required ||
        lastSignal?.reason ||
        "Waiting for next 60s LLM audit cycle.",
      llm_status: marketState?.data_sources?.llm_status || null,
    };
  }, [lastDecision, lastSignal, marketState]);

  const rawJsonString = useMemo(() => {
    const target = jsonMode === "input" ? (marketState || {}) : outputJson;
    return JSON.stringify(target, null, 2);
  }, [jsonMode, marketState, outputJson]);

  const handleCopy = () => {
    navigator.clipboard.writeText(rawJsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([rawJsonString], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${jsonMode === "input" ? "market_state_input" : "llm_decision_output"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <aside className="w-full flex flex-col bg-[#0D121D] border-l border-[#1E2638] h-full overflow-hidden select-none font-mono">
      <div className="h-9 px-3 bg-[#0A0E17] border-b border-[#1E2638] flex items-center justify-between text-xs shrink-0">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setMainTab("json")}
            className={`px-2.5 py-1 rounded text-[11px] font-bold tracking-wider flex items-center gap-1.5 transition-colors ${mainTab === "json"
              ? "bg-[#161F30] text-cyan-300 border-b-2 border-cyan-400"
              : "text-slate-400 hover:text-slate-200"
              }`}
          >
            <FileCode size={12} />
            <span>SYSTEM JSON</span>
          </button>

          <button
            onClick={() => setMainTab("health")}
            className={`px-2.5 py-1 rounded text-[11px] font-bold tracking-wider flex items-center gap-1.5 transition-colors ${mainTab === "health"
              ? "bg-[#161F30] text-cyan-300 border-b-2 border-cyan-400"
              : "text-slate-400 hover:text-slate-200"
              }`}
          >
            <Activity size={12} />
            <span>32 DATA HEALTH</span>
            <span className="text-[9px] px-1 rounded bg-emerald-500/20 text-emerald-400 font-bold">
              {healthyCount}/32
            </span>
          </button>
        </div>

        {mainTab === "json" && (
          <div className="flex items-center gap-1">
            <button
              onClick={handleCopy}
              className="p-1 text-slate-400 hover:text-cyan-400 rounded transition-colors"
              title="Copy JSON to clipboard"
            >
              {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
            </button>
            <button
              onClick={handleDownload}
              className="p-1 text-slate-400 hover:text-cyan-400 rounded transition-colors"
              title="Download JSON file"
            >
              <Download size={12} />
            </button>
          </div>
        )}
      </div>

      {/* TAB 1: SYSTEM JSON VIEWER */}
      {mainTab === "json" && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-3 py-1.5 bg-[#090D15] border-b border-[#1E2638] flex items-center justify-between text-[11px]">
            <div className="flex items-center gap-1 bg-[#131926] p-0.5 rounded border border-[#1E2638]">
              <button
                onClick={() => setJsonMode("input")}
                className={`px-2 py-0.5 rounded text-[10px] font-bold ${jsonMode === "input"
                  ? "bg-cyan-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
                  }`}
              >
                1. INPUT STATE (FETCHED)
              </button>

              <button
                onClick={() => setJsonMode("output")}
                className={`px-2 py-0.5 rounded text-[10px] font-bold ${jsonMode === "output"
                  ? "bg-purple-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
                  }`}
              >
                2. LLM DECISION (RESPONSE)
              </button>
            </div>

            <span className="text-[9px] text-slate-400">
              {(rawJsonString.length / 1024).toFixed(1)} KB
            </span>
          </div>

          <div className="px-2.5 py-1 bg-[#0D121D] border-b border-[#1A2234] flex items-center gap-1.5">
            <Search size={11} className="text-slate-500" />
            <input
              type="text"
              value={jsonSearch}
              onChange={(e) => setJsonSearch(e.target.value)}
              placeholder="Filter keys in JSON..."
              className="w-full bg-transparent text-[10px] text-slate-300 placeholder:text-slate-600 outline-none"
            />
          </div>

          <div className="flex-1 overflow-auto p-2 bg-[#080B12] text-[10px] text-slate-300 font-mono select-text leading-relaxed">
            <pre className="whitespace-pre-wrap break-all">
              {rawJsonString.split("\n").map((line, idx) => {
                const isMatch = jsonSearch && line.toLowerCase().includes(jsonSearch.toLowerCase());
                return (
                  <div
                    key={idx}
                    className={`flex items-start gap-2 hover:bg-[#111726] px-1 py-0.2 ${isMatch ? "bg-amber-500/20 text-amber-200" : ""
                      }`}
                  >
                    <span className="w-7 text-right text-slate-600 select-none shrink-0 text-[9px]">
                      {idx + 1}
                    </span>
                    <span className="flex-1">
                      {line.includes('"') && !line.includes('":') ? (
                        <span className="text-emerald-400">{line}</span>
                      ) : line.includes('":') ? (
                        <>
                          <span className="text-cyan-300">{line.split('":')[0]}&quot;</span>:
                          <span className="text-amber-300">{line.split('":')[1]}</span>
                        </>
                      ) : (
                        line
                      )}
                    </span>
                  </div>
                );
              })}
            </pre>
          </div>
        </div>
      )}

      {/* TAB 2: 32 DATA HEALTH TELEMETRY */}
      {mainTab === "health" && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="p-3 bg-[#0A0E17] border-b border-[#1E2638] space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold text-slate-200">DATA INGESTION INTEGRITY</span>
              <span className="text-[11px] font-bold text-emerald-400">
                {Math.round((healthyCount / 32) * 100)}% HEALTHY
              </span>
            </div>

            <div className="w-full h-1.5 bg-[#161D2C] rounded-full overflow-hidden flex">
              <div style={{ width: `${(healthyCount / 32) * 100}%` }} className="bg-emerald-400 transition-all duration-500" />
              <div style={{ width: `${(warningCount / 32) * 100}%` }} className="bg-amber-400 transition-all duration-500" />
              <div style={{ width: `${(failCount / 32) * 100}%` }} className="bg-rose-500 transition-all duration-500" />
            </div>

            <div className="flex items-center gap-1 pt-1 text-[10px]">
              <button
                onClick={() => setHealthFilter("ALL")}
                className={`px-2 py-0.5 rounded border ${healthFilter === "ALL"
                  ? "bg-[#1E2638] text-white border-cyan-500/50"
                  : "text-slate-400 border-transparent hover:text-slate-200"
                  }`}
              >
                ALL (32)
              </button>

              <button
                onClick={() => setHealthFilter("OK")}
                className={`px-2 py-0.5 rounded border flex items-center gap-1 ${healthFilter === "OK"
                  ? "bg-emerald-950/40 text-emerald-300 border-emerald-500/50"
                  : "text-emerald-500 border-transparent hover:bg-emerald-950/20"
                  }`}
              >
                <span>● OK ({healthyCount})</span>
              </button>

              <button
                onClick={() => setHealthFilter("WARNING")}
                className={`px-2 py-0.5 rounded border flex items-center gap-1 ${healthFilter === "WARNING"
                  ? "bg-amber-950/40 text-amber-300 border-amber-500/50"
                  : "text-amber-500 border-transparent hover:bg-amber-950/20"
                  }`}
              >
                <span>▲ WARN ({warningCount})</span>
              </button>

              <button
                onClick={() => setHealthFilter("FAIL")}
                className={`px-2 py-0.5 rounded border flex items-center gap-1 ${healthFilter === "FAIL"
                  ? "bg-rose-950/40 text-rose-300 border-rose-500/50"
                  : "text-rose-500 border-transparent hover:bg-rose-950/20"
                  }`}
              >
                <span>✕ FAIL ({failCount})</span>
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1.5 text-xs">
            {filteredDimensions.map((dim) => {
              const statusBadge =
                dim.status === "OK"
                  ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                  : dim.status === "WARNING"
                    ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
                    : "bg-rose-500/15 text-rose-400 border-rose-500/30";

              return (
                <div
                  key={dim.id}
                  className="bg-[#101522] border border-[#1C2538] hover:border-[#2A3752] rounded p-2 transition-colors space-y-1"
                >
                  <div className="flex items-center justify-between text-[10px]">
                    <div className="flex items-center gap-1.5 font-bold">
                      <span className="text-cyan-400/90 font-mono">
                        #{dim.id < 10 ? `0${dim.id}` : dim.id}
                      </span>
                      <span className="text-slate-200">{dim.name}</span>
                    </div>

                    <span className={`px-1.5 py-0.2 rounded border text-[9px] font-bold ${statusBadge}`}>
                      {dim.status === "OK" ? "● FETCHING OK" : dim.status === "WARNING" ? "▲ WARN/STATIC" : "✕ OFFLINE"}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-[11px] pt-0.5">
                    <span className="text-slate-300 font-bold truncate max-w-[200px]">
                      {dim.valueFormatted}
                    </span>
                    <span className="text-slate-500 text-[9px]">
                      {dim.latencyMs}ms • {dim.source}
                    </span>
                  </div>

                  <div className="text-[9px] text-slate-400 bg-[#090D14] p-1 rounded border border-[#161E2E] truncate">
                    {dim.message}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </aside>
  );
}
