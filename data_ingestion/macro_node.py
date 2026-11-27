import asyncio
import logging
import time
import feedparser
import httpx
from bs4 import BeautifulSoup
from core.redis_client import redis_db
from core.config import settings

logger = logging.getLogger(__name__)


class MacroDataNode:
    """
    Polls contextual macro data (DXY, Brent Crude, US 10Y Yield, USD/INR, GIFT Nifty),
    FII/DII institutional flows (NSE India API + NSDL), and Live News (ET RSS + NewsAPI).
    Runs synchronous network libraries in worker threads so the asyncio event loop never stalls.
    """

    def __init__(self):
        self.is_running = False
        self.polling_interval = 120  # Refresh every 2 minutes for real-time global macro accuracy

        self.tickers = {
            "DXY": "DX-Y.NYB",
            "CRUDE": "BZ=F",     # Brent Crude Oil benchmark
            "BOND_10Y": "^TNX",  # US 10Y Treasury Yield
            "USDINR": "USDINR=X",
        }

        self.rss_url = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"

    def _fetch_yahoo_sync(self) -> dict:
        import yfinance as yf
        data = {}
        for name, symbol in self.tickers.items():
            try:
                hist = yf.Ticker(symbol).history(period="5d")
                if not hist.empty:
                    last_close = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last_close
                    data[name] = round(last_close, 2)
                    data[f"{name}_prev"] = round(prev_close, 2)
                    data[f"{name}_change"] = round(last_close - prev_close, 2)
            except Exception as e:
                logger.warning(f"Yahoo Finance failed for {name} ({symbol}): {e}")
                data[name] = None
        return data

    async def fetch_yahoo_data(self) -> dict:
        """Non-blocking wrapper around Yahoo Finance macro download."""
        return await asyncio.to_thread(self._fetch_yahoo_sync)

    async def fetch_alphavantage_fallback(self) -> dict:
        """Fallback to AlphaVantage if Yahoo Finance fails."""
        if not settings.ALPHA_VANTAGE_API_KEY:
            return {}

        data = {}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                url = f"https://www.alphavantage.co/query?function=TREASURY_YIELD&interval=daily&apikey={settings.ALPHA_VANTAGE_API_KEY}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    j = resp.json()
                    if j.get("data"):
                        data["BOND_10Y"] = round(float(j["data"][0]["value"]), 2)

                url_crude = f"https://www.alphavantage.co/query?function=BRENT&interval=daily&apikey={settings.ALPHA_VANTAGE_API_KEY}"
                resp_c = await client.get(url_crude)
                if resp_c.status_code == 200:
                    j_c = resp_c.json()
                    if j_c.get("data"):
                        data["CRUDE"] = round(float(j_c["data"][0]["value"]), 2)
        except Exception as e:
            logger.error(f"AlphaVantage fallback failed: {e}")

        return data

    def _fetch_gift_nifty_sync(self) -> dict:
        """Fetches live GIFT Nifty from Moneycontrol Global Indices feed."""
        try:
            from curl_cffi import requests as creq
            url = "https://priceapi.moneycontrol.com/technicalCompanyData/globalMarket/getGlobalIndicesListingData?view=overview&deviceType=W"
            resp = creq.get(url, impersonate="chrome", timeout=6)
            if resp.status_code == 200:
                data_list = resp.json().get("dataList", [])
                for sec in data_list:
                    for row in sec.get("data", []):
                        if len(row) >= 5 and ("GIFT NIFTY" in str(row[1]).upper() or row[0] == "in;gsx"):
                            price = float(str(row[2]).replace(",", ""))
                            net_chg = float(str(row[3]).replace(",", ""))
                            pct_chg = float(str(row[4]).replace(",", ""))
                            return {
                                "price": price,
                                "change": net_chg,
                                "pct_change": pct_chg,
                                "state": row[23] if len(row) > 23 else "",
                                "source": "moneycontrol_gift_nifty",
                            }
        except Exception as e:
            logger.debug(f"Moneycontrol GIFT Nifty probe failed: {e}")
        return {}

    async def fetch_upstox_gift_nifty(self):
        """Fetch real-time GIFT Nifty from Upstox REST API (when authenticated) or Moneycontrol fallback."""
        if settings.UPSTOX_ACCESS_TOKEN:
            url = "https://api.upstox.com/v2/market-quote/quotes"
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {settings.UPSTOX_ACCESS_TOKEN}",
            }
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(url, headers=headers, params={"instrument_key": "GLOBAL_INDEX|SGX NIFTY"})
                    if resp.status_code == 200:
                        data = resp.json().get("data", {})
                        if "GLOBAL_INDEX:SGX NIFTY" in data:
                            item = data["GLOBAL_INDEX:SGX NIFTY"]
                            lp = item.get("last_price")
                            if lp:
                                lp_f = float(lp)
                                prev_c = float((item.get("ohlc") or {}).get("close") or 0.0)
                                net_chg = float(item.get("net_change") or (lp_f - prev_c if prev_c > 0 else 0.0))
                                pct_chg = round((net_chg / prev_c) * 100.0, 2) if prev_c > 0 else 0.0
                                if net_chg == 0.0:
                                    # Enrich change from Moneycontrol GIFT Nifty if Upstox quote omits net_change
                                    mc = await asyncio.to_thread(self._fetch_gift_nifty_sync)
                                    if mc.get("change"):
                                        net_chg = float(mc["change"])
                                        pct_chg = float(mc.get("pct_change") or 0.0)
                                return {"price": lp_f, "change": round(net_chg, 2), "pct_change": pct_chg, "source": "upstox"}
            except Exception:
                pass

        return await asyncio.to_thread(self._fetch_gift_nifty_sync)

    def _fetch_rss_sync(self) -> list:
        try:
            feed = feedparser.parse(self.rss_url)
            return [
                {
                    "title": entry.title,
                    "headline": entry.title,
                    "summary": entry.get("summary", ""),
                    "link": entry.get("link", ""),
                    "date": entry.get("published", ""),
                    "source": "ET Markets",
                }
                for entry in feed.entries[:10]
            ]
        except Exception as e:
            logger.error(f"RSS Feed failed: {e}")
            return []

    async def fetch_news(self) -> dict:
        """Fetch live news from Economic Times RSS and optional NewsAPI."""
        indian_markets = await asyncio.to_thread(self._fetch_rss_sync)
        global_breaking = []

        if settings.NEWS_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    url = f"https://newsapi.org/v2/top-headlines?category=business&apiKey={settings.NEWS_API_KEY}"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        articles = resp.json().get("articles", [])
                        global_breaking = [
                            {
                                "title": a["title"],
                                "headline": a["title"],
                                "summary": a.get("description", ""),
                                "link": a.get("url", ""),
                                "date": a.get("publishedAt", ""),
                                "source": a.get("source", {}).get("name", "NewsAPI"),
                            }
                            for a in articles[:10]
                        ]
            except Exception as e:
                logger.error(f"NewsAPI failed: {e}")

        # Expose Indian market headlines in global feed only if NewsAPI key absent so UI always shows live headlines
        return {"indian_markets": indian_markets, "global_breaking": global_breaking}

    def _fetch_nse_fii_dii_sync(self) -> dict:
        """Fetches real FII/DII data from NSE fiidiiTradeReact using curl_cffi Chrome session."""
        fii_dii_data = {
            "fii_cash": None,
            "dii_cash": None,
            "fii_net_crores": None,
            "dii_net_crores": None,
            "fii_index_futures": None,
            "date": None,
        }
        try:
            from curl_cffi import requests as creq
            s = creq.Session(impersonate="chrome")
            s.get("https://www.nseindia.com/option-chain", timeout=8)
            resp = s.get(
                "https://www.nseindia.com/api/fiidiiTradeReact",
                headers={"Referer": "https://www.nseindia.com/"},
                timeout=8,
            )
            if resp.status_code == 200:
                for item in resp.json():
                    cat = str(item.get("category", "")).upper()
                    net_val = str(item.get("netValue", "0")).replace(",", "")
                    fii_dii_data["date"] = item.get("date")
                    try:
                        val = round(float(net_val), 2)
                    except Exception:
                        val = 0.0
                    if "DII" in cat:
                        fii_dii_data["dii_cash"] = val
                        fii_dii_data["dii_net_crores"] = val
                    elif "FII" in cat or "FPI" in cat:
                        fii_dii_data["fii_cash"] = val
                        fii_dii_data["fii_net_crores"] = val
        except Exception as e:
            logger.error(f"NSE FII/DII fetch error: {e}")

        # Optional NSDL FPI Derivatives Index Futures
        try:
            from curl_cffi import requests as creq
            resp_nsdl = creq.get("https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx", impersonate="chrome", timeout=8)
            if resp_nsdl.status_code == 200:
                soup = BeautifulSoup(resp_nsdl.text, "html.parser")
                tables = soup.find_all("table")
                if len(tables) > 1:
                    for row in tables[1].find_all("tr"):
                        cols = [c.text.strip() for c in row.find_all(["th", "td"])]
                        if len(cols) >= 8 and "Index Futures" in cols:
                            try:
                                buy_amt = float(cols[3].replace(",", ""))
                                sell_amt = float(cols[5].replace(",", ""))
                                fii_dii_data["fii_index_futures"] = round(buy_amt - sell_amt, 2)
                            except Exception:
                                pass
        except Exception as e:
            logger.debug(f"NSDL FPI Derivatives fetch skipped: {e}")

        return fii_dii_data

    async def fetch_fii_dii_data(self) -> dict:
        return await asyncio.to_thread(self._fetch_nse_fii_dii_sync)

    async def poll_once(self):
        """Runs a single full refresh of Macros, GIFT Nifty, News, and FII/DII."""
        macro_data = await self.fetch_yahoo_data()
        if not macro_data.get("DXY") or not macro_data.get("CRUDE"):
            av = await self.fetch_alphavantage_fallback()
            for k, v in av.items():
                if not macro_data.get(k) and v is not None:
                    macro_data[k] = v

        gift = await self.fetch_upstox_gift_nifty()
        if gift and gift.get("price"):
            macro_data["GIFT_NIFTY"] = gift["price"]
            macro_data["GIFT_NIFTY_change"] = gift.get("change", 0.0)
            macro_data["GIFT_NIFTY_pct"] = gift.get("pct_change", 0.0)

        news_data = await self.fetch_news()
        fii_dii_data = await self.fetch_fii_dii_data()

        full_macro_state = {
            "markets": macro_data,
            "news": news_data,
            "timestamp": time.time(),
            "source": "yahoo_moneycontrol_rss",
        }

        await redis_db.set_json("FII_DII_DATA", fii_dii_data)
        await redis_db.set_json("MACRO_STATE", full_macro_state)
        logger.info(
            f"Macro Updated: GIFT={macro_data.get('GIFT_NIFTY')}, DXY={macro_data.get('DXY')}, "
            f"Brent={macro_data.get('CRUDE')}, US10Y={macro_data.get('BOND_10Y')}, "
            f"FII={fii_dii_data.get('fii_net_crores')}"
        )

    async def run(self):
        """Polls on startup and every 2 minutes thereafter."""
        self.is_running = True
        logger.info("Macro Data Node started (2-minute polling).")

        while self.is_running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"Macro Node Failure: {e}")

            await asyncio.sleep(self.polling_interval)

    async def stop(self):
        self.is_running = False
        logger.info("Macro Data Node stopped.")
