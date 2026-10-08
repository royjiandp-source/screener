"""FastAPI server + scheduler. / FastAPI 서버 + 자동 실행.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
Open: http://localhost:8000
"""
import os
import threading
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path

from . import pipeline
from .db import TZ, connect, loads
from .web import render
from .filings.store import history
from .filings.service import source_status

MARKET_PATTERN = "^(KR|US|SG)$"

scheduler = None


def _start_scheduler():
    """News at 07:00, 12:00, 18:00, 23:00 + full scoring at 07:15 (server time zone, default SGT)."""
    from apscheduler.schedulers.background import BackgroundScheduler
    s = BackgroundScheduler(timezone=TZ)
    s.add_job(lambda: pipeline.run("news"), "cron", hour="7,12,18,23", minute=0, id="news")
    s.add_job(lambda: pipeline.run("score"), "cron", hour=7, minute=15, id="score")
    s.add_job(lambda: pipeline.run("catalog"), "cron", day_of_week="mon", hour=6, minute=30, id="catalog")
    s.start()
    return s


@asynccontextmanager
async def lifespan(app):
    global scheduler
    from .discovery.jobs import recover, start_pending
    c = connect()
    try:
        recover(c)
        start_pending(c)
    finally: c.close()
    if os.environ.get("DISABLE_SCHEDULER") != "1":
        scheduler = _start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="AI Investment Idea Discovery", version="1.0", lifespan=lifespan)
from .discovery.api import router as discovery_router
app.include_router(discovery_router)
from .discovery.limits import DiscoveryLimits
app.add_middleware(DiscoveryLimits)


@app.get("/", response_class=HTMLResponse)
def dashboard(market: str | None = Query(None, pattern=MARKET_PATTERN), query: str = Query('', max_length=100),
              min_score: float = Query(60, ge=0, le=100), observation_offset: int = Query(0, ge=0), value_offset: int = Query(0, ge=0)):
    con = connect()
    try:
        return render(pipeline.report(con, market=market, query=query, min_score=min_score,
                                      observation_offset=observation_offset, value_offset=value_offset))
    finally:
        con.close()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/report")
def api_report(market: str | None = Query(None, pattern=MARKET_PATTERN), query: str = Query('', max_length=100),
               min_score: float = Query(60, ge=0, le=100), observation_offset: int = Query(0, ge=0), value_offset: int = Query(0, ge=0),
               limit: int = Query(50, ge=1, le=100)):
    con = connect()
    try:
        from .web import fragments
        report = pipeline.report(con, market=market, query=query, min_score=min_score,
                                 observation_offset=observation_offset, value_offset=value_offset, limit=limit)
        return {**report, "fragments": fragments(report)}
    finally:
        con.close()


@app.get("/assets/{filename}")
def asset(filename: str):
    if filename not in ('dashboard.js', 'dashboard.css'):
        raise HTTPException(404, 'Asset not found')
    return FileResponse(Path(__file__).parent / filename)


@app.get("/api/stocks")
def api_stocks(market: str | None = Query(None, pattern=MARKET_PATTERN), limit: int = Query(50, ge=1, le=500)):
    con = connect()
    try:
        return [s for s in pipeline.stocks(con, market=market) if s.get("market") in pipeline.MARKETS][:limit]
    finally:
        con.close()


@app.get("/api/stocks/{ticker}")
def api_stock(ticker: str):
    con = connect()
    try:
        row = con.execute("SELECT day,data FROM stock_scores WHERE ticker=? ORDER BY day DESC LIMIT 1",
                          (ticker.upper(),)).fetchone()
        if not row or pipeline.market_of(ticker.upper()) not in pipeline.MARKETS:
            raise HTTPException(404, "Ticker not scored yet")
        return {"ticker": ticker.upper(), "day": row["day"], **pipeline.current_score(loads(row["data"], {}))}
    finally:
        con.close()


@app.get("/api/news")
def api_news(theme: str | None = None, limit: int = Query(50, le=500)):
    con = connect()
    try:
        rows = con.execute("SELECT title,url,source,published,market,themes,sentiment,confidence,industries,method"
                           " FROM articles WHERE analyzed=1 ORDER BY published DESC LIMIT 2000").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["themes"], d["industries"] = loads(d["themes"], []), loads(d["industries"], [])
            if theme and theme not in d["themes"]:
                continue
            out.append(d)
            if len(out) >= limit:
                break
        return out
    finally:
        con.close()


@app.post("/api/run")
def api_run(step: str = Query("all", pattern="^(catalog|news|official|flows|signals|score|all)$")):
    if pipeline.STATUS["running"]:
        return {"started": False, "reason": "already running", **pipeline.STATUS}
    threading.Thread(target=pipeline.run, args=(step,), daemon=True).start()
    return {"started": True, "step": step}


@app.get("/api/status")
def api_status():
    return pipeline.STATUS


@app.get("/api/filings/{ticker}")
def api_filings(ticker: str, as_of: datetime | None = None):
    if as_of and as_of.tzinfo is None:
        raise HTTPException(422, "as_of requires a timezone")
    con = connect()
    try:
        return history(con, ticker.upper(), as_of.isoformat() if as_of else None)
    finally:
        con.close()


@app.get("/api/sources")
def api_sources():
    con = connect()
    try:
        return source_status(con)
    finally:
        con.close()
