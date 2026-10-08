import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Broker APIs
    SHOONYA_USER_ID = os.getenv("SHOONYA_USER_ID", "")
    SHOONYA_PASSWORD = os.getenv("SHOONYA_PASSWORD", "")
    SHOONYA_TOTP_SECRET = os.getenv("SHOONYA_TOTP_SECRET", "")
    SHOONYA_API_KEY = os.getenv("SHOONYA_API_KEY", "")
    SHOONYA_API_SECRET = os.getenv("SHOONYA_API_SECRET", "")
    SHOONYA_VENDOR_CODE = os.getenv("SHOONYA_VENDOR_CODE", "")
    SHOONYA_IMEI = os.getenv("SHOONYA_IMEI", "")
    SHOONYA_BASE_URL = os.getenv("SHOONYA_BASE_URL", "https://api.shoonya.com/NorenWClientTP")

    DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
    DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")
    DHAN_BASE_URL = os.getenv("DHAN_BASE_URL", "https://api.dhan.co")
    DHAN_WSS_URL = os.getenv("DHAN_WSS_URL", "wss://api.dhan.co/v2/marketfeed")
    DHAN_SCRIP_MASTER_URL = os.getenv("DHAN_SCRIP_MASTER_URL", "https://images.dhan.co/api-data/api-scrip-master.csv")

    # LLM Providers
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # Macro & News APIs
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
    ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

    # Redis Config
    REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB = int(os.getenv("REDIS_DB", 0))

    # Risk Limits
    MAX_DAILY_LOSS = 5000.0
    MAX_CONSECUTIVE_LOSSES = 3

    # Execution Mode (PAPER or LIVE)
    TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")

settings = Config()
