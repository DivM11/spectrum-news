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
DEFAULT_COUNTRY = "US"

# Fixed one-click Topic prompts per Category (USA-focused). Verbatim queries -> high cache-hit rate.
DEFAULT_PROMPTS = {
    "Politics": "US 2026 midterm elections",
    "Science": "NASA Artemis lunar program update",
    "Tech": "US AI regulation Big Tech",
    "Economics": "Federal Reserve interest rates US economy",
    "Climate/Disasters": "US hurricane season FEMA response",
}

# Sidebar outlet allowlist. "All" = unrestricted. Domains map to web-search allowed_domains.
OUTLET_ALL = "All"
OUTLET_CHOICES = {
    "BBC": "bbc.com",
    "Reuters": "reuters.com",
    "Associated Press": "apnews.com",
    "NY Times": "nytimes.com",
    "Washington Post": "washingtonpost.com",
    "Wall Street Journal": "wsj.com",
    "The Guardian": "theguardian.com",
    "NPR": "npr.org",
    "CNN": "cnn.com",
    "Fox News": "foxnews.com",
    "Bloomberg": "bloomberg.com",
    "USA Today": "usatoday.com",
    "ABC News": "abcnews.go.com",
    "CBS News": "cbsnews.com",
    "NBC News": "nbcnews.com",
    "Al Jazeera": "aljazeera.com",
    "The Economist": "economist.com",
    "Financial Times": "ft.com",
}


def outlet_domains(selection: list[str]) -> list[str]:
    """Allowlist selection -> web-search domains. [All]/empty = unrestricted."""
    if not selection or OUTLET_ALL in selection:
        return []
    return [OUTLET_CHOICES[name] for name in selection if name in OUTLET_CHOICES]


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "") or default)
    except (TypeError, ValueError):
        return default


OPENROUTER_API_KEY = get("OPENROUTER_API_KEY", "")
RATING_MODEL = get("RATING_MODEL", "google/gemini-2.5-flash-lite")
SEARCH_MODEL = get("SEARCH_MODEL", "deepseek/deepseek-v4-flash")
JUDGE_MODEL = get("JUDGE_MODEL", "google/gemini-2.5-flash")
MAX_CONCURRENT_UNCACHED_RUNS = _int_env("MAX_CONCURRENT_UNCACHED_RUNS", 4)
CACHE_TTL_SECONDS = _int_env("CACHE_TTL_SECONDS", 3600)
DB_PATH = get("DB_PATH", "data/spectrum.db")
# Full SQLAlchemy URL wins when set (prod Postgres); otherwise the SQLite file.
DATABASE_URL = get("DATABASE_URL", "") or DB_PATH
OPENROUTER_BASE_URL = get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
