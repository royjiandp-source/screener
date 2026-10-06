"""Deterministic valuation; percentages are expressed in percentage points."""
import math


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def dcf(fcf, shares, growth=0, discount=10, terminal=2, years=5,
        cashflow_type="FCFF", net_debt=0):
    values = (fcf, shares, growth, discount, terminal, net_debt)
    if not all(finite(v) for v in values):
        raise ValueError("DCF inputs must be finite numbers")
    if (fcf <= 0 or shares <= 0 or growth <= -100 or terminal <= -100
            or discount <= terminal or discount <= 0
            or not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 50):
        raise ValueError("Invalid cash flow, shares, horizon or discount/terminal rates")
    if cashflow_type not in ("FCFF", "FCFE"):
        raise ValueError("Specify FCFF/WACC or FCFE/cost of equity")
    r, g, tg = discount / 100, growth / 100, terminal / 100
    cash = fcf
    present = 0
    for year in range(1, years + 1):
        cash *= 1 + g
        present += cash / (1 + r) ** year
    present += cash * (1 + tg) / (r - tg) / (1 + r) ** years
    if cashflow_type == "FCFF":
        present -= net_debt
    value = present / shares
    if not math.isfinite(value):
        raise ValueError("DCF exceeds numeric range")
    return value


def safety_margin(price, value):
    if not all(finite(v) and v > 0 for v in (price, value)):
        return None
    return (1 - price / value) * 100


def reverse_dcf(fcf, shares, price, discount=10, terminal=2, years=5,
                cashflow_type="FCFF", net_debt=0):
    """Price and cash flows must use the same currency; hold other inputs fixed."""
    if not finite(price) or price <= 0:
        raise ValueError("Price must be positive and finite")
    low, high = -50.0, 50.0

    def value(g):
        return dcf(fcf, shares, g, discount, terminal, years, cashflow_type, net_debt)

    bounds = {"min_growth": low, "max_growth": high, "years": years}
    if not value(low) <= price <= value(high):
        return {"status": "outside_search_range", **bounds, "implied_growth": None}
    for _ in range(80):
        mid = (low + high) / 2
        if value(mid) < price:
            low = mid
        else:
            high = mid
    return {"status": "estimated", **bounds, "implied_growth": (low + high) / 2,
            "note": "다른 가정을 고정한 첫 5년 현금흐름 성장률. 실현 가능성이나 매출 성장 예측이 아님"}


def evaluate(metrics):
    required = ("normalized_fcf", "shares", "discount_rate", "terminal_growth", "price")
    missing = [key for key in required if not finite(metrics.get(key))]
    if finite(metrics.get("price")) and metrics["price"] <= 0:
        missing.append("positive_price")
    kind = metrics.get("cashflow_type")
    if kind not in ("FCFF", "FCFE"):
        missing.append("cashflow_type")
    if kind == "FCFF" and not finite(metrics.get("net_debt")):
        missing.append("net_debt")
    trading, reporting = metrics.get("currency"), metrics.get("financial_currency")
    if not trading or not reporting:
        missing.append("currency")
    fx = 1 if trading and trading == reporting else metrics.get("fx_rate")
    if not finite(fx) or fx <= 0:
        missing.append("fx_rate")
    base = {"status": "data_insufficient", "missing": missing, "scenarios": {},
            "sensitivity": [], "currency": trading, "method": kind,
            "assumption_source": metrics.get("assumption_source", "user_inputs"),
            "normalization_method": metrics.get("normalization_method")}
    if missing:
        return base
    growth = metrics.get("revenue_growth")
    growth = max(-10, min(10, growth)) if finite(growth) else 0
    discount, terminal = metrics["discount_rate"], metrics["terminal_growth"]
    net_debt = metrics.get("net_debt", 0) if kind == "FCFF" else 0

    def compute(g, r, cash_factor=1):
        return dcf(metrics["normalized_fcf"] * cash_factor, metrics["shares"],
                   growth=g, discount=r, terminal=terminal,
                   cashflow_type=kind, net_debt=net_debt) * fx

    try:
        for name, g, r, factor in (
            ("conservative", growth - 3, discount + 2, 0.8),
            ("base", growth, discount, 1),
            ("optimistic", growth + 3, discount - 1, 1.1),
        ):
            value = compute(g, r, factor)
            base["scenarios"][name] = {"value": round(value, 4),
                "safety_margin": safety_margin(metrics.get("price"), value),
                "growth": g, "discount": r, "terminal": terminal, "cash_factor": factor}
        for r in (discount - 1, discount, discount + 1):
            for g in (growth - 2, growth, growth + 2):
                base["sensitivity"].append({"discount": r, "growth": g, "value": round(compute(g, r), 4)})
    except ValueError as exc:
        return {**base, "status": "invalid_assumptions", "scenarios": {},
                "sensitivity": [], "error": str(exc)}
    return {**base, "status": "estimated", "assumptions": {
        "normalized_fcf": metrics["normalized_fcf"], "shares": metrics["shares"],
        "net_debt": net_debt, "fx_rate": fx, "years": 5},
        "reverse_dcf": reverse_dcf(metrics["normalized_fcf"], metrics["shares"],
            metrics["price"] / fx, discount=discount, terminal=terminal,
            cashflow_type=kind, net_debt=net_debt)}
