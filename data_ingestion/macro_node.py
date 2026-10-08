import asyncio
import logging
import time
import yfinance as yf
import feedparser
import httpx
from bs4 import BeautifulSoup
from core.redis_client import redis_db
from core.config import settings

logger = logging.getLogger(__name__)

class MacroDataNode:
    """
    Polls contextual macro data (DXY, Crude, 10Y Yield, GIFT Nifty) and Live News (RSS + NewsAPI).
    Uses Yahoo Finance as primary, falls back to AlphaVantage API.
    """
    def __init__(self):
        self.is_running = False
        self.polling_interval = 300 # 5 minutes (as per PRD)
        
        # Tickers for Yahoo Finance
        self.tickers = {
            "DXY": "DX-Y.NYB",
            "CRUDE": "CL=F",
            "BOND_10Y": "^TNX"
        }
        
        self.rss_url = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"

    async def fetch_yahoo_data(self):
        """Fetch data from Yahoo Finance."""
        data = {}
        for name, symbol in self.tickers.items():
            try:
                # In real prod, this runs in a thread pool to prevent blocking asyncio
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1d")
                if not hist.empty:
                    data[name] = hist['Close'].iloc[-1]
            except Exception as e:
                logger.warning(f"Yahoo Finance failed for {name}: {e}")
                data[name] = None
        return data

    async def fetch_alphavantage_fallback(self):
        """Fallback to AlphaVantage if Yahoo fails."""
        logger.warning("Using AlphaVantage Fallback for Macro Data.")
        if not settings.ALPHA_VANTAGE_API_KEY:
             logger.error("ALPHA_VANTAGE_API_KEY missing from .env!")
             return {}
             
        data = {}
        try:
            async with httpx.AsyncClient() as client:
                # Fetch DXY equivalent or other macro indicators from AlphaVantage
                url = f"https://www.alphavantage.co/query?function=TREASURY_YIELD&interval=daily&apikey={settings.ALPHA_VANTAGE_API_KEY}"
                response = await client.get(url, timeout=5.0)
                if response.status_code == 200:
                    json_data = response.json()
                    # Example parsing of the last available yield
                    if "data" in json_data and len(json_data["data"]) > 0:
                        data["BOND_10Y"] = float(json_data["data"][0]["value"])
                        
                # Add Crude Oil
                url_crude = f"https://www.alphavantage.co/query?function=WTI&interval=daily&apikey={settings.ALPHA_VANTAGE_API_KEY}"
                response_crude = await client.get(url_crude, timeout=5.0)
                if response_crude.status_code == 200:
                    json_data = response_crude.json()
                    if "data" in json_data and len(json_data["data"]) > 0:
                        data["CRUDE"] = float(json_data["data"][0]["value"])
                        
        except Exception as e:
            logger.error(f"AlphaVantage API failed: {e}")
            
        return data

    async def fetch_news(self):
        """Fetch live news from RSS and NewsAPI (Section 6 of DATA_SOURCES)."""
        news_data = {"indian_markets": [], "global_breaking": []}
        
        # 1. Indian Markets RSS
        try:
            feed = feedparser.parse(self.rss_url)
            # Send title, summary, and link to the AI engine & frontend
            news_data["indian_markets"] = [
                {"title": entry.title, "summary": entry.get("summary", ""), "link": entry.get("link", ""), "date": entry.get("published", "")}
                for entry in feed.entries[:10]
            ]
        except Exception as e:
            logger.error(f"RSS Feed failed: {e}")
            
        # 2. Global Breaking (NewsAPI)
        if settings.NEWS_API_KEY:
            try:
                async with httpx.AsyncClient() as client:
                    url = f"https://newsapi.org/v2/top-headlines?category=business&apiKey={settings.NEWS_API_KEY}"
                    response = await client.get(url, timeout=5.0)
                    if response.status_code == 200:
                        articles = response.json().get("articles", [])
                        news_data["global_breaking"] = [
                            {"title": a["title"], "summary": a.get("description", ""), "link": a.get("url", ""), "date": a.get("publishedAt", "")} 
                            for a in articles[:10]
                        ]
            except Exception as e:
                logger.error(f"NewsAPI failed: {e}")
                
        return news_data

    async def fetch_fii_dii_data(self):
        """Scrape latest FII/DII data from NSE India API and NSDL for FPI Derivatives."""
        fii_dii_data = {"fii_cash": None, "dii_cash": None, "fii_index_futures": None}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        try:
            async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
                # 1. Fetch Cash data from NSE
                await client.get('https://www.nseindia.com')
                url = 'https://www.nseindia.com/api/fiidiiTradeReact'
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data:
                        cat = item.get("category", "")
                        net_val = item.get("netValue", "0")
                        try:
                            val = float(net_val.replace(',', ''))
                        except:
                            val = 0.0
                            
                        if cat == "DII":
                            fii_dii_data["dii_cash"] = val
                        elif cat == "FII/FPI":
                            fii_dii_data["fii_cash"] = val
                else:
                    logger.warning(f"NSE FII/DII API returned status: {resp.status_code}")

                # 2. Fetch Index Futures from NSDL
                nsdl_url = 'https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx'
                resp_nsdl = await client.get(nsdl_url)
                if resp_nsdl.status_code == 200:
                    soup = BeautifulSoup(resp_nsdl.text, 'html.parser')
                    tables = soup.find_all('table')
                    if len(tables) > 1:
                        derivatives_table = tables[1]
                        rows = derivatives_table.find_all('tr')
                        for row in rows:
                            cols = [c.text.strip() for c in row.find_all(['th', 'td'])]
                            if len(cols) >= 8 and 'Index Futures' in cols:
                                try:
                                    buy_amt = float(cols[3].replace(',', ''))
                                    sell_amt = float(cols[5].replace(',', ''))
                                    net_amt = buy_amt - sell_amt
                                    fii_dii_data["fii_index_futures"] = net_amt
                                except:
                                    pass
        except Exception as e:
            logger.error(f"Failed to fetch FII/DII data: {e}")
            
        return fii_dii_data

    async def fetch_upstox_gift_nifty(self):
        """Fetch real-time GIFT Nifty data via Upstox REST API."""
        if not settings.UPSTOX_ACCESS_TOKEN:
             return None
        url = "https://api.upstox.com/v2/market-quote/quotes"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {settings.UPSTOX_ACCESS_TOKEN}'
        }
        params = {'instrument_key': 'GLOBAL_INDEX|SGX NIFTY'}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, params=params, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json().get('data', {})
                    if 'GLOBAL_INDEX:SGX NIFTY' in data:
                        return data['GLOBAL_INDEX:SGX NIFTY'].get('last_price')
        except Exception as e:
            logger.error(f"Failed to fetch GIFT Nifty from Upstox: {e}")
        return None

    async def run(self):
        """Polls every 5 minutes and pushes to Redis."""
        self.is_running = True
        logger.info("Macro Data Node started (5-minute polling).")
        
        while self.is_running:
            try:
                # 1. Fetch Macros
                macro_data = await self.fetch_yahoo_data()
                if not macro_data.get("DXY"):
                    macro_data = await self.fetch_alphavantage_fallback()
                
                # Fetch Real GIFT Nifty from Upstox
                gift_nifty = await self.fetch_upstox_gift_nifty()
                if gift_nifty is not None:
                    macro_data["GIFT_NIFTY"] = gift_nifty
                else:
                    # Fallback to Yahoo if Upstox fails
                    macro_data["GIFT_NIFTY"] = macro_data.get("GIFT_NIFTY", None)
                
                # 2. Fetch News
                news_data = await self.fetch_news()
                
                # Combine State
                full_macro_state = {
                    "markets": macro_data,
                    "news": news_data,
                    "timestamp": time.time()
                }
                
                # Fetch FII/DII Data
                fii_dii_data = await self.fetch_fii_dii_data()
                await redis_db.set_json("FII_DII_DATA", fii_dii_data)
                
                # Push to Redis for the Slow Loop LLM to consume
                await redis_db.set_json("MACRO_STATE", full_macro_state)
                logger.info("Updated Macro, News & FII/DII State in Redis.")
                
            except Exception as e:
                logger.error(f"Macro Node Failure: {e}")
                
            await asyncio.sleep(self.polling_interval)

    async def stop(self):
        self.is_running = False
        logger.info("Macro Data Node stopped.")
