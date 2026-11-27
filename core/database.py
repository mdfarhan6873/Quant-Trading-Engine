import sqlite3
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trading_records.db")

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                qty INTEGER,
                price REAL,
                confidence INTEGER,
                reason TEXT,
                pnl REAL,
                mode TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        # Try to add 'mode' column if it doesn't exist (for backward compatibility)
        try:
            cursor.execute('ALTER TABLE trade_logs ADD COLUMN mode TEXT DEFAULT "PAPER"')
        except sqlite3.OperationalError:
            pass # Column exists
            
        # Try to add 'fund_balance' column if it doesn't exist
        try:
            cursor.execute('ALTER TABLE trade_logs ADD COLUMN fund_balance REAL DEFAULT 0.0')
        except sqlite3.OperationalError:
            pass # Column exists
            
        conn.commit()
        conn.close()
        logger.info("SQLite Database initialized at trading_records.db")
    except Exception as e:
        logger.error(f"Failed to initialize SQLite DB: {e}")

def set_setting(key: str, value: str):
    try:
        with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO system_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to save setting {key}: {e}")


def get_setting(key: str, default: str = None) -> str:
    try:
        with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.error(f"Failed to fetch setting {key}: {e}")
        return default


def log_trade(
    symbol: str,
    action: str,
    qty: int,
    price: float,
    confidence: int,
    reason: str,
    pnl: float = 0.0,
    mode: str = "PAPER",
    fund_balance: float = 0.0,
):
    try:
        with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trade_logs (timestamp, symbol, action, qty, price, confidence, reason, pnl, mode, fund_balance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (datetime.now().isoformat(), symbol, action, qty, price, confidence, reason, pnl, mode, fund_balance),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log trade to SQLite: {e}")
