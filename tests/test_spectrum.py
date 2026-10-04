import json
import os, sys, tempfile, time, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from spectrum_news import sources, search, analyzer, cache, config, db


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

    def test_normalize_domains(self):
        self.assertEqual(search.normalize_domains([" BBC.com ", "bbc.com", "", None]),
                         ["bbc.com"])
        self.assertEqual(search.normalize_domains(None), [])


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

    def test_allowed_domains_sent_to_tool(self):
        with mock.patch("requests.post", return_value=self._resp("[]")) as p:
            search._openrouter_search("q", model="m", api_key="k",
                                      base_url="https://x", max_results=4,
                                      allowed_domains=[" BBC.com ", "reuters.com"])
        params = p.call_args.kwargs["json"]["tools"][0]["parameters"]
        self.assertEqual(params["allowed_domains"], ["bbc.com", "reuters.com"])

    def test_no_domains_means_no_restriction(self):
        with mock.patch("requests.post", return_value=self._resp("[]")) as p:
            search._openrouter_search("q", model="m", api_key="k",
                                      base_url="https://x", max_results=4)
        params = p.call_args.kwargs["json"]["tools"][0]["parameters"]
        self.assertNotIn("allowed_domains", params)


class TestDefaults(unittest.TestCase):
    def test_prompts_cover_all_categories(self):
        self.assertEqual(set(config.DEFAULT_PROMPTS), set(config.CATEGORIES))
        self.assertTrue(all(v.strip() for v in config.DEFAULT_PROMPTS.values()))

    def test_default_country_is_selectable(self):
        self.assertIn(config.DEFAULT_COUNTRY, config.COUNTRY_PRESETS)

    def test_outlet_domains_all_and_empty_unrestricted(self):
        self.assertEqual(config.outlet_domains([]), [])
        self.assertEqual(config.outlet_domains([config.OUTLET_ALL]), [])
        self.assertEqual(config.outlet_domains([config.OUTLET_ALL, "BBC"]), [])

    def test_outlet_domains_maps_selection(self):
        self.assertEqual(config.outlet_domains(["BBC", "Reuters"]), ["bbc.com", "reuters.com"])
        self.assertEqual(config.outlet_domains(["Nope"]), [])


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
        self.assertNotEqual(cache.search_key(**{**base, "allowed_domains": ["bbc.com"]}),
                            cache.search_key(**base))
        self.assertEqual(cache.search_key(**{**base, "allowed_domains": ["BBC.com "]}),
                         cache.search_key(**{**base, "allowed_domains": ["bbc.com"]}))

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

    def test_sanitize_coerces_unknown_label(self):
        art = {"title": "T", "snippet": "s", "content": "s"}
        out = analyzer.sanitize({"bias_label": "Leftish", "bias_score": -2}, art)
        self.assertEqual(out["bias_label"], "Left")
        out = analyzer.sanitize({"bias_label": "???", "bias_score": 2.8}, art)
        self.assertEqual(out["bias_label"], "Far-Right")
        out = analyzer.sanitize({"bias_label": "Right", "bias_score": 2}, art)
        self.assertEqual(out["bias_label"], "Right")


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

        def fake_search(query, spec):
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
            out = pipeline.run_search("rally", "Politics", "", model="m", db_url=p,
                                      search_query_fn=fake_search, analyze_fn=fake_analyze)
            self.assertEqual(len(out["results"]), 2)
            scores = [r["analysis"]["bias_score"] for r in out["results"]]
            self.assertEqual(scores, sorted(scores))  # spectrum ordering

    def test_search_cached_between_runs(self):
        from spectrum_news import pipeline

        calls = []

        def counting_search(query, spec):
            calls.append((spec.topic, spec.category, spec.country))
            return [{"url": "https://x.com/a", "outlet": "x.com", "title": "A",
                     "snippet": "s", "content": "s", "published": ""}]

        def fake_analyze(article, model, key="", temperature=0.2):
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            kw = dict(model="m", db_url=p, search_query_fn=counting_search,
                      analyze_fn=fake_analyze, cache_ttl_seconds=3600)
            first = pipeline.run_search("rally", "Politics", "", **kw)
            second = pipeline.run_search("rally", "Politics", "", **kw)
            self.assertFalse(first["search_cache_hit"])
            self.assertTrue(second["search_cache_hit"])
            self.assertEqual(len(calls), 3)  # 3 query variants, ran once
            self.assertEqual(len(second["results"]), 1)

    def test_analysis_cached_between_runs(self):
        from spectrum_news import pipeline

        search_calls, analyze_calls = [], []

        def static_search(query, spec):
            search_calls.append(spec.search_model)
            return [{"url": "https://x.com/a", "outlet": "x.com", "title": "A",
                     "snippet": "steady body", "content": "steady body", "published": ""}]

        def counting_analyze(article, model, key="", temperature=0.2):
            analyze_calls.append(model)
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            base = dict(model="m", db_url=p, search_query_fn=static_search,
                        analyze_fn=counting_analyze, cache_ttl_seconds=3600)
            # Different search models -> search cache misses, but the same article
            # under the same rating model -> analysis cache hits.
            out1 = pipeline.run_search("rally", "Politics", "", search_model="s1", **base)
            out2 = pipeline.run_search("rally", "Politics", "", search_model="s2", **base)
            self.assertFalse(any(r.get("cached") for r in out1["results"]))
            self.assertFalse(out2["search_cache_hit"])
            self.assertEqual(len(search_calls), 6)  # 2 runs x 3 query variants
            self.assertEqual(len(analyze_calls), 1)
            self.assertTrue(all(r.get("cached") for r in out2["results"]))

    def test_search_spec_flows_end_to_end(self):
        from spectrum_news import pipeline

        seen = []

        def capturing_search(query, spec):
            seen.append(spec)
            return []

        def fake_analyze(article, model, key="", temperature=0.2):
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            pipeline.run_search("t", "Tech", "IN", model="m", search_model="s",
                                db_url=p, search_query_fn=capturing_search,
                                analyze_fn=fake_analyze,
                                allowed_domains=[" BBC.com "])
        self.assertEqual(len(seen), 3)  # one call per query variant
        spec = seen[0]
        self.assertEqual((spec.topic, spec.category, spec.country), ("t", "Tech", "IN"))
        self.assertEqual(spec.search_model, "s")
        self.assertEqual(spec.domains(), ["bbc.com"])

    def test_failing_article_falls_back_without_aborting_run(self):
        from spectrum_news import pipeline

        def ok_search(query, spec):
            return [
                {"url": "https://x.com/a", "outlet": "x.com", "title": "A",
                 "snippet": "s", "content": "s", "published": ""},
                {"url": "https://x.com/b", "outlet": "x.com", "title": "B",
                 "snippet": "s", "content": "s", "published": ""},
            ]

        def flaky_analyze(article, model, key="", temperature=0.2):
            if article["url"].endswith("/a"):
                raise RuntimeError("LLM 500")
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            out = pipeline.run_search("t", "Tech", "", model="m", db_url=p,
                                      search_query_fn=ok_search, analyze_fn=flaky_analyze)
            self.assertEqual(len(out["results"]), 2)
            by_url = {r["article"]["url"]: r for r in out["results"]}
            self.assertIn("heuristic fallback", by_url["https://x.com/a"]["analysis"]["verdict"])
            rows = db.fetch_run_evidence(p, out["run_id"])
            self.assertEqual(len(rows), 2)

    def test_uncached_runs_bounded_by_semaphore(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from spectrum_news import pipeline

        lock = threading.Lock()
        state = {"current": 0, "max": 0}

        def slow_search(query, spec):
            return [{"url": "https://x.com/a", "outlet": "x.com", "title": "A",
                     "snippet": "s", "content": "s", "published": ""}]

        def slow_analyze(article, model, key="", temperature=0.2):
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            try:
                time.sleep(0.15)
            finally:
                with lock:
                    state["current"] -= 1
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(
                    lambda i: pipeline.run_search(f"topic {i}", "Tech", "", model="m",
                                                  db_url=p, search_query_fn=slow_search,
                                                  analyze_fn=slow_analyze,
                                                  max_concurrent_uncached_runs=2),
                    range(6)))
        self.assertTrue(all(r["results"] for r in results))
        self.assertLessEqual(state["max"], 2)

    def test_cache_bypass_refetches(self):
        from spectrum_news import pipeline

        calls = []

        def counting_search(query, spec):
            calls.append(1)
            return []

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            kw = dict(model="m", db_url=p, search_query_fn=counting_search,
                      analyze_fn=lambda a, m, k="", temperature=0.2: analyzer.heuristic_analysis(a))
            pipeline.run_search("t", "Tech", "", use_cache=True, **kw)
            out = pipeline.run_search("t", "Tech", "", use_cache=False, **kw)
            self.assertFalse(out["search_cache_hit"])
            self.assertEqual(len(calls), 6)  # 2 runs x 3 query variants


class TestStore(unittest.TestCase):
    def test_config_ttl_tolerates_garbage(self):
        import importlib
        from spectrum_news import config as config_mod
        with mock.patch.dict(os.environ, {"CACHE_TTL_SECONDS": "bogus"}):
            reloaded = importlib.reload(config_mod)
            try:
                self.assertEqual(reloaded.CACHE_TTL_SECONDS, 3600)
            finally:
                importlib.reload(config_mod)
    def test_resolve_url(self):
        url = db.resolve_url("postgresql+psycopg://u:p@h/db")
        self.assertEqual(url, "postgresql+psycopg://u:p@h/db")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.db")
            self.assertTrue(db.resolve_url(p).startswith("sqlite:///"))
            self.assertTrue(db.resolve_url(p).endswith("x.db"))

    def test_sqlite_url_form_works(self):
        with tempfile.TemporaryDirectory() as d:
            url = "sqlite:///" + os.path.join(d, "u.db")
            db.init_db(url)
            rid = db.create_run(url, "T", "Tech", "", "m")
            self.assertEqual([r["id"] for r in db.list_runs(url)], [rid])

    def test_import_sqlite_roundtrip(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.db")
            db.init_db(src)
            rid = db.create_run(src, "T", "Tech", "US", "m")
            aid = db.insert_article(src, rid, {"url": "https://x.com/a", "outlet": "x.com",
                                               "title": "T", "snippet": "S", "content": "S",
                                               "published": ""})
            db.insert_analysis(src, aid, {"factuality_score": 80, "bias_label": "Center",
                                          "bias_score": 0, "summary": "s", "key_claims": ["c"],
                                          "loaded_phrases": [], "verdict": "v"},
                               {"mbfc_factuality": "High", "mbfc_bias": "Center", "popularity_rank": 5})
            dst = "sqlite:///" + os.path.join(d, "dst.db")
            script = os.path.normpath(os.path.join(os.path.dirname(__file__), "..",
                                                   "scripts", "import_sqlite.py"))
            proc = subprocess.run(["uv", "run", "python", script,
                                   "--from", src, "--to", dst],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = db.fetch_run_evidence(dst, rid)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["bias_label"], "Center")


class TestGraph(unittest.TestCase):
    def test_checkpoint_recorded_for_resume(self):
        from spectrum_news import graph as graph_mod

        def fake_query(query, spec):
            return [{"url": "https://x.com/a", "outlet": "x.com", "title": "A",
                     "snippet": "s", "content": "s", "published": ""}]

        def fake_analyze(article, model, key="", temperature=0.2):
            return analyzer.heuristic_analysis(article)

        with tempfile.TemporaryDirectory() as d:
            db_url = os.path.join(d, "t.db")
            tid = "resume-probe"
            with graph_mod.checkpointer(os.path.join(d, "ckpt.db")) as saver:
                compiled = graph_mod.build_graph(search_query_fn=fake_query,
                                                 analyze_fn=fake_analyze).compile(checkpointer=saver)
                final = compiled.invoke({
                    "topic": "t", "category": "Tech", "country": "",
                    "model": "m", "search_model": "m", "max_articles": 3,
                    "temperature": 0.2, "db_url": db_url, "api_key": "",
                    "base_url": "https://x", "allowed_domains": [],
                    "cache_ttl": 3600, "use_cache": True,
                }, config={"configurable": {"thread_id": tid}})
                self.assertEqual(final["run_id"], 1)
                # A later session can pick up the recorded checkpoint by thread id.
                self.assertIsNotNone(
                    saver.get({"configurable": {"thread_id": tid}}))

    def test_pg_conninfo_conversion(self):
        from spectrum_news import graph as graph_mod
        self.assertEqual(graph_mod.pg_conninfo_for("postgresql+psycopg://u:p@h/db"),
                         "postgresql://u:p@h/db")
        self.assertTrue(graph_mod.pg_conninfo_for("data/x.db").startswith("sqlite:///"))


class TestTracing(unittest.TestCase):
    def test_disabled_without_keys(self):
        from spectrum_news import tracing
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(tracing.enabled())

    def test_observe_passthrough_when_disabled(self):
        from spectrum_news import tracing
        with mock.patch.object(tracing, "enabled", return_value=False):
            @tracing.observe("probe")
            def add(a, b=0):
                return a + b
            self.assertEqual(add(1, b=2), 3)

    def test_score_never_raises(self):
        from spectrum_news import tracing
        with mock.patch.object(tracing, "enabled", return_value=False):
            tracing.score("t", "s", 1.0)  # must not raise


class TestEvals(unittest.TestCase):
    def _evidence(self, **over):
        base = {"article": {"url": "https://bbc.com/a", "outlet": "bbc.com",
                            "title": "T", "snippet": "S"},
                "analysis": {"factuality_score": 80, "bias_label": "Center",
                             "bias_score": 0, "summary": "s", "key_claims": ["c"],
                             "loaded_phrases": [], "verdict": "v"}}
        base["analysis"].update(over)
        return [base]

    def test_trajectory_perfect_run(self):
        from spectrum_news import evals
        out = evals.trajectory_score({"allowed_domains": '["bbc.com"]'},
                                     self._evidence())
        self.assertEqual(out["score"], 100.0)

    def test_trajectory_empty_evidence(self):
        from spectrum_news import evals
        self.assertEqual(evals.trajectory_score({}, [])["score"], 0.0)

    def test_trajectory_catches_domain_violation_and_bad_ranges(self):
        from spectrum_news import evals
        out = evals.trajectory_score({"allowed_domains": '["bbc.com"]'},
                                     self._evidence(factuality_score=140))
        self.assertFalse(out["checks"]["scores_in_range"])
        self.assertLess(out["score"], 100.0)
        bad = self._evidence()
        bad[0]["article"]["url"] = "https://random-blog.example/x"
        out = evals.trajectory_score({"allowed_domains": '["bbc.com"]'}, bad)
        self.assertFalse(out["checks"]["domains_honored"])

    def test_judge_final_parses_scores(self):
        from spectrum_news import evals
        payload = '{"factuality_plausibility": 90, "bias_plausibility": 70, "rationale": "ok"}'
        m = mock.Mock()
        m.json.return_value = {"choices": [{"message": {"content": payload}}]}
        m.raise_for_status.return_value = None
        with mock.patch("requests.post", return_value=m):
            out = evals.judge_final({"title": "T"}, {"summary": "s"},
                                    model="j", api_key="k", base_url="https://x")
        self.assertEqual(out["factuality_plausibility"], 90)
        self.assertEqual(out["bias_plausibility"], 70)

    def test_judge_cli_no_llm_reports_and_passes(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            db.init_db(p)
            rid = db.create_run(p, "T", "Tech", "", "m")
            aid = db.insert_article(p, rid, {"url": "https://x.com/a", "outlet": "x.com",
                                             "title": "T", "snippet": "S", "content": "S",
                                             "published": ""})
            db.insert_analysis(p, aid, {"factuality_score": 80, "bias_label": "Center",
                                        "bias_score": 0, "summary": "s", "key_claims": ["c"],
                                        "loaded_phrases": [], "verdict": "v"},
                               {"mbfc_factuality": "High", "mbfc_bias": "Center",
                                "popularity_rank": 5})
            script = os.path.normpath(os.path.join(os.path.dirname(__file__), "..",
                                                   "scripts", "judge_eval.py"))
            proc = subprocess.run(["uv", "run", "python", script, "--db", p,
                                   "--no-llm", "--min-score", "50"],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('"avg_trajectory": 100.0', proc.stdout)


class TestAppSmoke(unittest.TestCase):
    """Headless Streamlit regression tests (AppTest). Catches script-level
    crashes such as duplicate widget IDs without launching a browser."""

    def _run_app(self):
        from streamlit.testing.v1 import AppTest
        app_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(config, "DATABASE_URL", os.path.join(tmp.name, "ui.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        return AppTest.from_file(app_path, default_timeout=30).run()

    def test_initial_render_has_no_exception(self):
        at = self._run_app()
        self.assertFalse(at.exception)

    def test_chip_fills_topic_and_category(self):
        at = self._run_app()
        at.button(key="chip_Politics").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["topic"], config.DEFAULT_PROMPTS["Politics"])
        self.assertEqual(at.session_state["category"], "Politics")
        self.assertEqual(at.session_state["country"], config.DEFAULT_COUNTRY)


if __name__ == "__main__":
    unittest.main()
