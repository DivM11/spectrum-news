"""Outlet Source Profiles: MBFC lookup + popularity rank. Offline, pure functions."""
from __future__ import annotations

import csv
import os
from urllib.parse import urlparse

MBFC_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "mbfc_ratings.csv")
# Fallback when package layout differs (running from repo root):
if not os.path.exists(MBFC_CSV):
    for candidate in ("data/mbfc_ratings.csv", "spectrum-news/data/mbfc_ratings.csv"):
        if os.path.exists(candidate):
            MBFC_CSV = candidate
            break

# Curated popularity fallback (lower = more visited). Real Tranco dump can
# replace this via data/tranco.csv with `domain,rank` rows.
CURATED_POPULARITY = {
    "bbc.com": 80, "reuters.com": 250, "apnews.com": 400, "nytimes.com": 120,
    "washingtonpost.com": 200, "theguardian.com": 150, "wsj.com": 300,
    "bloomberg.com": 350, "economist.com": 900, "ft.com": 800,
    "npr.org": 500, "pbs.org": 1200, "abcnews.go.com": 600, "cbsnews.com": 650,
    "nbcnews.com": 550, "cnn.com": 100, "foxnews.com": 180, "usatoday.com": 450,
    "aljazeera.com": 700, "dw.com": 1100, "france24.com": 2500, "ndtv.com": 1500,
    "thehindu.com": 1300, "indianexpress.com": 1400, "bbc.co.uk": 90,
    "nature.com": 2000, "science.org": 3000, "techcrunch.com": 1000,
    "theverge.com": 950, "wired.com": 1100, "arstechnica.com": 1800,
    "forbes.com": 380, "fortune.com": 2200, "cnbc.com": 420,
    "noaa.gov": 1500, "nasa.gov": 700, "ipcc.ch": 20000, "who.int": 900,
}
DEFAULT_RANK = 999999

_mbfc_cache: dict | None = None
_tranco_cache: dict | None = None


def domain_of(url_or_domain: str) -> str:
    s = (url_or_domain or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    try:
        host = urlparse(s).hostname or ""
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def registrable_domain(host: str) -> str:
    """Naive eTLD+1: last two labels (handles co.uk style for our list)."""
    host = (host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # keep ccTLD second-levels like co.uk / co.in
    if parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _load_mbfc() -> dict:
    global _mbfc_cache
    if _mbfc_cache is not None:
        return _mbfc_cache
    table: dict = {}
    try:
        with open(MBFC_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = (row.get("domain") or "").strip().lower()
                if d:
                    table[d] = {
                        "mbfc_factuality": row.get("factuality", "Unknown"),
                        "mbfc_bias": row.get("bias", "Unknown"),
                    }
    except FileNotFoundError:
        pass
    _mbfc_cache = table
    return table


def _load_tranco() -> dict:
    global _tranco_cache
    if _tranco_cache is not None:
        return _tranco_cache
    table: dict = {}
    for candidate in ("data/tranco.csv",):
        try:
            with open(candidate, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        table[(row.get("domain") or "").lower()] = int(row.get("rank", DEFAULT_RANK))
                    except (TypeError, ValueError):
                        continue
        except FileNotFoundError:
            continue
    _tranco_cache = table
    return table


def mbfc_lookup(url_or_domain: str) -> dict:
    table = _load_mbfc()
    host = domain_of(url_or_domain)
    for key in (host, registrable_domain(host)):
        if key and key in table:
            return dict(table[key])
    return {"mbfc_factuality": "Unknown", "mbfc_bias": "Unknown"}


def popularity_lookup(url_or_domain: str) -> int:
    host = domain_of(url_or_domain)
    tranco = _load_tranco()
    for key in (host, registrable_domain(host)):
        if key and key in tranco:
            return tranco[key]
        if key and key in CURATED_POPULARITY:
            return CURATED_POPULARITY[key]
    return DEFAULT_RANK


def source_profile(url_or_domain: str) -> dict:
    return {
        "domain": registrable_domain(domain_of(url_or_domain)),
        **mbfc_lookup(url_or_domain),
        "popularity_rank": popularity_lookup(url_or_domain),
    }
