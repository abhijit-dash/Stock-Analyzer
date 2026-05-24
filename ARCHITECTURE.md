# Capex Guidance Analyzer — Architecture

## System Overview

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                        CAPEX GUIDANCE ANALYZER                              ║
║                   Indian Equity Research AI Assistant                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

 USER BROWSER
 ┌──────────────────────────────────────────────┐
 │  http://localhost:8501                        │
 │  ┌──────────┐ ┌───────────────────────────┐  │
 │  │ Sidebar  │ │      Main Content         │  │
 │  │ • Login  │ │  ┌──────┐ ┌──────────┐   │  │
 │  │ • Nav    │ │  │Screen│ │Rankings  │   │  │
 │  │ • Stats  │ │  │ Bldr │ │Dashboard │   │  │
 │  └──────────┘ │  └──────┘ └──────────┘   │  │
 └───────────────┴───────────────────────────┴──┘
          │ WebSocket (Streamlit protocol)
          ▼
╔══════════════════════════════════════════════════╗
║              app.py (Streamlit Server)           ║
║                                                  ║
║  Session State:                                  ║
║  ┌────────────────────────────────────────────┐  ║
║  │ logged_in • cookies • page                 │  ║
║  │ screen_results • analysis_results          │  ║
║  │ gb_metrics • current_ticker                │  ║
║  └────────────────────────────────────────────┘  ║
║                                                  ║
║  Pages (session_state.page):                     ║
║  ┌──────────┐ ┌────────┐ ┌──────────────────┐   ║
║  │   home   │ │ screen │ │     results      │   ║
║  └──────────┘ └────────┘ └──────────────────┘   ║
║  ┌──────────┐ ┌─────────────────────────────┐   ║
║  │ analysis │ │         rankings            │   ║
║  └──────────┘ └─────────────────────────────┘   ║
╚══════════════════════════════════════════════════╝
          │ Python function calls
          ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                              MODULES LAYER                                   ║
╠══════════════╦═══════════════╦════════════════╦════════════╦═════════════════╣
║ screener_    ║ screener_     ║ transcript_    ║ text_      ║ ai_analyzer     ║
║ login.py     ║ scraper.py    ║ fetcher.py     ║ extractor  ║ .py             ║
║              ║               ║                ║ .py        ║                 ║
║ Playwright   ║ run_screen()  ║ download_pdf() ║ PyMuPDF    ║ analyze_        ║
║ Chromium     ║ fetch_        ║ MD5 hash cache ║ pdfplumber ║ transcript()    ║
║ headless     ║ company()     ║ per-ticker dir ║ BeautifulS ║                 ║
║              ║ _parse_       ║                ║ extract_   ║ Focused prompt: ║
║ login_       ║ balance_      ║ fetch_latest_  ║ mgmt_      ║ • CAPEX plans   ║
║ screener()   ║ sheet()       ║ transcript()   ║ sections() ║ • Revenue guide ║
║              ║ _parse_doc_   ║                ║            ║ • New products  ║
║ Returns:     ║ links()       ║ Returns:       ║ Returns:   ║                 ║
║ cookies dict ║               ║ local PDF path ║ clean text ║ Returns:        ║
║              ║ Returns:      ║                ║            ║ analysis dict   ║
║              ║ companies[]   ║                ║            ║ scored 1-10     ║
╠══════════════╩═══════════════╩════════════════╩════════════╩═════════════════╣
║                         scoring_engine.py                                    ║
║  score_company(analysis, gb_metrics) → total_score 0-100                    ║
║  • AI aggregate (weighted capex/guidance/product scores) → 0-10 → ×10       ║
║  • Balance sheet bonus: Gross Block 3Y CAGR + CWIP level → 0-2 pts          ║
║  rank_companies(scores[]) → sorted list with rank field                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                            database.py (SQLite)                              ║
║  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  ║
║  │  companies  │ │ screen_runs  │ │  transcripts │ │    ai_analysis     │  ║
║  │  ticker     │ │  query       │ │  local_path  │ │  summary           │  ║
║  │  name       │ │  run_at      │ │  doc_type    │ │  capex_plans (JSON)│  ║
║  │  sector     │ │  result_count│ │  extracted   │ │  revenue_guidance  │  ║
║  │  market_cap │ └──────────────┘ │  _text       │ │  new_products      │  ║
║  └─────────────┘                  └──────────────┘ │  guidance_score    │  ║
║  ┌────────────────────────────────────────────────┐ │  management_tone  │  ║
║  │                   scores                       │ └────────────────────┘  ║
║  │  total_score (0-100) • capex_monetization      │                         ║
║  │  future_growth • ai_conviction • risk          │                         ║
║  └────────────────────────────────────────────────┘                         ║
╚══════════════════════════════════════════════════════════════════════════════╝

          ┌──────────────────────────────────────────────────┐
          │               EXTERNAL SYSTEMS                    │
          │                                                  │
          │  ┌─────────────────┐   ┌──────────────────────┐  │
          │  │  screener.in    │   │   Anthropic Claude   │  │
          │  │                 │   │   claude-haiku-4-5   │  │
          │  │ • Login/auth    │   │                      │  │
          │  │ • Screen query  │   │  Input: transcript   │  │
          │  │ • Balance sheet │   │  text (≤80K chars)   │  │
          │  │ • Concall links │   │                      │  │
          │  │ • PDF hosting   │   │  Output: JSON with   │  │
          │  │   (BSE/NSE)     │   │  • capex_plans       │  │
          │  └─────────────────┘   │  • revenue_guidance  │  │
          │                        │  • new_products      │  │
          │                        │  • scores (1-10)     │  │
          │                        │  • one_year_outlook  │  │
          │                        └──────────────────────┘  │
          └──────────────────────────────────────────────────┘
```

---

## Data Flow — AI Analysis Pipeline

```
  User clicks "Run AI Analysis" on AI Analysis page
         │
         ▼
  For each selected ticker:
  ┌─────────────────────────────────────────────────────────────────────┐
  │                                                                     │
  │  1. fetch_company_data(ticker, cookies)                             │
  │     └─▶ GET screener.in/company/TICKER/                            │
  │         └─▶ parse HTML: balance sheet + document links             │
  │                                                                     │
  │  2. fetch_latest_transcript(ticker, doc_links, cookies)            │
  │     └─▶ priority: concall > presentation > annual_report           │
  │         └─▶ download_pdf(url) → transcripts/TICKER/md5hash.pdf    │
  │             (cached: skip if file >1KB already exists)             │
  │                                                                     │
  │  3. extract_text(local_path)                                       │
  │     └─▶ PyMuPDF: extract all text pages                           │
  │         └─▶ fallback pdfplumber if fitz returns empty             │
  │             └─▶ extract_management_sections(text)                 │
  │                 (keyword-scored: capex/guidance/growth terms)      │
  │                 └─▶ truncate to 80,000 chars                       │
  │                                                                     │
  │  4. analyze_transcript(text, company_name, ticker)                 │
  │     └─▶ Claude API (claude-haiku-4-5-20251001)                     │
  │         Prompt: extract CAPEX plans, revenue guidance, new products│
  │         └─▶ parse JSON response                                   │
  │             └─▶ normalise: clamp scores 1-10, compute total       │
  │                                                                     │
  │  5. score_company(analysis, gb_metrics)                            │
  │     └─▶ AI aggregate + balance sheet bonus → 0-100 score          │
  │                                                                     │
  │  6. save to SQLite (ai_analysis + scores tables)                   │
  │                                                                     │
  └─────────────────────────────────────────────────────────────────────┘
         │
         ▼
  Rankings page: get_rankings() → sorted by total_score DESC
```

---

## Scoring Formula

```
  AI Score (0-10) = capex_score × 0.40
                  + guidance_score × 0.40
                  + new_product_score × 0.20

  Balance Sheet Bonus (0-2 pts):
    + 1.0  if Gross Block 3Y CAGR > 25%
    + 0.5  if Gross Block 3Y CAGR > 15%
    + 0.5  if CWIP > 500 Cr
    + 0.25 if CWIP > 100 Cr
    + 0.5  if asset_expansion_flag = True

  Total Score (0-100) = min(10, AI_score + BS_bonus) × 10
```

---

## Authentication Flow

```
  App startup (_init_state)
       │
       ├─▶ Try load_session() — read cache/screener_session.json
       │         │
       │         ├─▶ verify_session(cookies) — HEAD screener.in/home/
       │         │         │
       │         │         ├─▶ 200 OK ─▶ logged_in = True  ✓ (fast path)
       │         │         │
       │         │         └─▶ fail  ─▶ proceed to full login
       │         │
       │         └─▶ no file ─▶ proceed to full login
       │
       └─▶ login_screener(username, password)
                 │
                 └─▶ Playwright headless Chrome
                     1. goto screener.in/login/ (wait=domcontentloaded)
                     2. fill email + password (human-like delays)
                     3. click submit
                     4. wait for URL to leave /login/
                     5. extract cookies → save to cache/screener_session.json
                     6. logged_in = True, st.rerun()
```

---

## File Layout

```
Stock-Analyzer/
├── app.py                      # Streamlit app — 5-page router, all UI
├── config.py                   # Env vars, paths, screens, scoring weights
├── .env                        # Secrets (gitignored)
├── requirements.txt
├── README.md
├── ARCHITECTURE.md             # This file
│
├── modules/
│   ├── screener_login.py       # Playwright auth → cookie dict
│   ├── screener_scraper.py     # Screen results + BS + doc links
│   ├── transcript_fetcher.py   # PDF download with local MD5 cache
│   ├── text_extractor.py       # PDF/HTML → clean text + section extractor
│   ├── ai_analyzer.py          # Claude API: CAPEX, guidance, products
│   ├── scoring_engine.py       # 0-100 composite scorer + ranker
│   ├── database.py             # SQLite WAL, 7 tables
│   └── utils.py                # HTTP, retry, formatters
│
├── data/
│   └── capex_analyzer.db       # SQLite database
├── transcripts/
│   └── <TICKER>/               # Downloaded PDFs per company
├── logs/
│   ├── streamlit.log
│   ├── streamlit_err.log
│   └── app.log
├── cache/
│   └── screener_session.json   # Screener.in session cookies
└── reports/
    └── *.csv                   # Exported ranking CSVs
```
