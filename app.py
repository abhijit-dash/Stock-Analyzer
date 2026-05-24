"""
Capex Guidance Analyzer — main Streamlit application.

Pages (routed via st.session_state.page):
  login        — unauthenticated landing
  home         — dashboard / quick stats
  screen       — build and run Screener.in custom screens
  results      — view / filter screened companies
  analysis     — fetch transcripts + run AI analysis per company
  rankings     — final ranked leaderboard with charts

Run:
    streamlit run app.py
"""
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

import modules.database as db
from config import PREDEFINED_SCREENS, SCORING_WEIGHTS, SCREENER_USERNAME, SCREENER_PASSWORD
from modules.utils import fmt_cr, fmt_num, fmt_pct, score_color, score_label

# ── Page config (must be FIRST st call) ──────────────────────────────────────
st.set_page_config(
    page_title="Capex Guidance Analyzer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ---- Global dark theme tweaks ---- */
[data-testid="stAppViewContainer"] { background: #0a0e1a; }
[data-testid="stSidebar"]          { background: #0f1423; border-right: 1px solid #1e2a45; }
[data-testid="stHeader"]           { background: transparent; }

/* ---- Metric cards ---- */
[data-testid="metric-container"] {
    background: linear-gradient(135deg,#141927,#1c2440);
    border: 1px solid #243050;
    border-radius: 10px;
    padding: 0.8rem 1rem;
}

/* ---- Sidebar nav buttons ---- */
section[data-testid="stSidebar"] .stButton>button {
    background: transparent;
    border: 1px solid #243050;
    color: #c8d8f0;
    text-align: left;
    border-radius: 6px;
    padding: 0.45rem 0.9rem;
    width: 100%;
    transition: background 0.15s;
}
section[data-testid="stSidebar"] .stButton>button:hover {
    background: #1a2540;
    border-color: #3a7bd5;
    color: #ffffff;
}

/* ---- Score badges ---- */
.badge-green { color:#00e676; font-weight:700; font-size:1.15rem; }
.badge-amber { color:#ffb300; font-weight:700; font-size:1.15rem; }
.badge-red   { color:#ff5252; font-weight:700; font-size:1.15rem; }

/* ---- Company cards ---- */
.company-card {
    background: #141927;
    border: 1px solid #243050;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
}
.company-card h4 { margin: 0 0 0.3rem 0; color: #e0ecff; }
.company-card .sub { color: #7a94b8; font-size: 0.85rem; }

/* ---- Section headers ---- */
.section-header {
    color: #4fc3f7;
    font-size: 1rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 1.2rem 0 0.4rem 0;
}

/* ---- Tables ---- */
thead { background: #141927 !important; }

/* ---- Tabs ---- */
[data-testid="stTabs"] button { font-size:0.9rem; }

/* ---- Scrollable text area ---- */
.transcript-box {
    background:#0d1120; border:1px solid #243050; border-radius:8px;
    padding:1rem; max-height:400px; overflow-y:auto;
    font-family:monospace; font-size:0.82rem; color:#a0b8d8; white-space:pre-wrap;
}
</style>
""", unsafe_allow_html=True)


# ── Session state bootstrap ───────────────────────────────────────────────────

def _init_state() -> None:
    defaults: Dict[str, Any] = {
        "logged_in":              False,
        "cookies":                {},
        "page":                   "home",
        "screen_results":         [],
        "screen_name":            "",
        "screen_query":           "",
        "company_details":        {},
        "analysis_results":       {},
        "gb_metrics":             {},
        "current_ticker":         None,
        "fetch_log":              [],
        "_auto_login_attempted":  False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Auto-login using .env credentials (runs only once per session)
    if (
        not st.session_state.logged_in
        and not st.session_state._auto_login_attempted
        and SCREENER_USERNAME
        and SCREENER_PASSWORD
    ):
        st.session_state._auto_login_attempted = True
        try:
            from modules.screener_login import load_session, verify_session, login_screener
            # Try cached session first (fast path — no Playwright needed)
            cached = load_session()
            if cached and verify_session(cached):
                st.session_state.logged_in = True
                st.session_state.cookies   = cached
            else:
                # Full Playwright login
                cookies = login_screener(SCREENER_USERNAME, SCREENER_PASSWORD)
                if cookies:
                    st.session_state.logged_in = True
                    st.session_state.cookies   = cookies
        except Exception:
            pass  # fall through to manual login form


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _sidebar() -> None:
    with st.sidebar:
        st.markdown("## 📈 Capex Guidance")
        st.markdown("<small style='color:#5a7a9a'>Indian CAPEX Stock Analyzer</small>",
                    unsafe_allow_html=True)
        st.markdown("---")

        if not st.session_state.logged_in:
            _sidebar_login()
        else:
            _sidebar_nav()
            st.markdown("---")
            _sidebar_session_info()


def _sidebar_login() -> None:
    st.markdown("### 🔐 Login")
    st.caption("Enter your Screener.in credentials")
    with st.form("sidebar_login"):
        email    = st.text_input("Email / Username", placeholder="you@email.com")
        password = st.text_input("Password", type="password")
        submit   = st.form_submit_button("Login →", use_container_width=True)
    if submit:
        _do_login(email, password)


def _sidebar_nav() -> None:
    st.markdown("### Navigate")
    nav_items = [
        ("home",     "🏠  Dashboard"),
        ("screen",   "🔍  Screen Builder"),
        ("results",  "📊  Results"),
        ("analysis", "🤖  AI Analysis"),
        ("rankings", "🏆  Rankings"),
    ]
    for page_key, label in nav_items:
        active = st.session_state.page == page_key
        btn_type = "primary" if active else "secondary"
        if st.button(label, key=f"nav_{page_key}",
                     use_container_width=True, type=btn_type):
            st.session_state.page = page_key
            st.rerun()


def _sidebar_session_info() -> None:
    n_results   = len(st.session_state.screen_results)
    n_analysed  = len(st.session_state.analysis_results)
    st.metric("Companies in Screen", n_results)
    st.metric("Analysed",            n_analysed)
    st.markdown("---")
    if st.button("🚪 Logout", use_container_width=True):
        for k in ("logged_in", "cookies", "screen_results",
                  "analysis_results", "company_details"):
            st.session_state[k] = {} if isinstance(st.session_state[k], dict) else (
                [] if isinstance(st.session_state[k], list) else False
            )
        st.session_state.logged_in = False
        st.session_state.page      = "home"
        st.rerun()


# ── Login handler ─────────────────────────────────────────────────────────────

def _do_login(email: str, password: str) -> None:
    if not email or not password:
        st.sidebar.error("Enter both email and password.")
        return
    with st.spinner("Logging into Screener.in…"):
        try:
            from modules.screener_login import login_screener
            cookies = login_screener(email, password)
            if cookies:
                st.session_state.logged_in = True
                st.session_state.cookies   = cookies
                st.session_state.page      = "home"
                st.sidebar.success("✓ Logged in!")
                time.sleep(0.8)
                st.rerun()
            else:
                st.sidebar.error("Login failed — check credentials.")
        except Exception as exc:
            st.sidebar.error(f"Error: {exc}")


# ── Page: Home / Dashboard ────────────────────────────────────────────────────

def _page_home() -> None:
    st.title("📈 Capex Guidance Analyzer")
    st.markdown(
        "**AI-powered equity research for Indian CAPEX-led growth stories.**  \n"
        "Identify companies where Gross Block is compounding, management is guiding strongly, "
        "and future earnings growth probability is high."
    )

    if not st.session_state.logged_in:
        st.info("👈 Login with your Screener.in credentials in the sidebar to get started.")
        _render_feature_cards()
        return

    # ── Quick stats ───────────────────────────────────────────────────────
    companies  = db.get_all_companies()
    analyses   = db.get_all_analyses()
    rankings   = db.get_rankings()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies in DB", len(companies))
    c2.metric("Analysed", len(set(a["ticker"] for a in analyses)))
    if analyses:
        avg_score = sum(a.get("guidance_score") or 0 for a in analyses) / len(analyses)
        c3.metric("Avg Guidance Score", f"{avg_score:.1f} / 10")
    else:
        c3.metric("Avg Guidance Score", "—")
    if rankings:
        c4.metric("Top Score", f"{rankings[0]['total_score']:.0f} / 100")
    else:
        c4.metric("Top Score", "—")

    # ── Top 5 companies ───────────────────────────────────────────────────
    if rankings:
        st.markdown("### 🏆 Current Top 5 Companies")
        _render_ranking_table(rankings[:5])

    # ── Quick-start guide ─────────────────────────────────────────────────
    with st.expander("📖 How to use this app", expanded=not rankings):
        st.markdown("""
1. **Screen Builder** → choose a predefined CAPEX screen or write a custom Screener.in query.
2. **Results** → review the screened companies; the app fetches their balance sheet
   (Gross Block, CWIP, Net Block) to highlight true CAPEX cycles.
3. **AI Analysis** → select companies to fetch their latest concall transcript and
   run a deep AI analysis using Claude / GPT-4o.
4. **Rankings** → companies are ranked by a composite score combining AI guidance
   quality, CAPEX execution, management confidence, and balance sheet expansion.

> **Note:** CAPEX intensity is determined using Gross Block growth, CWIP trends, and
> Net Block expansion — NOT the "Capex last year" field.
        """)


def _render_feature_cards() -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
<div class="company-card">
<h4>🔍 Custom Screens</h4>
<p class="sub">Run Screener.in queries filtered by Gross Block growth, CWIP, ROCE, Sales growth and more.</p>
</div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""
<div class="company-card">
<h4>🤖 AI Analysis</h4>
<p class="sub">Claude / GPT-4o analyses concall transcripts for revenue guidance, CAPEX plans, and management confidence.</p>
</div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""
<div class="company-card">
<h4>🏆 Rankings</h4>
<p class="sub">Companies ranked by composite score: guidance quality, CAPEX monetisation, and growth probability.</p>
</div>""", unsafe_allow_html=True)


# ── Page: Screen Builder ──────────────────────────────────────────────────────

def _page_screen() -> None:
    st.title("🔍 Screen Builder")
    st.caption("Build a Screener.in query to find CAPEX-cycle companies. "
               "Balance sheet expansion (Gross Block / CWIP) is fetched separately for every result.")

    tab_pre, tab_custom = st.tabs(["📋 Predefined Screens", "✏️ Custom Query"])

    # ── Predefined ────────────────────────────────────────────────────────
    with tab_pre:
        st.markdown("Select a predefined screen template:")
        chosen_name = st.selectbox(
            "Screen", list(PREDEFINED_SCREENS.keys()), label_visibility="collapsed"
        )
        st.code(PREDEFINED_SCREENS[chosen_name], language="sql")

        with st.expander("ℹ️ Available Screener.in fields"):
            st.markdown("""
| Field | Example |
|---|---|
| `Sales growth 3Years` | `Sales growth 3Years > 15` |
| `Profit growth 3Years` | `Profit growth 3Years > 15` |
| `ROCE` | `ROCE > 15` |
| `OPM` | `OPM > 15` |
| `Debt to equity` | `Debt to equity < 1` |
| `Market Capitalization` | `Market Capitalization > 500` |
| `CWIP` | `CWIP > 100` |
| `Return on capital employed` | `Return on capital employed > 15` |
| `Sales growth` | `Sales growth > 15` |
| `Profit growth` | `Profit growth > 20` |
            """)

        n_results = st.number_input("Max results", 10, 100, 50, step=10)
        if st.button("▶ Run Screen", type="primary", use_container_width=True):
            _execute_screen(chosen_name, PREDEFINED_SCREENS[chosen_name], int(n_results))

    # ── Custom ────────────────────────────────────────────────────────────
    with tab_custom:
        st.markdown("Write a Screener.in query (AND / OR operators supported):")
        custom_query = st.text_area(
            "Custom query",
            placeholder=(
                "Sales growth 3Years > 15 AND ROCE > 15 AND CWIP > 50 AND "
                "Market Capitalization > 500"
            ),
            height=120,
            label_visibility="collapsed",
        )
        custom_name  = st.text_input("Screen name (optional)", value="My CAPEX Screen")
        n_custom     = st.number_input("Max results ", 10, 100, 50, step=10)
        if st.button("▶ Run Custom Screen", type="primary", use_container_width=True):
            if custom_query.strip():
                _execute_screen(
                    custom_name or "Custom Screen",
                    custom_query.strip(),
                    int(n_custom),
                )
            else:
                st.warning("Enter a query first.")


def _execute_screen(name: str, query: str, limit: int) -> None:
    from modules.screener_scraper import run_screen
    with st.spinner(f"Running screen: {name}…"):
        results = run_screen(query, st.session_state.cookies, limit=limit)

    if not results:
        st.error("Screen returned no results. Check your query or login session.")
        return

    # Save to DB and session
    for r in results:
        db.upsert_company({
            "ticker":       r.get("ticker", ""),
            "name":         r.get("name", ""),
            "sector":       r.get("sector", ""),
            "market_cap":   r.get("market_cap"),
            "screener_url": r.get("screener_url", ""),
            "sales_growth": r.get("sales_growth"),
            "roce":         r.get("roce"),
            "pe_ratio":     r.get("pe_ratio"),
        })

    db.save_screen_run(name, query, results)

    st.session_state.screen_results = results
    st.session_state.screen_name    = name
    st.session_state.screen_query   = query
    st.session_state.page           = "results"
    st.success(f"✓ Found {len(results)} companies. Redirecting to Results…")
    time.sleep(0.8)
    st.rerun()


# ── Page: Results ─────────────────────────────────────────────────────────────

def _page_results() -> None:
    st.title("📊 Screen Results")
    results: List[Dict] = st.session_state.screen_results

    if not results:
        st.info("No results yet — run a screen first.")
        if st.button("Go to Screen Builder"):
            st.session_state.page = "screen"
            st.rerun()
        return

    st.caption(f"Screen: **{st.session_state.screen_name}**  |  {len(results)} companies")

    # ── Filters ───────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        search_txt = st.text_input("🔍 Search company", "")
    with col_f2:
        min_roce   = st.number_input("Min ROCE (%)", 0.0, 100.0, 0.0, step=5.0)
    with col_f3:
        min_sales  = st.number_input("Min Sales Growth (%)", 0.0, 200.0, 0.0, step=5.0)

    filtered = [
        r for r in results
        if (not search_txt or search_txt.lower() in r.get("name", "").lower()
                              or search_txt.upper() in r.get("ticker", "").upper())
        and (r.get("roce") or 0) >= min_roce
        and (r.get("sales_growth") or 0) >= min_sales
    ]

    # ── Balance sheet fetch panel ─────────────────────────────────────────
    with st.expander("⚙️ Fetch Gross Block / CWIP data for all results", expanded=False):
        st.markdown(
            "This will visit each company page on Screener.in to extract "
            "**Gross Block history**, **Net Block**, **CWIP**, and **Depreciation** trends. "
            "This takes ~2-4 seconds per company."
        )
        if st.button("Fetch Balance Sheet Data", type="primary"):
            _fetch_balance_sheets(filtered)

    # ── Results table ─────────────────────────────────────────────────────
    if filtered:
        df = _build_results_df(filtered)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Name":         st.column_config.TextColumn(width="large"),
                "Market Cap":   st.column_config.TextColumn(width="medium"),
                "ROCE %":       st.column_config.NumberColumn(format="%.1f"),
                "Sales Gr %":   st.column_config.NumberColumn(format="%.1f"),
                "GB Growth %":  st.column_config.NumberColumn(format="%.1f"),
                "CWIP (Cr)":    st.column_config.NumberColumn(format="%.0f"),
                "Screener":     st.column_config.LinkColumn(width="small"),
            },
        )

        # ── Export ────────────────────────────────────────────────────────
        csv = df.to_csv(index=False).encode()
        st.download_button(
            "⬇ Export CSV", csv, "screen_results.csv", "text/csv", use_container_width=True
        )

        # ── Proceed to analysis ───────────────────────────────────────────
        st.markdown("---")
        tickers_for_analysis = [r["ticker"] for r in filtered]
        col_a1, col_a2 = st.columns([3, 1])
        with col_a1:
            selected = st.multiselect(
                "Select companies for AI analysis",
                tickers_for_analysis,
                default=tickers_for_analysis[:5],
                format_func=lambda t: f"{t} — {next((r['name'] for r in filtered if r['ticker']==t), t)}",
            )
        with col_a2:
            if st.button("Analyse Selected →", type="primary", use_container_width=True):
                st.session_state.analysis_queue = selected
                st.session_state.page = "analysis"
                st.rerun()
    else:
        st.info("No companies match the current filters.")


def _build_results_df(results: List[Dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        gb_m = st.session_state.gb_metrics.get(r.get("ticker", ""), {})
        rows.append({
            "Ticker":       r.get("ticker", ""),
            "Name":         r.get("name", ""),
            "Sector":       r.get("sector", ""),
            "Market Cap":   fmt_cr(r.get("market_cap")),
            "ROCE %":       r.get("roce"),
            "Sales Gr %":   r.get("sales_growth"),
            "GB Growth %":  gb_m.get("gross_block_3y_cagr"),
            "CWIP (Cr)":    gb_m.get("cwip_latest"),
            "Screener":     r.get("screener_url", ""),
        })
    return pd.DataFrame(rows)


def _fetch_balance_sheets(companies: List[Dict]) -> None:
    from modules.screener_scraper import compute_gross_block_growth, fetch_company_data
    progress = st.progress(0)
    status   = st.empty()
    n = len(companies)
    for i, company in enumerate(companies):
        ticker = company.get("ticker", "")
        status.text(f"Fetching {ticker} ({i+1}/{n})…")
        data = fetch_company_data(ticker, st.session_state.cookies)
        if data and "error" not in data:
            history = data.get("gross_block_history", [])
            metrics = compute_gross_block_growth(history)
            st.session_state.gb_metrics[ticker] = metrics
            st.session_state.company_details[ticker] = data
            db.save_gross_block_history(ticker, history)
        progress.progress((i + 1) / n)
    status.text("✓ Done")
    st.success("Balance sheet data fetched successfully.")
    st.rerun()


# ── Page: AI Analysis ─────────────────────────────────────────────────────────

def _page_analysis() -> None:
    st.title("🤖 AI Analysis")
    st.caption(
        "Fetch the latest concall transcript for each company, extract text, "
        "and run an AI analysis to score guidance quality and CAPEX execution."
    )

    # Company selector
    all_tickers = [r["ticker"] for r in st.session_state.screen_results]
    preselect   = getattr(st.session_state, "analysis_queue", []) or all_tickers[:5]

    col_s1, col_s2 = st.columns([4, 1])
    with col_s1:
        tickers = st.multiselect(
            "Companies to analyse",
            all_tickers if all_tickers else list(db.get_all_companies()),
            default=[t for t in preselect if t in (all_tickers or [])],
        )
    with col_s2:
        run_btn = st.button("▶ Run Analysis", type="primary", use_container_width=True)

    if run_btn and tickers:
        _run_analysis_pipeline(tickers)

    # ── Show existing results ─────────────────────────────────────────────
    analyses = db.get_all_analyses()
    if not analyses:
        st.info("No analyses yet. Select companies and click 'Run Analysis'.")
        return

    st.markdown("---")
    st.markdown("### Results")

    ticker_filter = st.selectbox(
        "View analysis for",
        ["All"] + list(set(a["ticker"] for a in analyses)),
    )
    filtered_analyses = (
        analyses if ticker_filter == "All"
        else [a for a in analyses if a["ticker"] == ticker_filter]
    )

    for analysis in filtered_analyses[:20]:
        _render_analysis_card(analysis)


def _run_analysis_pipeline(tickers: List[str]) -> None:
    from modules.ai_analyzer import analyze_transcript
    from modules.scoring_engine import score_company
    from modules.text_extractor import extract_text
    from modules.transcript_fetcher import fetch_latest_transcript

    progress = st.progress(0)
    log_box  = st.empty()
    n        = len(tickers)
    log_msgs: List[str] = []

    def _log(msg: str) -> None:
        log_msgs.append(msg)
        log_box.markdown("\n".join(f"• {m}" for m in log_msgs[-8:]))

    for i, ticker in enumerate(tickers):
        _log(f"**{ticker}** — fetching documents…")

        # ── Get document links ─────────────────────────────────────────
        company_data = st.session_state.company_details.get(ticker)
        if not company_data:
            from modules.screener_scraper import fetch_company_data
            company_data = fetch_company_data(ticker, st.session_state.cookies)
            st.session_state.company_details[ticker] = company_data or {}

        doc_links = (company_data or {}).get("document_links", [])
        company_name = (company_data or {}).get("name", ticker)

        if not doc_links:
            _log(f"  ⚠ No document links found for {ticker}")
            progress.progress((i + 1) / n)
            continue

        # ── Download transcript ────────────────────────────────────────
        _log("  Downloading transcript…")
        doc = fetch_latest_transcript(ticker, doc_links, st.session_state.cookies)
        if not doc:
            _log(f"  ⚠ Could not download transcript for {ticker}")
            progress.progress((i + 1) / n)
            continue

        tr_id = db.upsert_transcript({
            "ticker":          ticker,
            "doc_type":        doc["doc_type"],
            "title":           doc["title"],
            "url":             doc["url"],
            "doc_date":        doc["doc_date"],
            "local_path":      doc["local_path"],
            "download_status": "downloaded",
        })

        # ── Extract text ───────────────────────────────────────────────
        _log("  Extracting text…")
        local_path = Path(doc["local_path"])
        text = extract_text(local_path)
        if not text:
            _log(f"  ⚠ Text extraction failed for {ticker}")
            progress.progress((i + 1) / n)
            continue

        db.upsert_transcript({"url": doc["url"], "extracted_text": text,
                               "download_status": "extracted",
                               "ticker": ticker, "doc_type": doc["doc_type"],
                               "title": doc["title"], "doc_date": doc["doc_date"],
                               "local_path": doc["local_path"]})

        # ── AI analysis ────────────────────────────────────────────────
        _log(f"  Running AI analysis ({len(text):,} chars)…")
        try:
            analysis = analyze_transcript(text, company_name, ticker)
        except RuntimeError as exc:
            err_str = str(exc)
            _log(f"  ✗ AI error: {err_str}")
            if "credits" in err_str.lower() or "billing" in err_str.lower():
                st.error(
                    "**Anthropic API has no credits.** "
                    "Please top up at https://console.anthropic.com/settings/billing "
                    "and retry.",
                    icon="💳",
                )
                break  # Stop pipeline — all subsequent calls will fail too
            progress.progress((i + 1) / n)
            continue
        except Exception as exc:
            _log(f"  ✗ AI error: {exc}")
            progress.progress((i + 1) / n)
            continue

        analysis["transcript_id"] = tr_id
        db.save_analysis(analysis)

        # ── Score ──────────────────────────────────────────────────────
        gb_metrics = st.session_state.gb_metrics.get(ticker, {})
        score_data = score_company(analysis, gb_metrics)
        db.upsert_score(score_data)

        st.session_state.analysis_results[ticker] = analysis
        _log(f"  ✓ Score: {score_data['total_score']:.0f}/100")
        progress.progress((i + 1) / n)

    st.success(f"Analysis complete for {n} company/companies.")
    st.rerun()


def _render_analysis_card(analysis: Dict[str, Any]) -> None:
    ticker      = analysis.get("ticker", "")
    name        = analysis.get("company_name") or analysis.get("name", ticker)
    total       = float(analysis.get("total_score") or analysis.get("guidance_score") or 0)
    capex_sc    = float(analysis.get("capex_score") or 0)
    guidance_sc = float(analysis.get("guidance_score") or 0)
    prod_sc     = float(analysis.get("new_product_score") or 0)
    tone        = (analysis.get("management_tone") or "neutral").replace("_", " ").title()
    label       = score_label(total)

    with st.expander(
        f"**{name}** ({ticker})  ·  Score: {total:.1f}/10 [{label}]  ·  {tone}",
        expanded=False,
    ):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Score",    f"{total:.1f}/10")
        col2.metric("CAPEX Score",    f"{capex_sc:.1f}/10")
        col3.metric("Guidance Score", f"{guidance_sc:.1f}/10")
        col4.metric("New Products",   f"{prod_sc:.1f}/10")

        tabs = st.tabs(["📝 Summary", "🏗️ CAPEX Plans",
                         "📈 Revenue Guidance", "🚀 New Products",
                         "🔮 1-Year Outlook", "⚠️ Risks"])

        with tabs[0]:
            st.markdown(analysis.get("summary", "—"))

        with tabs[1]:
            cp = analysis.get("capex_plans", {})
            if isinstance(cp, str):
                try:
                    cp = json.loads(cp)
                except Exception:
                    cp = {"description": cp}
            if cp:
                if cp.get("description"):
                    st.markdown(f"**Plan:** {cp['description']}")
                if cp.get("amount_crores"):
                    st.markdown(f"**Amount:** ₹{cp['amount_crores']:,.0f} Cr")
                if cp.get("timeline"):
                    st.markdown(f"**Timeline:** {cp['timeline']}")
                if cp.get("commissioning"):
                    st.markdown(f"**Commissioning:** {cp['commissioning']}")
                if cp.get("purpose"):
                    st.markdown(f"**Purpose:** {cp['purpose']}")
            else:
                st.info("No specific CAPEX plans mentioned in transcript.")

        with tabs[2]:
            rg = analysis.get("revenue_guidance", {})
            if isinstance(rg, str):
                try:
                    rg = json.loads(rg)
                except Exception:
                    rg = {"description": rg}
            if rg:
                if rg.get("description"):
                    st.markdown(f"**Guidance:** {rg['description']}")
                if rg.get("growth_target"):
                    st.markdown(f"**Target:** {rg['growth_target']}")
                if rg.get("timeframe"):
                    st.markdown(f"**Timeframe:** {rg['timeframe']}")
                if rg.get("confidence"):
                    st.markdown(f"**Confidence:** {rg['confidence'].title()}")
            else:
                st.info("No specific revenue guidance mentioned.")

        with tabs[3]:
            products = analysis.get("new_products", [])
            if isinstance(products, str):
                try:
                    products = json.loads(products)
                except Exception:
                    products = [products]
            if products:
                for p in products:
                    st.markdown(f"🚀 {p}")
            else:
                st.info("No new product launches mentioned.")

        with tabs[4]:
            st.markdown(analysis.get("one_year_outlook") or analysis.get("future_outlook") or "—")

        with tabs[5]:
            risks = analysis.get("key_risks") or analysis.get("risks", [])
            if isinstance(risks, str):
                try:
                    risks = json.loads(risks)
                except Exception:
                    risks = [risks]
            for r in risks:
                st.markdown(f"🔴 {r}")


def _render_radar_chart(scores: Dict[str, Any], ticker: str) -> None:
    from modules.scoring_engine import radar_data
    rd = radar_data(scores)
    labels = rd["labels"] + [rd["labels"][0]]
    values = rd["values"] + [rd["values"][0]]

    fig = go.Figure(go.Scatterpolar(
        r=values, theta=labels,
        fill="toself",
        fillcolor="rgba(0,180,216,0.15)",
        line=dict(color="#00b4d8", width=2),
        marker=dict(size=5, color="#00b4d8"),
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100],
                            tickfont=dict(color="#7a94b8", size=9),
                            gridcolor="#1e2a45"),
            angularaxis=dict(tickfont=dict(color="#c0d4f0", size=9),
                             gridcolor="#1e2a45"),
            bgcolor="#0a0e1a",
        ),
        paper_bgcolor="#0a0e1a",
        plot_bgcolor="#0a0e1a",
        showlegend=False,
        height=320,
        margin=dict(l=30, r=30, t=30, b=30),
        title=dict(text=f"{ticker} — Score Radar", font=dict(color="#c0d4f0", size=13)),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"radar_{ticker}")


# ── Page: Rankings ────────────────────────────────────────────────────────────

def _page_rankings() -> None:
    st.title("🏆 Rankings — Top CAPEX Guidance Stocks")
    rankings = db.get_rankings()

    if not rankings:
        st.info("No ranked companies yet. Run AI analysis first.")
        if st.button("Go to Analysis"):
            st.session_state.page = "analysis"
            st.rerun()
        return

    # ── Filters ───────────────────────────────────────────────────────────
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        sectors = ["All"] + sorted(set(r.get("sector", "Unknown") for r in rankings
                                       if r.get("sector")))
        sector_filter = st.selectbox("Filter by Sector", sectors)
    with col_f2:
        min_total = st.slider("Min Total Score", 0, 100, 0)

    filtered = [
        r for r in rankings
        if (sector_filter == "All" or r.get("sector") == sector_filter)
        and r.get("total_score", 0) >= min_total
    ]

    # ── Summary metrics ───────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ranked Companies", len(filtered))
    if filtered:
        c2.metric("Avg Total Score",   f"{sum(r['total_score'] or 0 for r in filtered)/len(filtered):.1f}")
        top = filtered[0]
        c3.metric("Top Company",       f"{top.get('name', top.get('ticker', ''))}")
        c4.metric("Top Score",         f"{top.get('total_score', 0):.0f}/100")

    st.markdown("---")

    # ── Bar chart ─────────────────────────────────────────────────────────
    top_n = filtered[:15]
    if top_n:
        fig = go.Figure(go.Bar(
            y=[r.get("name", r.get("ticker", ""))[:25] for r in top_n],
            x=[r.get("total_score", 0) for r in top_n],
            orientation="h",
            marker=dict(
                color=[r.get("total_score", 0) for r in top_n],
                colorscale=[[0, "#ff5252"], [0.5, "#ffb300"], [1, "#00e676"]],
                cmin=0, cmax=100,
            ),
            text=[f"{r.get('total_score',0):.0f}" for r in top_n],
            textposition="outside",
        ))
        fig.update_layout(
            title="Top 15 by Composite Score",
            xaxis=dict(range=[0, 110], title="Score (0-100)",
                       gridcolor="#1e2a45", color="#7a94b8"),
            yaxis=dict(autorange="reversed", color="#c0d4f0"),
            paper_bgcolor="#0a0e1a",
            plot_bgcolor="#0a0e1a",
            font=dict(color="#c0d4f0"),
            height=max(300, len(top_n) * 38 + 80),
            margin=dict(l=10, r=60, t=50, b=30),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Ranked table ──────────────────────────────────────────────────────
    st.markdown("### Full Leaderboard")
    _render_ranking_table(filtered)

    # ── Export ────────────────────────────────────────────────────────────
    if filtered:
        df_exp = pd.DataFrame([{
            "Rank":            r.get("rank", ""),
            "Ticker":          r.get("ticker", ""),
            "Name":            r.get("name", ""),
            "Sector":          r.get("sector", ""),
            "Total Score":     r.get("total_score", 0),
            "Future Growth":   r.get("future_growth_score", 0),
            "CAPEX Monetz":    r.get("capex_monetization_score", 0),
            "AI Conviction":   r.get("ai_conviction_score", 0),
            "Risk Score":      r.get("risk_score", 0),
            "Market Cap":      r.get("market_cap", ""),
            "Sales Growth %":  r.get("sales_growth", ""),
            "ROCE %":          r.get("roce", ""),
            "Mgmt Tone":       r.get("management_tone", ""),
        } for r in filtered])
        csv = df_exp.to_csv(index=False).encode()
        st.download_button(
            "⬇ Export Rankings CSV", csv, "capex_rankings.csv",
            "text/csv", use_container_width=True
        )

    # ── Detail cards ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Company Detail Cards")
    for r in filtered[:10]:
        _render_ranking_card(r)


def _render_ranking_table(rankings: List[Dict]) -> None:
    rows = []
    for r in rankings:
        score = r.get("total_score", 0) or 0
        kg = r.get("key_guidance") or {}
        if isinstance(kg, str):
            try:
                kg = json.loads(kg)
            except Exception:
                kg = {}
        capex_s  = kg.get("capex_score", 0) or 0
        guid_s   = (r.get("ai_guidance_score") or 0)
        prod_s   = kg.get("new_product_score", 0) or 0
        rows.append({
            "#":             r.get("rank", ""),
            "Ticker":        r.get("ticker", ""),
            "Name":          (r.get("name") or "")[:28],
            "Total (0-100)": f"{score:.0f}",
            "CAPEX Score":   f"{capex_s:.1f}",
            "Guidance":      f"{guid_s:.1f}",
            "New Products":  f"{prod_s:.1f}",
            "Tone":          (r.get("management_tone") or "").replace("_", " ").title(),
            "Mkt Cap Cr":    fmt_cr(r.get("market_cap")),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _render_ranking_card(r: Dict[str, Any]) -> None:
    ticker  = r.get("ticker", "")
    name    = r.get("name", ticker)
    score   = r.get("total_score", 0) or 0
    color   = score_color(score / 10)
    summary = r.get("summary", "")

    kg = r.get("key_guidance") or {}
    if isinstance(kg, str):
        try:
            kg = json.loads(kg)
        except Exception:
            kg = {}

    with st.expander(
        f"#{r.get('rank','-')}  **{name}** ({ticker})  ·  "
        f"<span style='color:{color}'>{score:.0f}/100</span>",
        expanded=False,
    ):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Score",  f"{score:.0f}/100")
        c2.metric("CAPEX Score",  f"{kg.get('capex_score', 0) or 0:.1f}/10")
        c3.metric("Guidance",     f"{r.get('ai_guidance_score', 0) or 0:.1f}/10")
        c4.metric("New Products", f"{kg.get('new_product_score', 0) or 0:.1f}/10")

        if summary:
            st.markdown(f"**Summary:** {summary[:500]}{'…' if len(summary or '') > 500 else ''}")

        # CAPEX Plans
        cp = kg.get("capex_plans") or {}
        if cp and isinstance(cp, dict) and cp.get("description"):
            st.markdown("**CAPEX Plans:**")
            st.markdown(f"- {cp.get('description', '')}")
            if cp.get("amount_crores"):
                st.markdown(f"- Amount: ₹{cp['amount_crores']:,.0f} Cr")
            if cp.get("timeline"):
                st.markdown(f"- Timeline: {cp['timeline']}")
            if cp.get("commissioning"):
                st.markdown(f"- Commissioning: {cp['commissioning']}")

        # Revenue Guidance
        rg = kg.get("revenue_guidance") or {}
        if rg and isinstance(rg, dict) and rg.get("description"):
            st.markdown("**Revenue Guidance:**")
            st.markdown(f"- {rg.get('description', '')}")
            if rg.get("growth_target"):
                st.markdown(f"- Target: {rg['growth_target']}")
            if rg.get("timeframe"):
                st.markdown(f"- Timeframe: {rg['timeframe']}")

        # New Products
        products = kg.get("new_products") or []
        if products and isinstance(products, list):
            st.markdown("**New Products / Segments:**")
            for p in products[:5]:
                st.markdown(f"🚀 {p}")

        # 1-Year Outlook
        outlook = r.get("future_outlook", "")
        if outlook:
            st.markdown(f"**1-Year Outlook:** {outlook[:400]}")


# ── Router ────────────────────────────────────────────────────────────────────

def main() -> None:
    _init_state()
    db.init_db()
    _sidebar()

    page = st.session_state.page
    if not st.session_state.logged_in:
        _page_home()
        return

    pages = {
        "home":     _page_home,
        "screen":   _page_screen,
        "results":  _page_results,
        "analysis": _page_analysis,
        "rankings": _page_rankings,
    }
    pages.get(page, _page_home)()


if __name__ == "__main__":
    main()
