"""SQLite storage. / 데이터 저장 (SQLite)."""
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo(os.environ.get("INVEST_TZ", "Asia/Singapore"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE, title TEXT, source TEXT, published TEXT,
    market TEXT, topic TEXT, content TEXT, collected TEXT,
    analyzed INTEGER DEFAULT 0, method TEXT,
    themes TEXT, sentiment TEXT, confidence INTEGER, industries TEXT
);
CREATE INDEX IF NOT EXISTS ix_articles_pub ON articles(published);
CREATE TABLE IF NOT EXISTS fin_cache (
    ticker TEXT, day TEXT, data TEXT, PRIMARY KEY (ticker, day)
);
CREATE TABLE IF NOT EXISTS macro (day TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS theme_scores (
    day TEXT, theme TEXT, data TEXT, PRIMARY KEY (day, theme)
);
CREATE TABLE IF NOT EXISTS stock_scores (
    day TEXT, ticker TEXT, market TEXT, total REAL, data TEXT,
    PRIMARY KEY (day, ticker)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT,
    step TEXT, status TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS filing_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, market TEXT NOT NULL,
    source TEXT NOT NULL, content_hash TEXT NOT NULL, observed_at TEXT NOT NULL,
    raw_json TEXT NOT NULL, UNIQUE(ticker, source, content_hash)
);
CREATE TABLE IF NOT EXISTS filing_facts (
    snapshot_id INTEGER NOT NULL, available_at TEXT NOT NULL, fact_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_filing_fact_snapshot ON filing_facts(snapshot_id);
CREATE TABLE IF NOT EXISTS official_entities (
    ticker TEXT NOT NULL, source TEXT NOT NULL, entity_id TEXT NOT NULL,
    PRIMARY KEY(ticker, source)
);
CREATE TABLE IF NOT EXISTS official_source_status (
    market TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("INVEST_DB", ROOT / "data" / "invest.db"))


def connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def today() -> str:
    return now().date().isoformat()


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def loads(s, default=None):
    if s is None:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def load_themes() -> dict:
    p = Path(os.environ.get("INVEST_THEMES", ROOT / "themes.json"))
    return json.loads(p.read_text(encoding="utf-8"))


def load_universe() -> dict:
    p = Path(os.environ.get("INVEST_UNIVERSE", ROOT / "universe.json"))
    return json.loads(p.read_text(encoding="utf-8"))
