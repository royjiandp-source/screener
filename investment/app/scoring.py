"""Risk engine + 100-point scoring engine. / 리스크 엔진 + 100점 스코어링.

Financial health 30 | Growth 20 | Valuation 20 | Theme momentum 15 | Macro 10 | Risk 5
Missing data: a category is scored on the metrics that exist; if none exist it gets half points.
"""


def lin(x, bad, good):
    """0 at `bad`, 1 at `good`, linear in between (works for both directions)."""
    if x is None:
        return None
    if good == bad:
        return 1.0
    v = (x - bad) / (good - bad)
    return max(0.0, min(1.0, v))


def _category(parts, max_pts):
    vals = [p for p in parts if p is not None]
    if not vals:
        return max_pts / 2, 0.0
    return max_pts * sum(vals) / len(vals), len(vals) / len(parts)


def financial_health(m):  # 30
    return _category([
        lin(m.get("roe"), 0, 15),            # ROE >= 15% good
        lin(m.get("roic"), 0, 10),           # ROIC >= 10% good
        lin(m.get("debt_ratio"), 300, 100),  # liabilities/equity <= 100% good
        lin(m.get("fcf_yield"), 0, 5),       # FCF yield >= 5% good
    ], 30)


def growth(m):  # 20
    return _category([
        lin(m.get("revenue_growth"), 0, 15),
        lin(m.get("eps_growth"), 0, 15),
    ], 20)


def _pos(x):
    """Negative multiples mean losses -> worst score."""
    if x is None:
        return None
    return x if x > 0 else 10_000


def valuation(m):  # 20
    return _category([
        lin(_pos(m.get("per")), 40, 15),
        lin(_pos(m.get("pbr")), 8, 1.5),
        lin(_pos(m.get("ev_ebitda")), 30, 10),
    ], 20)


def theme_score(tm: dict, max_count: int, flow) -> float:  # 15
    """News volume 40% + positive ratio 40% + money flow (theme 1M price momentum) 20%."""
    if not tm:
        return 0.0
    count = tm["news_count"] / max_count if max_count else 0
    pos = tm["pos_ratio"] - 0.5 * tm.get("neg_ratio", 0)
    f = lin(flow, -10, 10) if flow is not None else 0.5
    return round(15 * (0.4 * count + 0.4 * max(0.0, pos) + 0.2 * f), 2)


def macro_score(theme: str, cycle: str, cycles: dict) -> float:  # 10
    if cycle not in cycles:
        return 5.0
    if theme in cycles[cycle]:
        return 10.0
    favored_elsewhere = any(theme in v for k, v in cycles.items() if k not in (cycle, "_note"))
    return 4.0 if favored_elsewhere else 6.0


def risk(m: dict, theme_cfg: dict, risk_cfg: dict, theme_tm: dict) -> dict:  # 5
    flags = []
    c = (m.get("country") or "").strip()
    if c in risk_cfg.get("country", []):
        flags.append(f"Country risk: {c}")
    if c in risk_cfg.get("geopolitical", []):
        flags.append(f"Geopolitical: {c}")
    for r in theme_cfg.get("industry_risks", []):
        flags.append({"tariffs": "Industry: tariffs", "regulation": "Industry: regulation",
                      "rates": "Industry: interest rates"}.get(r, f"Industry: {r}"))
    if (m.get("debt_ratio") or 0) > 200:
        flags.append("High debt")
    if m.get("op_margin") is not None and m["op_margin"] < 0:
        flags.append("Operating loss")
    if m.get("fcf") is not None and m["fcf"] < 0:
        flags.append("Negative FCF")
    if theme_tm and theme_tm.get("neg_ratio", 0) >= 0.4:
        flags.append("Negative news flow")
    # industry flags count half
    pts = sum(0.5 if f.startswith("Industry") else 1 for f in flags)
    label = "Low" if pts <= 1 else "Medium" if pts <= 3 else "High"
    return {"score": round(max(0.0, 5 - pts), 2), "label": label, "flags": flags}


def is_avoid(m: dict, rk: dict) -> list:
    reasons = []
    if (m.get("debt_ratio") or 0) > 200:
        reasons.append("부채 과다 / High debt")
    if m.get("op_margin") is not None and m["op_margin"] < 0:
        reasons.append("적자 / Operating loss")
    if (m.get("fcf") is not None and m["fcf"] < 0) or (m.get("ocf_trend") is not None and m["ocf_trend"] < -15):
        reasons.append("현금흐름 악화 / Weak cash flow")
    if rk["label"] == "High":
        reasons.append("리스크 높음 / High risk")
    return reasons


def is_value_pick(m: dict) -> bool:
    per, roe, fy = m.get("per"), m.get("roe"), m.get("fcf_yield")
    return bool(per and 0 < per <= 18 and roe and roe >= 15 and fy and fy >= 4)


def score_stock(m, theme, theme_cfg, tm_all, max_count, flow, cycle, cycles, risk_cfg) -> dict:
    fin, fin_cov = financial_health(m)
    gro, gro_cov = growth(m)
    val, val_cov = valuation(m)
    th = theme_score(tm_all.get(theme), max_count, flow)
    mac = macro_score(theme, cycle, cycles)
    rk = risk(m, theme_cfg, risk_cfg, tm_all.get(theme))
    total = fin + gro + val + th + mac + rk["score"]
    return {
        "total": round(total, 1),
        "parts": {"financial": round(fin, 1), "growth": round(gro, 1), "valuation": round(val, 1),
                  "theme": round(th, 1), "macro": round(mac, 1), "risk": rk["score"]},
        "coverage": round((fin_cov + gro_cov + val_cov) / 3, 2),
        "risk": rk["label"], "risk_flags": rk["flags"],
        "avoid": is_avoid(m, rk), "value_pick": is_value_pick(m),
    }
