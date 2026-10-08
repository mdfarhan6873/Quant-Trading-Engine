import asyncio
import logging
import time
import pyotp
import hashlib
from typing import Dict, Any, Optional
import httpx
from core.config import settings

logger = logging.getLogger(__name__)

class ShoonyaRouter:
    """
    Primary Execution Engine routing trades through Shoonya (Finvasia).
    Chosen for zero-brokerage, high-frequency scalping profitability.
    Fully async for ultra-low latency execution.
    """
    def __init__(self):
        self.base_url = settings.SHOONYA_BASE_URL
        self.user_id = settings.SHOONYA_USER_ID
        self.password = settings.SHOONYA_PASSWORD
        self.vendor_code = settings.SHOONYA_VENDOR_CODE
        self.api_secret = settings.SHOONYA_API_SECRET
        self.imei = settings.SHOONYA_IMEI
        self.totp_secret = settings.SHOONYA_TOTP_SECRET
        
        self.session_token = None
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=3.0) # 3s timeout for strict SLA
        
    async def login(self) -> bool:
        """
        Authenticates with Shoonya using TOTP. Generates the jKey (session token).
        Must run at 9:00 AM before market open.
        """
        try:
            logger.info("Authenticating with Shoonya Execution API...")
            
            # Generate current TOTP
            totp = pyotp.TOTP(self.totp_secret).now()
            
            # Encrypt password (SHA256)
            pwd_sha256 = hashlib.sha256(self.password.encode('utf-8')).hexdigest()
            
            # App key is userid|vendor_code
            app_key = f"{self.user_id}|{self.api_secret}"
            app_key_sha256 = hashlib.sha256(app_key.encode('utf-8')).hexdigest()
            
            payload = {
                "apkversion": "1.0.0",
                "uid": self.user_id,
                "pwd": pwd_sha256,
                "factor2": totp,
                "vc": self.vendor_code,
                "appkey": app_key_sha256,
                "imei": self.imei,
                "source": "API"
            }
            
            # Noren API expects 'jData' as a JSON string in the request payload
            import json
            jData = f"jData={json.dumps(payload)}"
            
            response = await self.client.post("/QuickAuth", data=jData, headers={"Content-Type": "application/x-www-form-urlencoded"})
            
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get("stat") == "Ok":
                    self.session_token = res_data.get("susertoken")
                    logger.info("Successfully logged into Shoonya. Execution Engine Armed.")
                    return True
                else:
                    logger.error(f"Shoonya Login Failed: {res_data.get('emsg')}")
                    return False
            else:
                logger.error(f"Shoonya HTTP Error: {response.status_code}")
                return False
                
        except Exception as e:
            logger.critical(f"Shoonya Authentication Exception: {e}")
            return False

    async def _post_request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Helper to send authenticated requests."""
        if not self.session_token:
            raise Exception("ShoonyaRouter is not authenticated.")
            
        import json
        payload["uid"] = self.user_id
        
        # Shoonya expects the token as a query parameter 'jKey'
        jData = f"jData={json.dumps(payload)}&jKey={self.session_token}"
        
        try:
            start_time = time.time()
            response = await self.client.post(endpoint, data=jData, headers={"Content-Type": "application/x-www-form-urlencoded"})
            latency = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                logger.debug(f"Execution API latency: {latency:.2f} ms")
                return response.json()
            else:
                logger.error(f"Shoonya API HTTP {response.status_code} at {endpoint}")
                return {"stat": "Not_Ok", "emsg": f"HTTP {response.status_code}"}
        except httpx.TimeoutException:
            logger.error(f"Shoonya API Timeout at {endpoint}")
            return {"stat": "Not_Ok", "emsg": "API Timeout"}
        except Exception as e:
            logger.error(f"Shoonya API Exception: {e}")
            return {"stat": "Not_Ok", "emsg": str(e)}

    async def place_order(self, symbol: str, qty: int, side: str, order_type: str = "MKT", price: float = 0.0) -> Optional[str]:
        """
        Places a live order to the exchange.
        Returns the order number if successful, None if failed.
        """
        logger.info(f"PLACING ORDER: {side} {qty}x {symbol} | Type: {order_type}")
        
        # Determine exchange based on symbol
        exch = "NFO" if ("CE" in symbol or "PE" in symbol or "FUT" in symbol) else "NSE"
        
        payload = {
            "actid": self.user_id,
            "exch": exch,
            "tsym": symbol, # Trading symbol strictly in Shoonya format
            "qty": str(qty),
            "prc": str(price) if order_type == "LMT" else "0",
            "prd": "M", # 'M' for MIS (Intraday), 'C' for CNC/NRML
            "trantype": "B" if side.upper() == "BUY" else "S",
            "prctyp": order_type,
            "ret": "DAY"
        }
        
        response = await self._post_request("/PlaceOrder", payload)
        
        if response.get("stat") == "Ok":
            noren_ord_no = response.get("norenordno")
            logger.info(f"ORDER SUCCESS: {noren_ord_no}")
            return noren_ord_no
        else:
            logger.error(f"ORDER REJECTED: {response.get('emsg')}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancels a pending limit order."""
        logger.info(f"CANCELLING ORDER: {order_id}")
        payload = {"norenordno": order_id}
        response = await self._post_request("/CancelOrder", payload)
        
        if response.get("stat") == "Ok":
            logger.info(f"ORDER {order_id} CANCELLED SUCCESSFULLY.")
            return True
        else:
            logger.error(f"ORDER CANCEL FAILED: {response.get('emsg')}")
            return False

    async def close_all_positions(self) -> bool:
        """
        PHYSICAL KILL SWITCH TRIGGER.
        Instantly loops through all open positions and fires Market orders to close them.
        """
        logger.critical("KILL SWITCH TRIGGERED: CLOSING ALL OPEN POSITIONS!")
        payload = {"actid": self.user_id}
        response = await self._post_request("/PositionBook", payload)
        
        if response.get("stat") == "Ok":
            positions = response.get("positions", [])
            tasks = []
            for pos in positions:
                net_qty = int(pos.get("netqty", 0))
                if net_qty != 0:
                    symbol = pos.get("tsym")
                    side = "SELL" if net_qty > 0 else "BUY"
                    # Fire close order instantly asynchronously
                    tasks.append(self.place_order(symbol, abs(net_qty), side, "MKT"))
            
            if tasks:
                results = await asyncio.gather(*tasks)
                logger.critical(f"KILLED {len(results)} POSITIONS.")
            else:
                logger.info("No open positions to kill.")
            return True
        else:
            logger.error(f"Failed to fetch positions for Kill Switch: {response.get('emsg')}")
            return False

    async def shutdown(self):
        await self.client.aclose()
