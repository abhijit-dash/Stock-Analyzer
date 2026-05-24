"""
Central configuration for Capex Guidance Analyzer.
All environment-dependent values are loaded from .env via python-dotenv.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Directory layout ──────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
DATA_DIR       = BASE_DIR / "data"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
LOGS_DIR       = BASE_DIR / "logs"
CACHE_DIR      = BASE_DIR / "cache"
REPORTS_DIR    = BASE_DIR / "reports"

for _d in [DATA_DIR, TRANSCRIPTS_DIR, LOGS_DIR, CACHE_DIR, REPORTS_DIR]:
    _d.mkdir(exist_ok=True)

# ── Persistence ───────────────────────────────────────────────────────────────
DATABASE_PATH  = DATA_DIR / "capex_analyzer.db"
SESSION_FILE   = CACHE_DIR / "screener_session.json"
LOG_FILE       = LOGS_DIR / "app.log"

# ── Screener.in endpoints ─────────────────────────────────────────────────────
SCREENER_BASE_URL    = "https://www.screener.in"
SCREENER_LOGIN_URL   = f"{SCREENER_BASE_URL}/login/"
SCREENER_SCREEN_URL  = f"{SCREENER_BASE_URL}/screen/raw/"
SCREENER_COMPANY_URL = f"{SCREENER_BASE_URL}/company/"

# ── Screener.in credentials (optional — auto-login if set) ───────────────────
SCREENER_USERNAME = os.getenv("SCREENER_USERNAME", "")
SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD", "")

# ── AI backend ────────────────────────────────────────────────────────────────
AI_PROVIDER      = os.getenv("AI_PROVIDER", "anthropic").lower()   # "anthropic" | "openai"
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL  = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ── HTTP / retry tuning ───────────────────────────────────────────────────────
REQUEST_TIMEOUT        = 30
MAX_RETRIES            = 3
RATE_LIMIT_DELAY_MIN   = 1.5   # seconds between requests
RATE_LIMIT_DELAY_MAX   = 4.0

# ── Transcript chunking ───────────────────────────────────────────────────────
MAX_TRANSCRIPT_CHARS = 80_000  # truncate before sending to AI
CHUNK_SIZE           = 14_000  # chars per chunk when splitting
CHUNK_OVERLAP        = 500     # overlap between chunks

# ── Browser automation ────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# ── Predefined CAPEX screens (Screener.in query syntax) ───────────────────────
# NOTE: CAPEX expansion is inferred from Gross Block / CWIP / asset growth,
#       NOT from the "Capex last year" field per project requirements.
PREDEFINED_SCREENS: dict[str, str] = {
    "CAPEX Growth Leaders": (
        "Sales growth 3Years > 15 AND "
        "Profit growth 3Years > 15 AND "
        "ROCE > 15 AND "
        "Debt to equity < 1"
    ),
    "High CWIP Expansion": (
        "CWIP > 100 AND "
        "Market Capitalization > 500"
    ),
    "Strong Operating Leverage": (
        "OPM > 15 AND "
        "Return on capital employed > 15 AND "
        "Sales growth > 15"
    ),
    "Mid-Cap Asset Builders": (
        "Market Capitalization > 500 AND "
        "Market Capitalization < 10000 AND "
        "Sales growth > 15 AND "
        "ROCE > 15"
    ),
    "Industrial CAPEX Cycle": (
        "Sales growth > 10 AND "
        "ROCE > 12 AND "
        "Debt to equity < 2 AND "
        "OPM > 10"
    ),
    "High-Growth Small Caps": (
        "Market Capitalization < 5000 AND "
        "Sales growth 3Years > 20 AND "
        "ROCE > 15 AND "
        "Profit growth 3Years > 20"
    ),
    "Infrastructure & Capital Goods": (
        "Sales growth 3Years > 12 AND "
        "ROCE > 12 AND "
        "Debt to equity < 3"
    ),
    "CAPEX Gross Block Compounders": (
        "Gross block > Gross block preceding year * 1.5\n"
        "AND Sales growth 3Years > 12\n"
        "AND Profit growth 3Years > 5\n"
        "AND Return on capital employed > 10\n"
        "AND Market Capitalization < 10000\n"
        "AND Debt to equity < 1.5\n"
        "AND Market Capitalization > 100\n"
        "AND Is SME < 1\n"
        "AND Gross block > 10\n"
        "AND OPM > 8\n"
        "AND Price to book value < 6"
    ),
}

# ── Scoring dimension weights (must sum to 1.0) ───────────────────────────────
SCORING_WEIGHTS: dict[str, float] = {
    "revenue_guidance":      0.18,
    "ebitda_expansion":      0.15,
    "order_book_visibility": 0.10,
    "gross_block_expansion": 0.15,
    "capex_execution":       0.12,
    "margin_expansion":      0.08,
    "industry_tailwinds":    0.07,
    "management_confidence": 0.10,
    "demand_strength":       0.05,
}

# ── Document type keyword matching ────────────────────────────────────────────
DOCUMENT_KEYWORDS: dict[str, list[str]] = {
    "concall": [
        "concall", "conference call", "earnings call", "investor call",
        "analyst call", "q1", "q2", "q3", "q4", "quarterly", "transcript",
    ],
    "presentation": [
        "investor presentation", "investor day", "presentation", "ppt", "deck",
    ],
    "annual_report": ["annual report", "annual result", "ar20", "ar-20"],
}
