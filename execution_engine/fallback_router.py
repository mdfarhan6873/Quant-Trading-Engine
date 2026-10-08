import logging
import asyncio
from typing import Dict, Any, Optional
import httpx
from core.config import settings

logger = logging.getLogger(__name__)

class DhanFallbackRouter:
    """
    Emergency Fallback Execution Engine (Dhan).
    If Shoonya APIs drop, the system instantly switches to this node to manage positions.
    """
    def __init__(self):
        self.base_url = settings.DHAN_BASE_URL
        self.client_id = settings.DHAN_CLIENT_ID
        self.access_token = settings.DHAN_ACCESS_TOKEN
        
        self.headers = {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=3.0)
        
    async def place_order(self, symbol: str, qty: int, side: str, order_type: str = "MKT", price: float = 0.0) -> Optional[str]:
        """
        Places an emergency fallback order to Dhan.
        """
        logger.warning(f"FALLBACK ORDER INIT: {side} {qty}x {symbol}")
        
        # Determine exchange and segment
        exch = "NFO" if ("CE" in symbol or "PE" in symbol or "FUT" in symbol) else "NSE"
        segment = "OPTIONS" if ("CE" in symbol or "PE" in symbol) else ("FUTURES" if "FUT" in symbol else "EQUITY")
        
        payload = {
            "dhanClientId": self.client_id,
            "correlationId": "algo_fallback",
            "transactionType": "BUY" if side.upper() == "BUY" else "SELL",
            "exchangeSegment": f"{exch}_{segment}",
            "productType": "MARGIN",
            "orderType": "MARKET" if order_type == "MKT" else "LIMIT",
            "validity": "DAY",
            "tradingSymbol": symbol,
            "securityId": "", # In a real implementation, you'd map the symbol to Dhan's Security ID
            "quantity": qty,
            "price": price if order_type == "LMT" else 0
        }
        
        try:
            response = await self.client.post("/orders", json=payload)
            if response.status_code == 200:
                data = response.json()
                logger.warning(f"FALLBACK ORDER SUCCESS: {data.get('orderId')}")
                return data.get("orderId")
            else:
                logger.error(f"FALLBACK ORDER FAILED: {response.text}")
                return None
        except Exception as e:
            logger.critical(f"FALLBACK ROUTER EXCEPTION: {e}")
            return None

    async def close_all_positions(self) -> bool:
        """Emergency liquidation via Fallback"""
        logger.critical("FALLBACK KILL SWITCH INITIATED!")
        # Fetch Dhan positions
        try:
            response = await self.client.get("/positions")
            if response.status_code == 200:
                positions = response.json()
                tasks = []
                for pos in positions:
                    qty = int(pos.get("netQty", 0))
                    if qty != 0:
                        symbol = pos.get("tradingSymbol")
                        side = "SELL" if qty > 0 else "BUY"
                        tasks.append(self.place_order(symbol, abs(qty), side, "MKT"))
                
                if tasks:
                    await asyncio.gather(*tasks)
                    logger.critical("FALLBACK KILL SWITCH COMPLETED.")
                return True
        except Exception as e:
            logger.critical(f"FALLBACK KILL SWITCH FAILED: {e}")
            return False

    async def shutdown(self):
        await self.client.aclose()
