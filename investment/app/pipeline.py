"""Pipeline: news -> themes -> industries -> stocks -> financials -> valuation -> risk -> score.
파이프라인 실행 + 최종 리포트.

CLI:
    python -m app.pipeline news            # collect + analyze news
    python -m app.pipeline score           # financials + scoring
    python -m app.pipeline all             # everything
    python -m app.pipeline all --export ../docs/invest/index.html
"""
import argparse
import os
import time
import threading
import traceback
from pathlib import Path

from . import financials, news, scoring, themes as theme_mod
from .db import connect, dumps, load_themes, load_universe, loads, now, today
from .countries import SEARCH_MARKETS, market_of
from .filings import service as official
from .filings.store import verify_metrics

MARKETS = SEARCH_MARKETS
_lock = threading.Lock()
STATUS = {"running": False, "step": None, "started": None, "last": None}


# ------------------------------------------------------------------ steps
def run_news(con, markets=MARKETS) -> dict:
    cfg = load_themes()
    c = news.collect(con, tuple(m for m in markets if m in news.EDITIONS))
    a = theme_mod.analyze_pending(con, cfg["themes"])
    return {**c, **a}


def get_financials(con, tickers) -> dict:
    """Financials are cached once per day per ticker."""
    day, out, todo = today(), {}, []
    for t in tickers:
        row = con.execute("SELECT data FROM fin_cache WHERE ticker=? AND day=?", (t, day)).fetchone()
        cached = loads(row["data"], {}) if row else {}
        if cached and cached.get("schema_version") == "value-v2":
            out[t] = cached
        else:
            todo.append(t)
    for t, m in financials.fetch_many(todo).items():
        out[t] = m
        if m:
            con.execute("INSERT OR REPLACE INTO fin_cache(ticker,day,data) VALUES(?,?,?)",
                        (t, day, dumps(m)))
    con.commit()
    return out


def _score_queue(con, markets):
    """Configured candidates first (kept fresh daily), then the rest of the catalog, oldest first.
    Markets alternate so a large US catalog cannot starve KR/SG."""
    from .discovery.store import search
    universe = load_universe()
    configured = {t for m in markets for t in universe["markets"].get(m, [])}
    last = {r[0]: r[1] or "" for r in con.execute("SELECT ticker, MAX(day) FROM stock_scores GROUP BY ticker")}
    for r in con.execute("SELECT ticker, day FROM score_attempts"):
        last[r[0]] = max(last.get(r[0], ""), r[1] or "")
    day = today()
    queues = []
    for market in markets:
        tickers = list(dict.fromkeys(x["ticker"] for x in search(con, "", market, limit=1000000)["items"]
                                     if x["type"] in ("stock", "adr")))
        tickers = [t for t in tickers if last.get(t, "") < day]
        tickers.sort(key=lambda t: (t not in configured, last.get(t, ""), t))
        queues.append(tickers)
    return [q[i] for i in range(max((len(q) for q in queues), default=0)) for q in queues if i < len(q)]


def run_score(con, markets=MARKETS, tickers=None, limit=None, max_seconds=None) -> dict:
    """Score explicit tickers, or a bounded rotating batch of the whole catalog.
    전체 목록은 한 번에 평가하지 않고 매 실행마다 일부씩 순환 평가합니다."""
    universe = load_universe()
    pending = 0
    if tickers is None:
        limit = int(os.environ.get("INVEST_SCORE_BATCH", "150")) if limit is None else limit
        max_seconds = float(os.environ.get("INVEST_SCORE_SECONDS", "900")) if max_seconds is None else max_seconds
        queue = _score_queue(con, markets)
        tickers, pending = queue[:max(0, limit)], len(queue)
    stock_themes = {tk: [] for tk in tickers}
    th_cfg = load_themes()['themes']
    for name, cfg in th_cfg.items():
        for market in markets:
            for tk in cfg['tickers'].get(market, []):
                if tk in stock_themes:
                    stock_themes[tk].append(name)
    day = today()

    # 5) risk + 6) scoring, one ticker at a time so the time budget is respected
    scored, failed, attempted = 0, 0, 0
    started = time.monotonic()
    for tk, names in stock_themes.items():
        if max_seconds is not None and time.monotonic() - started >= max_seconds:
            break
        attempted += 1
        m = get_financials(con, [tk]).get(tk)
        if not m or m.get("fetch_error"):
            failed += 1
            con.execute("INSERT OR REPLACE INTO score_attempts(ticker,day,status) VALUES(?,?,?)", (tk, day, "failed"))
            con.commit()
            continue
        # User-supplied company assumptions override explicit illustrative defaults.
        m = {**universe.get("valuation_assumptions", {}), **m,
             **universe.get("company_assumptions", {}).get(tk, {})}
        verification = verify_metrics(con, tk, m)
        m["official_verification"] = verification
        if verification["status"] == "conflict":
            m["accounting_issue"] = True
        best = scoring.value_score(m)
        best["theme"] = names[0] if names else "Unclassified"
        best["all_themes"] = names
        data = {"metrics": m, **best, "market": market_of(tk),
                "listing_country": market_of(tk), "domicile_country": m.get("country")}
        con.execute("INSERT OR REPLACE INTO stock_scores(day,ticker,market,total,data) VALUES(?,?,?,?,?)",
                    (day, tk, market_of(tk), best["total"], dumps(data)))
        con.execute("INSERT OR REPLACE INTO score_attempts(ticker,day,status) VALUES(?,?,?)", (tk, day, "scored"))
        con.commit()
        scored += 1
    return {"day": day, "candidates": len(stock_themes), "attempted": attempted, "scored": scored,
            "failed": failed, "remaining_today": max(0, pending - attempted)}


def run_catalog(con, markets=MARKETS, max_age_days=None) -> dict:
    """Refresh exchange lists that are missing or older than INVEST_CATALOG_DAYS (default 7)."""
    import datetime as dt
    from .discovery.providers import refresh_market
    from .discovery.store import init
    from .filings.common import utc
    init(con)
    days = int(os.environ.get("INVEST_CATALOG_DAYS", "7")) if max_age_days is None else max_age_days
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(timespec="seconds")
    out = {}
    for market in markets:
        row = con.execute("SELECT MAX(observed_at) FROM catalog_snapshots WHERE market=?", (market,)).fetchone()
        if row and row[0] and utc(row[0]) >= cutoff:
            out[market] = "fresh"
            continue
        out[market] = refresh_market(con, market).get("status")
    return out


def run_signals(con, markets=MARKETS, limit=None, max_seconds=300):
    """Collect a bounded rotating batch before exporting; keep prior facts on failure."""
    from .discovery.store import search, save_flow
    from .discovery.profiles import enrich_listing
    from .filings.common import utc
    limit = int(os.environ.get('INVEST_SIGNAL_BATCH', '100')) if limit is None else limit
    latest = {r['listing_id']: r['attempted'] for r in con.execute(
        "SELECT listing_id, MAX(CASE WHEN kind='leadership' THEN period ELSE observed_at END) attempted FROM flow_snapshots "
        "WHERE kind IN ('leadership','signal_collection_status') GROUP BY listing_id")}
    scored = {r['ticker'] for r in con.execute('SELECT DISTINCT ticker FROM stock_scores')}
    day = utc()[:10]
    queues = []
    for market in markets:
        rows = [x for x in search(con, '', market, limit=1000000)['items']
                if x['type'] in ('stock', 'adr') and latest.get(x['id'], '')[:10] < day]
        rows.sort(key=lambda x: (latest.get(x['id'], ''), x['ticker'] not in scored, x['code']))
        queues.append(rows)
    # Alternate markets so a large US/KR catalog cannot starve the other markets.
    selected = [q[i] for i in range(max((len(q) for q in queues), default=0)) for q in queues if i < len(q)]
    result = {'candidates': len(selected), 'attempted': 0, 'collected': 0, 'failed': 0}
    started = time.monotonic()
    for item in selected[:max(0, limit)]:
        if time.monotonic() - started >= max_seconds:
            break
        try:
            data = enrich_listing(con, item['id'])
            if not data.get('period'):
                raise ValueError('No comparable price dates')
            state = {'status': 'collected', 'period': data['period']}
            result['collected'] += 1
        except Exception as exc:
            state = {'status': 'failed', 'reason': type(exc).__name__}
            result['failed'] += 1
        save_flow(con, item['id'], 'signal_collection_status', day, state)
        result['attempted'] += 1
    result['remaining'] = len(selected) - result['attempted']
    return result


def score_tickers(con, tickers):
    return run_score(con, tuple({market_of(t) for t in tickers}), tickers=tickers)


# ------------------------------------------------------------------ run wrapper
def run(step: str = "all", markets=MARKETS) -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "step": STATUS["step"]}
    con = connect()
    started = now().isoformat()
    STATUS.update(running=True, step=step, started=started)
    rid = con.execute("INSERT INTO runs(started,step,status) VALUES(?,?,?)",
                      (started, step, "running")).lastrowid
    con.commit()
    try:
        out = {}
        if step in ("catalog", "all"):
            out["catalog"] = run_catalog(con, markets)
        if step in ("news", "all"):
            out["news"] = run_news(con, markets)
        if step in ("official", "all"):
            out["official"] = official.collect(con, markets)
        if step in ("flows", "signals", "score", "all"):
            from .flows.collection import run_funds
            out["funds"] = run_funds(con, markets)
        if step in ("signals", "score", "all"):
            out["signals"] = run_signals(con, markets)
        if step in ("score", "all"):
            out["score"] = run_score(con, markets)
        status, msg = "ok", dumps(out)
    except Exception as e:
        traceback.print_exc()
        status, msg, out = "error", f"{type(e).__name__}: {e}", {"error": str(e)}
    finally:
        con.execute("UPDATE runs SET finished=?, status=?, message=? WHERE id=?",
                    (now().isoformat(), status, msg, rid))
        con.commit()
        con.close()
        STATUS.update(running=False, step=None, last={"step": step, "status": status, "at": now().isoformat()})
        _lock.release()
    return {"status": status, **out}


# ------------------------------------------------------------------ report
def latest_day(con):
    r = con.execute("SELECT MAX(day) d FROM stock_scores").fetchone()
    return r["d"] if r else None


def current_score(data):
    if data.get("score_version") == "value-v1":
        return data
    return {**data, "total": None, "parts": {}, "value_pick": False,
            "analysis_status": "requires_rerun", "valuation": {"status": "requires_rerun"}}


def stocks(con, day=None, market=None, limit=None) -> list:
    if day:
        q, args = "SELECT ticker,day,data FROM stock_scores WHERE day=?", [day]
    else:
        q, args = ("SELECT ticker,day,data FROM stock_scores s WHERE day="
                   "(SELECT MAX(day) FROM stock_scores newest WHERE newest.ticker=s.ticker)"), []
    if market:
        q += " AND market=?"
        args.append(market.upper())
    q += " ORDER BY total DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    return [{**current_score(loads(r["data"], {})), "ticker": r["ticker"], "day": r["day"]} for r in con.execute(q, args)]


def report(con, market=None, **filters) -> dict:
    from .dashboard import build_report
    return build_report(con, market=market, **filters)


def static_report(con):
    # Value candidates must never disappear behind inaccessible static pagination.
    result = report(con, limit=1000000)
    result['observations']['items'] = result['observations']['items'][:50]
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", nargs="?", default="all", choices=["catalog", "news", "official", "flows", "signals", "score", "all", "none"])
    ap.add_argument("--markets", nargs="+", default=list(MARKETS))
    ap.add_argument("--export", help="write the dashboard as a static HTML file")
    a = ap.parse_args()
    if a.step != "none":
        print(run(a.step, tuple(m.upper() for m in a.markets)))
    if a.export:
        from .web import render
        con = connect()
        p = Path(a.export)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render(static_report(con), static=True), encoding="utf-8")
        print(f"Exported: {p.resolve()}")


if __name__ == "__main__":
    main()
