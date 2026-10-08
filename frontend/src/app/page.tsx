"use client";

import { useEffect, useState } from "react";
import { Globe, MapPin, Brain, ShieldAlert, Antenna, Newspaper } from "lucide-react";
import { API_CONFIG } from "@/config/api";

interface Position {
  entry_price: number;
  qty: number;
  realized_pnl?: number;
}

interface DashboardData {
  status: string;
  market_state: {
    market_time?: string;
    indices?: {
      NIFTY50?: { ltp: number; volume: number; delta_volume: number; vwap: number; futures_premium: number };
      BANKNIFTY?: { ltp: number; volume: number; delta_volume: number; vwap: number; futures_premium: number };
      NIFTYIT?: { ltp: number; volume: number; delta_volume: number };
      INDIAVIX?: { ltp: number };
    };
    orderflow?: {
      NIFTY_PCR: number;
      BANKNIFTY_PCR: number;
      NIFTY_CVD: number;
      BANKNIFTY_CVD: number;
      AD_RATIO: number;
    };
    options_data?: {
      NIFTY_GEX: number;
      NIFTY_MAXPAIN: number;
      BANKNIFTY_GEX: number;
      BANKNIFTY_MAXPAIN: number;
      chain?: {
        NIFTY?: Record<string, { ltp: number; volume: number; oi: number; delta_oi: number; iv: number }>;
        BANKNIFTY?: Record<string, { ltp: number; volume: number; oi: number; delta_oi: number; iv: number }>;
      };
    };
    heavyweights?: Record<string, { ltp: number; volume: number; delta_volume: number; imbalance: number }>;
    macro?: Record<string, number>;
    institutional?: {
      fii_cash?: number;
      dii_cash?: number;
      fii_index_futures?: number;
    };
    prev_ohlc?: Record<string, { open: number; high: number; low: number; close: number }>;
    breaking_news?: Array<{ title?: string; summary?: string; link?: string; date?: string } | string>;
    indian_news?: Array<{ title?: string; summary?: string; link?: string; date?: string } | string>;
  };
  positions: Record<string, Position>;
  last_signal?: {
    action: string;
    symbol: string;
    confidence: number;
    reason: string;
  };
  trading_mode?: string;
}

const NewsItem = ({ n, type }: { n: { title?: string, summary?: string, link?: string, date?: string } | string, type: 'india' | 'global' }) => {
  const [expanded, setExpanded] = useState(false);
  const Icon = Newspaper;
  const iconColor = type === 'india' ? 'text-orange-500' : 'text-blue-500';
  
  const isObj = typeof n === 'object' && n !== null;
  const title = isObj ? n.title : n;
  const summary = isObj ? n.summary : undefined;
  const link = isObj ? n.link : undefined;
  const date = isObj ? n.date : undefined;

  const formattedDate = date ? new Date(date).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  }) : null;

  return (
    <li 
      className="flex gap-2 items-start bg-black/30 p-2 rounded border border-zinc-800 cursor-pointer hover:bg-black/50 transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <Icon className={`${iconColor} mt-0.5 shrink-0`} size={16} />
      <div className="flex flex-col w-full overflow-hidden">
        {link ? (
          <a 
            href={link} 
            target="_blank" 
            rel="noopener noreferrer" 
            className={`hover:underline hover:text-blue-400 w-full text-zinc-200 ${expanded ? '' : 'truncate'}`}
            onClick={(e) => e.stopPropagation()}
            title="Read full article"
          >
            {title}
          </a>
        ) : (
          <span className={`w-full text-zinc-200 ${expanded ? '' : 'truncate'}`} title={typeof title === 'string' ? title : ""}>
            {title}
          </span>
        )}
        
        {formattedDate && (
          <span className="text-zinc-500 text-[10px] w-full mt-0.5">
            {formattedDate}
          </span>
        )}

        {summary && (
          <span 
            className={`text-zinc-400 text-[10px] w-full mt-0.5 ${expanded ? 'line-clamp-none whitespace-normal' : 'line-clamp-2'}`}
            title={expanded ? "" : "Click to expand summary"}
          >
            {summary}
          </span>
        )}
      </div>
    </li>
  );
};
export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: NodeJS.Timeout;

    const connectWebSocket = () => {
      ws = new WebSocket(API_CONFIG.WS_URL);

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          setData(payload);
        } catch (err) {
          console.error("Error parsing websocket data", err);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        // Attempt to auto-reconnect after 3 seconds
        reconnectTimer = setTimeout(connectWebSocket, 3000);
      };

      ws.onerror = () => {
        console.warn("WebSocket disconnected. Attempting to reconnect...");
        ws.close();
      };
    };

    connectWebSocket();

    return () => {
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, []);

  const triggerKillSwitch = async () => {
    if (confirm("🚨 KILL SWITCH! 🚨\nAre you sure you want to trigger the KILL SWITCH? This will square off all positions at market price and halt the engine.")) {
      try {
        const res = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.KILL_SWITCH}`, {
          method: "POST"
        });
        const result = await res.json();
        alert(result.message);
      } catch {
        alert("Failed to trigger Kill Switch!");
      }
    }
  };

  const toggleTradingMode = async (currentMode: string | undefined) => {
    const targetMode = currentMode === "LIVE" ? "PAPER" : "LIVE";
    if (targetMode === "LIVE" && !confirm("⚠️ WARNING: You are switching to REAL LIVE TRADING. Real money will be used. Continue?")) {
      return;
    }
    
    try {
      const res = await fetch(`${API_CONFIG.BASE_URL}/api/set_mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: targetMode })
      });
      const result = await res.json();
      
      if (result.message === "MISSING_CREDENTIALS") {
        alert("❌ MISSING EXECUTION CREDENTIALS! ❌\n\nYou cannot switch to LIVE Trade. Please add your Groww or Dhan execution API Keys in the .env file.");
      } else if (result.status === "error") {
        alert("Error: " + result.message);
      }
    } catch {
      alert("Failed to reach server to switch mode.");
    }
  };

  if (!connected) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center text-white">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.5)]"></div>
          <p className="text-zinc-200 font-mono text-lg animate-pulse tracking-widest">Connecting to JINI AI Trading Engine...</p>
        </div>
      </div>
    );
  }

  const mState = data?.market_state;
  const ind = mState?.indices;
  const flow = mState?.orderflow;
  const opt = mState?.options_data;
  
  // Format numbers helper
  const fmt = (num: number | undefined, dec = 2) => num ? num.toFixed(dec) : "---";

  // Filter option chain to show top 5 active strikes based on volume
  const getActiveOptions = (chainData: Record<string, { ltp: number; volume: number; oi: number; delta_oi: number; iv: number }> | undefined) => {
    if (!chainData) return [];
    return Object.entries(chainData)
      .map(([strike, data]) => ({ strike, ...data }))
      .sort((a, b) => b.volume - a.volume)
      .slice(0, 5);
  };
  const niftyOptions = getActiveOptions(opt?.chain?.NIFTY);

  return (
    <div className="min-h-screen bg-zinc-950 text-white p-4 font-mono overflow-x-hidden">
      
      {/* HEADER */}
      <header className="flex justify-between items-center mb-4 bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-2xl">
        <div className="flex flex-col">
          <div className="flex items-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/gini.png" alt="Jini AI Logo" className="h-14 w-auto object-contain" />
          </div>
          <p className="text-sm text-zinc-300 mt-2 tracking-widest uppercase">
            ENGINE STATUS: {data?.status === "ONLINE" ? <span className="text-emerald-500 font-bold drop-shadow-[0_0_5px_rgba(16,185,129,0.8)]">ONLINE [ARMED]</span> : <span className="text-red-500 font-bold">OFFLINE</span>}
            &nbsp; | &nbsp; MARKET TIME: <span className="text-blue-300 font-bold">{mState?.market_time || "---"}</span>
          </p>
        </div>
        
        <div className="flex items-center gap-6">
          {/* Trading Mode Toggle */}
          <div className="flex items-center gap-3 bg-zinc-950 p-2 rounded-lg border border-zinc-700">
            <span className={`text-sm font-bold tracking-widest ${data?.trading_mode === "PAPER" ? "text-blue-400" : "text-zinc-500"}`}>PAPER</span>
            
            <button 
              onClick={() => toggleTradingMode(data?.trading_mode)}
              className={`relative w-16 h-8 rounded-full transition-colors ${data?.trading_mode === "LIVE" ? "bg-red-600" : "bg-blue-600"}`}
            >
              <div className={`absolute top-1 w-6 h-6 rounded-full bg-white transition-all shadow-md ${data?.trading_mode === "LIVE" ? "right-1" : "left-1"}`}></div>
            </button>
            
            <span className={`text-sm font-bold tracking-widest ${data?.trading_mode === "LIVE" ? "text-red-500 animate-pulse drop-shadow-[0_0_5px_rgba(239,68,68,0.8)]" : "text-zinc-500"}`}>LIVE</span>
          </div>

          <button 
            onClick={triggerKillSwitch}
            className="bg-red-600 hover:bg-red-500 text-white px-8 py-3 rounded font-black text-lg tracking-widest shadow-[0_0_20px_rgba(220,38,38,0.6)] transition-all hover:scale-105 active:scale-95 flex items-center gap-2"
          >
            <ShieldAlert size={24} /> KILL SWITCH
          </button>
        </div>
      </header>

      {/* TOP ROW: Indices & Advanced Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
        
        {/* NIFTY 50 Block */}
        <div className="bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-16 h-16 bg-blue-500/10 rounded-bl-full blur-2xl"></div>
          <h2 className="text-zinc-200 text-sm font-bold mb-2 tracking-wide">NIFTY 50</h2>
          <p className={`text-4xl font-black ${ind?.NIFTY50?.ltp ? "text-emerald-400" : "text-white"}`}>
            {fmt(ind?.NIFTY50?.ltp)}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 text-sm font-semibold">
            <div className="flex justify-between"><span className="text-zinc-300">Vol:</span><span className="text-blue-300">{ind?.NIFTY50?.volume || 0}</span></div>
            <div className="flex justify-between"><span className="text-zinc-300">VWAP:</span><span className="text-purple-300">{fmt(ind?.NIFTY50?.vwap)}</span></div>
            <div className="flex justify-between"><span className="text-zinc-300">Premium:</span><span className={ind?.NIFTY50?.futures_premium && ind.NIFTY50.futures_premium > 0 ? "text-emerald-400" : "text-red-400"}>{fmt(ind?.NIFTY50?.futures_premium)}</span></div>
            <div className="flex justify-between"><span className="text-zinc-300">PCR:</span><span className={flow?.NIFTY_PCR && flow.NIFTY_PCR > 1 ? "text-emerald-400" : "text-red-400"}>{fmt(flow?.NIFTY_PCR)}</span></div>
          </div>
        </div>

        {/* BANKNIFTY Block */}
        <div className="bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-16 h-16 bg-purple-500/10 rounded-bl-full blur-2xl"></div>
          <h2 className="text-zinc-200 text-sm font-bold mb-2 tracking-wide">BANKNIFTY</h2>
          <p className={`text-4xl font-black ${ind?.BANKNIFTY?.ltp ? "text-emerald-400" : "text-white"}`}>
            {fmt(ind?.BANKNIFTY?.ltp)}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 text-sm font-semibold">
            <div className="flex justify-between"><span className="text-zinc-300">Vol:</span><span className="text-blue-300">{ind?.BANKNIFTY?.volume || 0}</span></div>
            <div className="flex justify-between"><span className="text-zinc-300">VWAP:</span><span className="text-purple-300">{fmt(ind?.BANKNIFTY?.vwap)}</span></div>
            <div className="flex justify-between"><span className="text-zinc-300">Premium:</span><span className={ind?.BANKNIFTY?.futures_premium && ind.BANKNIFTY.futures_premium > 0 ? "text-emerald-400" : "text-red-400"}>{fmt(ind?.BANKNIFTY?.futures_premium)}</span></div>
            <div className="flex justify-between"><span className="text-zinc-300">PCR:</span><span className={flow?.BANKNIFTY_PCR && flow.BANKNIFTY_PCR > 1 ? "text-emerald-400" : "text-red-400"}>{fmt(flow?.BANKNIFTY_PCR)}</span></div>
          </div>
        </div>

        {/* NIFTY IT Block */}
        <div className="bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-16 h-16 bg-teal-500/10 rounded-bl-full blur-2xl"></div>
          <h2 className="text-zinc-200 text-sm font-bold mb-2 tracking-wide">NIFTY IT</h2>
          <p className={`text-3xl font-black ${ind?.NIFTYIT?.ltp ? "text-emerald-400" : "text-white"}`}>
            {fmt(ind?.NIFTYIT?.ltp)}
          </p>
          <div className="mt-4 flex flex-col gap-2 text-sm font-semibold">
            <div className="flex justify-between"><span className="text-zinc-300">Vol:</span><span className="text-blue-300">{ind?.NIFTYIT?.volume || 0}</span></div>
            <div className="flex justify-between"><span className="text-zinc-300">Δ Vol:</span><span className="text-yellow-300">{ind?.NIFTYIT?.delta_volume || 0}</span></div>
          </div>
        </div>

        {/* ORDERFLOW & GREEKS */}
        <div className="bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-xl col-span-1 md:col-span-2 flex flex-col justify-between">
          <h2 className="text-zinc-200 text-sm font-bold mb-3 tracking-wide">ORDERFLOW & GEX</h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-black/50 p-3 rounded border border-zinc-600">
              <p className="text-xs text-zinc-300 mb-1 font-semibold">NIFTY CVD</p>
              <p className={`text-xl font-bold ${flow?.NIFTY_CVD && flow.NIFTY_CVD > 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(flow?.NIFTY_CVD, 0)}</p>
            </div>
            <div className="bg-black/50 p-3 rounded border border-zinc-600">
              <p className="text-xs text-zinc-300 mb-1 font-semibold">BANK CVD</p>
              <p className={`text-xl font-bold ${flow?.BANKNIFTY_CVD && flow.BANKNIFTY_CVD > 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(flow?.BANKNIFTY_CVD, 0)}</p>
            </div>
            <div className="bg-black/50 p-3 rounded border border-zinc-600">
              <p className="text-xs text-zinc-300 mb-1 font-semibold">NIFTY GEX (Gamma)</p>
              <p className={`text-xl font-bold ${opt?.NIFTY_GEX && opt.NIFTY_GEX > 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(opt?.NIFTY_GEX, 0)}</p>
            </div>
            <div className="bg-black/50 p-3 rounded border border-zinc-600">
              <p className="text-xs text-zinc-300 mb-1 font-semibold">A/D RATIO</p>
              <p className={`text-xl font-bold ${flow?.AD_RATIO && flow.AD_RATIO >= 1 ? "text-emerald-400" : "text-red-400"}`}>{fmt(flow?.AD_RATIO)}</p>
            </div>
          </div>
        </div>
      </div>

      {/* MIDDLE ROW: Options Chain, Portfolio, Heavyweights */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-4">
        
        {/* ACTIVE OPTIONS CHAIN SCANNER */}
        <div className="bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-xl col-span-1 lg:col-span-1 h-80 overflow-hidden flex flex-col">
          <h2 className="text-zinc-200 text-sm font-bold mb-3 border-b border-zinc-700 pb-2 tracking-wide">ACTIVE OPTIONS (NIFTY)</h2>
          <div className="overflow-y-auto space-y-2 text-xs">
            {niftyOptions.length === 0 ? (
              <p className="text-zinc-300 italic">No chain data...</p>
            ) : (
              niftyOptions.map((optData) => (
                <div key={optData.strike} className="flex flex-col bg-black/40 p-2 rounded border border-zinc-700">
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-bold text-white text-sm">{optData.strike}</span>
                    <span className="text-emerald-400 font-bold">{fmt(optData.ltp)}</span>
                  </div>
                  <div className="flex justify-between text-zinc-300 font-semibold">
                    <span>IV: {fmt(optData.iv)}%</span>
                    <span>OI: {optData.oi}</span>
                    <span className={optData.delta_oi > 0 ? 'text-emerald-400' : 'text-red-400'}>ΔOI: {optData.delta_oi > 0 ? '+' : ''}{optData.delta_oi}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* ACTIVE PORTFOLIO */}
        <div className="bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-xl col-span-1 lg:col-span-2 flex flex-col">
          <h2 className="text-zinc-200 text-sm font-bold mb-3 border-b border-zinc-700 pb-2 flex justify-between tracking-wide">
            <span>LIVE PORTFOLIO & PnL</span>
            <span className="text-emerald-400 font-bold drop-shadow-[0_0_5px_rgba(16,185,129,0.8)]">REAL-TIME</span>
          </h2>
          
          <div className="flex-1 overflow-y-auto">
            {(!data?.positions || Object.keys(data.positions).length === 0) ? (
              <div className="flex flex-col items-center justify-center h-full text-zinc-300 space-y-2 font-semibold">
                <Antenna className="w-10 h-10 opacity-80 text-blue-400 mb-2 animate-pulse" />
                <span className="italic tracking-wider text-base">Scanning for high-probability setups...</span>
              </div>
            ) : (
              <div className="space-y-3">
                {Object.entries(data.positions).map(([symbol, pos]: [string, Position]) => {
                  const pnl = pos.realized_pnl || 0; 
                  return (
                    <div key={symbol} className="bg-black/60 p-4 rounded border-l-4 border-l-blue-500 border border-zinc-600 flex justify-between items-center">
                      <div>
                        <h3 className="font-black text-2xl text-white">{symbol}</h3>
                        <p className="text-sm text-zinc-300 mt-1 font-mono font-bold">ENTRY: <span className="text-white">{pos.entry_price.toFixed(2)}</span> | QTY: <span className="text-white">{pos.qty}</span></p>
                      </div>
                      <div className="text-right">
                        <p className={`text-4xl font-black ${pnl >= 0 ? 'text-emerald-400 drop-shadow-[0_0_8px_rgba(16,185,129,0.6)]' : 'text-red-400 drop-shadow-[0_0_8px_rgba(239,68,68,0.6)]'}`}>
                          {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
                        </p>
                        <p className="text-xs text-zinc-300 font-bold uppercase tracking-widest mt-1">Realized PnL</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* HEAVYWEIGHTS TAPE */}
        <div className="bg-zinc-900 border border-zinc-700 p-4 rounded-lg shadow-xl col-span-1 lg:col-span-1 h-80 overflow-hidden flex flex-col">
          <h2 className="text-zinc-200 text-sm font-bold mb-3 border-b border-zinc-700 pb-2 tracking-wide">HEAVYWEIGHTS</h2>
          <div className="overflow-y-auto space-y-2 pr-2 text-sm">
            {!mState?.heavyweights || Object.keys(mState.heavyweights).length === 0 ? (
              <p className="text-zinc-300 italic">No heavyweight data...</p>
            ) : (
              Object.entries(mState.heavyweights).map(([sym, hdata]) => (
                <div key={sym} className="flex justify-between items-center bg-black/40 p-2 rounded border border-zinc-700">
                  <span className="font-bold text-white w-1/3 truncate text-xs">{sym}</span>
                  <span className="text-zinc-200 font-semibold">{fmt(hdata.ltp)}</span>
                  <span className={`text-right font-semibold text-xs ${hdata.imbalance > 1.2 ? 'text-emerald-400' : hdata.imbalance < 0.8 ? 'text-red-400' : 'text-zinc-300'}`}>
                    imb: {fmt(hdata.imbalance)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

      </div>

      {/* BOTTOM ROW: AI Reasoning & Macro */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        
        {/* DUAL-BRAIN REASONING */}
        <div className="bg-black border border-zinc-700 p-5 rounded-lg shadow-xl relative overflow-hidden">
          <div className="absolute -bottom-10 -right-10 w-32 h-32 bg-emerald-500/10 rounded-full blur-3xl"></div>
          <h2 className="text-white text-sm font-bold mb-4 border-b border-zinc-700 pb-2 flex items-center gap-2 tracking-wide">
            <Brain className="text-pink-400" size={18} /> JINI AI CONSENSUS TERMINAL
          </h2>
          
          {data?.last_signal ? (
            data.last_signal.action === "ANALYSIS" ? (
              <div className="space-y-4 relative z-10 h-full flex flex-col justify-start">
                <div className="bg-blue-900/20 p-4 rounded border border-blue-500/30 text-center mb-2">
                  <h3 className="text-lg font-black text-blue-400 mb-1 tracking-widest uppercase flex justify-center items-center gap-2">
                    <span className="animate-pulse h-2 w-2 bg-blue-400 rounded-full"></span> 
                    AFTER HOURS MARKET PERSPECTIVE
                  </h3>
                  <p className="text-zinc-400 text-xs font-semibold">
                    Market is currently closed. Jini is analyzing macro indices, FII/DII data, and options positioning to build the next session bias.
                  </p>
                </div>
                <div className="bg-zinc-900/80 p-4 rounded border border-zinc-600 flex-1 overflow-y-auto">
                  <span className="block text-zinc-200 font-bold mb-2 text-sm tracking-wide">JINI NARRATIVE:</span>
                  <p className="text-blue-300 font-medium leading-relaxed text-sm block bg-black/50 p-4 rounded border border-blue-900/50 whitespace-pre-wrap">
                    &quot;{data.last_signal.reason}&quot;
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-4 text-base font-mono relative z-10">
                <div className="flex items-center gap-4 bg-zinc-900/80 p-3 rounded border border-zinc-600">
                  <span className="text-zinc-200 font-bold w-24">ACTION:</span>
                  <span className={`font-black text-2xl ${data.last_signal.action === 'HOLD' ? 'text-yellow-400' : data.last_signal.action === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>
                    {data.last_signal.action}
                  </span>
                </div>
                <div className="flex items-center gap-4 bg-zinc-900/80 p-3 rounded border border-zinc-600">
                  <span className="text-zinc-200 font-bold w-24">TARGET:</span>
                  <span className="text-blue-300 font-black text-xl">{data.last_signal.symbol || "N/A"}</span>
                </div>
                <div className="flex items-center gap-4 bg-zinc-900/80 p-3 rounded border border-zinc-600">
                  <span className="text-zinc-200 font-bold w-24">CONFIDENCE:</span>
                  <div className="flex-1 bg-zinc-950 h-4 rounded-full overflow-hidden border border-zinc-600">
                    <div 
                      className={`h-full ${data.last_signal.confidence > 80 ? 'bg-emerald-500' : data.last_signal.confidence > 50 ? 'bg-yellow-500' : 'bg-red-500'}`}
                      style={{ width: `${data.last_signal.confidence}%` }}
                    ></div>
                  </div>
                  <span className="text-white font-black text-xl">{data.last_signal.confidence || 0}%</span>
                </div>
                <div className="bg-zinc-900/80 p-4 rounded border border-zinc-600 mt-2">
                  <span className="block text-zinc-200 font-bold mb-2 text-sm">JINI RATIONALE:</span>
                  <span className="text-emerald-300 font-medium leading-relaxed text-sm block bg-black/50 p-3 rounded border border-emerald-900/50">&quot;{data.last_signal.reason}&quot;</span>
                </div>
              </div>
            )
          ) : (
            <div className="text-zinc-300 flex flex-col items-center justify-center h-48 space-y-4">
              <div className="animate-pulse flex space-x-4 w-full px-8">
                <div className="flex-1 space-y-4 py-1">
                  <div className="h-3 bg-zinc-700 rounded w-3/4"></div>
                  <div className="space-y-3">
                    <div className="h-3 bg-zinc-700 rounded"></div>
                    <div className="h-3 bg-zinc-700 rounded w-5/6"></div>
                  </div>
                </div>
              </div>
              <p className="text-sm font-bold tracking-widest text-zinc-400">Jini is analyzing neural net consensus...</p>
            </div>
          )}
        </div>

        {/* GLOBAL MACRO, INST & NEWS PREVIEW */}
        <div className="bg-zinc-900 border border-zinc-700 p-5 rounded-lg shadow-xl flex flex-col justify-between">
          <div>
            <h2 className="text-zinc-200 text-sm font-bold mb-3 border-b border-zinc-700 pb-2 tracking-wide flex justify-between">
              <span>GLOBAL MACRO & INST FLOWS</span>
              {mState?.macro?.GIFT_NIFTY && <span className="text-emerald-400 font-bold text-xs bg-emerald-400/10 px-2 py-0.5 rounded border border-emerald-400/20">GIFT: {fmt(mState.macro.GIFT_NIFTY)}</span>}
            </h2>
            
            <div className="grid grid-cols-4 gap-3 mb-4 text-center">
              <div className="bg-black/60 p-2 rounded border border-zinc-600">
                <p className="text-[10px] text-zinc-400 font-semibold mb-1">10Y YIELD</p>
                <p className="text-sm font-black text-white">{fmt(mState?.macro?.BOND_10Y)}%</p>
              </div>
              <div className="bg-black/60 p-2 rounded border border-zinc-600">
                <p className="text-[10px] text-zinc-400 font-semibold mb-1">DXY</p>
                <p className="text-sm font-black text-white">{fmt(mState?.macro?.DXY)}</p>
              </div>
              <div className="bg-black/60 p-2 rounded border border-zinc-600">
                <p className="text-[10px] text-zinc-400 font-semibold mb-1">CRUDE</p>
                <p className="text-sm font-black text-white">${fmt(mState?.macro?.CRUDE)}</p>
              </div>
              <div className="bg-black/60 p-2 rounded border border-zinc-600">
                <p className="text-[10px] text-zinc-400 font-semibold mb-1">FII CASH (Cr)</p>
                <p className={`text-sm font-black ${mState?.institutional?.fii_cash && mState.institutional.fii_cash > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {mState?.institutional?.fii_cash ? (mState.institutional.fii_cash > 0 ? '+' : '') + fmt(mState.institutional.fii_cash) : '---'}
                </p>
              </div>
            </div>
            
            <div className="grid grid-cols-4 gap-3 mb-4 text-center">
              <div className="bg-black/60 p-2 rounded border border-zinc-600">
                <p className="text-[10px] text-zinc-400 font-semibold mb-1">DII CASH (Cr)</p>
                <p className={`text-sm font-black ${mState?.institutional?.dii_cash && mState.institutional.dii_cash > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {mState?.institutional?.dii_cash ? (mState.institutional.dii_cash > 0 ? '+' : '') + fmt(mState.institutional.dii_cash) : '---'}
                </p>
              </div>
              <div className="bg-black/60 p-2 rounded border border-zinc-600">
                <p className="text-[10px] text-zinc-400 font-semibold mb-1">FII IDX FUT</p>
                <p className={`text-sm font-black ${mState?.institutional?.fii_index_futures && mState.institutional.fii_index_futures > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {mState?.institutional?.fii_index_futures ? (mState.institutional.fii_index_futures > 0 ? '+' : '') + fmt(mState.institutional.fii_index_futures) : '---'}
                </p>
              </div>
              <div className="bg-black/60 p-2 rounded border border-zinc-600 col-span-2">
                <p className="text-[10px] text-zinc-400 font-semibold mb-1">PREV CLOSE (NF | BNF)</p>
                <p className="text-sm font-black text-zinc-300">
                  {fmt(mState?.prev_ohlc?.NIFTY50?.close)} | {fmt(mState?.prev_ohlc?.BANKNIFTY?.close)}
                </p>
              </div>
            </div>
          </div>
          
          <div className="mt-2">
            <h2 className="text-zinc-200 text-sm font-bold mb-3 border-b border-zinc-700 pb-2 tracking-wide">INDIA VIX & VOLATILITY</h2>
            <div className="flex items-center gap-6 bg-black/40 p-4 rounded border border-zinc-700">
              <div>
                <p className="text-xs text-zinc-300 font-semibold mb-1">SPOT VIX</p>
                <p className={`text-3xl font-black ${ind?.INDIAVIX?.ltp && ind.INDIAVIX.ltp > 15 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {fmt(ind?.INDIAVIX?.ltp)}
                </p>
              </div>
              <div className="flex-1">
                <p className="text-xs text-zinc-300 font-semibold mb-1">MAX PAIN LEVEL</p>
                <div className="flex gap-4">
                  <div className="bg-black/40 px-2 py-1 rounded border border-zinc-700">
                    <span className="text-xs font-bold text-zinc-400 mr-1">NF:</span>
                    <span className="text-sm font-black text-blue-300">{opt?.NIFTY_MAXPAIN || "---"}</span>
                  </div>
                  <div className="bg-black/40 px-2 py-1 rounded border border-zinc-700">
                    <span className="text-xs font-bold text-zinc-400 mr-1">BNF:</span>
                    <span className="text-sm font-black text-purple-300">{opt?.BANKNIFTY_MAXPAIN || "---"}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-zinc-700 h-32 overflow-y-auto">
            <p className="text-xs text-zinc-300 font-bold mb-2 tracking-wide">LIVE BREAKING NEWS STREAM</p>
            <ul className="text-xs text-zinc-200 space-y-2 font-medium">
              {mState?.indian_news?.map((n: { title?: string, summary?: string, link?: string } | string, i: number) => (
                <NewsItem key={`ind-${i}`} n={n} type="india" />
              ))}
              {mState?.breaking_news?.map((n: { title?: string, summary?: string, link?: string } | string, i: number) => (
                <NewsItem key={`glo-${i}`} n={n} type="global" />
              ))}
              {(!mState?.indian_news?.length && !mState?.breaking_news?.length) && (
                <li className="italic text-zinc-400 bg-black/30 p-2 rounded">No breaking news...</li>
              )}
            </ul>
          </div>
        </div>

      </div>

    </div>
  );
}
