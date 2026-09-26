import json
import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from spectrum_news import sources, search, analyzer, cache, db


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


class TestCache(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            key = cache.search_key("Rates", "Economics", "IN", "m", 9)
            self.assertIsNone(cache.get(p, key, 3600))
            arts = [{"url": "https://x.com/a", "title": "A"}]
            cache.put(p, key, arts)
            self.assertEqual(cache.get(p, key, 3600), arts)

    def test_namespaces_isolate_same_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            cache.put(p, cache.CacheKey("a", "k"), {"v": 1})
            self.assertIsNone(cache.get(p, cache.CacheKey("b", "k"), 3600))
            self.assertEqual(cache.get(p, cache.CacheKey("a", "k"), 3600), {"v": 1})

    def test_search_key_normalizes_case_and_whitespace(self):
        self.assertEqual(cache.search_key(" Rates ", "Economics", "", "m", 9),
                         cache.search_key("rates", "economics", "", "m", 9))

    def test_search_key_differs_per_inputs(self):
        base = dict(topic="t", category="c", country="", search_model="m", max_articles=9)
        self.assertNotEqual(cache.search_key(**{**base, "topic": "other"}),
                            cache.search_key(**base))
        self.assertNotEqual(cache.search_key(**{**base, "search_model": "other"}),
                            cache.search_key(**base))

    def test_analysis_key_tracks_content_model_temperature(self):
        art = {"url": "https://x.com/a", "title": "A", "content": "body"}
        same = {"url": "https://X.com/a/", "title": "A", "content": "body"}
        self.assertEqual(cache.analysis_key(art, "m", 0.2), cache.analysis_key(same, "m", 0.2))
        self.assertNotEqual(cache.analysis_key(art, "m", 0.2),
                            cache.analysis_key({**art, "content": "changed"}, "m", 0.2))
        self.assertNotEqual(cache.analysis_key(art, "m", 0.2),
                            cache.analysis_key(art, "other", 0.2))
        self.assertNotEqual(cache.analysis_key(art, "m", 0.2),
                            cache.analysis_key(art, "m", 0.9))

    def test_expired_and_disabled_ttl_miss(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            key = cache.search_key("t", "c", "", "m", 9)
            cache.put(p, key, [{"url": "u"}])
            self.assertIsNone(cache.get(p, key, 0))
            self.assertIsNone(cache.get(p, key, -5))

    def test_clear_all_and_per_namespace(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            skey = cache.search_key("t", "c", "", "m", 9)
            akey = cache.analysis_key({"url": "u"}, "m", 0.2)
            cache.put(p, skey, [{"url": "u"}])
            cache.put(p, akey, {"factuality_score": 1})
            self.assertEqual(cache.clear(p, cache.SEARCH_NS), 1)
            self.assertIsNone(cache.get(p, skey, 3600))
            self.assertIsNotNone(cache.get(p, akey, 3600))
            self.assertEqual(cache.clear(p), 1)
            self.assertIsNone(cache.get(p, akey, 3600))
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

    def test_search_cached_between_runs(self):
        from spectrum_news import pipeline

        calls = []

        def counting_search(topic, category, country="", max_articles=9, api_key="",
                            search_model="m", base_url="https://x"):
            calls.append((topic, category, country))
            return [{"url": "https://x.com/a", "outlet": "x.com", "title": "A",
                     "snippet": "s", "content": "s", "published": ""}]

        def fake_analyze(article, model, key="", temperature=0.2):
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            kw = dict(model="m", db_path=p, search_fn=counting_search,
                      analyze_fn=fake_analyze, cache_ttl_seconds=3600)
            first = pipeline.run_search("rally", "Politics", "", **kw)
            second = pipeline.run_search("rally", "Politics", "", **kw)
            self.assertFalse(first["search_cache_hit"])
            self.assertTrue(second["search_cache_hit"])
            self.assertEqual(len(calls), 1)  # search ran once
            self.assertEqual(len(second["results"]), 1)

    def test_analysis_cached_between_runs(self):
        from spectrum_news import pipeline

        search_calls, analyze_calls = [], []

        def static_search(topic, category, country="", max_articles=9, api_key="",
                          search_model="m", base_url="https://x"):
            search_calls.append(search_model)
            return [{"url": "https://x.com/a", "outlet": "x.com", "title": "A",
                     "snippet": "steady body", "content": "steady body", "published": ""}]

        def counting_analyze(article, model, key="", temperature=0.2):
            analyze_calls.append(model)
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            base = dict(model="m", db_path=p, search_fn=static_search,
                        analyze_fn=counting_analyze, cache_ttl_seconds=3600)
            # Different search models -> search cache misses, but the same article
            # under the same rating model -> analysis cache hits.
            out1 = pipeline.run_search("rally", "Politics", "", search_model="s1", **base)
            out2 = pipeline.run_search("rally", "Politics", "", search_model="s2", **base)
            self.assertFalse(any(r.get("cached") for r in out1["results"]))
            self.assertFalse(out2["search_cache_hit"])
            self.assertEqual(len(search_calls), 2)
            self.assertEqual(len(analyze_calls), 1)
            self.assertTrue(all(r.get("cached") for r in out2["results"]))

    def test_cache_bypass_refetches(self):
        from spectrum_news import pipeline

        calls = []

        def counting_search(topic, category, country="", max_articles=9, api_key="",
                            search_model="m", base_url="https://x"):
            calls.append(1)
            return []

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            kw = dict(model="m", db_path=p, search_fn=counting_search,
                      analyze_fn=lambda a, m, k="", temperature=0.2: analyzer.heuristic_analysis(a))
            pipeline.run_search("t", "Tech", "", use_cache=True, **kw)
            out = pipeline.run_search("t", "Tech", "", use_cache=False, **kw)
            self.assertFalse(out["search_cache_hit"])
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
