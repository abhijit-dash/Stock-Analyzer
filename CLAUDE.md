# Stock Analyzer — Claude Code Context

## Project Overview
A Streamlit web app for stock analysis built with Python. It provides interactive price charts and fundamental analysis for any publicly traded stock ticker.

## Stack
- **Framework**: Streamlit
- **Data**: yfinance (Yahoo Finance — no API key required)
- **Charting**: Plotly (candlestick, line, bar charts via plotly.graph_objects and subplots)
- **Data wrangling**: pandas

## Project Structure
```
Stock-Analyzer/
├── app.py              # Main Streamlit application (single-file app)
├── requirements.txt    # Python dependencies
├── CLAUDE.md           # This file
├── .gitignore
└── venv/               # Local Python virtual environment (not committed)
```

## Running the App
```bash
# Install dependencies
pip install -r requirements.txt

# Run the app (opens in browser at http://localhost:8501)
streamlit run app.py
```

## Key App Features
1. **Price Chart tab** — Candlestick or line chart with optional 20/50-day MAs and volume bars
2. **Fundamentals tab** — Valuation, profitability, per-share, and balance sheet metrics
3. **Financials tab** — Annual income statement and cash flow charts + raw data tables

## Code Conventions
- All yfinance calls are wrapped in `@st.cache_data(ttl=300)` to avoid redundant network requests
- Helper functions `fmt_large`, `fmt_pct`, `fmt_num` handle None-safe number formatting
- Dark Plotly theme (`template="plotly_dark"`) used throughout for consistency
- App is a single `app.py` file — keep it that way unless complexity clearly warrants modules

## Extending the App
When adding new features, follow these patterns:
- New data fetches → add a `@st.cache_data` function near the top
- New sections → add a new `st.tab` or expander inside an existing tab
- New charts → use `plotly.graph_objects` for consistency
- Keep sidebar controls consolidated in the `with st.sidebar:` block

## Common yfinance Objects
```python
ticker = yf.Ticker("AAPL")
ticker.info          # dict of ~100 fundamental fields
ticker.history(...)  # OHLCV DataFrame
ticker.income_stmt   # Annual income statement DataFrame
ticker.balance_sheet # Annual balance sheet DataFrame
ticker.cashflow      # Annual cash flow DataFrame
```
