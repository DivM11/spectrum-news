"""Opt-in integration tests against REAL external services.

Skipped by default (no keys/network in unit runs). Enable explicitly:

  TEST_POSTGRES_URL=postgresql+psycopg://...  uv run python -m unittest tests.test_integration -v
  RUN_LIVE_LLM_TESTS=1  (uses OPENROUTER_API_KEY; spends a few cents)

These are the only tests that touch Postgres-dialect paths (upsert, setval)
and real model behavior (tool use, JSON discipline) — everything else in
test_spectrum.py runs hermetically on SQLite/mocks.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

PG_URL = os.environ.get("TEST_POSTGRES_URL", "")
LIVE_LLM = os.environ.get("RUN_LIVE_LLM_TESTS", "") == "1" and bool(os.environ.get("OPENROUTER_API_KEY"))


@unittest.skipUnless(PG_URL, "TEST_POSTGRES_URL not set")
class TestPostgresStore(unittest.TestCase):
    def test_roundtrip_and_upsert(self):
        from spectrum_news import cache, db
        db.init_db(PG_URL)
        rid = db.create_run(PG_URL, "T", "Tech", "US", "m")
        aid = db.insert_article(PG_URL, rid, {"url": "https://x.com/a", "outlet": "x.com",
                                              "title": "T", "snippet": "S", "content": "S",
                                              "published": ""})
        db.insert_analysis(PG_URL, aid, {"factuality_score": 80, "bias_label": "Center",
                                         "bias_score": 0, "summary": "s", "key_claims": ["c"],
                                         "loaded_phrases": [], "verdict": "v"},
                           {"mbfc_factuality": "High", "mbfc_bias": "Center", "popularity_rank": 5})
        rows = db.fetch_run_evidence(PG_URL, rid)
        self.assertEqual(len(rows), 1)

        key = cache.search_key("t", "c", "", "m", 9)
        cache.put(PG_URL, key, [{"url": "u"}])
        cache.put(PG_URL, key, [{"url": "u2"}])  # exercises on_conflict_do_update
        self.assertEqual(cache.get(PG_URL, key, 3600), [{"url": "u2"}])
        self.assertGreaterEqual(cache.clear(PG_URL), 1)

    def test_import_then_insert_no_id_collision(self):
        import subprocess
        from spectrum_news import db
        script = os.path.normpath(os.path.join(os.path.dirname(__file__), "..",
                                               "scripts", "import_sqlite.py"))
        proc = subprocess.run(
            ["uv", "run", "python", script, "--from", os.environ.get("TEST_SQLITE_SRC", "data/spectrum.db"),
             "--to", PG_URL],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The setval fix: next insert must not collide with imported ids.
        rid = db.create_run(PG_URL, "post-import", "Tech", "", "m")
        self.assertIsInstance(rid, int)


@unittest.skipUnless(LIVE_LLM, "RUN_LIVE_LLM_TESTS=1 + OPENROUTER_API_KEY required")
class TestLiveOpenRouter(unittest.TestCase):
    def test_analyze_returns_contract(self):
        from spectrum_news import analyzer, config
        article = {"url": "https://reuters.com/world/x", "outlet": "reuters.com",
                   "title": "Central bank holds rates steady",
                   "snippet": "The central bank held its benchmark rate, citing inflation near target.",
                   "content": "The central bank held its benchmark rate on Thursday, citing inflation near target."}
        out = analyzer.analyze_article(article, config.RATING_MODEL,
                                       api_key=os.environ["OPENROUTER_API_KEY"])
        for key in ("factuality_score", "bias_label", "bias_score", "summary",
                    "key_claims", "loaded_phrases", "verdict"):
            self.assertIn(key, out)
        self.assertGreaterEqual(out["factuality_score"], 50)  # real outlet, real claims

    def test_search_returns_articles(self):
        from spectrum_news import config, search
        arts = search._openrouter_search(
            "Federal Reserve interest rate decision", model=config.SEARCH_MODEL,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=config.OPENROUTER_BASE_URL, max_results=3)
        self.assertGreaterEqual(len(arts), 1)
        self.assertTrue(all(a["url"].startswith("http") for a in arts))


if __name__ == "__main__":
    unittest.main()
