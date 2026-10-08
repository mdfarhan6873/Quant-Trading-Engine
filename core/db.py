import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Manages the SQLite database for persistent records like Trade Logs, Daily PnL, and IV History.
    (As required by PRD Section 10 and Data Sources Section 4).
    """
    def __init__(self, db_path: str = "data/trading_engine.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Creates the required tables if they do not exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Trade Log Table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        symbol TEXT NOT NULL,
                        action TEXT NOT NULL,
                        qty INTEGER NOT NULL,
                        price REAL NOT NULL,
                        reason TEXT
                    )
                """)
                
                # Daily PnL Table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_pnl (
                        date DATE PRIMARY KEY,
                        total_pnl REAL NOT NULL,
                        max_drawdown REAL
                    )
                """)

                # 30-Day IV History Table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS iv_history (
                        date DATE,
                        symbol TEXT,
                        iv_value REAL,
                        PRIMARY KEY (date, symbol)
                    )
                """)
                conn.commit()
                logger.info("SQLite Database initialized successfully.")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")

# Global DB instance
db_manager = DatabaseManager()
