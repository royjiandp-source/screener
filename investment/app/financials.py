"""Financial statement analyzer + valuation (Yahoo Finance, free).
재무제표 분석 + 가치평가.

Income Statement: revenue growth, operating margin, EPS growth
Balance Sheet:    debt ratio, cash, current ratio
Cash Flow:        operating cash flow, FCF, capex
Derived:          ROE, ROIC, FCF yield
Valuation:        PER, PBR, PSR, EV/EBITDA, simple DCF
"""
import math
import time
import statistics
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf


def annual_fcff(inc, cf):
    """FCFF = EBIT(1-tax) + D&A - capex + cash-flow change in WC.

    Yahoo's WC row is the cash-flow impact (increase in WC is negative).
    Only complete, matching periods are used; missing values stay missing.
    """
    def cell(frame, date, names):
        for name in names:
            if name in frame.index:
                return _num(frame.loc[name, date])
        return None

    out = []
    for date in sorted(set(inc.columns) & set(cf.columns)):
        ebit = cell(inc, date, ("EBIT", "Operating Income"))
        tax = cell(inc, date, ("Tax Rate For Calcs",))
        da = cell(cf, date, ("Depreciation And Amortization", "Depreciation Amortization Depletion"))
        capex = cell(cf, date, ("Capital Expenditure",))
        wc = cell(cf, date, ("Change In Working Capital",))
        if any(v is None for v in (ebit, tax, da, capex, wc)) or not 0 <= tax <= 1:
            continue
        out.append({"period_end": date.strftime("%Y-%m-%d"),
                    "fcff": ebit * (1 - tax) + da - abs(capex) + wc})
    return out


def _num(x):
    try:
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return None


def _row(df: pd.DataFrame, *names) -> list:
    """Return the first matching row as a list of floats, oldest -> newest."""
    if df is None or df.empty:
        return []
    for n in names:
        if n in df.index:
            s = df.loc[n]
            s = s[sorted(s.index)]  # columns are dates
            return [v for v in (_num(x) for x in s.values) if v is not None]
    return []


def _last(vals):
    return vals[-1] if vals else None


def _cagr(vals):
    """Compound annual growth (%) over the available years."""
    if len(vals) < 2 or vals[0] is None or vals[-1] is None or vals[0] <= 0 or vals[-1] <= 0:
        return None
    years = len(vals) - 1
    return ((vals[-1] / vals[0]) ** (1 / years) - 1) * 100


def _pct(a, b):
    return a / b * 100 if a is not None and b not in (None, 0) else None


def _fx(from_cur, to_cur):
    if not from_cur or not to_cur:
        return None
    if from_cur == to_cur:
        return 1.0
    try:
        h = yf.Ticker(f"{from_cur}{to_cur}=X").history(period="5d")["Close"]
        return float(h.iloc[-1])
    except Exception:
        return None


def simple_dcf(fcf, growth_pct, shares, discount=9.0, terminal=2.5, years=5):
    """Very simple 2-stage DCF per share (in the statement currency)."""
    if not fcf or fcf <= 0 or not shares or shares <= 0 or discount <= terminal or years <= 0:
        return None
    g = max(0.0, min(growth_pct or 0.0, 15.0)) / 100
    r, tg = discount / 100, terminal / 100
    pv, f = 0.0, fcf
    for t in range(1, years + 1):
        f *= 1 + g
        pv += f / (1 + r) ** t
    tv = f * (1 + tg) / (r - tg) / (1 + r) ** years
    return (pv + tv) / shares


def fetch(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info or {}
    inc, bs, cf = t.income_stmt, t.balance_sheet, t.cashflow

    revenue = _row(inc, "Total Revenue", "Operating Revenue")
    op_inc = _row(inc, "Operating Income", "EBIT")
    ebit = _row(inc, "EBIT", "Operating Income")
    net = _row(inc, "Net Income", "Net Income Common Stockholders")
    eps = _row(inc, "Diluted EPS", "Basic EPS")
    tax_rate = _last(_row(inc, "Tax Rate For Calcs"))

    equity = _last(_row(bs, "Stockholders Equity", "Common Stock Equity"))
    liab = _last(_row(bs, "Total Liabilities Net Minority Interest"))
    debt = _last(_row(bs, "Total Debt"))
    cash = _last(_row(bs, "Cash And Cash Equivalents",
                      "Cash Cash Equivalents And Short Term Investments"))
    cur_a = _last(_row(bs, "Current Assets"))
    cur_l = _last(_row(bs, "Current Liabilities"))

    ocf = _row(cf, "Operating Cash Flow")
    capex = _last(_row(cf, "Capital Expenditure"))
    fcf = _last(_row(cf, "Free Cash Flow"))

    price_cur = info.get("currency")
    fin_cur = info.get("financialCurrency")
    fx = _fx(fin_cur, price_cur)
    mcap = _num(info.get("marketCap"))

    roic = None
    if ebit and all(v is not None for v in (equity, debt, cash, tax_rate)):
        invested = debt + equity - cash
        if invested > 0 and 0 <= tax_rate <= 1:
            roic = ebit[-1] * (1 - tax_rate) / invested * 100

    fcf_yield = None
    if fcf is not None and mcap and fx:
        fcf_yield = fcf * fx / mcap * 100

    rev_growth = _cagr(revenue[-4:]) if len(revenue) >= 2 else None
    if rev_growth is None and info.get("revenueGrowth") is not None:
        rev_growth = _num(info["revenueGrowth"]) * 100
    eps_growth = _cagr(eps[-4:]) if len(eps) >= 2 else None
    if eps_growth is None and info.get("earningsGrowth") is not None:
        eps_growth = _num(info["earningsGrowth"]) * 100

    roe = _pct(_last(net), equity) if equity is not None and equity > 0 else None
    if roe is None and equity is not None and equity > 0 and info.get("returnOnEquity") is not None:
        roe = _num(info["returnOnEquity"]) * 100
    op_margin = _pct(_last(op_inc), _last(revenue))
    if op_margin is None and info.get("operatingMargins") is not None:
        op_margin = _num(info["operatingMargins"]) * 100

    # Raw CFO-capex is not FCFF. The legacy DCF field is no longer populated.
    dcf = None
    price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    dcf_upside = (dcf * fx / price - 1) * 100 if dcf and fx and price else None

    try:
        h = t.history(period="3mo")["Close"]
        mom_1m = (h.iloc[-1] / h.iloc[-22] - 1) * 100 if len(h) > 22 else None
    except Exception:
        mom_1m = None

    r = lambda x, d=2: round(x, d) if x is not None else None  # noqa: E731
    history = annual_fcff(inc, cf)
    normalized = statistics.median(p["fcff"] for p in history) if len(history) >= 3 else None
    return {
        "schema_version": "value-v1",
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "country": info.get("country"), "sector": info.get("sector"),
        "industry": info.get("industry"), "currency": price_cur,
        "financial_currency": fin_cur, "fx_rate": fx,
        "shares": _num(info.get("sharesOutstanding")),
        "share_basis_verified": not ("." not in ticker and info.get("country") not in (None, "United States")),
        "equity_nonpositive": equity is not None and equity <= 0,
        "net_debt": debt - cash if debt is not None and cash is not None else None,
        "fcff_history": history, "normalized_fcf": normalized,
        "cashflow_type": "FCFF", "normalization_method": "median_of_available_annual_fcff_min_3_years",
        "data_quality": "unverified", "source": "Yahoo Finance",
        "source_url": f"https://finance.yahoo.com/quote/{ticker}/financials/",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "period_end": history[-1]["period_end"] if history else None,
        "normalization_note": "역사적 중앙값은 초기 추정치이며 비경상 항목·주식보상·리스·ADR 조정 검토 필요",
        "price": r(price), "market_cap": mcap,
        # income statement
        "revenue_growth": r(rev_growth), "op_margin": r(op_margin), "eps_growth": r(eps_growth),
        # balance sheet
        "debt_ratio": r(_pct(liab, equity)) if equity is not None and equity > 0 else None,
        "cash": cash, "current_ratio": r(cur_a / cur_l if cur_a and cur_l else _num(info.get("currentRatio"))),
        # cash flow
        "ocf": _last(ocf), "ocf_trend": r(_cagr(ocf[-3:])) if len(ocf) >= 2 else None,
        "fcf": fcf, "capex": capex,
        # derived
        "roe": r(roe), "roic": r(roic), "fcf_yield": r(fcf_yield),
        # valuation
        "per": r(_num(info.get("trailingPE"))), "fwd_per": r(_num(info.get("forwardPE"))),
        "pbr": r(_num(info.get("priceToBook"))),
        "psr": r(_num(info.get("priceToSalesTrailing12Months"))),
        "ev_ebitda": r(_num(info.get("enterpriseToEbitda"))),
        "dcf_value": r(dcf * fx if dcf and fx else None), "dcf_upside": r(dcf_upside, 1),
        "mom_1m": r(mom_1m),
        "years": len(revenue),
    }


def fetch_many(tickers, pause: float = 0.4) -> dict:
    out = {}
    for tk in tickers:
        try:
            out[tk] = fetch(tk)
        except Exception as e:
            print(f"[fin] {tk}: {type(e).__name__}: {e}")
            out[tk] = None
        time.sleep(pause)
    return out
