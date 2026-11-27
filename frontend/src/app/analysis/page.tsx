"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { format } from "date-fns";
import { ArrowLeft, RefreshCw, CheckCircle2, XCircle, BarChart2, Activity } from "lucide-react";
import { API_CONFIG } from "@/config/api";

interface Trade {
  timestamp: string; mode: string; action: string;
  symbol: string; price: number; current_ltp?: number | null;
  confidence: number; pnl: number; fund_balance?: number; reason: string;
}

function HealthRow({ label, status }: { label: string; status: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0">
      <span className="text-[11px] font-semibold text-slate-600">{label}</span>
      {status
        ? <span className="flex items-center gap-1 text-[10px] font-bold text-green-600"><CheckCircle2 size={11} /> PASS</span>
        : <span className="flex items-center gap-1 text-[10px] font-bold text-red-500"><XCircle size={11} /> FAIL</span>}
    </div>
  );
}

function Panel({ title, badge, children, className = "" }: {
  title: React.ReactNode; badge?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={`flex flex-col bg-white border border-slate-200 rounded-sm shadow-sm ${className}`}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100 bg-slate-50 shrink-0">
        <span className="text-[10px] font-bold tracking-widest uppercase text-slate-500">{title}</span>
        {badge && <span className="text-[9px] font-bold text-slate-400">{badge}</span>}
      </div>
      <div className="flex flex-col flex-1 min-h-0">{children}</div>
    </div>
  );
}

export default function AnalysisPage() {
  const [trades,     setTrades]     = useState<Trade[]>([]);
  const [health,     setHealth]     = useState<Record<string, unknown> | null>(null);
  const [logs,       setLogs]       = useState<string[]>([]);
  const [modeFilter, setModeFilter] = useState("ALL");

  useEffect(() => {
    const fetchAll = async () => {
      try { setTrades((await (await fetch(`${API_CONFIG.BASE_URL}/api/trades?mode=${modeFilter}`)).json()).trades || []); } catch {}
      try { setHealth(await (await fetch(`${API_CONFIG.BASE_URL}/api/system/health`)).json()); } catch {}
      try { setLogs((await (await fetch(`${API_CONFIG.BASE_URL}/api/system/logs`)).json()).logs || []); } catch {}
    };
    fetchAll();
    const logInt = setInterval(async () => {
      try { setLogs((await (await fetch(`${API_CONFIG.BASE_URL}/api/system/logs`)).json()).logs || []); } catch {}
    }, 5000);
    return () => clearInterval(logInt);
  }, [modeFilter]);

  const sells   = trades.filter(t => t.action === "SELL");
  const pnl     = sells.reduce((s, t) => s + (t.pnl || 0), 0);
  const wins    = sells.filter(t => t.pnl > 0).length;
  const acc     = sells.length > 0 ? ((wins / sells.length) * 100).toFixed(1) : "0.0";

  return (
    <div className="min-h-screen bg-slate-50 font-mono text-slate-900 flex flex-col">

      {/* Header */}
      <header className="bg-white border-b border-slate-200 px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <BarChart2 size={14} className="text-[#05B3D0]" />
          <span className="text-[12px] font-black tracking-tight text-slate-900">Analytics &amp; Diagnostics</span>
          <span className="w-px h-5 bg-slate-200" />
          <span className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Engine Audit · Health · Log Stream</span>
        </div>
        <Link href="/">
          <button className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold tracking-wider border border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-600 rounded-sm transition-colors">
            <ArrowLeft size={11} /> DASHBOARD
          </button>
        </Link>
      </header>

      <main className="flex-1 p-3">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">

          {/* ── Sidebar ── */}
          <div className="lg:col-span-1 space-y-3">

            {/* Mode filter */}
            <Panel title="Mode Filter">
              <div className="p-2">
                <div className="flex rounded-sm overflow-hidden border border-slate-200 text-[10px] font-black tracking-wider">
                  {["ALL", "PAPER", "LIVE"].map(m => (
                    <button key={m} onClick={() => setModeFilter(m)}
                      className={`flex-1 py-1.5 transition-colors ${
                        modeFilter === m ? "bg-[#05B3D0] text-white" : "bg-slate-50 text-slate-500 hover:bg-slate-100"
                      }`}>
                      {m}
                    </button>
                  ))}
                </div>
              </div>
            </Panel>

            {/* Performance KPIs */}
            <Panel title="Performance" badge={`${trades.length} tickets`}>
              <div className="p-3 space-y-2.5">
                <div className="bg-slate-50 border border-slate-100 rounded-sm p-2.5">
                  <div className="text-[9px] font-semibold uppercase tracking-widest text-slate-400 mb-1">Total Realized PnL</div>
                  <div className={`text-xl font-black ${pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {pnl >= 0 ? "+" : ""}₹{pnl.toFixed(2)}
                  </div>
                </div>
                <div className="bg-slate-50 border border-slate-100 rounded-sm p-2.5">
                  <div className="text-[9px] font-semibold uppercase tracking-widest text-slate-400 mb-1">Win Accuracy</div>
                  <div className="text-xl font-black text-slate-900">{acc}%</div>
                </div>
                <div className="bg-slate-50 border border-slate-100 rounded-sm p-2.5">
                  <div className="text-[9px] font-semibold uppercase tracking-widest text-slate-400 mb-1">Profitable</div>
                  <div className="text-xl font-black text-[#05B3D0]">{wins} / {sells.length}</div>
                </div>
              </div>
            </Panel>

            {/* Health */}
            <Panel title="Subsystem Health">
              <div className="px-3 py-2">
                {health ? (
                  <>
                    <HealthRow label="SQLite Ledger"    status={health.database_connected as boolean} />
                    <HealthRow label="Redis Store"      status={health.redis_connected as boolean} />
                    <HealthRow label="Upstox Feed"      status={health.data_receiving as boolean} />
                    <HealthRow label="Exec Broker"      status={health.broker_configured as boolean} />
                    {Array.isArray(health.errors) && health.errors.length > 0 && (
                      <div className="mt-2 p-2 bg-red-50 border border-red-100 rounded-sm">
                        <p className="text-[10px] text-red-600 font-bold mb-1">Active Warnings</p>
                        {(health.errors as string[]).map((e, i) => (
                          <p key={i} className="text-[10px] text-red-500">{e}</p>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="flex items-center gap-2 py-4 text-slate-400">
                    <RefreshCw size={12} className="animate-spin text-[#05B3D0]" />
                    <span className="text-[10px]">Polling…</span>
                  </div>
                )}
              </div>
            </Panel>
          </div>

          {/* ── Main area ── */}
          <div className="lg:col-span-3 space-y-3">

            {/* Trade Ledger */}
            <Panel title="Audited Order Ticket Ledger" badge={`${trades.length} records`} className="flex-none">
              <div className="overflow-auto" style={{ maxHeight: 440 }}>
                <table className="w-full text-[11px] font-mono">
                  <thead className="sticky top-0 bg-white z-10">
                    <tr className="border-b border-slate-100">
                      {["Timestamp", "Mode", "Action", "Instrument", "Fill Price", "Live LTP", "Conf.", "PnL", "Rationale"].map(h => (
                        <th key={h} className="text-left px-3 py-2 text-[9px] font-bold tracking-widest uppercase text-slate-400 whitespace-nowrap bg-slate-50">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                        <td className="px-3 py-1.5 text-[10px] text-slate-400 whitespace-nowrap">
                          {t.timestamp && !Number.isNaN(Date.parse(t.timestamp))
                            ? format(new Date(t.timestamp), "MMM dd, HH:mm:ss")
                            : "—"}
                        </td>
                        <td className="px-3 py-1.5">
                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-sm ${
                            t.mode === "LIVE"
                              ? "bg-red-50 text-red-600 border border-red-100"
                              : "bg-[#05B3D0]/10 text-[#05B3D0]"
                          }`}>{t.mode}</span>
                        </td>
                        <td className={`px-3 py-1.5 font-black ${t.action === "BUY" ? "text-green-600" : "text-red-600"}`}>
                          {t.action}
                        </td>
                        <td className="px-3 py-1.5 font-bold text-slate-900">{t.symbol}</td>
                        <td className="px-3 py-1.5 text-right font-semibold">₹{t.price}</td>
                        <td className="px-3 py-1.5 text-right font-semibold text-[#05B3D0]">
                          {typeof t.current_ltp === "number" && t.current_ltp > 0 ? `₹${t.current_ltp.toFixed(2)}` : "—"}
                        </td>
                        <td className="px-3 py-1.5 text-right font-bold text-[#05B3D0]">{t.confidence}%</td>
                        <td className={`px-3 py-1.5 text-right font-black whitespace-nowrap ${t.pnl > 0 ? "text-green-600" : t.pnl < 0 ? "text-red-600" : "text-slate-300"}`}>
                          {t.action === "SELL" ? `${t.pnl >= 0 ? "+" : ""}₹${t.pnl.toFixed(2)}` : "—"}
                        </td>
                        <td className="px-3 py-1.5 text-slate-500 max-w-[180px] truncate" title={t.reason}>
                          {t.reason}
                        </td>
                      </tr>
                    ))}
                    {trades.length === 0 && (
                      <tr>
                        <td colSpan={9} className="text-center py-10 text-slate-300 text-[11px] italic">
                          No order tickets matching filter
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>

            {/* Log stream */}
            <Panel title={<span className="flex items-center gap-1.5"><Activity size={10} className="text-[#05B3D0]" /> Log Stream</span>}
              badge={<span className="flex items-center gap-1"><span className="live-dot" style={{ width: 5, height: 5 }} /> STREAMING</span>}
            >
              <div className="overflow-y-auto p-3 bg-slate-50 font-mono text-[10px] text-slate-500 leading-relaxed" style={{ height: 220 }}>
                {logs.length === 0
                  ? <span className="text-slate-300 italic">Awaiting engine logs…</span>
                  : logs.map((log, i) => (
                    <div key={i} className="hover:text-slate-900 transition-colors whitespace-pre-wrap py-0.5">
                      <span className="text-[#05B3D0] font-bold select-none mr-1.5">›</span>{log}
                    </div>
                  ))
                }
              </div>
            </Panel>
          </div>
        </div>
      </main>
    </div>
  );
}
