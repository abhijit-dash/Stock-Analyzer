"""
Screener.in login automation using Playwright (sync API).

Flow:
  1. Launch headless Chromium with a realistic profile.
  2. Navigate to the login page, fill credentials with human-like delays.
  3. Submit the form and wait for the dashboard redirect.
  4. Extract all cookies and return them as a plain dict.
  5. Optionally persist the cookie jar to disk for reuse.

The returned cookie dict is passed to utils.make_session() for all
subsequent requests-based calls — Playwright is only used for this step.
"""
import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SCREENER_BASE_URL, SCREENER_LOGIN_URL, SESSION_FILE, USER_AGENT


# ── Internal helpers ──────────────────────────────────────────────────────────

def _human_delay(min_ms: int = 80, max_ms: int = 350) -> None:
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


def _type_humanlike(locator: "Locator", text: str) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Type text one character at a time with random inter-key delays."""
    for char in text:
        locator.press(char)
        time.sleep(random.uniform(0.04, 0.14))


# ── Public API ────────────────────────────────────────────────────────────────

def login_screener(username: str, password: str) -> Optional[Dict[str, str]]:
    """
    Log in to Screener.in and return a cookie dict on success.

    Args:
        username: Screener.in e-mail / login name.
        password: Account password (never logged).

    Returns:
        Dict mapping cookie name → value, or None on failure.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.error(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )
        return None

    logger.info("Starting Screener.in login for: {}", username)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()

        try:
            # ── Navigate to login page ─────────────────────────────────────
            logger.debug("Navigating to {}", SCREENER_LOGIN_URL)
            page.goto(SCREENER_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            _human_delay(400, 900)

            # ── Fill username ──────────────────────────────────────────────
            user_field = page.wait_for_selector(
                'input[name="username"]', timeout=10_000
            )
            user_field.click()
            _human_delay(100, 250)
            _type_humanlike(user_field, username)
            _human_delay(200, 500)

            # ── Fill password ──────────────────────────────────────────────
            pwd_field = page.wait_for_selector(
                'input[name="password"]', timeout=10_000
            )
            pwd_field.click()
            _human_delay(100, 250)
            _type_humanlike(pwd_field, password)
            _human_delay(300, 700)

            # ── Submit ─────────────────────────────────────────────────────
            submit = page.wait_for_selector(
                'button[type="submit"]', timeout=10_000
            )
            _human_delay(200, 400)
            submit.click()

            # ── Wait for post-login redirect ───────────────────────────────
            page.wait_for_function(
                "() => !window.location.pathname.includes('/login')",
                timeout=15_000,
            )
            _human_delay(500, 1000)

            current_url = page.url
            if "login" in current_url:
                # Still on login — try to read the error
                err_el = page.query_selector(".errorlist, .alert-danger, #error-msg")
                err_text = err_el.inner_text() if err_el else "Unknown error"
                logger.error("Login failed. Page message: {}", err_text)
                return None

            logger.info("Login successful — landed on: {}", current_url)

            # ── Extract cookies ────────────────────────────────────────────
            raw_cookies: List[Dict] = context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in raw_cookies}

            save_session(raw_cookies)
            return cookies_dict

        except PWTimeout as exc:
            logger.error("Playwright timeout during login: {}", exc)
            try:
                page.screenshot(
                    path=str(Path(__file__).parent.parent / "logs" / "login_error.png")
                )
            except Exception:
                pass
            return None
        except Exception as exc:
            logger.exception("Unexpected error during login: {}", exc)
            return None
        finally:
            browser.close()


def save_session(cookies: List[Dict]) -> None:
    """Persist raw Playwright cookie list to disk."""
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        logger.debug("Session saved to {}", SESSION_FILE)
    except Exception as exc:
        logger.warning("Could not save session: {}", exc)


def load_session() -> Optional[Dict[str, str]]:
    """
    Load cookies from disk and return as name→value dict.
    Returns None if the file doesn't exist or is corrupt.
    """
    if not SESSION_FILE.exists():
        return None
    try:
        raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return {c["name"]: c["value"] for c in raw}
    except Exception as exc:
        logger.warning("Failed to load session: {}", exc)
        return None


def verify_session(cookies: Dict[str, str]) -> bool:
    """
    Make a lightweight authenticated request to check if the session is valid.
    Returns True if still logged in.
    """
    import requests as req
    try:
        s = req.Session()
        for k, v in cookies.items():
            s.cookies.set(k, v, domain="screener.in")
        resp = s.get(
            f"{SCREENER_BASE_URL}/home/",
            timeout=10,
            allow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )
        # Screener redirects to /login/ when session is expired
        return resp.status_code == 200 or (
            resp.status_code in (301, 302)
            and "login" not in resp.headers.get("Location", "")
        )
    except Exception:
        return False
