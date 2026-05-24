# Capex Guidance Analyzer

AI-powered equity research assistant for Indian stock market CAPEX-led growth stories.

## What it does

Identifies NSE/BSE companies where:
- **Gross Block is compounding** — fixed-asset base expanding aggressively (>1.5× YoY)
- **Management is guiding strongly** — specific revenue targets, timelines, growth rates
- **New products / segments being launched** — incremental growth drivers beyond base business
- **CAPEX will convert to earnings** — commissioning timelines, utilisation ramp plans

For each screened company it:
1. Downloads the **latest concall transcript** (PDF) from Screener.in
2. Extracts management commentary using PyMuPDF / pdfplumber
3. Sends to **Claude AI** with a focused prompt asking for CAPEX plans, revenue guidance, and new product launches
4. Scores each signal 1-10 and produces a **composite ranking**

> **CAPEX intensity = Gross Block / CWIP / Net Block growth**, NOT "Capex last year" field.

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI Framework | Streamlit |
| Browser Automation | Playwright (Chromium) |
| Data Source | Screener.in (authenticated scraping) |
| PDF Extraction | PyMuPDF (fitz) → pdfplumber fallback |
| HTML Extraction | BeautifulSoup4 + lxml |
| AI Analysis | Anthropic Claude (claude-haiku-4-5 default) |
| Database | SQLite via Python `sqlite3` |
| Data Wrangling | pandas |
| Charting | Plotly (dark theme) |
| HTTP | requests (session-based with Screener cookies) |
| Config | python-dotenv |
| Logging | loguru |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     User Browser (localhost:8501)                │
└──────────────────────────┬──────────────────────────────────────┘
                           │  WebSocket (Streamlit protocol)
┌──────────────────────────▼──────────────────────────────────────┐
│                    app.py  (Streamlit Server)                    │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Sidebar    │  │  Page Router │  │   Session State      │   │
│  │  (Login /   │  │  home        │  │   logged_in, cookies │   │
│  │   Nav)      │  │  screen      │  │   screen_results     │   │
│  └──────┬──────┘  │  results     │  │   analysis_results   │   │
│         │         │  analysis    │  └──────────────────────┘   │
│         │         │  rankings    │                              │
│         │         └──────┬───────┘                              │
└─────────┼────────────────┼────────────────────────────────────--┘
          │                │
          │          ┌─────▼──────────────────────────────────────┐
          │          │              modules/                       │
          │          │                                             │
          │  ┌───────▼──────┐   ┌──────────────────┐             │
          │  │screener_login│   │screener_scraper  │             │
          │  │  Playwright  │   │  • run_screen()   │             │
          │  │  Chromium    │   │  • fetch_company()│             │
          │  │  headless    │   │  • _parse_bs()    │             │
          │  └───────┬──────┘   └────────┬─────────┘             │
          │          │                   │                         │
          │     cookies               doc_links                   │
          │          │                   │                         │
          │          └────────┬──────────┘                         │
          │                   │                                    │
          │          ┌────────▼─────────┐                         │
          │          │transcript_fetcher│                         │
          │          │  download_pdf()  │                         │
          │          │  cached locally  │                         │
          │          └────────┬─────────┘                         │
          │                   │  local PDF path                    │
          │          ┌────────▼─────────┐                         │
          │          │  text_extractor  │                         │
          │          │  PyMuPDF / pdfp  │                         │
          │          │  extract_mgmt_   │                         │
          │          │  sections()      │                         │
          │          └────────┬─────────┘                         │
          │                   │  clean text                        │
          │          ┌────────▼─────────┐   ┌──────────────────┐ │
          │          │  ai_analyzer     │──▶│ Anthropic Claude │ │
          │          │  analyze_        │   │ claude-haiku-4-5 │ │
          │          │  transcript()    │◀──│ (API call)       │ │
          │          └────────┬─────────┘   └──────────────────┘ │
          │                   │  analysis dict                     │
          │          ┌────────▼─────────┐                         │
          │          │ scoring_engine   │                         │
          │          │ score_company()  │                         │
          │          │ 0-100 composite  │                         │
          │          └────────┬─────────┘                         │
          │                   │                                    │
          │          ┌────────▼─────────┐                         │
          │          │   database.py    │                         │
          │          │   SQLite WAL     │                         │
          │          │   7 tables       │                         │
          │          └──────────────────┘                         │
          │                                                        │
          └────────────────────────────────────────────────────────┘

External Systems:
  screener.in ──── balance sheets, screens, concall PDF links
  Anthropic API ── Claude AI analysis (CAPEX, guidance, products)
  BSE / NSE ────── PDF hosting for concall transcripts
```

---

## Project Structure

```
Stock-Analyzer/
├── app.py                    ← Streamlit app (5 pages, single-file router)
├── config.py                 ← All constants, predefined screens, env loading
├── .env                      ← API keys + Screener.in credentials (gitignored)
├── requirements.txt
│
├── modules/
│   ├── screener_login.py     ← Playwright login → cookie extraction
│   ├── screener_scraper.py   ← Screen execution + balance sheet / doc parsing
│   ├── transcript_fetcher.py ← Download PDFs with MD5-hash-based local cache
│   ├── text_extractor.py     ← PDF → clean text; keyword-scored section extractor
│   ├── ai_analyzer.py        ← Claude / GPT-4o: CAPEX + guidance + products
│   ├── scoring_engine.py     ← Weighted composite score (0-100) + ranking
│   ├── database.py           ← SQLite persistence (7 tables, WAL mode)
│   └── utils.py              ← HTTP helpers, retry, rate-limit, formatters
│
├── data/                     ← SQLite database (capex_analyzer.db)
├── transcripts/              ← Downloaded PDFs, per-ticker directories
├── logs/                     ← streamlit.log, streamlit_err.log, app.log
├── cache/                    ← screener_session.json (cookies)
└── reports/                  ← Exported CSV rankings
```

---

## Quick Start

### 1. Install dependencies

```powershell
# Windows PowerShell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure `.env`

```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001   # cheap & fast; use claude-sonnet-4-6 for higher quality
SCREENER_USERNAME=your@email.com
SCREENER_PASSWORD=yourpassword
```

### 3. Run

```powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

Opens at **http://localhost:8501** — auto-logs into Screener.in on first load.

---

## App Workflow

| Step | Page | What happens |
|---|---|---|
| 1 | **Login** | Auto-login using `.env` credentials (Playwright headless Chrome); session cached |
| 2 | **Screen Builder** | Pick predefined CAPEX screen or write custom Screener.in query |
| 3 | **Results** | Browse companies; fetch Gross Block / CWIP history per company |
| 4 | **AI Analysis** | Download concall PDF → extract text → Claude AI scores 3 signals |
| 5 | **Rankings** | Companies sorted by composite 0-100 score |

---

## AI Analysis — What Claude Extracts

For each concall transcript, Claude (Haiku) extracts exactly **3 signals**:

| Signal | Score (1-10) | Weight | What it looks for |
|---|---|---|---|
| **CAPEX Plans** | `capex_score` | 40% | Plant expansions, ₹ amounts, commissioning dates, purpose |
| **Revenue Guidance** | `guidance_score` | 40% | Specific % growth targets, revenue numbers, timeframes |
| **New Products** | `new_product_score` | 20% | New segments, geographies, product launches |

**Composite AI score** = capex × 0.4 + guidance × 0.4 + products × 0.2 (0-10)

**Dashboard total score** (0-100) = AI composite × 10 + balance sheet bonus (Gross Block CAGR, CWIP)

---

## Predefined Screens

| Screen | Key Filters |
|---|---|
| CAPEX Growth Leaders | Sales 3Y > 15%, Profit 3Y > 15%, ROCE > 15%, D/E < 1 |
| High CWIP Expansion | CWIP > 100 Cr, MCap > 500 Cr |
| Strong Operating Leverage | OPM > 15%, ROCE > 15%, Sales > 15% |
| Mid-Cap Asset Builders | MCap 500–10,000 Cr, Sales > 15%, ROCE > 15% |
| Industrial CAPEX Cycle | Sales > 10%, ROCE > 12%, D/E < 2, OPM > 10% |
| High-Growth Small Caps | MCap < 5,000 Cr, Sales 3Y > 20%, ROCE > 15% |
| Infrastructure & Capital Goods | Sales 3Y > 12%, ROCE > 12%, D/E < 3 |
| **CAPEX Gross Block Compounders** | Gross Block > prev yr × 1.5, Sales 3Y > 12%, ROCE > 10%, MCap 100-10,000 Cr, OPM > 8%, P/B < 6 |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (if Claude) | — | Get at console.anthropic.com |
| `OPENAI_API_KEY` | Yes (if GPT-4o) | — | OpenAI API key |
| `AI_PROVIDER` | No | `anthropic` | `anthropic` or `openai` |
| `ANTHROPIC_MODEL` | No | `claude-haiku-4-5-20251001` | Claude model ID |
| `SCREENER_USERNAME` | No | — | Auto-login email |
| `SCREENER_PASSWORD` | No | — | Auto-login password |

---

## Notes

- Session cookie cached at `cache/screener_session.json` — no re-login while valid
- PDFs cached at `transcripts/<TICKER>/` — never re-downloaded
- All AI results in `data/capex_analyzer.db` (SQLite, WAL mode)
- If Claude API shows "credit balance too low" → add credits at console.anthropic.com/settings/billing
- App works without AI key — screens and balance sheet data still function
