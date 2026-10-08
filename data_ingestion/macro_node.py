import asyncio
import logging
import time
import yfinance as yf
import feedparser
import httpx
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
            "BOND_10Y": "^TNX",
            "GIFT_NIFTY": "^NSEI" # Proxy for GIFT Nifty in YF
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
            news_data["indian_markets"] = [entry.title for entry in feed.entries[:3]]
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
                        news_data["global_breaking"] = [a["title"] for a in articles[:3]]
            except Exception as e:
                logger.error(f"NewsAPI failed: {e}")
                
        return news_data

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
                
                # 2. Fetch News
                news_data = await self.fetch_news()
                
                # Combine State
                full_macro_state = {
                    "markets": macro_data,
                    "news": news_data,
                    "timestamp": time.time()
                }
                
                # Push to Redis for the Slow Loop LLM to consume
                await redis_db.set_json("MACRO_STATE", full_macro_state)
                logger.info("Updated Macro & News State in Redis.")
                
            except Exception as e:
                logger.error(f"Macro Node Failure: {e}")
                
            await asyncio.sleep(self.polling_interval)

    async def stop(self):
        self.is_running = False
        logger.info("Macro Data Node stopped.")
