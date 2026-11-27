"use client";

import React, { useEffect, useState, useRef, useCallback, useSyncExternalStore } from "react";
import { API_CONFIG } from "@/config/api";
import { DashboardWebSocketPayload } from "@/types/market";
import { HeaderIDE } from "@/components/HeaderIDE";
import { LeftCategorizedData } from "@/components/LeftCategorizedData";
import { CenterChart } from "@/components/CenterChart";
import { CenterTradeDetails } from "@/components/CenterTradeDetails";
import { RightTelemetryAndJSON } from "@/components/RightTelemetryAndJSON";
import { FooterStatusBar } from "@/components/FooterStatusBar";
import { WifiOff, Terminal, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";

const subscribeNoop = () => () => {};

export default function QuantTerminalDashboard() {
  // Guarantees SSR HTML and initial hydration frame are 100% identical even when browser extensions mutate DOM attributes
  const hasMounted = useSyncExternalStore(subscribeNoop, () => true, () => false);

  const [data, setData] = useState<DashboardWebSocketPayload | null>(null);
  const [connected, setConnected] = useState(false);
  const [paperFunds, setPaperFunds] = useState(50000);

  // Interactive IDE Resizable Layout State
  const [leftWidth, setLeftWidth] = useState(340);
  const [rightWidth, setRightWidth] = useState(400);
  const [chartHeightPct, setChartHeightPct] = useState(58);
  const [showLeftPanel, setShowLeftPanel] = useState(true);
  const [showRightPanel, setShowRightPanel] = useState(true);
  const [chartMaximized, setChartMaximized] = useState(false);

  const mainRef = useRef<HTMLElement | null>(null);
  const centerRef = useRef<HTMLElement | null>(null);
  const dragModeRef = useRef<"left" | "right" | "vertical" | null>(null);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!dragModeRef.current) return;
    if (dragModeRef.current === "left" && mainRef.current) {
      const rect = mainRef.current.getBoundingClientRect();
      const next = Math.max(220, Math.min(560, e.clientX - rect.left));
      setLeftWidth(next);
    } else if (dragModeRef.current === "right" && mainRef.current) {
      const rect = mainRef.current.getBoundingClientRect();
      const next = Math.max(260, Math.min(620, rect.right - e.clientX));
      setRightWidth(next);
    } else if (dragModeRef.current === "vertical" && centerRef.current) {
      const rect = centerRef.current.getBoundingClientRect();
      if (rect.height > 0) {
        const pct = ((e.clientY - rect.top) / rect.height) * 100;
        setChartHeightPct(Math.max(28, Math.min(86, pct)));
      }
    }
  }, []);

  const stopDragging = useCallback(() => {
    dragModeRef.current = null;
    document.body.style.cursor = "";
  }, []);

  useEffect(() => {
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", stopDragging);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopDragging);
    };
  }, [handleMouseMove, stopDragging]);

  useEffect(() => {
    if (!hasMounted) return;

    fetch(`${API_CONFIG.BASE_URL}/api/paper_funds`)
      .then((r) => r.json())
      .then((d) => {
        if (d.funds) setPaperFunds(d.funds);
      })
      .catch(() => {});

    let ws: WebSocket;
    let timer: ReturnType<typeof setTimeout>;

    const connectWS = () => {
      ws = new WebSocket(API_CONFIG.WS_URL);

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          setData(parsed);
          if (typeof parsed.paper_funds === "number" && Number.isFinite(parsed.paper_funds)) {
            setPaperFunds(parsed.paper_funds);
          }
        } catch (err) {
          console.error("Failed to parse WebSocket JSON payload:", err);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        timer = setTimeout(connectWS, 2000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connectWS();

    return () => {
      clearTimeout(timer);
      ws?.close();
    };
  }, [hasMounted]);

  const handleUpdateFunds = async (newFunds: number) => {
    try {
      const resp = await fetch(`${API_CONFIG.BASE_URL}/api/paper_funds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ funds: newFunds }),
      });
      const res = await resp.json();
      if (res.status === "success") {
        setPaperFunds(newFunds);
      }
    } catch {
      alert("Failed to update paper funds balance.");
    }
  };

  const handleToggleMode = async (currentMode?: string) => {
    const nextMode = currentMode === "LIVE" ? "PAPER" : "LIVE";
    if (nextMode === "LIVE") {
      const confirmed = confirm("⚠️ Switch to LIVE trading mode? Real broker capital will be engaged.");
      if (!confirmed) return;
    }

    try {
      const resp = await fetch(`${API_CONFIG.BASE_URL}/api/set_mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: nextMode }),
      });
      const res = await resp.json();
      if (res.message === "MISSING_CREDENTIALS") {
        alert("❌ Missing Broker Credentials in .env (Add Groww or Dhan API keys).");
      }
    } catch {
      alert("Failed to toggle trading mode.");
    }
  };

  const handleKillSwitch = async () => {
    const confirmed = confirm("🚨 EMERGENCY KILL SWITCH:\nImmediately square off ALL active positions and halt the trading engine?");
    if (!confirmed) return;

    try {
      const resp = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.KILL_SWITCH}`, {
        method: "POST",
      });
      const res = await resp.json();
      alert(res.message || "Kill switch executed.");
    } catch {
      alert("Failed to execute emergency kill switch.");
    }
  };

  const handleSquareOffPosition = async (symbol: string) => {
    const confirmed = confirm(`Close active position for ${symbol}?`);
    if (!confirmed) return;
    try {
      await fetch(`${API_CONFIG.BASE_URL}/api/close_position`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol }),
      });
    } catch {}
  };

  const startDrag = (mode: "left" | "right" | "vertical") => {
    dragModeRef.current = mode;
    document.body.style.cursor = mode === "vertical" ? "row-resize" : "col-resize";
  };

  // Initial SSR & Hydration Shell (zero mismatch risk)
  if (!hasMounted) {
    return (
      <div
        suppressHydrationWarning
        className="h-screen w-screen bg-[#070A0F] text-slate-400 font-mono flex items-center justify-center text-xs"
      >
        Loading JINI Quant Terminal IDE...
      </div>
    );
  }

  const ms = data?.market_state;
  const positions = data?.positions || {};
  const lastSignal = data?.last_signal;
  const lastDecision = data?.last_decision;
  const tradingMode = data?.trading_mode || "PAPER";

  if (!connected && !data) {
    return (
      <div className="h-screen w-screen bg-[#070A0F] text-slate-300 font-mono flex items-center justify-center p-4">
        <div className="w-96 bg-[#0E131F] border border-[#1E2638] rounded-md shadow-2xl overflow-hidden">
          <div className="h-8 bg-[#090D15] border-b border-[#1E2638] px-3 flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 font-bold text-slate-300">
              <Terminal size={12} className="text-cyan-400" />
              <span>JINI QUANT TERMINAL IDE</span>
            </div>
            <WifiOff size={12} className="text-rose-400 animate-pulse" />
          </div>

          <div className="p-4 space-y-3 text-xs">
            <p className="text-slate-400">Connecting to Python Real-Time Market Engine...</p>
            <div className="text-[10px] bg-[#07090E] p-2 rounded border border-[#1A2234] text-cyan-400 break-all font-mono">
              {API_CONFIG.WS_URL}
            </div>
            <div className="w-full h-1.5 bg-[#141A28] rounded-full overflow-hidden">
              <div className="h-full bg-cyan-400 animate-pulse w-3/4" />
            </div>
            <div className="flex items-center justify-between text-[10px] text-slate-500 pt-1">
              <span>Awaiting live WebSocket handshake...</span>
              <span className="text-cyan-400 animate-spin">◒</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen w-screen bg-[#070A0F] text-slate-200 font-mono flex flex-col overflow-hidden select-none">
      <HeaderIDE
        connected={connected}
        marketState={ms}
        lastSignal={lastSignal}
        lastDecision={lastDecision}
        tradingMode={tradingMode}
        paperFunds={paperFunds}
        executionState={data?.execution_state}
        onUpdateFunds={handleUpdateFunds}
        onToggleMode={handleToggleMode}
        onKillSwitch={handleKillSwitch}
      />

      <main ref={mainRef} className="flex-1 flex overflow-hidden min-h-0 relative">
        {/* Left Dimensions Sidebar */}
        {showLeftPanel && !chartMaximized && (
          <div style={{ width: `${leftWidth}px` }} className="hidden md:flex shrink-0 h-full overflow-hidden">
            <LeftCategorizedData
              marketState={ms}
              lastDecision={lastDecision}
            />
          </div>
        )}

        {/* Left Horizontal Splitter */}
        {!chartMaximized && (
          <div className="hidden md:flex flex-col items-center justify-between bg-[#090D15] border-r border-[#1E2638] shrink-0">
            <button
              onClick={() => setShowLeftPanel(!showLeftPanel)}
              className="p-1 text-slate-500 hover:text-cyan-400 transition-colors"
              title={showLeftPanel ? "Collapse left sidebar" : "Expand left sidebar"}
            >
              {showLeftPanel ? <PanelLeftClose size={12} /> : <PanelLeftOpen size={12} />}
            </button>
            {showLeftPanel && (
              <div
                onMouseDown={() => startDrag("left")}
                onDoubleClick={() => setLeftWidth(340)}
                className="flex-1 w-1.5 cursor-col-resize hover:bg-cyan-500/40 active:bg-cyan-400/60 transition-colors"
                title="Drag to resize left panel horizontally (double-click to reset)"
              />
            )}
          </div>
        )}

        {/* Center Chart & Bottom Trade Details */}
        <section ref={centerRef} className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
          <div
            style={{ height: chartMaximized ? "100%" : `${chartHeightPct}%` }}
            className="min-h-[200px] w-full shrink-0 overflow-hidden"
          >
            <CenterChart
              marketState={ms}
              lastDecision={lastDecision}
              isMaximized={chartMaximized}
              onToggleMaximize={() => setChartMaximized(!chartMaximized)}
            />
          </div>

          {!chartMaximized && (
            <>
              {/* Vertical Drag Splitter (Chart <-> Trade Details) */}
              <div
                onMouseDown={() => startDrag("vertical")}
                onDoubleClick={() => setChartHeightPct(58)}
                className="h-1.5 w-full bg-[#090D15] border-y border-[#1E2638] hover:bg-cyan-500/40 active:bg-cyan-400/60 cursor-row-resize flex items-center justify-center shrink-0 transition-colors"
                title="Drag up/down to resize chart vertically (double-click to reset)"
              >
                <span className="w-10 h-0.5 rounded bg-slate-600" />
              </div>

              <div className="flex-1 min-h-[140px] w-full overflow-hidden flex flex-col">
                <CenterTradeDetails
                  positions={positions}
                  lastDecision={lastDecision}
                  lastSignal={lastSignal}
                  marketState={ms}
                  tradingMode={tradingMode}
                  onSquareOffPosition={handleSquareOffPosition}
                />
              </div>
            </>
          )}
        </section>

        {/* Right Horizontal Splitter */}
        {!chartMaximized && (
          <div className="hidden md:flex flex-col items-center justify-between bg-[#090D15] border-l border-[#1E2638] shrink-0">
            <button
              onClick={() => setShowRightPanel(!showRightPanel)}
              className="p-1 text-slate-500 hover:text-cyan-400 transition-colors"
              title={showRightPanel ? "Collapse right sidebar" : "Expand right sidebar"}
            >
              {showRightPanel ? <PanelRightClose size={12} /> : <PanelRightOpen size={12} />}
            </button>
            {showRightPanel && (
              <div
                onMouseDown={() => startDrag("right")}
                onDoubleClick={() => setRightWidth(400)}
                className="flex-1 w-1.5 cursor-col-resize hover:bg-cyan-500/40 active:bg-cyan-400/60 transition-colors"
                title="Drag to resize right panel horizontally (double-click to reset)"
              />
            )}
          </div>
        )}

        {/* Right Health & JSON Inspector */}
        {showRightPanel && !chartMaximized && (
          <div style={{ width: `${rightWidth}px` }} className="hidden md:flex shrink-0 h-full overflow-hidden">
            <RightTelemetryAndJSON
              marketState={ms}
              lastDecision={lastDecision}
              lastSignal={lastSignal}
            />
          </div>
        )}
      </main>

      <FooterStatusBar
        connected={connected}
        tradingMode={tradingMode}
        hasPositions={Object.keys(positions || {}).length > 0}
        marketState={ms}
      />
    </div>
  );
}
