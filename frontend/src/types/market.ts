export interface Position {
  entry_price?: number;
  avg_price?: number;
  qty?: number;
  net_qty?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  symbol?: string;
  current_ltp?: number;
  stop_loss?: number;
  take_profit?: number;
  trailing_sl?: number;
  lots?: number;
}

export interface LLMProviderStatus {
  configured: boolean;
  free_tier: boolean;
  model: string;
  status: string;
  last_error?: string | null;
  latency_ms?: number | null;
}

export interface LLMStatusSummary {
  healthy: boolean;
  configured_cloud_count: number;
  active_providers: string[];
  action_required?: string | null;
  transient_warning?: string | null;
  providers?: Record<string, LLMProviderStatus>;
  updated_at?: number;
}

export interface FactorAuditItem {
  id?: number;
  factor_id?: number;
  name: string;
  category?: string;
  value: string | number | null;
  status: "AVAILABLE" | "SUPPORTING" | "CONFLICTING" | "NEUTRAL" | "WARNING" | "UNAVAILABLE";
  evidence?: "BULLISH" | "BEARISH" | "NEUTRAL" | "MISSING";
  critical?: boolean;
  weight?: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  analysis?: string;
  decision_impact?: "SUPPORTS" | "CONFLICTS" | "NEUTRAL" | "RISK" | "UNKNOWN";
}

export interface FactorAuditSummary {
  total_factors_required?: number;
  total_factors_evaluated?: number;
  available_count?: number;
  supporting_count?: number;
  bullish_count?: number;
  bearish_count?: number;
  conflicting_count?: number;
  warning_count?: number;
  neutral_count?: number;
  unavailable_count?: number;
  critical_failures?: string[] | number;
  net_alignment_pct?: number;
  win_probability?: number | null;
}

export interface LLMDecisionContract {
  decision_id?: string;
  timestamp?: string;
  instrument?: string;
  timeframe?: string;
  action?: string;
  direction?: string;
  setup?: string;
  symbol?: string | null;
  lots?: number;
  confidence?: number;
  provider?: string;
  factor_audit?: {
    summary_metrics?: FactorAuditSummary;
    factors?: FactorAuditItem[];
  };
  reason?: string;
  risk_controls?: {
    data_quality_passed?: boolean;
    critical_checks_passed?: boolean;
    daily_loss_limit_passed?: boolean;
    position_size_validated?: boolean;
    broker_state_reconciled?: boolean;
    execution_authorized?: boolean;
    max_lots_permitted?: number;
    min_confidence_required?: number;
  };
}

export interface OptionContractData {
  ltp: number;
  volume: number;
  delta_volume?: number;
  oi: number;
  delta_oi?: number;
  iv?: number;
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  rho?: number;
  bid?: number;
  ask?: number;
  tbq?: number;
  tsq?: number;
  bid_ask_spread?: number;
}

export interface HeavyweightData {
  ltp: number;
  close?: number;
  day_change?: number;
  day_change_pct?: number;
  volume: number;
  delta_volume?: number;
  imbalance: number;
  delta_ltp_1m?: number;
  source?: string;
}

export interface NewsItemData {
  title?: string;
  headline?: string;
  summary?: string;
  link?: string;
  date?: string;
  source?: string;
  sentiment?: "BULLISH" | "BEARISH" | "NEUTRAL" | "POSITIVE" | "NEGATIVE";
}

export interface MultiDaySessionData {
  date: string;
  regime: string;
  nifty_open?: number;
  nifty_high?: number;
  nifty_low?: number;
  nifty_close?: number;
  banknifty_high?: number;
  banknifty_low?: number;
  banknifty_close?: number;
  fii_net_crores?: number | null;
  dii_net_crores?: number | null;
  oi_insight?: string;
  session_lesson?: string;
}

export interface MultiDayMemoryData {
  rolling_window?: string;
  structural_bias?: string;
  anchors?: {
    nifty_3d_high?: number | null;
    nifty_3d_low?: number | null;
    nifty_weekly_vwap?: number | null;
    banknifty_3d_high?: number | null;
    banknifty_3d_low?: number | null;
    banknifty_weekly_vwap?: number | null;
    fii_3d_net_crores?: number | null;
    fii_index_futures_long_pct?: number | null;
    weekly_expiry_oi_walls?: {
      NIFTY_CALL_WALL?: number;
      NIFTY_PUT_WALL?: number;
      BANKNIFTY_CALL_WALL?: number;
      BANKNIFTY_PUT_WALL?: number;
    };
  };
  prior_sessions?: MultiDaySessionData[];
  engine_experience?: {
    recent_trades_count?: number;
    wins?: number;
    losses?: number;
    win_rate?: string;
    realized_pnl_inr?: number;
    realized_pnl?: number;
    key_lesson?: string;
  };
}

export interface QuantRAGPrecedent {
  regime_id: string;
  name: string;
  similarity_pct: number;
  market_phase: string;
  empirical_win_rate: string;
  historical_outcome: string;
  lesson_learned: string;
  quant_directive: string;
}

export interface QuantRAGContext {
  matched_archetype: string;
  similarity_score: number;
  regimes: QuantRAGPrecedent[];
  key_risk_warning: string;
  quant_directive: string;
}

export interface MarketStateData {
  market_time?: string;
  timestamp?: number;
  is_market_open?: boolean;
  analysis_window?: string | null;
  data_sources?: {
    redis_connected?: boolean;
    upstox_ws?: { connected?: boolean; token_valid?: boolean; reason?: string; instruments?: number };
    live_poller?: string;
    last_poll_ts?: number;
    nifty_source?: string;
    vix_source?: string;
    llm_status?: LLMStatusSummary;
  };
  multi_day_memory?: MultiDayMemoryData;
  quant_rag_context?: QuantRAGContext;
  indices?: {
    NIFTY50?: {
      ltp: number;
      open?: number;
      high?: number;
      low?: number;
      prev_close?: number;
      day_change?: number;
      day_change_pct?: number;
      volume: number;
      delta_volume?: number;
      vwap: number;
      futures_ltp?: number;
      futures_premium?: number;
      delta_price_1m?: number;
      dist_to_vwap?: number;
      delta_dist_to_vwap?: number;
      source?: string;
    };
    BANKNIFTY?: {
      ltp: number;
      open?: number;
      high?: number;
      low?: number;
      prev_close?: number;
      day_change?: number;
      day_change_pct?: number;
      volume: number;
      delta_volume?: number;
      vwap: number;
      futures_ltp?: number;
      futures_premium?: number;
      delta_price_1m?: number;
      dist_to_vwap?: number;
      source?: string;
    };
    NIFTYIT?: {
      ltp: number;
      prev_close?: number;
      day_change?: number;
      day_change_pct?: number;
      volume?: number;
      delta_volume?: number;
      delta_price_1m?: number;
      source?: string;
    };
    INDIAVIX?: {
      ltp: number;
      prev_close?: number;
      delta_vix?: number;
      delta_vix_1m?: number;
      pct_change?: number;
      open?: number;
      high?: number;
      low?: number;
      source?: string;
    };
  };
  orderflow?: {
    NIFTY_PCR: number;
    BANKNIFTY_PCR: number;
    NIFTY_CVD: number;
    delta_nifty_cvd_1m?: number;
    BANKNIFTY_CVD: number;
    delta_banknifty_cvd_1m?: number;
    AD_RATIO: number;
    AD_ADVANCES?: number;
    AD_DECLINES?: number;
  };
  options_data?: {
    NIFTY_GEX: number;
    NIFTY_MAXPAIN: number;
    BANKNIFTY_GEX: number;
    BANKNIFTY_MAXPAIN: number;
    chain?: {
      NIFTY?: Record<string, OptionContractData>;
      BANKNIFTY?: Record<string, OptionContractData>;
    };
  };
  heavyweights?: Record<string, HeavyweightData>;
  macro?: Record<string, number | null>;
  institutional?: {
    fii_net_crores?: number | null;
    dii_net_crores?: number | null;
    fii_cash?: number | null;
    dii_cash?: number | null;
    fii_index_futures?: number | null;
    date?: string | null;
  };
  prev_ohlc?: Record<
    string,
    { open?: number; high?: number; low?: number; close?: number; pdh?: number; pdl?: number; pdc?: number; pivot?: number; r1?: number; s1?: number }
  >;
  breaking_news?: Array<NewsItemData | string>;
  indian_news?: Array<NewsItemData | string>;
  portfolio?: Record<string, Position>;
}

export interface ExecutionStateSummary {
  mode?: string;
  is_halted?: boolean;
  realized_pnl_today?: number;
  unrealized_pnl?: number;
  capital_available?: number;
  trades_executed_today?: number;
  max_daily_trades?: number;
  cooldown_remaining_seconds?: number;
  updated_at?: number;
}

export interface TradeLogRow {
  id?: number;
  timestamp: string;
  symbol: string;
  action: string;
  qty: number;
  price: number;
  confidence: number;
  pnl: number;
  fund_balance?: number;
  current_ltp?: number | null;
  mode: string;
  reason?: string;
}

export interface RoundTripTrade {
  id: string;
  status: "CLOSED" | "OPEN";
  side: string;
  mode: string;
  symbol: string;
  qty: number;
  entry_time?: string | null;
  entry_price?: number | null;
  exit_time?: string | null;
  exit_price?: number | null;
  hold_seconds?: number | null;
  current_ltp?: number | null;
  gross_pnl: number;
  brokerage: number;
  net_pnl: number;
  if_held_pnl?: number | null;
  fund_after?: number;
  confidence?: number;
  entry_reason?: string | null;
  exit_reason?: string | null;
}

export interface DashboardWebSocketPayload {
  status: string;
  market_state: MarketStateData;
  positions: Record<string, Position>;
  last_signal?: {
    action?: string;
    symbol?: string;
    confidence?: number;
    reason?: string;
    qty?: number;
    lots?: number;
  };
  last_decision?: LLMDecisionContract;
  trading_mode?: string;
  paper_funds?: number;
  execution_state?: ExecutionStateSummary;
}

export interface DimensionHealthItem {
  id: number;
  category: "A" | "B" | "C" | "D" | "E";
  categoryName: string;
  name: string;
  keyPath: string;
  status: "OK" | "WARNING" | "FAIL";
  valueFormatted: string;
  latencyMs: number;
  source: string;
  message: string;
}
