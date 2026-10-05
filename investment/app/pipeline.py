"""Pipeline: news -> themes -> industries -> stocks -> financials -> valuation -> risk -> score.
파이프라인 실행 + 최종 리포트.

CLI:
    python -m app.pipeline news            # collect + analyze news
    python -m app.pipeline score           # financials + scoring
    python -m app.pipeline all             # everything
    python -m app.pipeline all --export ../docs/invest/index.html
"""
import argparse
import threading
import traceback
from pathlib import Path

from . import financials, macro, news, scoring, themes as theme_mod
from .db import connect, dumps, load_themes, loads, now, today

MARKETS = ("US", "KR", "SG")
_lock = threading.Lock()
STATUS = {"running": False, "step": None, "started": None, "last": None}


# ------------------------------------------------------------------ steps
def run_news(con, markets=MARKETS) -> dict:
    cfg = load_themes()
    c = news.collect(con, markets)
    a = theme_mod.analyze_pending(con, cfg["themes"])
    return {**c, **a}


def get_macro(con, refresh=False) -> dict:
    day = today()
    row = con.execute("SELECT data FROM macro WHERE day=?", (day,)).fetchone()
    if row and not refresh:
        return loads(row["data"], {})
    data = macro.snapshot()
    con.execute("INSERT OR REPLACE INTO macro(day,data) VALUES(?,?)", (day, dumps(data)))
    con.commit()
    return data


def get_financials(con, tickers) -> dict:
    """Financials are cached once per day per ticker."""
    day, out, todo = today(), {}, []
    for t in tickers:
        row = con.execute("SELECT data FROM fin_cache WHERE ticker=? AND day=?", (t, day)).fetchone()
        if row:
            out[t] = loads(row["data"])
        else:
            todo.append(t)
    for t, m in financials.fetch_many(todo).items():
        out[t] = m
        if m:
            con.execute("INSERT OR REPLACE INTO fin_cache(ticker,day,data) VALUES(?,?,?)",
                        (t, day, dumps(m)))
    con.commit()
    return out


def market_of(ticker: str) -> str:
    if ticker.endswith((".KS", ".KQ")):
        return "KR"
    if ticker.endswith(".SI"):
        return "SG"
    return "US"


def run_score(con, markets=MARKETS) -> dict:
    cfg = load_themes()
    th_cfg, cycles, risk_cfg = cfg["themes"], cfg["cycles"], cfg["risk"]

    # 1) theme engine output  2) macro cycle
    tm = theme_mod.theme_momentum(con, th_cfg)
    mac = get_macro(con)
    cycle = mac.get("cycle", "Unknown")

    # 3) industry mapping -> candidate stocks
    stock_themes: dict[str, list] = {}
    for name, c in th_cfg.items():
        for m in markets:
            for tk in c["tickers"].get(m, []):
                stock_themes.setdefault(tk, []).append(name)

    # 4) financial statements + valuation
    fin = get_financials(con, list(stock_themes))

    # money flow proxy: average 1-month price move of each theme's stocks
    flows = {}
    for name, c in th_cfg.items():
        moves = [fin[t]["mom_1m"] for m in markets for t in c["tickers"].get(m, [])
                 if fin.get(t) and fin[t].get("mom_1m") is not None]
        flows[name] = round(sum(moves) / len(moves), 2) if moves else None
    max_count = max((v["news_count"] for v in tm.values()), default=0)

    day = today()
    con.execute("DELETE FROM theme_scores WHERE day=?", (day,))
    con.execute("DELETE FROM stock_scores WHERE day=?", (day,))
    for name in th_cfg:
        t = tm[name]
        row = {**{k: v for k, v in t.items()}, "flow_1m": flows[name],
               "score": scoring.theme_score(t, max_count, flows[name]),
               "industries": th_cfg[name]["industries"],
               "favored_by_cycle": name in cycles.get(cycle, [])}
        con.execute("INSERT INTO theme_scores(day,theme,data) VALUES(?,?,?)", (day, name, dumps(row)))

    # 5) risk + 6) scoring
    scored = 0
    for tk, names in stock_themes.items():
        m = fin.get(tk)
        if not m:
            continue
        best = None
        for name in names:  # a stock in several themes uses its best theme
            s = scoring.score_stock(m, name, th_cfg[name], tm, max_count, flows[name],
                                    cycle, cycles, risk_cfg)
            if best is None or s["total"] > best["total"]:
                best = {**s, "theme": name}
        best["all_themes"] = names
        data = {"metrics": m, **best, "market": market_of(tk)}
        con.execute("INSERT INTO stock_scores(day,ticker,market,total,data) VALUES(?,?,?,?,?)",
                    (day, tk, market_of(tk), best["total"], dumps(data)))
        scored += 1
    con.commit()
    return {"day": day, "cycle": cycle, "candidates": len(stock_themes), "scored": scored}


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
        if step in ("news", "all"):
            out["news"] = run_news(con, markets)
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


def stocks(con, day=None, market=None, limit=None) -> list:
    day = day or latest_day(con)
    if not day:
        return []
    q, args = "SELECT ticker,data FROM stock_scores WHERE day=?", [day]
    if market:
        q += " AND market=?"
        args.append(market.upper())
    q += " ORDER BY total DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    return [{"ticker": r["ticker"], **loads(r["data"], {})} for r in con.execute(q, args)]


def theme_table(con, day=None) -> list:
    day = day or latest_day(con)
    rows = [{"theme": r["theme"], **loads(r["data"], {})}
            for r in con.execute("SELECT theme,data FROM theme_scores WHERE day=?", (day,))]
    return sorted(rows, key=lambda x: x.get("score", 0), reverse=True)


def report(con) -> dict:
    day = latest_day(con)
    all_stocks = stocks(con, day)
    mac = loads((con.execute("SELECT data FROM macro ORDER BY day DESC LIMIT 1").fetchone() or {"data": None})["data"], {})
    last_run = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    n_news = con.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
    top = [s for s in all_stocks if not s.get("avoid")]
    by_market = {m: [s for s in top if s["market"] == m][:5] for m in MARKETS}
    return {
        "day": day, "generated": now().isoformat(timespec="minutes"),
        "macro": mac, "themes": theme_table(con, day),
        "top_stocks": top[:10], "top_by_market": by_market,
        "value_picks": [s for s in all_stocks if s.get("value_pick") and not s.get("avoid")][:10],
        "avoid_list": [s for s in all_stocks if s.get("avoid")],
        "news_total": n_news,
        "last_run": dict(last_run) if last_run else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", nargs="?", default="all", choices=["news", "score", "all", "none"])
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
        p.write_text(render(report(con), static=True), encoding="utf-8")
        print(f"Exported: {p.resolve()}")


if __name__ == "__main__":
    main()
