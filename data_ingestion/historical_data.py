import logging
from typing import List, Dict, Any
import upstox_client
from upstox_client.rest import ApiException
from core.config import settings
import time
logger = logging.getLogger(__name__)

class UpstoxHistoryClient:
    """
    Handles fetching historical data from Upstox for calculations like
    VWAP, PDH/PDL, and IV Crush.
    Respects free tier rate limits: 10 requests/second.
    """
    def __init__(self):
        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = settings.UPSTOX_ACCESS_TOKEN
        self.api_client = upstox_client.ApiClient(self.configuration)
        self.history_api = upstox_client.HistoryApi(self.api_client)
        self._last_request_time = 0.0

    def _wait_for_rate_limit(self):
        """Ensures we do not exceed 10 requests per second (0.1s between calls)"""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
        self._last_request_time = time.time()

    def get_historical_data(self, instrument_key: str, interval: str, to_date: str, from_date: str) -> List[Dict[str, Any]]:
        """
        Fetch historical candles.
        interval: '1minute', '30minute', 'day' etc.
        to_date: 'YYYY-MM-DD'
        from_date: 'YYYY-MM-DD'
        """
        api_version = '2.0'
        self._wait_for_rate_limit()
        try:
            # The API method name might vary slightly (e.g. get_historical_candle_data1)
            api_response = self.history_api.get_historical_candle_data1(
                instrument_key=instrument_key,
                interval=interval,
                to_date=to_date,
                from_date=from_date,
                api_version=api_version
            )
            
            # Extract data
            if api_response and hasattr(api_response, 'data') and hasattr(api_response.data, 'candles'):
                candles = api_response.data.candles
                result = []
                for candle in candles:
                    # candle format: [timestamp, open, high, low, close, volume, oi]
                    if len(candle) >= 6:
                        result.append({
                            "timestamp": candle[0],
                            "open": candle[1],
                            "high": candle[2],
                            "low": candle[3],
                            "close": candle[4],
                            "volume": candle[5],
                            "oi": candle[6] if len(candle) > 6 else 0
                        })
                return result
            return []
            
        except ApiException as e:
            logger.error(f"Upstox History API Exception: {e}")
            return []

    def get_intraday_data(self, instrument_key: str, interval: str) -> List[Dict[str, Any]]:
        """
        Fetch intraday candles for the current day.
        interval: '1minute', '5minute', etc.
        """
        api_version = '2.0'
        self._wait_for_rate_limit()
        try:
            api_response = self.history_api.get_intra_day_candle_data(
                instrument_key=instrument_key,
                interval=interval,
                api_version=api_version
            )
            
            if api_response and hasattr(api_response, 'data') and hasattr(api_response.data, 'candles'):
                candles = api_response.data.candles
                result = []
                for candle in candles:
                    if len(candle) >= 6:
                        result.append({
                            "timestamp": candle[0],
                            "open": candle[1],
                            "high": candle[2],
                            "low": candle[3],
                            "close": candle[4],
                            "volume": candle[5],
                            "oi": candle[6] if len(candle) > 6 else 0
                        })
                return result
            return []
        except ApiException as e:
            logger.error(f"Upstox Intraday History API Exception: {e}")
            return []

# Usage example:
# client = UpstoxHistoryClient()
# candles = client.get_historical_data("NSE_INDEX|Nifty 50", "day", "2023-11-01", "2023-10-01")
