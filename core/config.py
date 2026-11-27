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

    # Groww API
    GROWW_CLIENT_ID = os.getenv("GROWW_CLIENT_ID", "")
    GROWW_PASSWORD = os.getenv("GROWW_PASSWORD", "")
    GROWW_TOTP_SECRET = os.getenv("GROWW_TOTP_SECRET", "")
    GROWW_API_KEY = os.getenv("GROWW_API_KEY", "")
    GROWW_API_SECRET = os.getenv("GROWW_API_SECRET", "")

    UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY", "")
    UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET", "")
    UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI", "")
    UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")


    # LLM Providers (Paid & Free Tiers + Local Ollama)
    TOKENROUTER_API_KEY = os.getenv("TOKENROUTER_API_KEY", "")
    TOKENROUTER_BASE_URL = os.getenv("TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1")
    TOKENROUTER_MODEL = os.getenv("TOKENROUTER_MODEL", "deepseek/deepseek-v4.1-flash-1017-free")
    TOKENROUTER_FALLBACK_MODEL = os.getenv("TOKENROUTER_FALLBACK_MODEL", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "llama-3.3-70b")
    LLM_MIN_CONFIDENCE = int(os.getenv("LLM_MIN_CONFIDENCE", "78"))

    # Macro & News APIs
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
    ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

    # Redis Config
    REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB = int(os.getenv("REDIS_DB", 0))

    # Risk Limits & Capital
    MAX_CAPITAL = float(os.getenv("MAX_CAPITAL", "50000.0"))
    MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "5000.0"))
    MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))

    # Execution Mode (PAPER or LIVE)
    TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")

settings = Config()
