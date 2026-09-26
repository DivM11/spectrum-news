"""Spectrum News — Streamlit front-end."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st

from spectrum_news import config, db, pipeline

st.set_page_config(page_title="Spectrum News", page_icon="📰", layout="wide")

# ---- Sidebar: rating model config ----
st.sidebar.header("⚙️ Rating model")
preset = st.sidebar.selectbox("Model preset", config.MODEL_PRESETS, index=0)
custom = st.sidebar.text_input("Custom model ID (overrides preset)", value="")
MODEL = (custom.strip() or preset).strip() or config.RATING_MODEL
MAX_ARTICLES = st.sidebar.slider("Max articles", 3, 15, 9)
TEMPERATURE = st.sidebar.slider("Temperature", 0.0, 1.0, 0.2, 0.05)
st.sidebar.caption(f"DB: `{config.DB_PATH}`")
has_or = bool(os.environ.get("OPENROUTER_API_KEY"))
has_tav = bool(os.environ.get("TAVILY_API_KEY"))
st.sidebar.write(("✅" if has_or else "⚠️ keyless") + " OpenRouter")
st.sidebar.write(("✅" if has_tav else "⚠️ DDG fallback") + " Tavily")

st.title("📰 Spectrum News")
st.caption("AI fact-checking + bias highlighting across outlets. Scores are estimates — open the sources.")

# ---- Inputs ----
col1, col2, col3 = st.columns([3, 2, 2])
with col1:
    topic = st.text_input("Topic", placeholder="e.g. central bank rate hike, Chandrayaan-4, EU AI Act")
with col2:
    category = st.selectbox("Category", config.CATEGORIES, index=0)
with col3:
    country = st.selectbox("Country filter", config.COUNTRY_PRESETS, index=0)
    country_free = st.text_input("…or free text", value="")
COUNTRY = (country_free.strip() or country).strip()

run_btn = st.button("🔍 Run fact-check", type="primary", disabled=not topic.strip())

# ---- History ----
db.init_db(config.DB_PATH)
runs = db.list_runs(config.DB_PATH)
labels = {f"#{r['id']} · {r['topic']} [{r['category']}] ({r['model']})": r["id"] for r in runs}
sel = st.selectbox("History (reload past evidence set)", ["— new run —", *labels.keys()])

if sel != "— new run —":
    rows = db.fetch_run_evidence(config.DB_PATH, labels[sel])
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
        out = pipeline.run_search(
            topic.strip(), category, COUNTRY, model=MODEL,
            max_articles=MAX_ARTICLES, temperature=TEMPERATURE,
            db_path=config.DB_PATH,
            tavily_key=os.environ.get("TAVILY_API_KEY", ""),
            openrouter_key=os.environ.get("OPENROUTER_API_KEY", ""),
        )
    st.success(f"Run #{out['run_id']}: {len(out['results'])} articles · model `{MODEL}`")
    render = out["results"]
else:
    render = None
    st.info("Enter a Topic, pick a Category, hit **Run fact-check**. Works keyless (DDG + heuristic); add `TAVILY_API_KEY` + `OPENROUTER_API_KEY` for full quality.")

# ---- Spectrum view ----
if render is not None:
    if not render:
        st.warning("No articles found. Try a broader topic or different country.")
    else:
        st.subheader(f"Spectrum — left → center → right ({len(render)} articles)")
        # bias color bar
        cols = st.columns(len(render))
        for c, r in zip(cols, render):
            a, an, p = r["article"], r["analysis"], r["profile"]
            with c:
                st.metric(a["outlet"] or "unknown", f"{an['bias_label']}",
                          f"bias {an['bias_score']:+.1f} · fact {an['factuality_score']:.0f}")
        st.divider()
        for r in render:
            a, an, p = r["article"], r["analysis"], r["profile"]
            with st.expander(f"[{an['bias_label']}] {a['title']} — {a['outlet']}", expanded=False):
                st.write(an["summary"])
                st.markdown(f"🔗 [{a['outlet']}]({a['url']})" + (f" · _{a['published']}_" if a.get("published") else ""))
                m1, m2, m3 = st.columns(3)
                m1.metric("Factuality", f"{an['factuality_score']:.0f}/100")
                m2.metric("Bias", f"{an['bias_score']:+.1f}", an["bias_label"])
                pop = p.get("popularity_rank", 999999)
                m3.metric("MBFC", f"{p.get('mbfc_factuality', '?')} / {p.get('mbfc_bias', '?')}",
                          f"pop #{pop}" if pop < 999999 else "pop n/a")
                if an.get("key_claims"):
                    st.markdown("**Key claims:**")
                    for cl in an["key_claims"]:
                        st.markdown(f"- {cl}")
                if an.get("loaded_phrases"):
                    st.markdown("**⚠️ Loaded phrasing:** " + ", ".join(f"`{x}`" for x in an["loaded_phrases"]))
                st.caption(f"Verdict: {an['verdict']}")
