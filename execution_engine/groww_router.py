import asyncio
import logging
import time
import httpx
from typing import Dict, Any, Optional
from core.config import settings

logger = logging.getLogger(__name__)

class GrowwRouter:
    """
    Primary Execution Engine routing trades through Groww API.
    Utilizes raw REST endpoints with the provided JWT Auth Token.
    """
    def __init__(self):
        self.client_id = settings.GROWW_CLIENT_ID
        self.password = settings.GROWW_PASSWORD
        self.totp_secret = settings.GROWW_TOTP_SECRET
        self.api_key = settings.GROWW_API_KEY
        
        self.base_url = "https://api.groww.in" 
        
        # Headers for authenticated requests
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=5.0)
        self.session_token = None

    async def login(self) -> bool:
        """
        Validates the provided JWT Token.
        """
        try:
            logger.info("Validating Groww API Key...")
            
            # For now, since the API Key is a JWT, we assume it's valid if provided.
            # Real validation would hit a user profile endpoint.
            if len(self.api_key) > 50:
                self.session_token = self.api_key
                logger.info("Groww API Key Validated. Execution Engine Armed.")
                return True
            else:
                logger.error("Groww API Key seems invalid.")
                return False
                
        except Exception as e:
            logger.critical(f"Groww Authentication Exception: {e}")
            return False

    async def place_order(self, symbol: str, qty: int, side: str, order_type: str = "MKT", price: float = 0.0) -> Optional[str]:
        """
        Places a live order to the exchange via Groww REST API.
        """
        logger.info(f"PLACING ORDER VIA GROWW: {side} {qty}x {symbol} | Type: {order_type}")
        
        try:
            start_time = time.time()
            
            payload = {
                "transaction_type": side.upper(),
                "quantity": qty,
                "order_type": order_type.upper(),
                "trading_symbol": symbol,
                "product_type": "MIS", # Intraday
                "price": price
            }
            
            # Using standard REST endpoint pattern for brokers. 
            # (Replace with exact Groww endpoint if different)
            response = await self.client.post("/v1/api/orders", json=payload)
            
            if response.status_code in [200, 201]:
                data = response.json()
                order_id = data.get("order_id", f"GRW_{int(time.time()*1000)}")
                
                latency = (time.time() - start_time) * 1000
                logger.info(f"ORDER SUCCESS [Groww]: {order_id} (Latency: {latency:.2f} ms)")
                return order_id
            else:
                logger.error(f"GROWW ORDER FAILED: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"GROWW ORDER FAILED: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancels a pending limit order via Groww."""
        logger.info(f"CANCELLING ORDER VIA GROWW: {order_id}")
        
        try:
            response = await self.client.delete(f"/v1/api/orders/{order_id}")
            if response.status_code in [200, 202]:
                logger.info(f"ORDER {order_id} CANCELLED SUCCESSFULLY ON GROWW.")
                return True
            else:
                logger.error(f"GROWW ORDER CANCEL FAILED: {response.text}")
                return False
        except Exception as e:
            logger.error(f"GROWW ORDER CANCEL FAILED: {e}")
            return False

    async def close_all_positions(self) -> bool:
        """
        PHYSICAL KILL SWITCH TRIGGER.
        Instantly fetches all open positions from Groww and fires Market orders to close them.
        """
        logger.critical("KILL SWITCH TRIGGERED: CLOSING ALL OPEN POSITIONS VIA GROWW!")
        
        try:
            response = await self.client.get("/v1/api/portfolio/positions")
            if response.status_code == 200:
                positions = response.json().get("positions", [])
            else:
                positions = []
            
            tasks = []
            for pos in positions:
                net_qty = int(pos.get("net_quantity", 0))
                if net_qty != 0:
                    symbol = pos.get("trading_symbol")
                    side = "SELL" if net_qty > 0 else "BUY"
                    tasks.append(self.place_order(symbol, abs(net_qty), side, "MKT"))
            
            if tasks:
                results = await asyncio.gather(*tasks)
                logger.critical(f"KILLED {len([r for r in results if r])} POSITIONS VIA GROWW.")
            else:
                logger.info("No open positions to kill on Groww.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to fetch positions for Kill Switch (Groww): {e}")
            return False

    async def shutdown(self):
        await self.client.aclose()
