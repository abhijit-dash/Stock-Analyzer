"""
AI analysis engine — focused on CAPEX plans, revenue guidance, new product launches.

Uses Claude (Anthropic) or GPT-4o (OpenAI).
The transcript is truncated to MAX_TRANSCRIPT_CHARS and sent in a single call.
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    AI_PROVIDER, ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    MAX_TRANSCRIPT_CHARS,
    OPENAI_API_KEY, OPENAI_MODEL,
)
from modules.text_extractor import extract_management_sections
from modules.utils import truncate_text


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a senior Indian equity research analyst. "
    "Analyse concall transcripts and return ONLY valid JSON — no markdown, no extra text."
)

_ANALYSIS_PROMPT = """Analyse this concall transcript for {company_name} ({ticker}).
Extract ONLY these three signals and score each 1-10:

TRANSCRIPT:
{text}

---
Return ONLY this JSON (all fields required, no extra keys):
{{
  "summary": "2-3 sentence summary of the concall highlights",
  "capex_plans": {{
    "description": "What specific capex is planned (plant, machinery, capacity)",
    "amount_crores": <number or null>,
    "timeline": "e.g. FY26-FY27 or 18 months",
    "commissioning": "When new capacity goes live",
    "purpose": "expansion / new plant / maintenance"
  }},
  "revenue_guidance": {{
    "description": "Management's exact revenue or growth guidance",
    "growth_target": "e.g. 20-25% YoY or Rs 500 Cr revenue",
    "timeframe": "FY26 / next 2 years / etc",
    "confidence": "high / medium / low"
  }},
  "new_products": [
    "New product, segment, or geography being launched — one per item"
  ],
  "key_risks": ["Risk 1", "Risk 2"],
  "management_tone": "very_bullish|bullish|neutral|cautious|very_cautious",
  "capex_score": <1-10, 10=large specific well-funded capex with clear ROI timeline>,
  "guidance_score": <1-10, 10=specific multi-year high-conviction revenue guidance>,
  "new_product_score": <1-10, 10=multiple launches with clear revenue opportunity>,
  "one_year_outlook": "2-3 sentence view on how this stock may perform in the next 12 months based on the concall"
}}"""


# ── AI client helpers ─────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(f"Anthropic API key invalid: {exc}") from exc
    except anthropic.BadRequestError as exc:
        msg_str = str(exc).lower()
        if "credit" in msg_str or "billing" in msg_str or "balance" in msg_str:
            raise RuntimeError(
                "Anthropic API has no credits. "
                "Add credits at https://console.anthropic.com/settings/billing"
            ) from exc
        raise


def _call_openai(prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=2048,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _call_ai(prompt: str) -> str:
    if AI_PROVIDER == "openai":
        return _call_openai(prompt)
    return _call_claude(prompt)


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _parse_ai_response(raw: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m2 = re.search(r"\{[\s\S]+\}", raw)
    if m2:
        try:
            return json.loads(m2.group(0))
        except json.JSONDecodeError:
            pass
    logger.error("Could not parse AI response as JSON")
    return None


# ── Main analysis function ────────────────────────────────────────────────────

def analyze_transcript(
    text: str,
    company_name: str,
    ticker: str,
) -> Dict[str, Any]:
    """
    Analyse a concall transcript. Returns structured dict with CAPEX plans,
    revenue guidance, new product launches, and ranking scores.
    """
    if not text or len(text.strip()) < 200:
        logger.warning("Transcript text too short to analyse for {}", ticker)
        return _empty_analysis(ticker, company_name)

    # Focus on management commentary and truncate
    focused = extract_management_sections(text)
    focused = truncate_text(focused, MAX_TRANSCRIPT_CHARS)

    logger.info("Analysing {} ({} chars)", ticker, len(focused))

    prompt = _ANALYSIS_PROMPT.format(
        company_name=company_name,
        ticker=ticker,
        text=focused,
    )

    try:
        raw = _call_ai(prompt)
        result = _parse_ai_response(raw)
        if result:
            result["model_used"] = ANTHROPIC_MODEL if AI_PROVIDER == "anthropic" else OPENAI_MODEL
            return _normalise(result, ticker, company_name)
    except RuntimeError:
        raise  # propagate credit/auth errors to show in UI
    except Exception as exc:
        logger.exception("AI call failed for {}: {}", ticker, exc)

    return _empty_analysis(ticker, company_name)


def _normalise(data: Dict[str, Any], ticker: str, company_name: str) -> Dict[str, Any]:
    data.setdefault("ticker",       ticker)
    data.setdefault("company_name", company_name)
    data.setdefault("summary",      "Analysis not available.")
    data.setdefault("capex_plans",  {})
    data.setdefault("revenue_guidance", {})
    data.setdefault("new_products", [])
    data.setdefault("key_risks",    [])
    data.setdefault("management_tone", "neutral")
    data.setdefault("one_year_outlook", "")
    data.setdefault("model_used",   AI_PROVIDER)

    # Clamp scores 1-10
    for key in ("capex_score", "guidance_score", "new_product_score"):
        v = float(data.get(key) or 5)
        data[key] = max(1.0, min(10.0, v))

    # Composite total: capex 40%, guidance 40%, new products 20%
    data["total_score"] = round(
        data["capex_score"] * 0.40
        + data["guidance_score"] * 0.40
        + data["new_product_score"] * 0.20,
        2,
    )

    # Compat fields used by scoring_engine / database
    data["overall_guidance_score"] = data["guidance_score"]
    data["confidence_score"]       = data["guidance_score"]
    data["growth_probability"]     = round(data["total_score"] / 10.0, 2)
    data["capex_execution_score"]  = data["capex_score"]
    data.setdefault("future_outlook", data.get("one_year_outlook", ""))
    data.setdefault("bullish_points", [])
    data.setdefault("risks",          data.get("key_risks", []))
    data.setdefault("sector_outlook", "")

    # Compat scores dict
    s = data.get("total_score", 5)
    data["scores"] = {
        "revenue_guidance":      data["guidance_score"],
        "ebitda_expansion":      s,
        "order_book_visibility": s,
        "gross_block_expansion": data["capex_score"],
        "capex_execution":       data["capex_score"],
        "margin_expansion":      s,
        "industry_tailwinds":    s,
        "management_confidence": data["guidance_score"],
        "demand_strength":       data["new_product_score"],
    }
    return data


def _empty_analysis(ticker: str, company_name: str) -> Dict[str, Any]:
    return {
        "ticker": ticker, "company_name": company_name,
        "summary": "No transcript data available.",
        "capex_plans": {}, "revenue_guidance": {}, "new_products": [],
        "key_risks": [], "management_tone": "neutral", "one_year_outlook": "",
        "capex_score": 0.0, "guidance_score": 0.0, "new_product_score": 0.0,
        "total_score": 0.0,
        "overall_guidance_score": 0.0, "confidence_score": 0.0,
        "growth_probability": 0.0, "capex_execution_score": 0.0,
        "future_outlook": "", "bullish_points": [], "risks": [],
        "sector_outlook": "", "model_used": AI_PROVIDER,
        "scores": {k: 0.0 for k in [
            "revenue_guidance", "ebitda_expansion", "order_book_visibility",
            "gross_block_expansion", "capex_execution", "margin_expansion",
            "industry_tailwinds", "management_confidence", "demand_strength",
        ]},
    }


# ── Public helpers ────────────────────────────────────────────────────────────

def calculate_guidance_score(analysis: Dict[str, Any]) -> float:
    return float(analysis.get("total_score") or analysis.get("overall_guidance_score") or 0)
