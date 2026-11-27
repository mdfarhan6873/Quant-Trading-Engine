"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { RefreshCw, Maximize2, Minimize2, RotateCcw } from "lucide-react";
import {
  createChart,
  CandlestickSeries,
  AreaSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  TickMarkType,
  UTCTimestamp,
  Time,
} from "lightweight-charts";
import { API_CONFIG } from "@/config/api";
import { MarketStateData, LLMDecisionContract } from "@/types/market";

interface CenterChartProps {
  marketState?: MarketStateData | null;
  lastDecision?: LLMDecisionContract | null;
  isMaximized?: boolean;
  onToggleMaximize?: () => void;
}

type IndexTab = "NIFTY50" | "BANKNIFTY" | "INDIAVIX";
type TimeframeKey = "1m" | "3m" | "5m" | "15m" | "30m" | "1h" | "1d" | "1wk";
type RangeKey = "1D" | "5D" | "1M" | "6M" | "1Y" | "5Y" | "MAX";

interface Candle {
  timestamp: number;
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface CrosshairLegend {
  timeLabel: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  changePct: number;
}

const TIMEFRAMES: TimeframeKey[] = ["1m", "3m", "5m", "15m", "30m", "1h", "1d", "1wk"];
const RANGES: RangeKey[] = ["1D", "5D", "1M", "6M", "1Y", "5Y", "MAX"];

const DEFAULT_RANGE_FOR_TF: Record<TimeframeKey, RangeKey> = {
  "1m": "1D",
  "3m": "1D",
  "5m": "5D",
  "15m": "1M",
  "30m": "1M",
  "1h": "6M",
  "1d": "1Y",
  "1wk": "5Y",
};

const DEFAULT_TF_FOR_RANGE: Record<RangeKey, TimeframeKey> = {
  "1D": "1m",
  "5D": "5m",
  "1M": "15m",
  "6M": "1h",
  "1Y": "1d",
  "5Y": "1wk",
  "MAX": "1wk",
};

function formatIstAxisTick(time: Time, tickMarkType: TickMarkType): string {
  if (typeof time !== "number") return String(time);
  const date = new Date(time * 1000);
  if (tickMarkType === 0) {
    return new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", year: "numeric" }).format(date);
  }
  if (tickMarkType === 1) {
    return new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", month: "short" }).format(date);
  }
  if (tickMarkType === 2) {
    return new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" }).format(date);
  }
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatIstTime(unixSec: number, isLongTerm: boolean): string {
  const date = new Date(unixSec * 1000);
  if (isLongTerm) {
    return new Intl.DateTimeFormat("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      year: "2-digit",
    }).format(date);
  }
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function sanitizeBars(raw: Candle[]): Candle[] {
  const seen = new Set<number>();
  const sorted = [...raw]
    .filter((c) => c && Number.isFinite(c.timestamp) && c.open > 0 && c.close > 0)
    .sort((a, b) => a.timestamp - b.timestamp);

  const unique: Candle[] = [];
  for (const bar of sorted) {
    if (!seen.has(bar.timestamp)) {
      seen.add(bar.timestamp);
      unique.push(bar);
    }
  }
  return unique;
}

export function CenterChart({ marketState, isMaximized = false, onToggleMaximize }: CenterChartProps) {
  const [activeTab, setActiveTab] = useState<IndexTab>("NIFTY50");
  const [chartType, setChartType] = useState<"candle" | "area">("candle");
  const [timeframe, setTimeframe] = useState<TimeframeKey>("1m");
  const [range, setRange] = useState<RangeKey>("1D");
  const [showVWAP, setShowVWAP] = useState(true);
  const [showLevels, setShowLevels] = useState(true);
  const [autoScaleY, setAutoScaleY] = useState(true);

  const [candles, setCandles] = useState<Candle[]>([]);
  const [hovered, setHovered] = useState<CrosshairLegend | null>(null);
  const [loading, setLoading] = useState(false);
  const [feedSource, setFeedSource] = useState<string>("EXCHANGE");

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Area"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const shouldFitNextDataRef = useRef(true);
  const lastViewKeyRef = useRef("");

  const ind = marketState?.indices;
  const nifty = ind?.NIFTY50;
  const bank = ind?.BANKNIFTY;
  const vix = ind?.INDIAVIX;
  const prevOHLC = marketState?.prev_ohlc;

  const isLongTerm = timeframe === "1d" || timeframe === "1wk";

  const currentLTP = useMemo(() => {
    if (activeTab === "NIFTY50") return nifty?.ltp ?? 0;
    if (activeTab === "BANKNIFTY") return bank?.ltp ?? 0;
    return vix?.ltp ?? 0;
  }, [activeTab, nifty?.ltp, bank?.ltp, vix?.ltp]);

  const currentVWAP = activeTab === "NIFTY50" ? (nifty?.vwap ?? 0) : activeTab === "BANKNIFTY" ? (bank?.vwap ?? 0) : 0;
  const pdh = activeTab === "NIFTY50"
    ? (prevOHLC?.NIFTY50?.pdh ?? prevOHLC?.NIFTY50?.high ?? 0)
    : activeTab === "BANKNIFTY"
      ? (prevOHLC?.BANKNIFTY?.pdh ?? prevOHLC?.BANKNIFTY?.high ?? 0)
      : 0;
  const pdl = activeTab === "NIFTY50"
    ? (prevOHLC?.NIFTY50?.pdl ?? prevOHLC?.NIFTY50?.low ?? 0)
    : activeTab === "BANKNIFTY"
      ? (prevOHLC?.BANKNIFTY?.pdl ?? prevOHLC?.BANKNIFTY?.low ?? 0)
      : 0;

  const fetchCandles = useCallback(async (sym: IndexTab, tf: TimeframeKey, rng: RangeKey, isUserSwitch = false) => {
    if (isUserSwitch) setLoading(true);
    try {
      const res = await fetch(`${API_CONFIG.BASE_URL}/api/candles/${sym}?interval=${tf}&range=${rng}`);
      if (res.ok) {
        const json = await res.json();
        const cleaned = sanitizeBars(json.candles || []);
        setCandles(cleaned);
        setFeedSource((json.source || "EXCHANGE").toUpperCase());
      }
    } catch {
      // Preserve last rendered series on transient reconnect
    } finally {
      if (isUserSwitch) setLoading(false);
    }
  }, []);

  // Reload whenever symbol, timeframe, or range changes + auto-refresh active intraday views
  useEffect(() => {
    const viewKey = `${activeTab}|${timeframe}|${range}|${chartType}`;
    if (lastViewKeyRef.current !== viewKey) {
      shouldFitNextDataRef.current = true;
      lastViewKeyRef.current = viewKey;
    }

    const initTimer = setTimeout(() => {
      void fetchCandles(activeTab, timeframe, range, true);
    }, 0);

    const refreshMs = isLongTerm ? 120000 : 30000;
    const pollId = setInterval(() => {
      void fetchCandles(activeTab, timeframe, range, false);
    }, refreshMs);

    return () => {
      clearTimeout(initTimer);
      clearInterval(pollId);
    };
  }, [activeTab, timeframe, range, chartType, isLongTerm, fetchCandles]);

  // Initialize & clean up Lightweight Charts canvas cleanly
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "#0C101A" },
        textColor: "#94A3B8",
        fontSize: 10,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      },
      grid: {
        vertLines: { color: "#151E2E" },
        horzLines: { color: "#151E2E" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#334155", style: LineStyle.Dashed, labelBackgroundColor: "#0E7490" },
        horzLine: { color: "#334155", style: LineStyle.Dashed, labelBackgroundColor: "#0E7490" },
      },
      rightPriceScale: {
        borderColor: "#1E2638",
        autoScale: true,
        scaleMargins: { top: 0.1, bottom: 0.22 },
      },
      timeScale: {
        borderColor: "#1E2638",
        timeVisible: !isLongTerm,
        secondsVisible: false,
        rightOffset: 6,
        tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => formatIstAxisTick(time, tickMarkType),
      },
      localization: {
        timeFormatter: (t: Time) => (typeof t === "number" ? formatIstTime(t, isLongTerm) : String(t)),
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: {
          time: true,
          price: true,
        },
        axisDoubleClickReset: {
          time: true,
          price: true,
        },
      },
    });

    const mainSeries =
      chartType === "candle"
        ? chart.addSeries(CandlestickSeries, {
            upColor: "#10B981",
            downColor: "#F43F5E",
            borderUpColor: "#10B981",
            borderDownColor: "#F43F5E",
            wickUpColor: "#34D399",
            wickDownColor: "#FB7185",
          })
        : chart.addSeries(AreaSeries, {
            lineColor: "#06B6D4",
            lineWidth: 2,
            topColor: "rgba(6, 182, 212, 0.28)",
            bottomColor: "rgba(6, 182, 212, 0.02)",
          });

    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.84, bottom: 0 },
    });

    chartRef.current = chart;
    mainSeriesRef.current = mainSeries;
    volumeSeriesRef.current = volSeries;
    shouldFitNextDataRef.current = true;

    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries.length || !chartRef.current) return;
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) {
        chartRef.current.applyOptions({ width: Math.floor(width), height: Math.floor(height) });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      priceLinesRef.current = [];
      chart.remove();
      chartRef.current = null;
      mainSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [chartType, isLongTerm]);

  // Populate historical/intraday candle + volume data whenever fetched candles change
  useEffect(() => {
    const mainSeries = mainSeriesRef.current;
    const volSeries = volumeSeriesRef.current;
    const chart = chartRef.current;
    if (!mainSeries || !volSeries || !chart || candles.length === 0) return;

    if (chartType === "candle") {
      (mainSeries as ISeriesApi<"Candlestick">).setData(
        candles.map((c) => ({
          time: c.timestamp as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );
    } else {
      (mainSeries as ISeriesApi<"Area">).setData(
        candles.map((c) => ({
          time: c.timestamp as UTCTimestamp,
          value: c.close,
        }))
      );
    }

    volSeries.setData(
      candles.map((c) => ({
        time: c.timestamp as UTCTimestamp,
        value: c.volume || 0,
        color: c.close >= c.open ? "rgba(16, 185, 129, 0.35)" : "rgba(244, 63, 94, 0.35)",
      }))
    );

    if (shouldFitNextDataRef.current) {
      chart.timeScale().fitContent();
      shouldFitNextDataRef.current = false;
    }

    const barMap = new Map<number, Candle>();
    candles.forEach((c) => barMap.set(c.timestamp, c));

    const handleCrosshairMove = (param: { time?: Time }) => {
      if (!param.time || typeof param.time !== "number") {
        setHovered(null);
        return;
      }
      const bar = barMap.get(param.time);
      if (!bar) {
        setHovered(null);
        return;
      }
      const chgPct = bar.open > 0 ? ((bar.close - bar.open) / bar.open) * 100 : 0;
      setHovered({
        timeLabel: formatIstTime(bar.timestamp, isLongTerm),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        volume: bar.volume || 0,
        changePct: chgPct,
      });
    };

    chart.subscribeCrosshairMove(handleCrosshairMove);
    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
    };
  }, [candles, chartType, isLongTerm]);

  // Live tick overlay onto latest candle bar without resetting viewport zoom/pan
  useEffect(() => {
    const mainSeries = mainSeriesRef.current;
    if (!mainSeries || candles.length === 0 || currentLTP <= 0) return;
    const latest = candles[candles.length - 1];
    const t = latest.timestamp as UTCTimestamp;
    if (chartType === "candle") {
      (mainSeries as ISeriesApi<"Candlestick">).update({
        time: t,
        open: latest.open,
        high: Math.max(latest.high, currentLTP),
        low: Math.min(latest.low, currentLTP),
        close: currentLTP,
      });
    } else {
      (mainSeries as ISeriesApi<"Area">).update({
        time: t,
        value: currentLTP,
      });
    }
  }, [candles, currentLTP, chartType]);

  // Draw VWAP, PDH, and PDL dashed overlays cleanly
  useEffect(() => {
    const mainSeries = mainSeriesRef.current;
    if (!mainSeries) return;

    priceLinesRef.current.forEach((line) => {
      try {
        mainSeries.removePriceLine(line);
      } catch {
        // Ignore already removed lines
      }
    });
    priceLinesRef.current = [];

    if (showVWAP && !isLongTerm && currentVWAP > 0) {
      priceLinesRef.current.push(
        mainSeries.createPriceLine({
          price: currentVWAP,
          color: "#F59E0B",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "VWAP",
        })
      );
    }
    if (showLevels && pdh > 0) {
      priceLinesRef.current.push(
        mainSeries.createPriceLine({
          price: pdh,
          color: "#A855F7",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: "PDH",
        })
      );
    }
    if (showLevels && pdl > 0) {
      priceLinesRef.current.push(
        mainSeries.createPriceLine({
          price: pdl,
          color: "#A855F7",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: "PDL",
        })
      );
    }
  }, [showVWAP, showLevels, isLongTerm, currentVWAP, pdh, pdl, chartType, candles.length]);

  const handleSelectTimeframe = (tf: TimeframeKey) => {
    setTimeframe(tf);
    setRange(DEFAULT_RANGE_FOR_TF[tf]);
  };

  const handleSelectRange = (rng: RangeKey) => {
    setRange(rng);
    // Automatically step timeframe to match long-term/short-term horizon smoothly
    if ((rng === "1M" || rng === "6M" || rng === "1Y" || rng === "5Y" || rng === "MAX") && (timeframe === "1m" || timeframe === "3m" || timeframe === "5m")) {
      setTimeframe(DEFAULT_TF_FOR_RANGE[rng]);
    } else if (rng === "1D" && (timeframe === "1d" || timeframe === "1wk")) {
      setTimeframe("1m");
    } else if (rng === "5D" && (timeframe === "1d" || timeframe === "1wk")) {
      setTimeframe("5m");
    }
  };

  const latestBar = candles.length > 0 ? candles[candles.length - 1] : null;
  const displayLegend = hovered || (latestBar
    ? {
        timeLabel: formatIstTime(latestBar.timestamp, isLongTerm),
        open: latestBar.open,
        high: latestBar.high,
        low: latestBar.low,
        close: currentLTP > 0 ? currentLTP : latestBar.close,
        volume: latestBar.volume,
        changePct: latestBar.open > 0 ? (((currentLTP > 0 ? currentLTP : latestBar.close) - latestBar.open) / latestBar.open) * 100 : 0,
      }
    : null);

  const isAboveVwap = currentLTP > 0 && currentVWAP > 0 && currentLTP >= currentVWAP;

  return (
    <div className="flex flex-col bg-[#0C101A] border-b border-[#1E2638] h-full overflow-hidden select-none font-mono">
      {/* Top Toolbar: Indices + Timeframe + Range + Overlays */}
      <div className="min-h-9 px-3 py-1 bg-[#0A0E17] border-b border-[#1E2638] flex flex-wrap items-center justify-between gap-2 text-xs shrink-0">
        <div className="flex items-center gap-1 flex-wrap">
          <button
            onClick={() => setActiveTab("NIFTY50")}
            className={`px-2 py-1 rounded text-[11px] font-bold tracking-wider transition-colors ${
              activeTab === "NIFTY50"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            NIFTY 50 ({nifty?.ltp ? `₹${nifty.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"})
          </button>

          <button
            onClick={() => setActiveTab("BANKNIFTY")}
            className={`px-2 py-1 rounded text-[11px] font-bold tracking-wider transition-colors ${
              activeTab === "BANKNIFTY"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            BANK NIFTY ({bank?.ltp ? `₹${bank.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"})
          </button>

          <button
            onClick={() => setActiveTab("INDIAVIX")}
            className={`px-2 py-1 rounded text-[11px] font-bold tracking-wider transition-colors ${
              activeTab === "INDIAVIX"
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            VIX ({vix?.ltp ? vix.ltp.toFixed(2) : "—"})
          </button>
        </div>

        <div className="flex items-center flex-wrap gap-1.5">
          {/* Timeframe Selector */}
          <div className="flex items-center bg-[#131926] p-0.5 rounded border border-[#1E2638] text-[10px]">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => handleSelectTimeframe(tf)}
                className={`px-1.5 py-0.5 rounded transition-colors ${
                  timeframe === tf ? "bg-cyan-600 text-white font-bold" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {tf.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Horizon Range Presets */}
          <div className="flex items-center bg-[#131926] p-0.5 rounded border border-[#1E2638] text-[10px]">
            {RANGES.map((rng) => (
              <button
                key={rng}
                onClick={() => handleSelectRange(rng)}
                className={`px-1.5 py-0.5 rounded transition-colors ${
                  range === rng ? "bg-indigo-600 text-white font-bold" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {rng}
              </button>
            ))}
          </div>

          {!isLongTerm && activeTab !== "INDIAVIX" && (
            <button
              onClick={() => setShowVWAP(!showVWAP)}
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                showVWAP ? "bg-amber-500/20 text-amber-300 border-amber-500/40" : "text-slate-500 border-[#1E2638]"
              }`}
            >
              VWAP
            </button>
          )}

          {activeTab !== "INDIAVIX" && (
            <button
              onClick={() => setShowLevels(!showLevels)}
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                showLevels ? "bg-purple-500/20 text-purple-300 border-purple-500/40" : "text-slate-500 border-[#1E2638]"
              }`}
            >
              PDH/PDL
            </button>
          )}

          <button
            onClick={() => setChartType(chartType === "candle" ? "area" : "candle")}
            className="text-[10px] text-slate-300 hover:text-cyan-400 px-1.5 py-0.5 rounded bg-[#131926] border border-[#1E2638]"
          >
            {chartType === "candle" ? "CANDLES" : "AREA"}
          </button>

          <button
            onClick={() => {
              const nextAuto = !autoScaleY;
              setAutoScaleY(nextAuto);
              chartRef.current?.priceScale("right").applyOptions({ autoScale: nextAuto });
            }}
            className={`text-[10px] px-1.5 py-0.5 rounded border ${
              autoScaleY ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" : "text-slate-400 border-[#1E2638]"
            }`}
            title="Toggle Vertical Y-Axis Auto-Scale (or drag price axis directly)"
          >
            AUTO Y
          </button>

          <button
            onClick={() => {
              setAutoScaleY(true);
              chartRef.current?.priceScale("right").applyOptions({ autoScale: true });
              chartRef.current?.timeScale().fitContent();
            }}
            className="p-1 text-slate-400 hover:text-cyan-400 rounded"
            title="Reset horizontal & vertical chart scale"
          >
            <RotateCcw size={12} />
          </button>

          {onToggleMaximize && (
            <button
              onClick={onToggleMaximize}
              className={`p-1 rounded transition-colors ${isMaximized ? "text-cyan-400 bg-cyan-500/15" : "text-slate-400 hover:text-cyan-400"}`}
              title={isMaximized ? "Restore split IDE layout" : "Maximize chart panel"}
            >
              {isMaximized ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
            </button>
          )}

          <button
            onClick={() => void fetchCandles(activeTab, timeframe, range, true)}
            className="p-1 text-slate-400 hover:text-cyan-400 rounded"
            title="Reload OHLC data"
          >
            <RefreshCw size={12} className={loading ? "animate-spin text-cyan-400" : ""} />
          </button>
        </div>
      </div>

      {/* Live OHLCV Crosshair Readout Bar */}
      <div className="px-3 py-1 bg-[#0B0F18] border-b border-[#161E2E] flex flex-wrap items-center justify-between gap-2 text-[10px] shrink-0">
        {displayLegend ? (
          <div className="flex flex-wrap items-center gap-3 text-slate-300">
            <span className="text-cyan-400 font-bold">{displayLegend.timeLabel} IST</span>
            <span>O: <b className="text-white">{displayLegend.open.toFixed(2)}</b></span>
            <span>H: <b className="text-emerald-400">{displayLegend.high.toFixed(2)}</b></span>
            <span>L: <b className="text-rose-400">{displayLegend.low.toFixed(2)}</b></span>
            <span>
              C: <b className={displayLegend.changePct >= 0 ? "text-emerald-400" : "text-rose-400"}>{displayLegend.close.toFixed(2)}</b>
              {" "}({displayLegend.changePct >= 0 ? "+" : ""}{displayLegend.changePct.toFixed(2)}%)
            </span>
            {displayLegend.volume > 0 && (
              <span>VOL: <b className="text-slate-200">{displayLegend.volume.toLocaleString("en-IN")}</b></span>
            )}
          </div>
        ) : (
          <span className="text-slate-500">Hover chart to inspect OHLCV bars • Scroll to zoom • Drag to pan</span>
        )}

        {activeTab !== "INDIAVIX" && currentVWAP > 0 && !isLongTerm && (
          <div className="flex items-center gap-2">
            <span className="text-amber-300">VWAP: {currentVWAP.toFixed(2)}</span>
            <span className={`font-bold ${isAboveVwap ? "text-emerald-400" : "text-rose-400"}`}>
              ({isAboveVwap ? "+" : ""}{(currentLTP - currentVWAP).toFixed(1)} pts)
            </span>
          </div>
        )}
      </div>

      {/* Lightweight Charts Canvas Container */}
      <div className="relative flex-1 w-full min-h-[140px] overflow-hidden bg-[#0C101A]">
        <div ref={containerRef} className="w-full h-full" />
        {(candles.length === 0 || loading) && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0C101A]/75 text-slate-400 text-xs pointer-events-none">
            {loading ? `Loading ${activeTab} ${timeframe.toUpperCase()} (${range}) real exchange bars...` : `Waiting for ${activeTab} candles...`}
          </div>
        )}
      </div>

      {/* Footer Info Strip */}
      <div className="h-6 px-3 bg-[#090D15] border-t border-[#182030] flex items-center justify-between text-[10px] text-slate-400 shrink-0">
        <div className="flex items-center gap-3">
          <span>
            SOURCE: <span className="text-emerald-400 font-bold">{feedSource} ({candles.length} BARS • {timeframe.toUpperCase()} / {range})</span>
          </span>
          {pdh > 0 && <span>PDH: <span className="text-slate-200">{pdh.toFixed(1)}</span></span>}
          {pdl > 0 && <span>PDL: <span className="text-slate-200">{pdl.toFixed(1)}</span></span>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-cyan-400 font-bold">INTERACTIVE ZOOM &amp; PAN</span>
        </div>
      </div>
    </div>
  );
}
