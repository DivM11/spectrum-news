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

# Search models should support tool calling (required by the openrouter:web_search tool).
SEARCH_MODEL_PRESETS = [
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "anthropic/claude-3.5-haiku",
]

COUNTRY_PRESETS = ["", "US", "UK", "IN", "EU", "Global"]


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


OPENROUTER_API_KEY = get("OPENROUTER_API_KEY", "")
RATING_MODEL = get("RATING_MODEL", "openai/gpt-4o-mini")
SEARCH_MODEL = get("SEARCH_MODEL", "openai/gpt-4o-mini")
CACHE_TTL_SECONDS = int(get("CACHE_TTL_SECONDS", "3600") or 3600)
DB_PATH = get("DB_PATH", "data/spectrum.db")
OPENROUTER_BASE_URL = get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
