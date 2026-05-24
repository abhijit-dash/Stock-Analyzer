"""
Text extraction from PDFs and HTML documents.

Strategy:
  PDF  → try PyMuPDF (fitz) first (fast, high quality)
         fall back to pdfplumber if fitz fails
  HTML → BeautifulSoup with noise removal

Post-processing:
  • Remove page numbers, headers/footers, watermarks.
  • Normalise whitespace.
  • Optionally isolate management commentary / Q&A sections.
"""
import re
import sys
from pathlib import Path
from typing import List, Optional

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── PDF extraction ─────────────────────────────────────────────────────────

def extract_pdf_text(path: Path) -> str:
    """
    Extract readable text from a PDF file.
    Tries PyMuPDF first; falls back to pdfplumber.
    """
    text = _try_fitz(path)
    if not text or len(text) < 200:
        logger.debug("fitz produced little text, trying pdfplumber for {}", path.name)
        text = _try_pdfplumber(path)
    if not text:
        logger.warning("Both PDF extractors failed for {}", path.name)
        return ""
    return clean_text(text)


def _try_fitz(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages: List[str] = []
        for page in doc:
            pages.append(page.get_text("text"))
        doc.close()
        return "\n".join(pages)
    except ImportError:
        logger.debug("PyMuPDF (fitz) not available")
        return ""
    except Exception as exc:
        logger.warning("fitz error on {}: {}", path.name, exc)
        return ""


def _try_pdfplumber(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages: List[str] = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)
    except ImportError:
        logger.debug("pdfplumber not available")
        return ""
    except Exception as exc:
        logger.warning("pdfplumber error on {}: {}", path.name, exc)
        return ""


# ── HTML extraction ────────────────────────────────────────────────────────

def extract_html_text(path: Path) -> str:
    """Extract readable text from a locally-saved HTML file."""
    try:
        from bs4 import BeautifulSoup
        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        # Remove nav / header / footer / script / style noise
        for tag in soup(["script", "style", "nav", "header", "footer",
                          "aside", "noscript", "iframe"]):
            tag.decompose()
        return clean_text(soup.get_text(separator="\n"))
    except Exception as exc:
        logger.warning("HTML extraction failed for {}: {}", path.name, exc)
        return ""


# ── Dispatch ───────────────────────────────────────────────────────────────

def extract_text(path: Path) -> str:
    """Route to the correct extractor based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix in (".html", ".htm"):
        return extract_html_text(path)
    # Treat everything else as plain text
    try:
        return clean_text(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        logger.error("Cannot read {}: {}", path, exc)
        return ""


# ── Text cleaning ──────────────────────────────────────────────────────────

# Patterns that commonly appear in scanned concall PDFs and add no value
_NOISE_PATTERNS = [
    re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),                    # bare page numbers
    re.compile(r"Moderator[\s:]+.{0,80}", re.IGNORECASE),        # moderator labels
    re.compile(r"www\.\S+\.com", re.IGNORECASE),                  # URLs
    re.compile(r"\(Operator Instructions\)", re.IGNORECASE),
    re.compile(r"Safe\s+Harbor\s+Statement", re.IGNORECASE),
    re.compile(r"This\s+transcript.*?purposes\s+only\.", re.IGNORECASE | re.DOTALL),
    re.compile(r"-{3,}"),                                          # long dashes
    re.compile(r"={3,}"),                                          # long equals
    re.compile(r"\f"),                                             # form-feed chars
]


def clean_text(text: str) -> str:
    """Normalise and de-noise extracted text."""
    # Replace common Unicode junk
    text = text.replace(" ", " ").replace("’", "'").replace("‘", "'")
    text = text.replace("–", "-").replace("—", " - ").replace("…", "...")

    for pat in _NOISE_PATTERNS:
        text = pat.sub(" ", text)

    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)
    # Strip trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


# ── Section detection ──────────────────────────────────────────────────────

_MGMT_SECTION_MARKERS = [
    "management discussion",
    "management commentary",
    "opening remarks",
    "business overview",
    "financial highlights",
    "performance review",
    "chairman",
    "managing director",
    "chief executive",
    "ceo",
    "cfo",
    "md&a",
]

_GUIDANCE_MARKERS = [
    "guidance",
    "outlook",
    "forecast",
    "target",
    "next year",
    "next quarter",
    "fy25", "fy26", "fy27",
    "going forward",
    "expect",
    "anticipate",
    "projection",
]

_CAPEX_MARKERS = [
    "capex",
    "capital expenditure",
    "gross block",
    "plant",
    "capacity",
    "commissioning",
    "utilization",
    "cwip",
    "expansion",
    "greenfield",
    "brownfield",
    "new facility",
    "new plant",
]


def extract_management_sections(text: str) -> str:
    """
    Extract paragraphs likely to contain management commentary and guidance.
    Returns a condensed version of the text (max ~40 000 chars) focused on
    forward-looking statements and CAPEX commentary.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 80]

    scored: List[tuple[int, str]] = []
    for para in paragraphs:
        lower = para.lower()
        score = 0
        for m in _MGMT_SECTION_MARKERS:
            if m in lower:
                score += 3
        for m in _GUIDANCE_MARKERS:
            if m in lower:
                score += 2
        for m in _CAPEX_MARKERS:
            if m in lower:
                score += 2
        scored.append((score, para))

    # Keep top paragraphs + always include the first few (opening remarks)
    top = sorted(scored, key=lambda x: -x[0])[:80]
    opening = [p for _, p in scored[:10]]

    merged = opening + [p for _, p in top if p not in opening]
    # Deduplicate while preserving order
    seen: set = set()
    unique: List[str] = []
    for p in merged:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    result = "\n\n".join(unique)
    # Hard cap to avoid blowing the AI context window
    return result[:40_000]
