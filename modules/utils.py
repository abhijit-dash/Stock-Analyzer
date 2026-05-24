"""
Shared utilities: logging, HTTP sessions, rate limiting, number formatting.
"""
import random
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    LOG_FILE, RATE_LIMIT_DELAY_MIN, RATE_LIMIT_DELAY_MAX,
    REQUEST_TIMEOUT, USER_AGENT,
)

F = TypeVar("F", bound=Callable[..., Any])

# ── Logging setup ─────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    """Configure loguru to write to file and stderr."""
    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add(LOG_FILE, level="DEBUG", rotation="10 MB", retention="7 days",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}")


setup_logging()


# ── HTTP session ──────────────────────────────────────────────────────────────

def make_session(cookies: Optional[Dict[str, str]] = None) -> requests.Session:
    """
    Build a requests.Session pre-loaded with Screener.in cookies.
    Call this once per logical request group — it's cheap.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    if cookies:
        for name, value in cookies.items():
            session.cookies.set(name, value, domain="screener.in")
        # Django CSRF header for POST requests
        if "csrftoken" in cookies:
            session.headers["X-CSRFToken"] = cookies["csrftoken"]
            session.headers["Referer"] = "https://www.screener.in/"
    return session


def safe_get(
    session: requests.Session,
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    **kwargs: Any,
) -> Optional[requests.Response]:
    """GET with logging; returns None on failure."""
    try:
        resp = session.get(url, timeout=timeout, **kwargs)
        resp.raise_for_status()
        logger.debug("GET {} → {}", url, resp.status_code)
        return resp
    except requests.RequestException as exc:
        logger.warning("GET {} failed: {}", url, exc)
        return None


# ── Rate limiting ─────────────────────────────────────────────────────────────

def human_delay(
    min_s: float = RATE_LIMIT_DELAY_MIN,
    max_s: float = RATE_LIMIT_DELAY_MAX,
) -> None:
    """Random sleep to avoid triggering anti-bot heuristics."""
    time.sleep(random.uniform(min_s, max_s))


def rate_limited(func: F) -> F:
    """Decorator: add a human-like delay before every call."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        human_delay()
        return func(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


def retry(max_attempts: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """Decorator: retry on exception with exponential back-off."""
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            wait = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts:
                        raise
                    logger.warning(
                        "{} attempt {}/{} failed: {}. Retrying in {:.1f}s…",
                        func.__name__, attempt, max_attempts, exc, wait,
                    )
                    time.sleep(wait)
                    wait *= backoff
        return wrapper  # type: ignore[return-value]
    return decorator


# ── Number formatting ─────────────────────────────────────────────────────────

def fmt_cr(value: Any, decimals: int = 0) -> str:
    """Format a number as Indian Rupee Crores (e.g. 1,234 Cr)."""
    if value is None:
        return "—"
    try:
        v = float(value)
        if abs(v) >= 1_00_000:
            return f"₹{v/1_00_000:.1f}L Cr"
        if abs(v) >= 1_000:
            return f"₹{v/1_000:.1f}K Cr"
        return f"₹{v:,.{decimals}f} Cr"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(value: Any, decimals: int = 1) -> str:
    try:
        return f"{float(value):.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_num(value: Any, decimals: int = 2) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def score_color(score: float) -> str:
    """Return a CSS color string based on a 0–10 score."""
    if score >= 7.5:
        return "#00e676"
    if score >= 5.0:
        return "#ffb300"
    return "#ff5252"


def score_label(score: float) -> str:
    if score >= 7.5:
        return "Strong"
    if score >= 5.0:
        return "Moderate"
    return "Weak"


def parse_float(text: str) -> Optional[float]:
    """Parse a string that may contain commas or percentage signs."""
    if not text:
        return None
    try:
        return float(text.replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    # Try to cut at a sentence boundary
    cut = text[:max_chars]
    last_period = cut.rfind(". ")
    if last_period > max_chars * 0.8:
        return cut[:last_period + 1]
    return cut + "…"
