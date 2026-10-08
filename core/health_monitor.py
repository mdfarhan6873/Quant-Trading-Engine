import asyncio
import logging
import time
from core.redis_client import redis_db
from core.config import settings

logger = logging.getLogger(__name__)

class HealthMonitor:
    """
    The System Watchdog (Enforces the 'Blindness Rule' from the PRD).
    Monitors the heartbeat of the data streams. If data stops flowing, it halts trading.
    """
    def __init__(self):
        self.is_monitoring = False
        self.last_tick_time = time.time()
        # How many seconds of silence before we assume the data feed is dead
        self.CRITICAL_TIMEOUT_SECONDS = 3.0 
        
    async def monitor_heartbeat(self):
        """Listens for ticks. Updates the heartbeat timestamp."""
        pubsub = redis_db.client.pubsub()
        await pubsub.subscribe("TICK_STREAM")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                self.last_tick_time = time.time()
                # If we were previously halted, we can resume
                await self._set_system_status("ONLINE")

    async def _set_system_status(self, status: str):
        """Updates the global trading status in Redis."""
        current_status = await redis_db.get_json("SYSTEM_STATUS")
        if current_status != {"state": status}:
            await redis_db.set_json("SYSTEM_STATUS", {"state": status})
            logger.info(f"System State changed to: {status}")
            
            if status == "HALTED":
                # Instantly broadcast the kill switch to the Execution Engine
                await redis_db.publish_message("EMERGENCY_HALT", {"reason": "Data Stream Timeout (Blindness Rule)"})

    async def run(self):
        """Main loop that continuously checks if we have gone blind."""
        self.is_monitoring = True
        logger.info("Health Monitor online. Watching for data integrity...")
        
        # Start listening to the heartbeat in the background
        asyncio.create_task(self.monitor_heartbeat())
        
        # Ensure we start in a HALTED state until we get our first data tick
        await self._set_system_status("HALTED")
        
        while self.is_monitoring:
            time_since_last_tick = time.time() - self.last_tick_time
            
            if time_since_last_tick > self.CRITICAL_TIMEOUT_SECONDS:
                logger.critical(f"DATA TIMEOUT! No ticks received for {time_since_last_tick:.1f}s. Enacting Blindness Rule.")
                await self._set_system_status("HALTED")
                
            await asyncio.sleep(1) # Check health every 1 second

    async def stop(self):
        self.is_monitoring = False
        logger.info("Health Monitor stopped.")
