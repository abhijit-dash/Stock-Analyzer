"""
Scoring engine — combines AI dimension scores with balance sheet signals
to produce a final composite investment score for each company.

Output scores (all 0–100):
  total_score              — primary ranking score
  future_growth_score      — revenue + earnings expansion probability
  risk_score               — lower is riskier
  ai_conviction_score      — AI confidence in the analysis
  capex_monetization_score — likelihood that current CAPEX generates future EPS
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SCORING_WEIGHTS


# ── Core scorer ───────────────────────────────────────────────────────────────

def score_company(
    analysis: Dict[str, Any],
    gross_block_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute all scores for a company from AI analysis + balance sheet data.

    Args:
        analysis:             Output of ai_analyzer.analyze_transcript().
        gross_block_metrics:  Output of screener_scraper.compute_gross_block_growth().

    Returns:
        Dict of score fields suitable for database.upsert_score().
    """
    ticker = analysis.get("ticker", "UNKNOWN")
    scores = analysis.get("scores", {})
    gb_metrics = gross_block_metrics or {}

    # ── AI dimension scores (0-10) → weighted aggregate (0-10) ────────────
    weighted = sum(
        float(scores.get(k, 5)) * w
        for k, w in SCORING_WEIGHTS.items()
    )
    weight_sum = sum(SCORING_WEIGHTS.values()) or 1.0
    ai_agg = weighted / weight_sum  # 0-10

    # ── Balance sheet bonus (0-2 points) ──────────────────────────────────
    bs_bonus = _balance_sheet_bonus(gb_metrics)

    # ── Final composite (0-10 → scaled to 0-100) ──────────────────────────
    raw_total = min(10.0, ai_agg + bs_bonus)
    total_score = round(raw_total * 10, 1)

    # ── Sub-scores (0-100) ────────────────────────────────────────────────
    future_growth = _future_growth_score(scores, gb_metrics) * 10
    capex_monetz  = _capex_monetization_score(scores, gb_metrics) * 10
    ai_conviction = float(analysis.get("confidence_score", 5)) * 10
    risk          = _risk_score(analysis) * 10          # higher = less risk = better

    # ── Per-dimension scores (0-100) for the breakdown table ──────────────
    score_breakdown = {
        k: round(float(scores.get(k, 5)) * 10, 1)
        for k in SCORING_WEIGHTS
    }

    result = {
        "ticker":                     ticker,
        "total_score":                total_score,
        "future_growth_score":        round(future_growth, 1),
        "risk_score":                 round(risk, 1),
        "ai_conviction_score":        round(ai_conviction, 1),
        "capex_monetization_score":   round(capex_monetz, 1),
        "revenue_guidance_score":     round(float(scores.get("revenue_guidance", 5)) * 10, 1),
        "ebitda_expansion_score":     round(float(scores.get("ebitda_expansion", 5)) * 10, 1),
        "order_book_score":           round(float(scores.get("order_book_visibility", 5)) * 10, 1),
        "gross_block_score":          round(float(scores.get("gross_block_expansion", 5)) * 10, 1),
        "management_confidence_score": round(float(scores.get("management_confidence", 5)) * 10, 1),
        "score_breakdown":            score_breakdown,
    }
    logger.debug("Scores for {}: total={}", ticker, total_score)
    return result


def _balance_sheet_bonus(gb: Dict[str, Any]) -> float:
    """
    Add up to +2 points for strong balance sheet expansion signals.
    These are objective numbers, not AI-generated.
    """
    bonus = 0.0
    cagr3 = gb.get("gross_block_3y_cagr")
    cwip  = gb.get("cwip_latest", 0) or 0
    flag  = gb.get("asset_expansion_flag", False)

    if cagr3 is not None:
        if cagr3 > 25:
            bonus += 1.0
        elif cagr3 > 15:
            bonus += 0.5

    if cwip > 500:
        bonus += 0.5
    elif cwip > 100:
        bonus += 0.25

    if flag:
        bonus += 0.5

    return min(2.0, bonus)


def _future_growth_score(scores: Dict, gb: Dict) -> float:
    """0-10 probability of future earnings growth."""
    keys = ["revenue_guidance", "ebitda_expansion",
            "gross_block_expansion", "capex_execution"]
    avg = sum(float(scores.get(k, 5)) for k in keys) / len(keys)

    cagr3 = gb.get("gross_block_3y_cagr") or 0
    bs_bonus = min(1.5, cagr3 / 20)

    return min(10.0, avg + bs_bonus)


def _capex_monetization_score(scores: Dict, gb: Dict) -> float:
    """
    How likely is current CAPEX to produce earnings in the next 2-3 years?
    Considers execution quality, order book, and asset expansion pace.
    """
    keys = [
        "capex_execution", "order_book_visibility",
        "demand_strength", "gross_block_expansion",
    ]
    avg = sum(float(scores.get(k, 5)) for k in keys) / len(keys)

    # If there's active CWIP, cap expansion is ongoing — good sign
    cwip = gb.get("cwip_latest", 0) or 0
    cwip_bonus = 0.5 if cwip > 100 else 0.0

    return min(10.0, avg + cwip_bonus)


def _risk_score(analysis: Dict[str, Any]) -> float:
    """
    Inverted risk: 10 = low risk, 1 = high risk.
    Derived from management tone, number of risks, and confidence.
    """
    tone_map = {
        "very_bullish": 9, "bullish": 7.5, "neutral": 5,
        "cautious": 3, "very_cautious": 1.5,
    }
    tone_score = tone_map.get(analysis.get("management_tone", "neutral"), 5)
    n_risks = len(analysis.get("risks", []))
    risk_penalty = min(2.0, n_risks * 0.3)
    confidence   = float(analysis.get("confidence_score", 5))

    raw = (tone_score * 0.4) + (confidence * 0.4) - risk_penalty
    return max(1.0, min(10.0, raw))


# ── Ranking ───────────────────────────────────────────────────────────────────

def rank_companies(score_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort companies by total_score (descending) and assign rank.
    Modifies each dict in-place and returns the sorted list.
    """
    sorted_list = sorted(
        score_list,
        key=lambda d: d.get("total_score", 0),
        reverse=True,
    )
    for i, item in enumerate(sorted_list, start=1):
        item["rank"] = i
    return sorted_list


def score_and_rank_all(
    analyses: List[Dict[str, Any]],
    gb_metrics_map: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, Any]]:
    """
    Score and rank a list of analysis dicts in one call.

    Args:
        analyses:       List from ai_analyzer.analyze_transcript().
        gb_metrics_map: {ticker: gross_block_metrics} for balance sheet bonus.

    Returns:
        Ranked list of score dicts (suitable for database.upsert_score()).
    """
    gb_map = gb_metrics_map or {}
    scored = [
        score_company(a, gb_map.get(a.get("ticker", "")))
        for a in analyses
        if a.get("ticker")
    ]
    return rank_companies(scored)


# ── Formatting helpers ────────────────────────────────────────────────────────

def score_badge(score: float) -> str:
    """Return emoji + label for a 0–100 score."""
    if score >= 75:
        return f"🟢 {score:.0f}"
    if score >= 50:
        return f"🟡 {score:.0f}"
    return f"🔴 {score:.0f}"


def radar_data(score_breakdown: Dict[str, float]) -> Dict[str, Any]:
    """
    Prepare data for a Plotly radar chart from the score_breakdown dict.
    """
    labels = [
        "Revenue\nGuidance", "EBITDA\nExpansion", "Order\nBook",
        "Gross Block\nExpansion", "CAPEX\nExecution", "Margin\nExpansion",
        "Industry\nTailwinds", "Mgmt\nConfidence", "Demand\nStrength",
    ]
    key_order = [
        "revenue_guidance", "ebitda_expansion", "order_book_visibility",
        "gross_block_expansion", "capex_execution", "margin_expansion",
        "industry_tailwinds", "management_confidence", "demand_strength",
    ]
    values = [float(score_breakdown.get(k, 50)) for k in key_order]
    return {"labels": labels, "values": values}
