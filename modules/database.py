"""
SQLite persistence layer for Capex Guidance Analyzer.
All tables are created on first run via init_db().
"""
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATABASE_PATH


# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(DATABASE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    finally:
        con.close()


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables and indices (idempotent)."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT    UNIQUE NOT NULL,
                name         TEXT    NOT NULL,
                sector       TEXT,
                market_cap   REAL,
                screener_url TEXT,
                sales_growth REAL,
                roce         REAL,
                pe_ratio     REAL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS screen_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                screen_name  TEXT,
                screen_query TEXT,
                result_count INTEGER,
                run_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS screen_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER,
                ticker          TEXT,
                gross_block     REAL,
                gross_block_3y  REAL,
                net_block       REAL,
                cwip            REAL,
                depreciation    REAL,
                asset_turnover  REAL,
                raw_metrics     TEXT,
                FOREIGN KEY (run_id) REFERENCES screen_runs(id),
                FOREIGN KEY (ticker) REFERENCES companies(ticker)
            );

            CREATE TABLE IF NOT EXISTS transcripts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker           TEXT    NOT NULL,
                doc_type         TEXT,
                title            TEXT,
                url              TEXT    UNIQUE,
                doc_date         TEXT,
                local_path       TEXT,
                extracted_text   TEXT,
                download_status  TEXT    DEFAULT 'pending',
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticker) REFERENCES companies(ticker)
            );

            CREATE TABLE IF NOT EXISTS ai_analysis (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker                TEXT    NOT NULL,
                transcript_id         INTEGER,
                summary               TEXT,
                bullish_points        TEXT,
                risks                 TEXT,
                future_outlook        TEXT,
                key_guidance          TEXT,
                guidance_score        REAL,
                confidence_score      REAL,
                growth_probability    REAL,
                capex_execution_score REAL,
                management_tone       TEXT,
                sector_outlook        TEXT,
                scores_json           TEXT,
                model_used            TEXT,
                analyzed_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticker)         REFERENCES companies(ticker),
                FOREIGN KEY (transcript_id)  REFERENCES transcripts(id)
            );

            CREATE TABLE IF NOT EXISTS scores (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker                      TEXT    UNIQUE NOT NULL,
                total_score                 REAL,
                future_growth_score         REAL,
                risk_score                  REAL,
                ai_conviction_score         REAL,
                capex_monetization_score    REAL,
                revenue_guidance_score      REAL,
                ebitda_expansion_score      REAL,
                order_book_score            REAL,
                gross_block_score           REAL,
                management_confidence_score REAL,
                rank                        INTEGER,
                score_breakdown             TEXT,
                scored_at                   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticker) REFERENCES companies(ticker)
            );

            CREATE TABLE IF NOT EXISTS gross_block_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT NOT NULL,
                year         TEXT,
                gross_block  REAL,
                net_block    REAL,
                cwip         REAL,
                depreciation REAL,
                fixed_assets REAL,
                FOREIGN KEY (ticker) REFERENCES companies(ticker)
            );

            CREATE INDEX IF NOT EXISTS idx_tr_ticker  ON transcripts(ticker);
            CREATE INDEX IF NOT EXISTS idx_ai_ticker  ON ai_analysis(ticker);
            CREATE INDEX IF NOT EXISTS idx_sc_score   ON scores(total_score DESC);
            CREATE INDEX IF NOT EXISTS idx_gb_ticker  ON gross_block_history(ticker);
        """)
        con.commit()
    logger.debug("DB initialised at {}", DATABASE_PATH)


# ── Companies ─────────────────────────────────────────────────────────────────

def upsert_company(c: Dict[str, Any]) -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO companies
                (ticker, name, sector, market_cap, screener_url,
                 sales_growth, roce, pe_ratio, last_updated)
            VALUES (:ticker,:name,:sector,:market_cap,:screener_url,
                    :sales_growth,:roce,:pe_ratio,CURRENT_TIMESTAMP)
            ON CONFLICT(ticker) DO UPDATE SET
                name=excluded.name, sector=excluded.sector,
                market_cap=excluded.market_cap,
                screener_url=excluded.screener_url,
                sales_growth=excluded.sales_growth,
                roce=excluded.roce, pe_ratio=excluded.pe_ratio,
                last_updated=CURRENT_TIMESTAMP
        """, {
            "ticker":       c.get("ticker"),
            "name":         c.get("name"),
            "sector":       c.get("sector"),
            "market_cap":   c.get("market_cap"),
            "screener_url": c.get("screener_url"),
            "sales_growth": c.get("sales_growth"),
            "roce":         c.get("roce"),
            "pe_ratio":     c.get("pe_ratio"),
        })
        con.commit()


def get_all_companies() -> List[Dict]:
    with _conn() as con:
        return [dict(r) for r in
                con.execute("SELECT * FROM companies ORDER BY name").fetchall()]


def get_company(ticker: str) -> Optional[Dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM companies WHERE ticker=?", (ticker,)
        ).fetchone()
        return dict(row) if row else None


# ── Screen runs ───────────────────────────────────────────────────────────────

def save_screen_run(
    screen_name: str, query: str, results: List[Dict]
) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO screen_runs (screen_name,screen_query,result_count) VALUES (?,?,?)",
            (screen_name, query, len(results)),
        )
        run_id = cur.lastrowid
        for r in results:
            con.execute("""
                INSERT INTO screen_results
                    (run_id,ticker,gross_block,gross_block_3y,net_block,
                     cwip,depreciation,asset_turnover,raw_metrics)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                run_id, r.get("ticker"), r.get("gross_block"),
                r.get("gross_block_3y"), r.get("net_block"), r.get("cwip"),
                r.get("depreciation"), r.get("asset_turnover"),
                json.dumps(r.get("raw_metrics", {})),
            ))
        con.commit()
        return run_id


# ── Transcripts ───────────────────────────────────────────────────────────────

def upsert_transcript(data: Dict[str, Any]) -> int:
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO transcripts
                (ticker,doc_type,title,url,doc_date,
                 local_path,extracted_text,download_status)
            VALUES (:ticker,:doc_type,:title,:url,:doc_date,
                    :local_path,:extracted_text,:download_status)
            ON CONFLICT(url) DO UPDATE SET
                local_path=excluded.local_path,
                extracted_text=excluded.extracted_text,
                download_status=excluded.download_status
        """, {
            "ticker":          data.get("ticker", ""),
            "doc_type":        data.get("doc_type", "concall"),
            "title":           data.get("title", ""),
            "url":             data.get("url", ""),
            "doc_date":        data.get("doc_date", ""),
            "local_path":      data.get("local_path", ""),
            "extracted_text":  data.get("extracted_text", ""),
            "download_status": data.get("download_status", "pending"),
        })
        con.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_transcripts(ticker: str) -> List[Dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM transcripts WHERE ticker=? ORDER BY doc_date DESC",
            (ticker,),
        ).fetchall()]


def get_transcript_text(transcript_id: int) -> Optional[str]:
    with _conn() as con:
        row = con.execute(
            "SELECT extracted_text FROM transcripts WHERE id=?",
            (transcript_id,),
        ).fetchone()
        return row["extracted_text"] if row else None


# ── AI analysis ───────────────────────────────────────────────────────────────

def save_analysis(data: Dict[str, Any]) -> int:
    with _conn() as con:
        # Pack the new focused fields into key_guidance JSON
        kg = dict(data.get("key_guidance") or {})
        kg["capex_plans"]       = data.get("capex_plans", {})
        kg["revenue_guidance"]  = data.get("revenue_guidance", {})
        kg["new_products"]      = data.get("new_products", [])
        kg["capex_score"]       = data.get("capex_score", 0.0)
        kg["new_product_score"] = data.get("new_product_score", 0.0)
        kg["total_score_ai"]    = data.get("total_score", 0.0)

        one_year = data.get("one_year_outlook") or data.get("future_outlook", "")
        risks    = data.get("key_risks") or data.get("risks", [])

        cur = con.execute("""
            INSERT INTO ai_analysis
                (ticker,transcript_id,summary,bullish_points,risks,
                 future_outlook,key_guidance,guidance_score,confidence_score,
                 growth_probability,capex_execution_score,management_tone,
                 sector_outlook,scores_json,model_used)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("ticker"),
            data.get("transcript_id"),
            data.get("summary", ""),
            json.dumps(data.get("bullish_points", [])),
            json.dumps(risks),
            one_year,
            json.dumps(kg),
            data.get("guidance_score", 0.0),
            data.get("confidence_score", 0.0),
            data.get("growth_probability", 0.0),
            data.get("capex_execution_score", data.get("capex_score", 0.0)),
            data.get("management_tone", "neutral"),
            data.get("sector_outlook", ""),
            json.dumps(data.get("scores", {})),
            data.get("model_used", ""),
        ))
        con.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_latest_analysis(ticker: str) -> Optional[Dict]:
    with _conn() as con:
        row = con.execute("""
            SELECT * FROM ai_analysis WHERE ticker=?
            ORDER BY analyzed_at DESC LIMIT 1
        """, (ticker,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for f in ("bullish_points", "risks", "key_guidance", "scores_json"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        return d


def get_all_analyses() -> List[Dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT a.*, c.name AS company_name, c.sector, c.market_cap
            FROM   ai_analysis a
            LEFT JOIN companies c ON a.ticker = c.ticker
            ORDER BY a.guidance_score DESC
        """).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        for f in ("bullish_points", "risks", "key_guidance", "scores_json"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        results.append(d)
    return results


# ── Scores ────────────────────────────────────────────────────────────────────

def upsert_score(data: Dict[str, Any]) -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO scores
                (ticker,total_score,future_growth_score,risk_score,
                 ai_conviction_score,capex_monetization_score,
                 revenue_guidance_score,ebitda_expansion_score,
                 order_book_score,gross_block_score,
                 management_confidence_score,rank,score_breakdown,scored_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(ticker) DO UPDATE SET
                total_score=excluded.total_score,
                future_growth_score=excluded.future_growth_score,
                risk_score=excluded.risk_score,
                ai_conviction_score=excluded.ai_conviction_score,
                capex_monetization_score=excluded.capex_monetization_score,
                revenue_guidance_score=excluded.revenue_guidance_score,
                ebitda_expansion_score=excluded.ebitda_expansion_score,
                order_book_score=excluded.order_book_score,
                gross_block_score=excluded.gross_block_score,
                management_confidence_score=excluded.management_confidence_score,
                rank=excluded.rank,
                score_breakdown=excluded.score_breakdown,
                scored_at=CURRENT_TIMESTAMP
        """, (
            data["ticker"],
            data.get("total_score", 0.0),
            data.get("future_growth_score", 0.0),
            data.get("risk_score", 0.0),
            data.get("ai_conviction_score", 0.0),
            data.get("capex_monetization_score", 0.0),
            data.get("revenue_guidance_score", 0.0),
            data.get("ebitda_expansion_score", 0.0),
            data.get("order_book_score", 0.0),
            data.get("gross_block_score", 0.0),
            data.get("management_confidence_score", 0.0),
            data.get("rank", 999),
            json.dumps(data.get("score_breakdown", {})),
        ))
        con.commit()


def get_rankings() -> List[Dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT s.*, c.name, c.sector, c.market_cap, c.sales_growth, c.roce,
                   a.summary, a.future_outlook, a.management_tone,
                   a.guidance_score AS ai_guidance_score,
                   a.key_guidance
            FROM   scores s
            LEFT JOIN companies    c ON s.ticker = c.ticker
            LEFT JOIN ai_analysis  a ON s.ticker = a.ticker
            ORDER BY s.total_score DESC
        """).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d.get("score_breakdown"):
            try:
                d["score_breakdown"] = json.loads(d["score_breakdown"])
            except Exception:
                pass
        results.append(d)
    return results


# ── Gross block history ───────────────────────────────────────────────────────

def save_gross_block_history(ticker: str, history: List[Dict]) -> None:
    with _conn() as con:
        con.execute(
            "DELETE FROM gross_block_history WHERE ticker=?", (ticker,)
        )
        for row in history:
            con.execute("""
                INSERT INTO gross_block_history
                    (ticker,year,gross_block,net_block,cwip,depreciation,fixed_assets)
                VALUES (?,?,?,?,?,?,?)
            """, (
                ticker,
                row.get("year"),
                row.get("gross_block"),
                row.get("net_block"),
                row.get("cwip"),
                row.get("depreciation"),
                row.get("fixed_assets"),
            ))
        con.commit()


def get_gross_block_history(ticker: str) -> List[Dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM gross_block_history WHERE ticker=? ORDER BY year",
            (ticker,),
        ).fetchall()]
