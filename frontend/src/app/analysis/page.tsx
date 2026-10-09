"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { format } from "date-fns";
import { API_CONFIG } from "@/config/api";

interface Trade {
  timestamp: string;
  mode: string;
  action: string;
  symbol: string;
  price: number;
  confidence: number;
  pnl: number;
  reason: string;
}

export default function AnalysisPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [modeFilter, setModeFilter] = useState("ALL");

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const res = await fetch(`${API_CONFIG.BASE_URL}/api/trades?mode=${modeFilter}`);
        const data = await res.json();
        setTrades(data.trades || []);
      } catch (e) {
        console.error(e);
      }
    };

    const fetchHealth = async () => {
      try {
        const res = await fetch(`${API_CONFIG.BASE_URL}/api/system/health`);
        const data = await res.json();
        setHealth(data);
      } catch (e) {
        console.error(e);
      }
    };

    const fetchLogs = async () => {
      try {
        const res = await fetch(`${API_CONFIG.BASE_URL}/api/system/logs`);
        const data = await res.json();
        setLogs(data.logs || []);
      } catch (e) {
        console.error(e);
      }
    };

    fetchTrades();
    fetchHealth();
    fetchLogs();

    // Refresh logs every 5s
    const logInterval = setInterval(fetchLogs, 5000);
    return () => clearInterval(logInterval);
  }, [modeFilter]);

  // KPIs
  const totalTrades = trades.length;
  const sellTrades = trades.filter(t => t.action === "SELL");
  const totalPnl = sellTrades.reduce((sum, t) => sum + (t.pnl || 0), 0);
  const profitableTrades = sellTrades.filter(t => (t.pnl || 0) > 0).length;
  const accuracy = sellTrades.length > 0 ? ((profitableTrades / sellTrades.length) * 100).toFixed(2) : "0.00";

  return (
    <div className="min-h-screen bg-[#050505] text-gray-200 font-sans p-6">
      <header className="flex justify-between items-center mb-8 border-b border-gray-800 pb-4">
        <div>
          <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">
            System Analysis & Diagnostics
          </h1>
          <p className="text-gray-400 text-sm mt-1">Jini Algo Post-Market Review</p>
        </div>
        <Link href="/">
          <button className="px-6 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm font-medium transition-colors border border-gray-700">
            ← Back to Dashboard
          </button>
        </Link>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">

        {/* LEFT COLUMN: Controls & KPIs & Health */}
        <div className="lg:col-span-1 space-y-6">

          {/* Controls */}
          <div className="bg-[#111] border border-gray-800 p-5 rounded-xl shadow-2xl">
            <h2 className="text-lg font-bold mb-4 text-gray-300">Filters</h2>
            <div className="flex bg-gray-900 rounded-lg p-1 border border-gray-800">
              {['ALL', 'PAPER', 'LIVE'].map(m => (
                <button
                  key={m}
                  onClick={() => setModeFilter(m)}
                  className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-all ${modeFilter === m ? 'bg-blue-600 text-white shadow-md' : 'text-gray-400 hover:text-white'
                    }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          {/* KPIs */}
          <div className="bg-[#111] border border-gray-800 p-5 rounded-xl shadow-2xl space-y-4">
            <h2 className="text-lg font-bold text-gray-300">Performance</h2>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Total PnL</span>
              <span className={`text-xl font-bold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                ₹{totalPnl.toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Accuracy</span>
              <span className="text-lg font-bold text-blue-400">{accuracy}%</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Total Trades</span>
              <span className="text-lg font-bold text-gray-300">{totalTrades}</span>
            </div>
          </div>

          {/* Health Checks */}
          <div className="bg-[#111] border border-gray-800 p-5 rounded-xl shadow-2xl">
            <h2 className="text-lg font-bold mb-4 text-gray-300">System Health</h2>
            {health ? (
              <div className="space-y-3">
                <HealthRow label="Database Connected" status={health.database_connected as boolean} />
                <HealthRow label="Redis (Market Data)" status={health.redis_connected as boolean} />
                <HealthRow label="Data Stream Active" status={health.data_receiving as boolean} />
                <HealthRow label="Broker Configured" status={health.broker_configured as boolean} />

                {Array.isArray(health.errors) && health.errors.length > 0 && (
                  <div className="mt-4 p-3 bg-red-900/20 border border-red-500/30 rounded-lg">
                    <p className="text-xs text-red-400 font-semibold mb-1">Active Alerts:</p>
                    <ul className="list-disc list-inside text-xs text-red-300">
                      {(health.errors as string[]).map((err: string, i: number) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <div className="animate-pulse flex space-x-2">
                <div className="w-4 h-4 bg-gray-700 rounded-full"></div>
                <div className="h-4 bg-gray-700 rounded w-24"></div>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: Trades & Logs */}
        <div className="lg:col-span-3 space-y-6">

          {/* Trade Ledger */}
          <div className="bg-[#111] border border-gray-800 rounded-xl shadow-2xl overflow-hidden flex flex-col h-[500px]">
            <div className="p-4 border-b border-gray-800 bg-[#161616]">
              <h2 className="text-lg font-bold text-gray-300">Trade Ledger</h2>
            </div>
            <div className="overflow-auto flex-1 p-0">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-400 uppercase bg-[#1a1a1a] sticky top-0">
                  <tr>
                    <th className="px-4 py-3">Time</th>
                    <th className="px-4 py-3">Mode</th>
                    <th className="px-4 py-3">Action</th>
                    <th className="px-4 py-3">Symbol</th>
                    <th className="px-4 py-3">Price</th>
                    <th className="px-4 py-3">Conf.</th>
                    <th className="px-4 py-3">PnL</th>
                    <th className="px-4 py-3">AI Logic</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t, i) => (
                    <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors">
                      <td className="px-4 py-3 whitespace-nowrap text-gray-400">
                        {format(new Date(t.timestamp), "MMM dd, HH:mm:ss")}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${t.mode === 'LIVE' ? 'bg-red-900/50 text-red-400 border border-red-500/30' : 'bg-blue-900/50 text-blue-400 border border-blue-500/30'}`}>
                          {t.mode}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-bold">
                        <span className={t.action === 'BUY' ? 'text-emerald-400' : 'text-red-400'}>{t.action}</span>
                      </td>
                      <td className="px-4 py-3 font-mono">{t.symbol}</td>
                      <td className="px-4 py-3">₹{t.price}</td>
                      <td className="px-4 py-3 text-blue-300">{t.confidence}%</td>
                      <td className={`px-4 py-3 font-bold ${t.pnl > 0 ? 'text-emerald-400' : t.pnl < 0 ? 'text-red-400' : 'text-gray-500'}`}>
                        {t.action === 'SELL' ? `₹${t.pnl.toFixed(2)}` : '-'}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500 truncate max-w-[200px]" title={t.reason}>
                        {t.reason}
                      </td>
                    </tr>
                  ))}
                  {trades.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-gray-500">No trades found for this filter.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* System Logs */}
          <div className="bg-[#111] border border-gray-800 rounded-xl shadow-2xl flex flex-col h-[300px]">
            <div className="p-4 border-b border-gray-800 bg-[#161616]">
              <h2 className="text-lg font-bold text-gray-300">Live System Logs</h2>
            </div>
            <div className="overflow-auto flex-1 p-4 bg-black font-mono text-[11px] text-gray-400 leading-relaxed">
              {logs.map((log, i) => (
                <div key={i} className="whitespace-pre-wrap">{log}</div>
              ))}
              {logs.length === 0 && <div>No logs found or logger not writing to file.</div>}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

function HealthRow({ label, status }: { label: string, status: boolean }) {
  return (
    <div className="flex justify-between items-center p-2 bg-gray-900/50 rounded border border-gray-800">
      <span className="text-sm text-gray-300">{label}</span>
      {status ? (
        <span className="flex items-center text-emerald-400 text-xs font-bold">
          <div className="w-2 h-2 rounded-full bg-emerald-500 mr-2 shadow-[0_0_8px_rgba(16,185,129,0.8)]"></div>
          PASS
        </span>
      ) : (
        <span className="flex items-center text-red-400 text-xs font-bold">
          <div className="w-2 h-2 rounded-full bg-red-500 mr-2 shadow-[0_0_8px_rgba(239,68,68,0.8)]"></div>
          FAIL
        </span>
      )}
    </div>
  );
}
