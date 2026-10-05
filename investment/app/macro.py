"""Macro data (FRED, free CSV - no key needed) + economic cycle.
거시경제 데이터 + 경기 사이클 판단.
"""
import io

import pandas as pd
import requests

SERIES = {
    "FEDFUNDS": "Fed funds rate",
    "DGS10": "US 10Y yield",
    "CPIAUCSL": "CPI",
    "PPIACO": "PPI",
    "GDPC1": "Real GDP",
    "UNRATE": "Unemployment",
    "M2SL": "Money supply M2",
}


def fred(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"]


def _yoy(s: pd.Series, periods: int):
    if len(s) <= periods:
        return None
    return round((s.iloc[-1] / s.iloc[-1 - periods] - 1) * 100, 2)


def classify(gdp_yoy, gdp_yoy_prev, unemp_rise, rate_change_6m=None) -> str:
    """Expansion / Recovery / Slowdown / Recession (simple rules)."""
    if gdp_yoy is None:
        return "Unknown"
    if gdp_yoy < 0 or (unemp_rise is not None and unemp_rise >= 0.5):
        return "Recession"
    improving = gdp_yoy_prev is not None and gdp_yoy >= gdp_yoy_prev
    if improving and gdp_yoy_prev is not None and gdp_yoy_prev < 1.5:
        return "Recovery"
    if improving:
        return "Expansion"
    return "Slowdown"


def snapshot() -> dict:
    data = {}
    s = {}
    for k in SERIES:
        try:
            s[k] = fred(k)
        except Exception as e:
            data.setdefault("errors", []).append(f"{k}: {type(e).__name__}")
    g = s.get("GDPC1")
    u = s.get("UNRATE")
    f = s.get("FEDFUNDS")
    gdp_yoy = _yoy(g, 4) if g is not None else None
    gdp_yoy_prev = _yoy(g.iloc[:-1], 4) if g is not None and len(g) > 5 else None
    unemp = round(float(u.iloc[-1]), 2) if u is not None else None
    unemp_rise = round(float(u.iloc[-1] - u.iloc[-12:].min()), 2) if u is not None else None
    data.update({
        "fed_rate": round(float(f.iloc[-1]), 2) if f is not None else None,
        "fed_change_6m": round(float(f.iloc[-1] - f.iloc[-7]), 2) if f is not None and len(f) > 7 else None,
        "us10y": round(float(s["DGS10"].iloc[-1]), 2) if "DGS10" in s else None,
        "cpi_yoy": _yoy(s["CPIAUCSL"], 12) if "CPIAUCSL" in s else None,
        "ppi_yoy": _yoy(s["PPIACO"], 12) if "PPIACO" in s else None,
        "gdp_yoy": gdp_yoy, "gdp_yoy_prev": gdp_yoy_prev,
        "unemployment": unemp, "unemp_rise_12m": unemp_rise,
        "m2_yoy": _yoy(s["M2SL"], 12) if "M2SL" in s else None,
        "as_of": {k: v.index[-1].date().isoformat() for k, v in s.items()},
    })
    data["cycle"] = classify(gdp_yoy, gdp_yoy_prev, unemp_rise, data["fed_change_6m"])
    return data
