"""
Screener.in data extraction — screen execution and company page parsing.

Two main responsibilities:
  1. run_screen()        — submit a custom query and return a list of companies.
  2. fetch_company_data() — visit a company page and extract:
       • Balance sheet rows (Gross Block, Net Block, CWIP, Depreciation)
       • Document links (concall transcripts, presentations, annual reports)
       • Basic fundamentals (sector, P/E, market cap, ROCE, sales growth)

CAPEX expansion is inferred from Gross Block / CWIP / Net Block growth trends
on the balance sheet — NOT from the "Capex last year" field.
"""
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    DOCUMENT_KEYWORDS, SCREENER_BASE_URL, SCREENER_COMPANY_URL,
    SCREENER_SCREEN_URL,
)
from modules.utils import human_delay, make_session, parse_float, retry, safe_get


# ── Screen execution ──────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=3.0)
def run_screen(
    query: str,
    cookies: Dict[str, str],
    limit: int = 50,
    page: int = 1,
) -> List[Dict[str, Any]]:
    """
    Execute a Screener.in custom screen query.

    Returns a list of dicts, each containing:
      ticker, name, screener_url, and any numeric columns the query returns.
    """
    session = make_session(cookies)
    params = {
        "query": query,
        "limit": limit,
        "page": page,
        "sort": "",
        "order": "asc",
    }
    url = f"{SCREENER_SCREEN_URL}?{urllib.parse.urlencode(params)}"
    logger.info("Running screen: {}", url)

    resp = safe_get(session, url)
    if resp is None:
        logger.error("Screen request returned no response")
        return []

    return _parse_screen_results(resp.text, query)


def _parse_screen_results(html: str, query: str) -> List[Dict[str, Any]]:
    """Parse the HTML results table from a Screener.in screen page."""
    soup = BeautifulSoup(html, "lxml")

    # Detect login redirect
    if soup.find("input", {"name": "username"}):
        logger.error("Screen request redirected to login — session expired")
        return []

    table = (
        soup.find("table", class_="data-table")
        or soup.find("table", id="data-table")
        or soup.find("table")
    )
    if not table:
        logger.warning("No results table found in screen response")
        return []

    # ── Parse column headers ───────────────────────────────────────────────
    headers: List[str] = []
    thead = table.find("thead")
    if thead:
        for th in thead.find_all("th"):
            headers.append(th.get_text(strip=True))

    # ── Parse rows ─────────────────────────────────────────────────────────
    companies: List[Dict[str, Any]] = []
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue

        # Company name and link are always in the second cell
        link_tag = cells[1].find("a")
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        name = link_tag.get_text(strip=True)
        ticker = _extract_ticker(href)

        if not ticker:
            continue

        company: Dict[str, Any] = {
            "ticker":      ticker,
            "name":        name,
            "screener_url": f"{SCREENER_BASE_URL}{href}",
        }

        # Map remaining cells to header names
        for i, cell in enumerate(cells[2:], start=2):
            col_name = headers[i] if i < len(headers) else f"col_{i}"
            company[col_name] = parse_float(cell.get_text(strip=True))

        # Friendly aliases used by the rest of the app
        company.setdefault("market_cap",   company.get("Market Cap", company.get("Market Capitalization")))
        company.setdefault("sales_growth", company.get("Sales growth"))
        company.setdefault("roce",         company.get("ROCE", company.get("Return on capital employed")))
        company.setdefault("pe_ratio",     company.get("P/E", company.get("P/E Ratio")))

        companies.append(company)

    logger.info("Screen returned {} companies", len(companies))
    return companies


def _extract_ticker(href: str) -> Optional[str]:
    """Extract NSE/BSE ticker from a Screener.in company URL path."""
    # e.g. /company/RELIANCE/ or /company/RELIANCE/consolidated/
    parts = [p for p in href.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "company":
        return parts[1].upper()
    return None


# ── Company page parsing ──────────────────────────────────────────────────────

@retry(max_attempts=3, delay=3.0)
def fetch_company_data(
    ticker: str,
    cookies: Dict[str, str],
    consolidated: bool = True,
) -> Dict[str, Any]:
    """
    Fetch and parse a Screener.in company page.

    Returns:
        {
          "ticker": str,
          "name": str,
          "sector": str,
          "gross_block_history": list[dict],   # [{year, gross_block, net_block, cwip, depreciation}]
          "document_links": list[dict],         # [{title, url, doc_type, doc_date}]
          "fundamentals": dict,
        }
    """
    suffix = "consolidated/" if consolidated else ""
    url = f"{SCREENER_COMPANY_URL}{ticker}/{suffix}"
    session = make_session(cookies)
    human_delay(1.0, 2.5)

    resp = safe_get(session, url)
    if resp is None and consolidated:
        # Fallback to standalone
        url = f"{SCREENER_COMPANY_URL}{ticker}/"
        resp = safe_get(session, url)
    if resp is None:
        logger.error("Could not fetch company page for {}", ticker)
        return {"ticker": ticker, "error": "page_fetch_failed"}

    soup = BeautifulSoup(resp.text, "lxml")
    return {
        "ticker":              ticker,
        "name":                _parse_company_name(soup),
        "sector":              _parse_sector(soup),
        "gross_block_history": _parse_balance_sheet(soup, ticker),
        "document_links":      _parse_document_links(soup),
        "fundamentals":        _parse_fundamentals(soup),
    }


def _parse_company_name(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1", class_="h2") or soup.find("h1")
    return h1.get_text(strip=True) if h1 else "Unknown"


def _parse_sector(soup: BeautifulSoup) -> str:
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "/screen/" in href and "sector" in href.lower():
            return a.get_text(strip=True)
    # Fallback: look for sector in company profile
    for span in soup.find_all("span"):
        txt = span.get_text(strip=True)
        if "sector" in txt.lower():
            return txt.split(":")[-1].strip()
    return "Unknown"


def _parse_balance_sheet(soup: BeautifulSoup, ticker: str) -> List[Dict]:
    """
    Extract Gross Block, Net Block, CWIP, and Depreciation from the
    balance sheet section.  Returns a list ordered by year ascending.
    """
    section = (
        soup.find("section", id="balance-sheet")
        or soup.find("div", id="balance-sheet")
    )
    if not section:
        logger.warning("Balance sheet section not found for {}", ticker)
        return []

    table = section.find("table")
    if not table:
        return []

    # ── Year headers ───────────────────────────────────────────────────────
    header_row = table.find("thead") or table.find("tr")
    years: List[str] = []
    if header_row:
        for th in header_row.find_all(["th", "td"]):
            txt = th.get_text(strip=True)
            if re.match(r"(Mar|Sep|Jun|Dec)\s*\d{2,4}", txt) or re.match(r"\d{4}", txt) or txt == "TTM":
                years.append(txt)

    # ── Row data ───────────────────────────────────────────────────────────
    target_rows = {
        "gross_block":   ["gross block", "gross fixed assets", "gross tangible"],
        "net_block":     ["net block", "net fixed assets", "tangible assets"],
        "cwip":          ["capital work in progress", "cwip", "work in progress"],
        "depreciation":  ["accumulated depreciation", "depreciation", "amortisation"],
        "fixed_assets":  ["fixed assets", "total fixed assets", "net assets", "tangible fixed"],
    }
    extracted: Dict[str, List[Optional[float]]] = {k: [] for k in target_rows}

    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        row_label = cells[0].get_text(strip=True).lower()
        for field, keywords in target_rows.items():
            if any(kw in row_label for kw in keywords):
                values = [parse_float(c.get_text(strip=True)) for c in cells[1:]]
                extracted[field] = values
                break

    # Use fixed_assets as proxy for gross_block if gross_block not found
    if not extracted["gross_block"] and extracted["fixed_assets"]:
        extracted["gross_block"] = extracted["fixed_assets"]

    if not years or not extracted["gross_block"]:
        logger.warning("Could not parse balance sheet numbers for {}", ticker)
        return []

    # ── Zip into list of yearly dicts ──────────────────────────────────────
    history: List[Dict] = []
    for i, year in enumerate(years):
        def _get(field: str) -> Optional[float]:
            vals = extracted[field]
            return vals[i] if i < len(vals) else None

        history.append({
            "year":        year,
            "gross_block": _get("gross_block"),
            "net_block":   _get("net_block"),
            "cwip":        _get("cwip"),
            "depreciation": _get("depreciation"),
            "fixed_assets": _get("fixed_assets"),
        })

    return history


def _parse_document_links(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """
    Find all external PDF / document links on the company page.
    Classifies each link as concall | presentation | annual_report | other.
    """
    docs: List[Dict[str, str]] = []
    seen_urls: set = set()

    # Look in dedicated document sections first, then fall back to all <a> tags
    doc_containers = (
        soup.find_all("section", class_=re.compile(r"doc", re.I))
        + soup.find_all("div", class_=re.compile(r"doc", re.I))
        + [soup]  # full page fallback
    )

    for container in doc_containers:
        for a in container.find_all("a", href=True):
            href: str = a["href"].strip()
            if not href or href in seen_urls:
                continue
            # Only external or PDF links
            if not (href.startswith("http") or href.endswith(".pdf")):
                if not href.startswith("/"):
                    continue
                href = f"{SCREENER_BASE_URL}{href}"

            title = a.get_text(strip=True) or a.get("title", "")
            if not title or len(title) < 4:
                continue

            seen_urls.add(href)
            doc_type = _classify_document(title, href)
            if doc_type == "other" and container is soup:
                # Skip noise from the full-page fallback
                continue

            # Attempt to extract a date from the title
            doc_date = _extract_date_from_title(title)
            docs.append({
                "title":    title,
                "url":      href,
                "doc_type": doc_type,
                "doc_date": doc_date,
            })

    logger.debug("Found {} document links", len(docs))
    return docs


def _classify_document(title: str, url: str) -> str:
    combined = (title + " " + url).lower()
    for doc_type, keywords in DOCUMENT_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return doc_type
    return "other"


def _extract_date_from_title(title: str) -> str:
    # Patterns like "Q3 FY24", "March 2024", "2023-24"
    patterns = [
        r"Q[1-4]\s*FY\s*\d{2,4}",
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}",
        r"\d{4}-\d{2,4}",
        r"\b\d{4}\b",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


def _parse_fundamentals(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract key fundamental numbers from the company overview section."""
    result: Dict[str, Any] = {}
    # Screener shows ratios in a #top-ratios or .company-ratios section
    for section_id in ("top-ratios", "company-ratios", "ratios"):
        section = soup.find(id=section_id) or soup.find(class_=section_id)
        if section:
            for li in section.find_all("li"):
                spans = li.find_all("span")
                if len(spans) >= 2:
                    key = spans[0].get_text(strip=True).lower()
                    val = spans[-1].get_text(strip=True)
                    result[key] = val
    return result


# ── Gross block growth helpers ────────────────────────────────────────────────

def compute_gross_block_growth(history: List[Dict]) -> Dict[str, Any]:
    """
    Compute CAPEX-cycle metrics from balance sheet history.

    Returns:
      latest_gross_block, gross_block_3y_cagr, cwip_latest,
      net_block_latest, depreciation_latest, asset_expansion_flag
    """
    if not history:
        return {}

    gb = [h["gross_block"] for h in history if h.get("gross_block") is not None]
    cwip = [h["cwip"] for h in history if h.get("cwip") is not None]
    nb = [h["net_block"] for h in history if h.get("net_block") is not None]
    depr = [h["depreciation"] for h in history if h.get("depreciation") is not None]

    def cagr(series: List[float], years: int = 3) -> Optional[float]:
        if len(series) < years + 1:
            return None
        start, end = series[-(years + 1)], series[-1]
        if start <= 0:
            return None
        return ((end / start) ** (1 / years) - 1) * 100

    return {
        "latest_gross_block":   gb[-1] if gb else None,
        "gross_block_3y_cagr":  cagr(gb, 3),
        "gross_block_5y_cagr":  cagr(gb, 5),
        "cwip_latest":          cwip[-1] if cwip else None,
        "net_block_latest":     nb[-1] if nb else None,
        "depreciation_latest":  depr[-1] if depr else None,
        # Flag if CWIP or Gross Block jumped sharply (expansion cycle)
        "asset_expansion_flag": (
            (cwip[-1] or 0) > (cwip[-2] or 0) * 1.3
            if len(cwip) >= 2 else False
        ),
    }


# ── Convenience wrapper ───────────────────────────────────────────────────────

def extract_companies(
    tickers: List[str],
    cookies: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Fetch detailed company data (balance sheet + documents) for a list of tickers.
    Adds a random delay between requests to respect Screener.in rate limits.
    """
    results: List[Dict[str, Any]] = []
    for i, ticker in enumerate(tickers):
        logger.info("Fetching company data {}/{}: {}", i + 1, len(tickers), ticker)
        data = fetch_company_data(ticker, cookies)
        if data and "error" not in data:
            gb_metrics = compute_gross_block_growth(data.get("gross_block_history", []))
            data.update(gb_metrics)
        results.append(data)
        human_delay(2.0, 4.0)
    return results
