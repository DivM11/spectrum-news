import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from spectrum_news import sources, search, analyzer, db


class TestSources(unittest.TestCase):
    def test_mbfc_known(self):
        self.assertEqual(sources.mbfc_lookup("https://www.bbc.com/news/x")["mbfc_bias"], "Center")

    def test_mbfc_unknown(self):
        self.assertEqual(sources.mbfc_lookup("https://random-blog-xyz.example/a")["mbfc_factuality"], "Unknown")

    def test_popularity_known_and_unknown(self):
        self.assertLess(sources.popularity_lookup("reuters.com"), 999999)
        self.assertEqual(sources.popularity_lookup("no-such-outlet-xyz.example"), 999999)

    def test_registrable(self):
        self.assertEqual(sources.registrable_domain("www.bbc.co.uk"), "bbc.co.uk")


class TestSearch(unittest.TestCase):
    def test_queries_include_country(self):
        qs = search.build_queries("rate hike", "Economics", "IN")
        self.assertEqual(len(qs), 3)
        self.assertTrue(all("IN" in q for q in qs))

    def test_dedupe(self):
        a = search.normalize("https://x.com/a", "T", "S")
        b = search.normalize("https://x.com/a/", "T2", "S2")
        self.assertEqual(len(search.dedupe([a, b])), 1)


class TestAnalyzer(unittest.TestCase):
    def test_heuristic_keyless(self):
        a = {"title": "Test", "snippet": "short", "content": "", "url": "https://x.com", "outlet": "x.com"}
        out = analyzer.analyze_article(a, "openai/gpt-4o-mini", api_key="")
        self.assertIn("factuality_score", out)
        self.assertIn("bias_score", out)

    def test_parse_fences(self):
        parsed = analyzer.parse_json_lenient('```json\n{"a": 1}\n```')
        self.assertEqual(parsed, {"a": 1})


class TestDb(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            db.init_db(p)
            rid = db.create_run(p, "T", "Tech", "", "m")
            aid = db.insert_article(p, rid, {"url": "https://x.com/a", "outlet": "x.com",
                                             "title": "T", "snippet": "S", "content": "S", "published": ""})
            db.insert_analysis(p, aid, {"factuality_score": 80, "bias_label": "Center",
                                        "bias_score": 0, "summary": "s", "key_claims": ["c"],
                                        "loaded_phrases": [], "verdict": "v"},
                               {"mbfc_factuality": "High", "mbfc_bias": "Center", "popularity_rank": 5})
            rows = db.fetch_run_evidence(p, rid)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["bias_label"], "Center")


class TestPipeline(unittest.TestCase):
    def test_end_to_end_with_fakes(self):
        from spectrum_news import pipeline

        def fake_search(topic, category, country="", max_articles=9, tavily_key=""):
            return [
                {"url": "https://reuters.com/a", "outlet": "reuters.com", "title": "A",
                 "snippet": "markets rally", "content": "markets rally", "published": ""},
                {"url": "https://foxnews.com/b", "outlet": "foxnews.com", "title": "B",
                 "snippet": "freedom patriots rally", "content": "freedom patriots rally", "published": ""},
            ]

        def fake_analyze(article, model, key="", temperature=0.2):
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            out = pipeline.run_search("rally", "Politics", "", model="m", db_path=p,
                                      search_fn=fake_search, analyze_fn=fake_analyze)
            self.assertEqual(len(out["results"]), 2)
            scores = [r["analysis"]["bias_score"] for r in out["results"]]
            self.assertEqual(scores, sorted(scores))  # spectrum ordering


if __name__ == "__main__":
    unittest.main()
