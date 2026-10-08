"""Value calculations and country isolation use offline, deterministic inputs."""
import math

import pytest


def test_dcf_cashflow_type_and_claims():
    from app import valuation
    firm = valuation.dcf(100, 10, growth=0, discount=10, terminal=0,
                         years=1, cashflow_type="FCFF", net_debt=100)
    equity = valuation.dcf(100, 10, growth=0, discount=10, terminal=0,
                           years=1, cashflow_type="FCFE", net_debt=100)
    assert firm == pytest.approx(90)
    assert equity == pytest.approx(100)


@pytest.mark.parametrize("kwargs", [
    {"discount": 2, "terminal": 2}, {"shares": 0}, {"fcf": math.nan},
    {"years": 0}, {"cashflow_type": "UNKNOWN"}, {"growth": -101},
])
def test_dcf_rejects_invalid_inputs(kwargs):
    from app import valuation
    values = {"fcf": 100, "shares": 10}
    values.update(kwargs)
    with pytest.raises(ValueError):
        valuation.dcf(**values)


def test_safety_margin_and_currency_gate():
    from app import valuation
    assert valuation.safety_margin(70, 100) == pytest.approx(30)
    assert valuation.safety_margin(120, 100) == pytest.approx(-20)
    assert valuation.safety_margin(70, 0) is None
    m = {"normalized_fcf": 100, "shares": 10, "net_debt": 0,
         "cashflow_type": "FCFF", "discount_rate": 10, "terminal_growth": 2,
         "revenue_growth": 5, "price": 70, "currency": "USD", "financial_currency": "KRW"}
    assert valuation.evaluate(m)["status"] == "data_insufficient"
    m["fx_rate"] = 0.001
    result = valuation.evaluate(m)
    assert result["status"] == "estimated"
    assert len(result["scenarios"]) == 3
    assert result["scenarios"]["conservative"]["value"] < result["scenarios"]["optimistic"]["value"]
    assert len(result["sensitivity"]) == 9


def test_missing_data_and_special_industries_are_not_candidates():
    from app import scoring
    assert scoring.value_score({})["total"] is None
    assert scoring.value_score({})["value_pick"] is False
    assert scoring.value_score({"sector": "Financial Services"})["analysis_status"] == "special_model_required"
    assert scoring.value_score({"industry": "REIT - Retail"})["analysis_status"] == "special_model_required"


def test_country_mapping_does_not_guess_unknown_listings():
    from app.pipeline import market_of
    assert market_of("7203.T") == "UNKNOWN"      # JP/TW/HK are no longer supported
    assert market_of("0700.HK") == "UNKNOWN"
    assert market_of("D05.SI") == "SG"
    assert market_of("TSM") == "US"
    assert market_of("FOO.UNKNOWN") == "UNKNOWN"


def test_value_score_has_no_news_or_macro_component():
    from app import scoring
    m = {"normalized_fcf": 100, "shares": 10, "net_debt": 0, "cashflow_type": "FCFF",
         "discount_rate": 10, "terminal_growth": 2, "currency": "USD",
         "financial_currency": "USD", "price": 50, "roic": 20, "op_margin": 25,
         "ocf": 110, "fcf": 100, "debt_ratio": 50,
         "revenue_growth": 5, "eps_growth": 6}
    result = scoring.value_score(m)
    assert 0 <= result["total"] <= 100
    assert set(result["parts"]) == {"valuation", "quality", "financial", "allocation", "growth"}
    assert result["parts"]["allocation"] == 0  # no sourced governance inputs
    assert result["data_quality"] == "unverified"


def test_country_api_and_empty_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("INVEST_DB", str(tmp_path / "countries.db"))
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get('/api/countries').status_code==404
    assert set(c.get('/api/report').json()['coverage'])=={'KR','SG','US'}
    assert c.get('/api/stocks?market=ZZ').status_code==422
    assert c.get('/api/stocks?limit=0').status_code==422
    assert c.get('/?market=JP').status_code==422
    page=c.get('/?market=KR')
    assert page.status_code==200 and '전체 목록 미확보' in page.text


def test_fcff_uses_aligned_years_and_does_not_fill_missing_zero():
    import pandas as pd
    from app.financials import annual_fcff
    dates = pd.to_datetime(["2023-12-31", "2024-12-31", "2025-12-31"])
    inc = pd.DataFrame({d: [100, 0.2] for d in dates}, index=["EBIT", "Tax Rate For Calcs"])
    cf = pd.DataFrame({dates[0]: [10, -20, -5], dates[1]: [10, -20, float("nan")],
                       dates[2]: [10, -20, -5]},
                      index=["Depreciation And Amortization", "Capital Expenditure", "Change In Working Capital"])
    assert annual_fcff(inc, cf) == [{"period_end": "2023-12-31", "fcff": 65.0},
                                   {"period_end": "2025-12-31", "fcff": 65.0}]


def test_pipeline_scores_catalog_without_theme_membership(tmp_path, monkeypatch):
    from app import pipeline
    from app.discovery.providers import listing
    from app.discovery.store import replace_catalog
    monkeypatch.setenv('INVEST_DB',str(tmp_path/'u.db'))
    monkeypatch.setattr(pipeline,'get_financials',lambda c,ts:{'999999.KS':{'price':10}})
    con=pipeline.connect()
    replace_catalog(con,'KR',[listing('KR','KOSPI','999999','Unclassified company')],'Exchange','2026-10-01T00:00:00Z',True)
    pipeline.run_score(con,markets=('KR',))
    stocks=pipeline.stocks(con,market='KR')
    assert stocks[0]['analysis_status']=='data_insufficient' and stocks[0]['total'] is None
    assert pipeline.report(con)['value_candidates']['total']==0
    con.close()


def test_partial_market_run_preserves_other_countries(tmp_path, monkeypatch):
    from app import pipeline
    from app.db import dumps
    from app.discovery.providers import listing
    from app.discovery.store import replace_catalog
    monkeypatch.setenv('INVEST_DB',str(tmp_path/'partial.db'))
    monkeypatch.setattr(pipeline,'get_financials',lambda c,ts:{})
    con=pipeline.connect()
    for t,market in [('AAPL','US'),('D05.SI','SG')]:
        con.execute('INSERT INTO stock_scores VALUES(?,?,?,?,?)',(pipeline.today(),t,market,None,dumps({'market':market,'score_version':'value-v1','total':None,'metrics':{}})))
    con.commit()
    replace_catalog(con,'KR',[listing('KR','KOSPI','999999','Example')],'Exchange','2026-10-01T00:00:00Z',True)
    pipeline.run_score(con,markets=('KR',))
    assert pipeline.stocks(con,market='US')[0]['ticker']=='AAPL'
    assert pipeline.stocks(con,market='SG')[0]['ticker']=='D05.SI'
    con.close()


def test_positive_valuation_is_exposed_in_catalog_report(tmp_path,monkeypatch):
    from app import pipeline
    from app.discovery.providers import listing
    from app.discovery.store import replace_catalog
    from app.web import render
    monkeypatch.setenv('INVEST_DB',str(tmp_path/'rank.db'))
    metrics={'ticker':'EXAMPLE','normalized_fcf':100,'shares':10,'cashflow_type':'FCFF','net_debt':0,
             'discount_rate':10,'terminal_growth':2,'currency':'USD','financial_currency':'USD',
             'price':50,'fcf':100,'ocf':120}
    monkeypatch.setattr(pipeline,'get_financials',lambda c,ts:{'EXAMPLE':metrics})
    con=pipeline.connect()
    replace_catalog(con,'US',[listing('US','NASDAQ','EXAMPLE','Example')],'Exchange','2026-10-01T00:00:00Z',True)
    pipeline.run_score(con,markets=('US',))
    result=pipeline.report(con,market='US',min_score=0)
    assert result['value_candidates']['items'][0]['analysis']['valuation']['status']=='estimated'
    assert '보수적' in render(result) and '안전마진' in render(result)
    con.close()


def test_missing_price_and_unconfirmed_adr_cannot_rank():
    from app.scoring import value_score
    m = {"normalized_fcf": 100, "shares": 10, "net_debt": 0,
         "cashflow_type": "FCFF", "discount_rate": 10, "terminal_growth": 2,
         "currency": "USD", "financial_currency": "USD"}
    assert value_score(m)["total"] is None
    m.update(price=10, share_basis_verified=False)
    assert value_score(m)["analysis_status"] == "review_required"
    assert not value_score(m)["value_pick"]


def test_old_financial_cache_is_refetched(tmp_path, monkeypatch):
    from app import pipeline
    from app.db import dumps
    monkeypatch.setenv("INVEST_DB", str(tmp_path / "cache.db"))
    con = pipeline.connect()
    con.execute("INSERT INTO fin_cache VALUES(?,?,?)", ("AAPL", pipeline.today(), dumps({"roe": 10})))
    con.commit()
    monkeypatch.setattr(pipeline.financials, "fetch_many", lambda tickers: {
        ticker: {"schema_version": "value-v1", "normalized_fcf": 100} for ticker in tickers})
    assert pipeline.get_financials(con, ["AAPL"])["AAPL"]["normalized_fcf"] == 100
    con.close()


def test_absent_tax_debt_or_cash_do_not_create_roic(monkeypatch):
    import pandas as pd
    from app import financials
    date = pd.Timestamp("2025-12-31")
    class T:
        info = {"currency": "USD", "financialCurrency": "USD"}
        income_stmt = pd.DataFrame({date: [100, -10]}, index=["EBIT", "Net Income"])
        balance_sheet = pd.DataFrame({date: [-10, 100]}, index=["Stockholders Equity", "Total Liabilities Net Minority Interest"])
        cashflow = pd.DataFrame()
        def history(self, period):
            return pd.DataFrame({"Close": []})
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: T())
    result = financials.fetch("TEST")
    assert result["roic"] is None
    assert result["roe"] is None
    assert result["debt_ratio"] is None
    assert result["equity_nonpositive"] is True


def test_legacy_api_scores_require_rerun(tmp_path, monkeypatch):
    from app.db import connect, dumps
    from app.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setenv("INVEST_DB", str(tmp_path / "legacy.db"))
    con = connect()
    con.execute("INSERT INTO stock_scores VALUES(?,?,?,?,?)", ("2026-10-05", "AAPL", "US", 95,
        dumps({"market": "US", "total": 95, "metrics": {}})))
    con.commit()
    con.close()
    c = TestClient(app)
    assert c.get("/api/stocks/AAPL").json()["total"] is None
    assert c.get("/api/stocks").json()[0]["analysis_status"] == "requires_rerun"


def test_reverse_dcf_recovers_price_implied_growth():
    from app import valuation
    price = valuation.dcf(100, 10, growth=5, discount=10, terminal=2, net_debt=20)
    result = valuation.reverse_dcf(100, 10, price, discount=10, terminal=2, net_debt=20)
    assert result["status"] == "estimated"
    assert result["implied_growth"] == pytest.approx(5, abs=1e-5)
    assert valuation.reverse_dcf(100, 10, 1e9)["status"] == "outside_search_range"
    with pytest.raises(ValueError):
        valuation.reverse_dcf(100, 10, -1)


def test_dashboard_uses_relative_paths_and_konex_is_excluded():
    from pathlib import Path
    import inspect
    from app.discovery import providers
    js = (Path(__file__).resolve().parents[1] / 'app' / 'dashboard.js').read_text()
    assert "'/api/" not in js and "'api/report?" in js
    assert "konexMkt" not in inspect.getsource(providers.fetch_catalog)
