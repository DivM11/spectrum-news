"""Env config. All settings overridable via env / Streamlit sidebar."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CATEGORIES = ["Politics", "Science", "Tech", "Economics", "Climate/Disasters"]

MODEL_PRESETS = [
    "google/gemini-2.5-flash-lite",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-v4-flash",
    "anthropic/claude-haiku-4.5",
]

# Search models should support tool calling (required by the openrouter:web_search tool).
SEARCH_MODEL_PRESETS = [
    "deepseek/deepseek-v4-flash",
    "google/gemini-2.5-flash-lite",
    "qwen/qwen3.7-flash",
    "openai/gpt-4o-mini",
]

COUNTRY_PRESETS = ["", "US", "UK", "IN", "EU", "Global"]


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


OPENROUTER_API_KEY = get("OPENROUTER_API_KEY", "")
RATING_MODEL = get("RATING_MODEL", "google/gemini-2.5-flash-lite")
SEARCH_MODEL = get("SEARCH_MODEL", "deepseek/deepseek-v4-flash")
CACHE_TTL_SECONDS = int(get("CACHE_TTL_SECONDS", "3600") or 3600)
DB_PATH = get("DB_PATH", "data/spectrum.db")
OPENROUTER_BASE_URL = get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
