"""
Transcript and document fetcher for Capex Guidance Analyzer.

Responsibilities:
  • Download PDFs / HTML documents linked from Screener.in company pages.
  • Cache downloads locally under TRANSCRIPTS_DIR/<ticker>/.
  • Skip re-downloading if a cached copy exists.
  • Return local file paths and metadata suitable for text extraction.
"""
import hashlib
import sys
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import REQUEST_TIMEOUT, SCREENER_BASE_URL, TRANSCRIPTS_DIR
from modules.utils import human_delay, make_session, retry, safe_get


# ── Helpers ───────────────────────────────────────────────────────────────────

def _url_to_filename(url: str) -> str:
    """Deterministic file name derived from the URL — preserves extension."""
    digest = hashlib.md5(url.encode()).hexdigest()[:12]
    suffix = Path(url.split("?")[0]).suffix[:6] or ".pdf"
    return f"{digest}{suffix}"


def _ticker_dir(ticker: str) -> Path:
    d = TRANSCRIPTS_DIR / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Core download ─────────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=3.0)
def download_pdf(
    url: str,
    ticker: str,
    cookies: Optional[Dict[str, str]] = None,
) -> Optional[Path]:
    """
    Download a PDF (or HTML) document to the local transcript cache.

    Returns:
        Path to the saved file, or None on failure.
    """
    dest = _ticker_dir(ticker) / _url_to_filename(url)
    if dest.exists() and dest.stat().st_size > 1_024:
        logger.debug("Cache hit: {}", dest)
        return dest

    session = make_session(cookies or {})
    # Some BSE/NSE links redirect through Screener — set referer
    session.headers["Referer"] = SCREENER_BASE_URL + "/"

    resp = safe_get(session, url, timeout=60, stream=True)
    if resp is None:
        return None

    content_type = resp.headers.get("Content-Type", "")
    # Adjust extension based on actual content type
    if "html" in content_type and dest.suffix != ".html":
        dest = dest.with_suffix(".html")
    elif "pdf" in content_type and dest.suffix != ".pdf":
        dest = dest.with_suffix(".pdf")

    try:
        dest.write_bytes(resp.content)
        logger.info("Downloaded ({} bytes) → {}", len(resp.content), dest.name)
        return dest
    except OSError as exc:
        logger.error("Could not write {}: {}", dest, exc)
        return None


# ── Document fetching ─────────────────────────────────────────────────────────

def fetch_latest_transcript(
    ticker: str,
    document_links: List[Dict[str, str]],
    cookies: Optional[Dict[str, str]] = None,
    prefer_types: Optional[List[str]] = None,
) -> Optional[Dict]:
    """
    Select and download the most recent relevant document for a ticker.

    Priority order (configurable via prefer_types):
      concall > presentation > annual_report > other

    Returns:
        A dict with keys: title, url, doc_type, doc_date, local_path
        or None if nothing suitable was found.
    """
    if prefer_types is None:
        prefer_types = ["concall", "presentation", "annual_report"]

    # Filter and rank documents
    ranked: List[Dict] = []
    for doc in document_links:
        dtype = doc.get("doc_type", "other")
        if dtype in prefer_types:
            ranked.append({**doc, "_priority": prefer_types.index(dtype)})

    if not ranked:
        logger.warning("No relevant documents found for {}", ticker)
        return None

    # Sort: primary = doc_type priority, secondary = date descending
    ranked.sort(key=lambda d: (d["_priority"], _negate_date(d.get("doc_date", ""))))
    best = ranked[0]

    human_delay(1.0, 2.5)
    local_path = download_pdf(best["url"], ticker, cookies)
    if local_path is None:
        logger.warning("Download failed for {} — {}", ticker, best["url"])
        return None

    return {
        "title":      best.get("title", ""),
        "url":        best["url"],
        "doc_type":   best.get("doc_type", "other"),
        "doc_date":   best.get("doc_date", ""),
        "local_path": str(local_path),
    }


def _negate_date(date_str: str) -> str:
    """Negate a date string so sorting gives newest first (lexicographic trick)."""
    return "".join(
        str(9 - int(c)) if c.isdigit() else c for c in date_str
    )


# ── Batch download ────────────────────────────────────────────────────────────

def fetch_all_documents(
    ticker: str,
    document_links: List[Dict[str, str]],
    cookies: Optional[Dict[str, str]] = None,
    max_docs: int = 5,
) -> List[Dict]:
    """
    Download up to max_docs of the most relevant documents for a ticker.

    Returns:
        List of dicts: {title, url, doc_type, doc_date, local_path}
    """
    priority_order = ["concall", "presentation", "annual_report"]
    sorted_docs = sorted(
        document_links,
        key=lambda d: priority_order.index(d.get("doc_type", "other"))
        if d.get("doc_type") in priority_order
        else 99,
    )[:max_docs]

    downloaded: List[Dict] = []
    for doc in sorted_docs:
        human_delay(1.5, 3.0)
        local_path = download_pdf(doc["url"], ticker, cookies)
        if local_path:
            downloaded.append({
                "title":      doc.get("title", ""),
                "url":        doc["url"],
                "doc_type":   doc.get("doc_type", "other"),
                "doc_date":   doc.get("doc_date", ""),
                "local_path": str(local_path),
            })

    logger.info("Downloaded {}/{} documents for {}", len(downloaded), len(sorted_docs), ticker)
    return downloaded


def extract_document_links(
    ticker: str,
    cookies: Dict[str, str],
) -> List[Dict[str, str]]:
    """
    Thin wrapper: fetch the company page and return its document links.
    Used when you already have cookies but haven't run a full screen.
    """
    from modules.screener_scraper import fetch_company_data
    data = fetch_company_data(ticker, cookies)
    return data.get("document_links", [])
