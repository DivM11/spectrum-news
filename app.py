"""Spectrum News — Streamlit front-end."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st

from spectrum_news import cache, config, db, pipeline

st.set_page_config(page_title="Spectrum News", page_icon="📰", layout="wide")

# ---- Pastel minimal theme (native widgets; compact metric type) ----
st.markdown("""<style>
.stApp { background-color: #FAF8F5; }
section[data-testid="stSidebar"] { background-color: #F3EFE7; }
[data-testid="stMetric"] {
    background: #FFFFFF; border: 1px solid #EAE1D3;
    border-radius: 12px; padding: 8px 14px; overflow: hidden;
}
[data-testid="stMetricLabel"] { font-size: 0.78rem; color: #8A7F6F; }
[data-testid="stMetricValue"] { font-size: 1.3rem; color: #4A4238; }
[data-testid="stExpander"] {
    background: #FFFFFF; border: 1px solid #EAE1D3; border-radius: 12px;
}
.stButton button { border-radius: 10px; }
h1, h2, h3 { color: #3E372E; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p { color: #4A4238; }
</style>""", unsafe_allow_html=True)

# ---- Sidebar: model config ----
st.sidebar.header("Model config")
preset = st.sidebar.selectbox("Rating model preset", config.MODEL_PRESETS, index=0)
with st.sidebar.expander("Custom rating model", expanded=False):
    custom = st.text_input("Rating model ID", value="", key="custom_rating_model",
                           help="Overrides the preset above when non-empty.")
MODEL = (custom.strip() or preset).strip() or config.RATING_MODEL
_search_presets = config.SEARCH_MODEL_PRESETS
_search_default = _search_presets.index(config.SEARCH_MODEL) if config.SEARCH_MODEL in _search_presets else 0
search_preset = st.sidebar.selectbox("Search model preset", _search_presets, index=_search_default)
with st.sidebar.expander("Custom search model", expanded=False):
    search_custom = st.text_input("Search model ID", value="", key="custom_search_model",
                                  help="Overrides the preset above when non-empty.")
SEARCH_MODEL = (search_custom.strip() or search_preset).strip() or config.SEARCH_MODEL
MAX_ARTICLES = st.sidebar.slider("Max articles", 3, 15, 9)
TEMPERATURE = st.sidebar.slider("Temperature", 0.0, 1.0, 0.2, 0.05)
st.sidebar.header("Outlets to search 🔴🟣🔵")
_outlet_options = [config.OUTLET_ALL, *config.OUTLET_CHOICES.keys()]
outlets = st.sidebar.multiselect(
    "Allowlist (All = every outlet)", _outlet_options, default=[config.OUTLET_ALL],
    help="Restrict web search to these outlets via allowed_domains. 'All' = unrestricted.",
)
ALLOWED_DOMAINS = config.outlet_domains(outlets)
_db_label = "Postgres" if "://" in str(config.DATABASE_URL) else f"`{config.DATABASE_URL}`"
st.sidebar.caption(f"DB: {_db_label}")
st.sidebar.caption(f"Search cache TTL: {config.CACHE_TTL_SECONDS}s")
if st.sidebar.button("Clear search cache"):
    removed = cache.clear(config.DATABASE_URL)
    st.sidebar.success(f"Cleared {removed} cached entr{'y' if removed == 1 else 'ies'}.")
has_or = bool(os.environ.get("OPENROUTER_API_KEY"))
st.sidebar.write(("✅ OpenRouter" if has_or else "⚠️ keyless (DDG + heuristic)"))

st.title("📰 Spectrum News")
st.caption("AI fact-checking + bias highlighting across outlets. Scores are estimates — open the sources.")

# ---- Default prompts (fixed chips, USA-focused) ----
if "topic" not in st.session_state:
    st.session_state.topic = ""
if "category" not in st.session_state:
    st.session_state.category = config.CATEGORIES[0]
if "country" not in st.session_state:
    st.session_state.country = config.DEFAULT_COUNTRY

st.caption("Try a USA default:")
chip_cols = st.columns(len(config.CATEGORIES))
for chip_col, cat in zip(chip_cols, config.CATEGORIES):
    if chip_col.button(cat, key=f"chip_{cat}", use_container_width=True):
        st.session_state.topic = config.DEFAULT_PROMPTS[cat]
        st.session_state.category = cat
        st.session_state.country = config.DEFAULT_COUNTRY
        st.rerun()

# ---- Inputs ----
col1, col2, col3 = st.columns([3, 2, 2])
with col1:
    topic = st.text_input("Topic", key="topic",
                          placeholder="e.g. central bank rate hike, Chandrayaan-4, EU AI Act")
with col2:
    category = st.selectbox("Category", config.CATEGORIES, key="category")
with col3:
    country = st.selectbox("Country filter", config.COUNTRY_PRESETS, key="country")
    country_free = st.text_input("...or free text", value="")
COUNTRY = (country_free.strip() or country).strip()

run_col, warm_col = st.columns([1, 1])
with run_col:
    run_btn = st.button("Run fact-check", type="primary", use_container_width=True,
                        disabled=not topic.strip())
with warm_col:
    warm_btn = st.button("Get the latest news", type="secondary", use_container_width=True,
                         help="Fetch and cache today's top stories across all 5 US categories.")

# ---- History ----
db.init_db(config.DATABASE_URL)
runs = db.list_runs(config.DATABASE_URL)
labels = {f"#{r['id']} · {r['topic']} [{r['category']}] ({r['model']})": r["id"] for r in runs}
sel = st.selectbox("History (reload past evidence set)", ["— new run —", *labels.keys()])

# ---- Lazy cache warming (explicit click only) ----
def _run_search(topic: str, category: str, country: str) -> dict:
    """Single call path for interactive + warm runs (same models, domains, TTL)."""
    return pipeline.run_search(
        topic, category, country, model=MODEL,
        search_model=(SEARCH_MODEL.strip() or MODEL),
        max_articles=MAX_ARTICLES, temperature=TEMPERATURE,
        db_url=config.DATABASE_URL,
        openrouter_key=os.environ.get("OPENROUTER_API_KEY", ""),
        allowed_domains=ALLOWED_DOMAINS,
        cache_ttl_seconds=config.CACHE_TTL_SECONDS,
    )


if warm_btn:
    defaults = list(config.DEFAULT_PROMPTS.items())
    progress = st.progress(0, text="Warming USA cache...")
    for i, (cat, prompt) in enumerate(defaults):
        _run_search(prompt, cat, config.DEFAULT_COUNTRY)
        progress.progress((i + 1) / len(defaults), text=f"Warmed {cat} ({i + 1}/{len(defaults)})")
    progress.empty()
    st.success("USA cache warmed — default topics now load instantly.")

if sel != "— new run —":
    rows = db.fetch_run_evidence(config.DATABASE_URL, labels[sel])
    st.subheader(f"Spectrum — run #{labels[sel]} ({len(rows)} articles)")
    _results = [{
        "article": {"url": r["url"], "outlet": r["outlet"], "title": r["title"],
                    "snippet": r["snippet"], "published": r["published"]},
        "profile": {"mbfc_factuality": r["mbfc_factuality"], "mbfc_bias": r["mbfc_bias"],
                    "popularity_rank": r["popularity_rank"]},
        "analysis": {"factuality_score": r["factuality_score"], "bias_label": r["bias_label"],
                     "bias_score": r["bias_score"], "summary": r["summary"],
                     "key_claims": json.loads(r["key_claims"] or "[]"),
                     "loaded_phrases": json.loads(r["loaded_phrases"] or "[]"),
                     "verdict": r["verdict"]},
    } for r in rows]
    render = _results
elif run_btn:
    with st.spinner("Searching outlets in parallel → profiling → analyzing…"):
        out = _run_search(topic.strip(), category, COUNTRY)
    st.success(f"Run #{out['run_id']}: {len(out['results'])} articles · search `{out['search_model']}` · rating `{MODEL}`")
    n_cached = sum(1 for r in out["results"] if r.get("cached"))
    if out.get("search_cache_hit"):
        st.caption("Search served from cache — same query, model, outlets, and article limit as a recent run.")
    if n_cached:
        st.caption(f"{n_cached}/{len(out['results'])} analyses served from cache.")
    render = out["results"]
else:
    render = None
    st.info("Enter a Topic, pick a Category, hit **Run fact-check**. Works keyless (DDG + heuristic); add `OPENROUTER_API_KEY` for web-search + LLM analysis.")

# ---- Spectrum view ----
if render is not None:
    if not render:
        st.warning("No articles found. Try a broader topic or different country.")
    else:
        st.subheader(f"Spectrum — left → center → right ({len(render)} articles)")
        with st.expander("What do these scores mean?", expanded=False):
            st.markdown(
                "- **Factuality (0-100):** how well the article's verifiable claims hold up. "
                "Thin snippets score lower. An estimate, not a truth certificate.\n"
                "- **Bias (-3..+3):** framing lean of *this article's* language, from far-left "
                "to far-right. Distinct from the outlet's overall reputation.\n"
                "- **MBFC:** the outlet's track record — factual-reporting level and political "
                "bias per Media Bias/Fact Check (curated list; `Unknown` = not covered).\n"
                "- **Popularity:** traffic rank (lower = more visited). Weighs reach vs niche."
            )
        # bias color bar
        cols = st.columns(len(render))
        for c, r in zip(cols, render):
            a, an, p = r["article"], r["analysis"], r["profile"]
            with c:
                st.metric(a["outlet"] or "unknown", f"{an['bias_label']}",
                          f"bias {an['bias_score']:+.1f} · fact {an['factuality_score']:.0f}",
                          help="Article framing lean and factuality estimate. Hover the metrics below for details.")
        st.divider()
        for r in render:
            a, an, p = r["article"], r["analysis"], r["profile"]
            with st.expander(f"[{an['bias_label']}] {a['title']} — {a['outlet']}", expanded=False):
                st.write(an["summary"])
                st.markdown(f"🔗 [{a['outlet']}]({a['url']})" + (f" · _{a['published']}_" if a.get("published") else ""))
                m1, m2, m3 = st.columns(3)
                m1.metric("Factuality", f"{an['factuality_score']:.0f}/100",
                          help="0-100 estimate of how well this article's verifiable claims hold up. "
                               "Lower when the snippet is thin. Not a truth certificate.")
                m2.metric("Bias", f"{an['bias_score']:+.1f}", an["bias_label"],
                          help="-3 (far-left) to +3 (far-right) framing lean of this article's "
                               "language. Different from the outlet's MBFC reputation.")
                pop = p.get("popularity_rank", 999999)
                m3.metric("MBFC", f"{p.get('mbfc_factuality', '?')} / {p.get('mbfc_bias', '?')}",
                          f"pop #{pop}" if pop < 999999 else "pop n/a",
                          help="Outlet track record from Media Bias/Fact Check (curated list; "
                               "Unknown = not covered) plus traffic rank — lower means more visited.")
                if an.get("key_claims"):
                    st.markdown("**Key claims:**")
                    for cl in an["key_claims"]:
                        st.markdown(f"- {cl}")
                if an.get("loaded_phrases"):
                    st.markdown("**⚠️ Loaded phrasing:** " + ", ".join(f"`{x}`" for x in an["loaded_phrases"]))
                st.caption(f"Verdict: {an['verdict']}")
