"""Official disclosure adapters and point-in-time evidence, without network calls."""
import pytest


@pytest.fixture
def filing_db(tmp_path, monkeypatch):
    monkeypatch.setenv("INVEST_DB", str(tmp_path / "filings.db"))
    from app.db import connect
    con = connect()
    yield con
    con.close()


def sec_data():
    return {"cik": 123, "facts": {"us-gaap": {"CashAndCashEquivalentsAtCarryingValue": {
        "units": {"USD": [
            {"end": "2025-12-31", "val": 100, "accn": "0000000123-26-000001",
             "filed": "2026-02-01", "form": "10-K"},
            {"end": "2025-12-31", "val": 120, "accn": "0000000123-26-000002",
             "filed": "2026-03-01", "form": "10-K/A"}]}}}}}


def test_sec_preserves_restatements_and_units():
    from app.filings.sec import parse_facts
    data = sec_data()
    data["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"]["EUR"] = [
        {"end": "2025-12-31", "val": 90, "accn": "0000000123-26-000001",
         "filed": "2026-02-01", "form": "10-K"}]
    rows = parse_facts(data)
    assert len(rows) == 3
    assert {r["unit"] for r in rows} == {"USD", "EUR"}
    assert {r["value"] for r in rows} == {100, 120, 90}
    assert rows[0]["entity_id"] == "SEC:0000000123"
    assert all(r["scope"] == "consolidated" for r in rows)


def test_storage_is_immutable_and_asof_has_no_future_data(filing_db):
    from app.filings.sec import parse_facts
    from app.filings.store import save_snapshot, facts_asof
    original = sec_data()
    original["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"].pop()
    first = save_snapshot(filing_db, "AAPL", "US", "SEC", original, parse_facts(original),
                          observed_at="2026-02-03T00:00:00+00:00")
    repeated = save_snapshot(filing_db, "AAPL", "US", "SEC", original, parse_facts(original),
                             observed_at="2026-02-04T00:00:00+00:00")
    assert first == repeated
    changed = sec_data()
    second = save_snapshot(filing_db, "AAPL", "US", "SEC", changed, parse_facts(changed),
                           observed_at="2026-03-03T00:00:00+00:00")
    assert second != first
    assert facts_asof(filing_db, "AAPL", "2026-02-02T00:00:00+00:00") == []
    feb = facts_asof(filing_db, "AAPL", "2026-02-20T00:00:00+00:00")
    assert {r["value"] for r in feb} == {100}
    march = facts_asof(filing_db, "AAPL", "2026-03-04T00:00:00+00:00")
    assert {r["value"] for r in march} == {100, 120}
    assert filing_db.execute("SELECT COUNT(*) FROM filing_snapshots").fetchone()[0] == 2


def test_dart_only_uses_requested_scope_and_never_infers_currency():
    from app.filings.dart import parse_accounts
    rows = [{"rcept_no": "20260301000001", "corp_code": "00126380", "sj_div": "BS",
             "account_id": "ifrs-full_CashAndCashEquivalents", "thstrm_amount": "1,200",
             "currency": "KRW", "fs_div": "CFS"},
            {"rcept_no": "20260301000001", "corp_code": "00126380", "sj_div": "BS",
             "account_id": "ifrs-full_CashAndCashEquivalents", "thstrm_amount": "900",
             "currency": "KRW", "fs_div": "OFS"}]
    filings = [{"rcept_no": "20260301000001", "rcept_dt": "20260301", "report_nm": "사업보고서 (2025.12)"}]
    result = parse_accounts({"status": "000", "list": rows}, filings, "CFS")
    assert len(result) == 1 and result[0]["value"] == 1200
    assert result[0]["period_end"] == "2025-12-31"
    assert result[0]["available_at"] == "2026-03-01T15:00:00+00:00"
    del rows[0]["currency"]
    assert parse_accounts({"status": "000", "list": rows}, filings, "CFS") == []


def test_dart_errors_do_not_expose_api_key():
    from app.filings.dart import check_response
    with pytest.raises(ValueError, match="DART status 020") as error:
        check_response({"status": "020", "message": "private-api-key"})
    assert "private-api-key" not in str(error.value)
    assert check_response({"status": "013"}) == []


def test_verification_requires_same_period_unit_and_scope(filing_db):
    from app.filings.sec import parse_facts
    from app.filings.store import save_snapshot, verify_metrics
    data = sec_data()
    save_snapshot(filing_db, "AAPL", "US", "SEC", data, parse_facts(data))
    m = {"cash": 120, "financial_currency": "USD", "statement_scope": "consolidated",
         "field_periods": {"cash": "2025-12-31"}}
    assert verify_metrics(filing_db, "AAPL", m)["status"] == "matched_fields"
    m["financial_currency"] = "KRW"
    assert verify_metrics(filing_db, "AAPL", m)["status"] == "not_comparable"
    m["financial_currency"] = "USD"
    m["cash"] = 200
    assert verify_metrics(filing_db, "AAPL", m)["status"] == "conflict"


def test_official_run_handles_missing_config_without_network(filing_db, monkeypatch):
    from app import pipeline
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    result = pipeline.run("official", markets=("KR", "US"))
    assert result["status"] == "ok"
    assert result["official"]["sources"]["KR"]["status"] == "not_configured"
    assert result["official"]["sources"]["US"]["status"] == "not_configured"


def test_filings_api_empty_and_asof_validation(filing_db):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    response = c.get("/api/filings/AAPL")
    assert response.status_code == 200 and response.json()["facts"] == []
    assert c.get("/api/filings/AAPL?as_of=bad-date").status_code == 422


def test_financials_carries_actual_field_period_without_assumed_scope(monkeypatch):
    import pandas as pd
    from app import financials
    class T:
        info = {"currency": "USD", "financialCurrency": "USD"}
        income_stmt = pd.DataFrame()
        cashflow = pd.DataFrame()
        balance_sheet = pd.DataFrame({pd.Timestamp("2024-12-31"): [100, 500],
                                     pd.Timestamp("2025-12-31"): [float("nan"), 600]},
                                    index=["Cash And Cash Equivalents", "Stockholders Equity"])
        def history(self, period):
            return pd.DataFrame({"Close": []})
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: T())
    m = financials.fetch("TEST")
    assert m["cash"] == 100
    assert m["field_periods"]["cash"] == "2024-12-31"
    assert m["field_periods"]["equity"] == "2025-12-31"
    assert m["statement_scope"] == "unspecified"


def test_conflicting_official_data_moves_stock_to_review(filing_db, monkeypatch, tmp_path):
    import json
    from app.filings.sec import parse_facts
    from app.filings.store import save_snapshot
    from app import pipeline
    data = sec_data()
    save_snapshot(filing_db, "AAPL", "US", "SEC", data, parse_facts(data))
    universe = tmp_path / "u.json"
    universe.write_text(json.dumps({"markets": {"US": ["AAPL"]}}))
    monkeypatch.setenv("INVEST_UNIVERSE", str(universe))
    m = {"normalized_fcf": 100, "shares": 10, "cashflow_type": "FCFF", "net_debt": 0,
         "discount_rate": 10, "terminal_growth": 2, "currency": "USD", "financial_currency": "USD",
         "price": 50, "cash": 200, "statement_scope": "consolidated",
         "field_periods": {"cash": "2025-12-31"}}
    monkeypatch.setattr(pipeline, "get_macro", lambda con: {})
    monkeypatch.setattr(pipeline, "get_financials", lambda con, tickers: {"AAPL": m})
    pipeline.run_score(filing_db, markets=("US",))
    s = pipeline.stocks(filing_db)[0]
    assert s["analysis_status"] == "review_required"
    assert not s["value_pick"]
    from app.web import render
    assert "공시 원본" in render(pipeline.report(filing_db))


def test_new_financial_schema_is_cached_once(filing_db, monkeypatch):
    from app import pipeline
    calls = []
    def fetch(tickers):
        calls.extend(tickers)
        return {ticker: {"schema_version": "value-v2", "field_periods": {}} for ticker in tickers}
    monkeypatch.setattr(pipeline.financials, "fetch_many", fetch)
    pipeline.get_financials(filing_db, ["AAPL"])
    pipeline.get_financials(filing_db, ["AAPL"])
    assert calls == ["AAPL"]


def test_country_report_retains_different_refresh_days(filing_db):
    from app import pipeline
    from app.db import dumps
    for ticker, market, day in [("AAPL", "US", "2026-10-05"), ("7203.T", "JP", "2026-10-06")]:
        filing_db.execute("INSERT INTO stock_scores VALUES(?,?,?,?,?)", (day, ticker, market, None,
             dumps({"market": market, "metrics": {}, "score_version": "value-v1", "total": None})))
    filing_db.commit()
    assert pipeline.stocks(filing_db, market="US")[0]["day"] == "2026-10-05"
    countries = pipeline.report(filing_db)["countries"]
    assert countries["US"]["analyzed"] == 1
    assert countries["JP"]["analyzed"] == 1


def test_total_ifrs_equity_is_not_compared_with_parent_equity(filing_db):
    from app.filings.sec import parse_facts
    from app.filings.store import save_snapshot, verify_metrics
    data = {"cik": 123, "facts": {"ifrs-full": {"Equity": {"units": {"USD": [
        {"end": "2025-12-31", "val": 100, "accn": "0000000123-26-000001",
         "filed": "2026-02-01", "form": "20-F"}]}}}}}
    save_snapshot(filing_db, "ASML", "US", "SEC", data, parse_facts(data))
    m = {"equity": 80, "financial_currency": "USD", "statement_scope": "consolidated",
         "field_periods": {"equity": "2025-12-31"}}
    assert verify_metrics(filing_db, "ASML", m)["status"] == "not_comparable"


def test_cash_with_investments_is_not_compared_to_cash_only(filing_db):
    from app.filings.sec import parse_facts
    from app.filings.store import save_snapshot, verify_metrics
    data = sec_data()
    save_snapshot(filing_db, "AAPL", "US", "SEC", data, parse_facts(data))
    m = {"cash": 120, "cash_semantics": "cash_and_investments", "financial_currency": "USD",
         "statement_scope": "consolidated", "field_periods": {"cash": "2025-12-31"}}
    assert verify_metrics(filing_db, "AAPL", m)["status"] == "not_comparable"
