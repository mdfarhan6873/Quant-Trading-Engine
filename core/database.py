import sqlite3
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trading_records.db")

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
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
                pnl REAL
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("SQLite Database initialized at trading_records.db")
    except Exception as e:
        logger.error(f"Failed to initialize SQLite DB: {e}")

def log_trade(symbol: str, action: str, qty: int, price: float, confidence: int, reason: str, pnl: float = 0.0):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO trade_logs (timestamp, symbol, action, qty, price, confidence, reason, pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), symbol, action, qty, price, confidence, reason, pnl))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log trade to SQLite: {e}")
