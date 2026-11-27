import asyncio
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, ".")

from core.redis_client import redis_db
from data_ingestion.daily_node import DailyDataNode
from data_ingestion.greeks_engine import GreeksEngine
from data_ingestion.eod_summarizer import EODSummarizer
from data_ingestion.live_market_poller import LiveMarketPoller
from data_ingestion.macro_node import MacroDataNode
from data_ingestion.orderflow_engine import OrderflowEngine
from data_ingestion.primary_node import PrimaryDataNode
from execution_engine.groww_router import GrowwRouter
from execution_engine.paper_trader import PaperTrader
from strategy_engine.llm_client import LLMClient
from strategy_engine.risk_manager import RiskManager
from strategy_engine.state_builder import StateBuilder


def run_offline_unit_checks():
    print("=== 1. OFFLINE UNIT CHECKS (Upstox V3, Greeks, PaperTrader, StateBuilder, Contract 1) ===")
    pnode = PrimaryDataNode()
    v3_tick = {
        "feeds": {
            "NSE_INDEX|India VIX": {
                "fullFeed": {
                    "indexFF": {
                        "ltpc": {"ltp": 16.81, "cp": 17.67},
                        "marketOHLC": {"ohlc": [{"interval": "1d", "open": 17.67, "high": 17.91, "low": 16.68, "close": 16.81}]},
                    }
                }
            },
            "NSE_INDEX|Nifty 50": {
                "fullFeed": {
                    "indexFF": {
                        "ltpc": {"ltp": 25884.50, "cp": 25819.25},
                        "marketOHLC": {"ohlc": [{"interval": "1d", "open": 25873.2, "high": 25974.95, "low": 25733.5, "close": 25884.5}]},
                    }
                }
            },
        }
    }
    asyncio.run(pnode.process_tick(v3_tick))

    async def verify_mem():
        vix = await redis_db.get_json("LTP:INDEX:INDIAVIX")
        n50 = await redis_db.get_json("LTP:INDEX:NIFTY50")
        assert vix and vix["ltp"] == 16.81 and vix["change"] == -0.86, f"Bad VIX tick: {vix}"
        assert n50 and n50["ltp"] == 25884.5 and n50["source"] == "upstox_ws", f"Bad N50 tick: {n50}"
        print(f"  Upstox V3 indexFF verified -> VIX={vix['ltp']} ({vix['change']}), NIFTY={n50['ltp']}")

        # PaperTrader L2 depth + normalized OPT symbol test
        await redis_db.set_json(
            "LTP:OPT:NIFTY:25700CE",
            {
                "ltp": 140.0,
                "bid": 139.5,
                "ask": 141.0,
                "bid_ask": {"depth": [{"bidP": 139.5, "bidQ": 650, "askP": 141.0, "askQ": 650}]},
            },
        )
        pt = PaperTrader()
        order_id, _ = await pt.place_order("NIFTY25700CE", 65, "BUY", "MKT")
        assert order_id and "PAPER_" in order_id, "PaperTrader failed to normalize OPT key / fill on askP"
        pos = pt.open_positions["NIFTY25700CE"]
        assert abs(pos["avg_price"] - 141.03) < 0.1, f"Expected ask slippage fill ~141.03, got {pos}"
        # Clamped over-sized SELL must close cleanly to 0 and never flip long position to SHORT
        close_id, _ = await pt.place_order("NIFTY25700CE", 195, "SELL", "MKT")
        assert close_id is not None and "NIFTY25700CE" not in pt.open_positions, "Over-sized SELL should clamp and close flat!"
        blocked_id, _ = await pt.place_order("NIFTY25700CE", 65, "SELL", "MKT")
        assert blocked_id is None, "Flat naked SELL must be blocked!"
        print(f"  PaperTrader L2 fill & long-only guard verified -> {order_id} @ ₹{pos['avg_price']}")

        # Heavyweight Upstox WS key fallback (change / pct_change -> day_change / day_change_pct)
        await redis_db.set_json(
            "LTP:EQ:RELIANCE",
            {"ltp": 1375.5, "close": 1396.2, "change": -20.7, "pct_change": -1.48, "volume": 1000000, "source": "upstox_ws"},
        )
        # StateBuilder rolling delta + Tripartite compression
        sb = StateBuilder()
        t_old = time.time() - 62.0
        sb._history_snapshots.append((
            t_old,
            {
                "indices": {
                    "NIFTY50": {"ltp": 25850.0, "volume": 100000, "dist_to_vwap": 10.0},
                    "BANKNIFTY": {"ltp": 63200.0, "volume": 50000, "dist_to_vwap": 5.0},
                    "NIFTYIT": {"ltp": 32900.0, "volume": 20000},
                    "INDIAVIX": {"ltp": 16.5},
                },
                "orderflow": {"NIFTY_CVD": 1000, "BANKNIFTY_CVD": -500},
                "heavyweights": {},
                "options_data": {"chain": {}},
            },
        ))
        state = await sb.build_market_state_dict()
        assert state["indices"]["NIFTY50"]["delta_price_1m"] == 34.5, f"Unexpected 1m delta: {state['indices']['NIFTY50']}"
        rel_hw = state.get("heavyweights", {}).get("RELIANCE", {})
        assert rel_hw.get("day_change_pct") == -1.48, f"Expected Upstox pct_change mapped to day_change_pct, got {rel_hw}"
        tri_str = sb.build_tripartite_llm_payload(state)
        tri = json.loads(tri_str)
        assert "part_a_previous_decision" in tri and "part_b_current_market_state" in tri and "part_c_current_execution_state" in tri
        print(f"  StateBuilder 1m delta & Upstox HW chg verified -> delta_price_1m=+{state['indices']['NIFTY50']['delta_price_1m']}, RELIANCE={rel_hw.get('day_change_pct')}%")

        # Quant RAG Trend-Down Recognition Check (must NOT misclassify -1.05% trend day as Midday Chop)
        rag_res = sb.rag_engine.search_similar_regimes({
            "indices": {
                "NIFTY50": {"ltp": 25620.0, "vwap": 25839.0, "day_change_pct": -1.05, "futures_premium": 114.0},
                "INDIAVIX": {"ltp": 16.5, "pct_change": -2.0},
            },
            "orderflow": {"NIFTY_CVD": -2500000, "NIFTY_PCR": 0.70, "AD_RATIO": 0.23},
            "options_data": {
                "NIFTY_GEX": 2.2e11,
                "NIFTY_MAXPAIN": 25700.0,
                "chain": {"NIFTY": {"25700CE": {"delta_oi": 1500000}, "25700PE": {"delta_oi": -900000}}},
            },
            "heavyweights": {
                "HDFCBANK": {"day_change_pct": -0.9, "imbalance": 0.9},
                "RELIANCE": {"day_change_pct": -1.4, "imbalance": 1.2},
                "INFY": {"day_change_pct": -2.3, "imbalance": 0.4},
                "TCS": {"day_change_pct": -2.1, "imbalance": 0.3},
            },
            "multi_day_memory": {"anchors": {"fii_index_futures_long_pct": 52.0}},
        })
        assert "Breakdown" in rag_res["matched_archetype"] or "Liquidation" in rag_res["matched_archetype"], f"RAG misclassified trend-down day: {rag_res}"
        print(f"  Quant RAG trend recognition verified -> {rag_res['matched_archetype']} ({rag_res['similarity_score']}%)")

        # LLMClient Contract 1 verification (blocks UNAVAILABLE/low-conf, authorizes clean >=78% Paper trend entry)
        lc = LLMClient()
        low_conf = lc._enforce_contract1({
            "action": "ENTER_CALL",
            "symbol": "OPT:NIFTY:25700CE",
            "lots": 2,
            "confidence": 70,
            "reason": "Early unconfirmed attempt",
            "factor_audit": {
                "factors": [
                    {"id": 1, "name": "Nifty Spot", "status": "UNAVAILABLE", "evidence": "MISSING", "critical": True},
                    {"id": 2, "name": "Futures", "status": "CONFLICTING", "evidence": "BEARISH", "critical": True},
                ]
            },
        })
        assert low_conf["action"] == "OBSERVE" and low_conf["risk_controls"]["execution_authorized"] is False
        assert low_conf["factor_audit"]["summary_metrics"]["critical_failures"] == 1
        assert len(low_conf["reason"]) > 20, "Reason should be preserved with audit note!"

        trend_ok = lc._enforce_contract1({
            "action": "ENTER_PUT",
            "symbol": "OPT:NIFTY:25600PE",
            "lots": 1,
            "confidence": 84,
            "reason": "Clean -1.05% breakdown below VWAP & PDL",
            "factor_audit": {
                "factors": [
                    {"id": 1, "name": "Nifty Spot", "status": "AVAILABLE", "evidence": "BEARISH", "critical": True},
                    {"id": 2, "name": "FII EOD", "status": "CONFLICTING", "evidence": "BULLISH", "critical": True},
                ]
            },
        })
        assert trend_ok["action"] == "ENTER_PUT" and trend_ok["risk_controls"]["execution_authorized"] is True
        print(f"  Contract 1 Python Guardrails verified -> low_conf={low_conf['action']}(False), trend={trend_ok['action']}(True)")

        # OrderflowEngine CVD reconnect/source-mismatch regression check
        oe = OrderflowEngine()
        await oe.process_tick({"symbol": "FUT:NIFTY:CURR", "ltp": 25700.0, "volume": 2700000, "source": "nse_official"})
        await oe.process_tick({"symbol": "FUT:NIFTY:CURR", "ltp": 25705.0, "volume": 2500000, "source": "upstox_ws"})
        cvd_after = await redis_db.get_json("METRIC:CVD:NIFTY50") or {"cvd": 0}
        assert abs(int(cvd_after.get("cvd", 0))) < 500000, f"CVD spiked on source switch: {cvd_after}"
        print(f"  OrderflowEngine CVD safety verified -> cvd={cvd_after.get('cvd')}")

        # Production RiskManager & PaperTrader restart-hydration / non-looping exit check (isolated temp SQLite)
        import core.database as db_mod
        import strategy_engine.episodic_memory as em_mod
        import strategy_engine.risk_manager as rm_mod

        orig_db = db_mod.DB_PATH
        tmp_dir = tempfile.mkdtemp(prefix="jini_test_")
        tmp_db = os.path.join(tmp_dir, "test_records.db")
        try:
            db_mod.DB_PATH = tmp_db
            rm_mod.DB_PATH = tmp_db
            em_mod.DB_PATH = tmp_db
            db_mod.init_db()

            await redis_db.set_json(
                "PAPER_POSITIONS",
                {"OPT:NIFTY:25700CE": {"net_qty": 65, "avg_price": 150.0, "realized_pnl": 0.0}},
            )
            rm = RiskManager(mode="PAPER")
            await rm.paper_trader.hydrate_from_redis()
            await rm.process_decision({"action": "SELL", "symbol": "OPT:NIFTY:25700CE", "qty": 65, "confidence": 100, "reason": "Unit Exit"})
            pos_after_exit = await redis_db.get_json("PAPER_POSITIONS") or {}
            assert "OPT:NIFTY:25700CE" not in pos_after_exit, f"Closed position lingered in Redis: {pos_after_exit}"
            # Re-sending SELL when flat MUST be a safe no-op (never open naked short or loop)
            count_before = len(rm.paper_trader.trade_log)
            await rm.process_decision({"action": "SELL", "symbol": "OPT:NIFTY:25700CE", "qty": 65, "confidence": 100, "reason": "Duplicate Exit"})
            assert len(rm.paper_trader.trade_log) == count_before, "Duplicate SELL executed when position already flat!"
        finally:
            db_mod.DB_PATH = orig_db
            rm_mod.DB_PATH = orig_db
            em_mod.DB_PATH = orig_db
            try:
                if os.path.exists(tmp_db):
                    os.remove(tmp_db)
                os.rmdir(tmp_dir)
            except Exception:
                pass
        gr = GrowwRouter()
        await gr.shutdown()
        assert EODSummarizer is not None
        print("  RiskManager non-looping exit, hydration, and GrowwRouter verified cleanly")

    asyncio.run(verify_mem())

    g = GreeksEngine()
    dte = g.compute_dte_from_date("01-Dec-2026")
    res = g.solve_greeks_sync("OPT:NIFTY:25900CE", 180.0, 25884.5, dte, 15.5)
    assert res.get("delta", 0) > 0.3 and res.get("vega", 0) > 0 and res.get("iv") == 15.5, f"Bad Greeks: {res}"
    print(f"  Vollib Greeks verified -> Delta={res['delta']}, Gamma={res['gamma']}, Theta={res['theta']}, Vega={res['vega']}, IV={res['iv']}%")


async def run_live_e2e_pipeline():
    print("\n=== 2. LIVE REAL-TIME E2E PIPELINE VERIFICATION ===")
    try:
        await asyncio.wait_for(redis_db.connect(), timeout=2.0)
        print(f"  Docker Redis Connected: {redis_db.is_connected}")
    except Exception as e:
        print(f"  Redis connection note: {e} (running on in-memory shim)")

    daily = DailyDataNode()
    greeks = GreeksEngine()
    poller = LiveMarketPoller(greeks_engine=greeks)
    macro = MacroDataNode()
    sb = StateBuilder()

    await daily.fetch_boot_data()
    await poller.poll_once()
    await macro.poll_once()

    state = await sb.build_market_state_dict()
    await redis_db.set_json("FULL_MARKET_STATE", state)

    ind = state.get("indices", {})
    n50 = ind.get("NIFTY50", {})
    bn = ind.get("BANKNIFTY", {})
    vix = ind.get("INDIAVIX", {})
    it = ind.get("NIFTYIT", {})
    fl = state.get("orderflow", {})
    opt = state.get("options_data", {})
    macro_d = state.get("macro", {})
    inst = state.get("institutional", {})
    candles = await redis_db.get_json("CHART:CANDLES:NIFTY50") or {}

    print(f"  NIFTY50:   ₹{n50.get('ltp')} | Fut ₹{n50.get('futures_ltp')} (Basis {n50.get('futures_premium')}) | VWAP ₹{n50.get('vwap')} | Src={n50.get('source')}")
    print(f"  BANKNIFTY: ₹{bn.get('ltp')} | Fut ₹{bn.get('futures_ltp')} (Basis {bn.get('futures_premium')}) | Chg={bn.get('day_change_pct')}%")
    print(f"  INDIA VIX: {vix.get('ltp')} (Δ {vix.get('delta_vix')}, {vix.get('pct_change')}%) | Src={vix.get('source')}")
    print(f"  NIFTY IT:  ₹{it.get('ltp')} ({it.get('day_change_pct')}%)")
    print(f"  ORDERFLOW: PCR={fl.get('NIFTY_PCR')} | AD={fl.get('AD_RATIO')} ({fl.get('AD_ADVANCES')}/{fl.get('AD_DECLINES')})")
    print(f"  OPTIONS:   Contracts={len(opt.get('chain', {}).get('NIFTY', {}))} | GEX={opt.get('NIFTY_GEX')} | MaxPain={opt.get('NIFTY_MAXPAIN')}")
    print(f"  HEAVYWTS:  Count={len(state.get('heavyweights', {}))} | HDFCBANK=₹{state.get('heavyweights', {}).get('HDFCBANK', {}).get('ltp')}")
    print(f"  MACRO:     GIFT={macro_d.get('GIFT_NIFTY')} | DXY={macro_d.get('DXY')} | Brent=${macro_d.get('CRUDE')} | US10Y={macro_d.get('BOND_10Y')}%")
    print(f"  INST/NEWS: FII=₹{inst.get('fii_net_crores')} Cr ({inst.get('date')}) | RSS={len(state.get('indian_news', []))}")
    print(f"  CANDLES:   NIFTY 1m bars={len(candles.get('candles', []))}")
    print(f"  MULTI-DAY: 3D High={state.get('multi_day_memory', {}).get('anchors', {}).get('nifty_3d_high')} | 3D Low={state.get('multi_day_memory', {}).get('anchors', {}).get('nifty_3d_low')}")

    assert n50.get("ltp", 0) > 23000, f"Unexpected stale NIFTY LTP: {n50.get('ltp')}"
    assert vix.get("ltp", 0) > 0, "India VIX missing!"
    assert len(opt.get("chain", {}).get("NIFTY", {})) > 10, "Option chain incomplete!"
    assert len(candles.get("candles", [])) > 10, "Real 1m candles missing!"

    # Verify long-term & multi-timeframe candle fetchers
    daily_1y = await asyncio.to_thread(poller._fetch_real_candles_sync, "NIFTY50", "1d", "1Y")
    weekly_5y = await asyncio.to_thread(poller._fetch_real_candles_sync, "BANKNIFTY", "1wk", "5Y")
    hourly_6m = await asyncio.to_thread(poller._fetch_real_candles_sync, "INDIAVIX", "1h", "6M")
    assert len(daily_1y) > 200, f"Expected >200 1d bars, got {len(daily_1y)}"
    assert len(weekly_5y) > 200, f"Expected >200 1wk bars, got {len(weekly_5y)}"
    assert len(hourly_6m) > 200, f"Expected >200 VIX 1h bars, got {len(hourly_6m)}"
    print(f"  LONG CANDLES: NIFTY 1d/1Y={len(daily_1y)} | BANK 1wk/5Y={len(weekly_5y)} | VIX 1h/6M={len(hourly_6m)}")

    await redis_db.close()
    print("\nALL LIVE PIPELINE ASSERTIONS PASSED!")


if __name__ == "__main__":
    if "--live" in sys.argv:
        asyncio.run(run_live_e2e_pipeline())
    else:
        run_offline_unit_checks()
