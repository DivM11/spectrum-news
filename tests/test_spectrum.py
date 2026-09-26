import json
import os, sys, tempfile, unittest
from unittest import mock
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


class TestOpenRouterSearch(unittest.TestCase):
    def _resp(self, content):
        m = mock.Mock()
        m.json.return_value = {"choices": [{"message": {"content": content}}]}
        m.raise_for_status.return_value = None
        return m

    def test_parses_json_array(self):
        payload = json.dumps([{"url": "https://reuters.com/a", "title": "A",
                               "snippet": "S", "published": "2026-09-01"}])
        with mock.patch("requests.post", return_value=self._resp(payload)):
            out = search._openrouter_search("q", model="m", api_key="k",
                                            base_url="https://x", max_results=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["outlet"], "reuters.com")
        self.assertEqual(out[0]["published"], "2026-09-01")

    def test_parses_wrapped_dict_and_fences(self):
        payload = '```json\n{"articles": [{"url": "https://bbc.com/x", "title": "T", "snippet": "S"}]}\n```'
        with mock.patch("requests.post", return_value=self._resp(payload)):
            out = search._openrouter_search("q", model="m", api_key="k",
                                            base_url="https://x", max_results=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["outlet"], "bbc.com")

    def test_skips_items_without_url(self):
        payload = json.dumps([{"title": "no url"}, {"url": "https://x.com/a", "title": "A"}])
        self.assertEqual(len(search.parse_articles(payload)), 1)

    def test_sends_web_search_tool(self):
        with mock.patch("requests.post", return_value=self._resp("[]")) as p:
            search._openrouter_search("q", model="m", api_key="k",
                                      base_url="https://x", max_results=4)
        body = p.call_args.kwargs["json"]
        self.assertEqual(body["model"], "m")
        self.assertEqual(body["tools"], [{"type": "openrouter:web_search",
                                          "parameters": {"max_results": 4, "max_total_results": 4}}])

    def test_falls_back_to_ddg_on_error(self):
        with mock.patch("requests.post", side_effect=RuntimeError("down")), \
             mock.patch.object(search, "_ddg_search", return_value=[{"url": "u"}]) as d:
            out = search._run_one("q", max_results=3, api_key="k",
                                  search_model="m", base_url="https://x")
        d.assert_called_once_with("q", 3)
        self.assertEqual(out, [{"url": "u"}])

    def test_keyless_uses_ddg_only(self):
        with mock.patch.object(search, "_ddg_search", return_value=[]) as d, \
             mock.patch("requests.post") as p:
            out = search._run_one("q", max_results=3, api_key="",
                                  search_model="m", base_url="https://x")
        p.assert_not_called()
        d.assert_called_once_with("q", 3)
        self.assertEqual(out, [])


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

        def fake_search(topic, category, country="", max_articles=9, api_key="",
                        search_model="m", base_url="https://x"):
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
