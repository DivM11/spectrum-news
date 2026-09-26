"""Env config. All settings overridable via env / Streamlit sidebar."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CATEGORIES = ["Politics", "Science", "Tech", "Economics", "Climate/Disasters"]

MODEL_PRESETS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-haiku",
    "meta-llama/llama-3.1-70b-instruct",
]

COUNTRY_PRESETS = ["", "US", "UK", "IN", "EU", "Global"]


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


OPENROUTER_API_KEY = get("OPENROUTER_API_KEY", "")
RATING_MODEL = get("RATING_MODEL", "openai/gpt-4o-mini")
TAVILY_API_KEY = get("TAVILY_API_KEY", "")
DB_PATH = get("DB_PATH", "data/spectrum.db")
OPENROUTER_BASE_URL = get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
