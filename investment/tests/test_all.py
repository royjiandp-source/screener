"""Offline tests with fake data (no internet needed). Run: pytest -q"""
import datetime as dt
import os
import random

import pytest

os.environ["DISABLE_SCHEDULER"] = "1"
os.environ.pop("GEMINI_API_KEY", None)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("INVEST_DB", str(tmp_path / "t.db"))
    from app import financials, macro, news

    def fake_rss(topic, market, days=2, n=15):
        now = dt.datetime.now(dt.timezone.utc)
        return [{"title": f"{topic} demand jumps as data center and nvidia gpu orders grow {i}",
                 "url": f"https://x/{market}/{topic}/{i}", "source": "Test",
                 "published": (now - dt.timedelta(hours=i)).isoformat(),
                 "content": "semiconductor and hbm news", "market": market, "topic": topic}
                for i in range(3)]

    def fake_fin(t):
        rnd = random.Random(t)
        return {"ticker": t, "name": f"Co {t}", "country": rnd.choice(["United States", "Taiwan", "South Korea"]),
                "sector": "Tech", "industry": "Chips", "currency": "USD", "price": 100.0,
                "market_cap": 1e11, "revenue_growth": rnd.uniform(-5, 30), "op_margin": rnd.uniform(-5, 40),
                "eps_growth": rnd.uniform(-10, 40), "debt_ratio": rnd.uniform(30, 260),
                "cash": 1e9, "current_ratio": 1.5, "ocf": 1e9, "ocf_trend": 5.0,
                "fcf": rnd.choice([1e9, 2e9, -1e8]), "capex": -1e8, "roe": rnd.uniform(-5, 40),
                "roic": rnd.uniform(0, 30), "fcf_yield": rnd.uniform(-1, 8), "per": rnd.uniform(8, 60),
                "fwd_per": 20.0, "pbr": rnd.uniform(1, 12), "psr": 5.0, "ev_ebitda": rnd.choice([None, 12.0, 25.0]),
                "dcf_value": 120.0, "dcf_upside": 20.0, "mom_1m": rnd.uniform(-8, 12), "years": 4}

    monkeypatch.setattr(news, "fetch_rss", fake_rss)
    monkeypatch.setattr(financials, "fetch", fake_fin)
    monkeypatch.setattr(financials.time, "sleep", lambda s: None)
    monkeypatch.setattr(macro, "snapshot", lambda: {"cycle": "Expansion", "fed_rate": 4.1, "cpi_yoy": 2.8,
                                                    "gdp_yoy": 2.1, "unemployment": 4.2})
    return tmp_path


def test_scoring_rules():
    from app import scoring
    assert scoring.lin(15, 0, 15) == 1 and scoring.lin(0, 0, 15) == 0
    assert scoring.lin(100, 300, 100) == 1          # lower debt is better
    good = {"roe": 30, "roic": 20, "debt_ratio": 50, "fcf_yield": 6}
    assert scoring.financial_health(good)[0] == 30
    assert scoring.financial_health({})[0] == 15     # missing -> half
    assert scoring.valuation({"per": -5})[0] == 0    # losses -> 0
    rk = scoring.risk({"country": "Taiwan", "debt_ratio": 250}, {"industry_risks": ["tariffs"]},
                      {"country": ["Taiwan"], "geopolitical": ["Taiwan"]}, {})
    assert rk["label"] == "High" and rk["score"] < 5


def test_macro_cycle():
    from app.macro import classify
    assert classify(-0.5, 1.0, 0.1) == "Recession"
    assert classify(1.2, 0.8, 0.1) == "Recovery"
    assert classify(2.5, 2.0, 0.1) == "Expansion"
    assert classify(1.8, 2.5, 0.2) == "Slowdown"


def test_pipeline_and_api(env):
    from fastapi.testclient import TestClient
    from app import pipeline
    from app.main import app

    out = pipeline.run("all")
    assert out["status"] == "ok", out
    assert out["news"]["new_articles"] > 0 and out["score"]["scored"] > 30

    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200 and "Top Themes" in r.text and "Avoid List" in r.text
    rep = c.get("/api/report").json()
    assert rep["themes"][0]["score"] >= rep["themes"][-1]["score"]
    # Legacy financial fixture has no normalized FCFF/shares: no fabricated ranking.
    assert rep["top_stocks"] == []
    assert len(rep["review_list"]) > 30
    assert all(s["total"] is None for s in rep["review_list"])
    assert c.get("/api/stocks?market=KR").json()[0]["market"] == "KR"
    assert c.get("/api/stocks/NVDA").json()["ticker"] == "NVDA"
    assert c.get("/api/stocks/ZZZZ").status_code == 404
    assert c.get("/api/macro").json()["cycle"] == "Expansion"
    assert len(c.get("/api/news?theme=AI%20Infrastructure").json()) > 0
    assert c.get("/api/status").json()["running"] is False

    # static export used by GitHub Pages
    from app.web import render
    html = render(pipeline.report(pipeline.connect()), static=True)
    assert "Run now" not in html and "Value Picks" in html


def test_financials_fetch_math(monkeypatch):
    """Check ROE / ROIC / growth / FCF yield math on a fake Yahoo ticker."""
    import pandas as pd
    from app import financials
    cols = pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"])

    class T:
        info = {"shortName": "Fake", "currency": "USD", "financialCurrency": "USD", "marketCap": 1000.0,
                "trailingPE": 20, "priceToBook": 3, "enterpriseToEbitda": 12, "sharesOutstanding": 10,
                "currentPrice": 100, "country": "United States"}
        income_stmt = pd.DataFrame({c: v for c, v in zip(cols, [
            [100, 20, 20, 10, 1.0, 0.2], [110, 22, 22, 11, 1.1, 0.2],
            [121, 24, 24, 12, 1.2, 0.2], [133.1, 27, 27, 14, 1.4, 0.2]])},
            index=["Total Revenue", "Operating Income", "EBIT", "Net Income", "Diluted EPS", "Tax Rate For Calcs"])
        balance_sheet = pd.DataFrame({cols[-1]: [70, 80, 50, 10, 40, 20]},
                                     index=["Stockholders Equity", "Total Liabilities Net Minority Interest",
                                            "Total Debt", "Cash And Cash Equivalents", "Current Assets",
                                            "Current Liabilities"])
        cashflow = pd.DataFrame({cols[-1]: [30, -10, 20]},
                                index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"])

        def history(self, period):
            return pd.DataFrame({"Close": [100.0] * 30 + [110.0]})

    monkeypatch.setattr(financials.yf, "Ticker", lambda t: T())
    m = financials.fetch("FAKE")
    assert m["revenue_growth"] == 10.0                    # 100 -> 133.1 over 3 yrs
    assert m["roe"] == 20.0                               # 14 / 70
    assert m["roic"] == round(27 * 0.8 / 110 * 100, 2)    # EBIT*(1-t)/(debt+equity-cash)
    assert m["fcf_yield"] == 2.0                          # 20 / 1000
    assert m["debt_ratio"] == round(80 / 70 * 100, 2)
    assert m["current_ratio"] == 2.0 and m["mom_1m"] == 10.0
    assert m["dcf_value"] is None  # raw CFO-capex must not be passed off as FCFF
    assert m["normalized_fcf"] is None  # fewer than three complete FCFF periods


def test_gemini_path(env, monkeypatch):
    """Gemini JSON answer is parsed and only allowed theme names are kept."""
    import json
    from app import themes as th
    from app.db import connect, load_themes
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    con = connect()
    con.execute("INSERT INTO articles(url,title,content,published) VALUES('u1','TSMC expands HBM','', '2099-01-01')")
    con.commit()
    rid = con.execute("SELECT id FROM articles").fetchone()[0]
    monkeypatch.setattr(th, "_gemini_batch", lambda a, t: {rid: {
        "id": rid, "themes": ["AI Infrastructure", "Made Up"], "sentiment": "Positive",
        "confidence": 95, "affectedIndustries": ["Memory"]}})
    out = th.analyze_pending(con, load_themes()["themes"])
    row = con.execute("SELECT * FROM articles WHERE id=?", (rid,)).fetchone()
    assert out["analyzed"] == 1 and row["method"] == "gemini"
    assert json.loads(row["themes"]) == ["AI Infrastructure"] and row["sentiment"] == "Positive"
