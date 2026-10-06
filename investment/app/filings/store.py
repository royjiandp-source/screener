"""Append-only evidence and conservative point-in-time access."""
import hashlib
import math

from ..db import dumps, loads
from .common import utc


def save_snapshot(con, ticker, market, source, raw, facts, observed_at=None):
    # Stable canonical hash makes repeated captures idempotent, while changed
    # payloads become new snapshots and cannot rewrite earlier observations.
    import json
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    stamp = utc(observed_at)
    with con:
        existing = con.execute("SELECT id FROM filing_snapshots WHERE ticker=? AND source=? AND content_hash=?",
                               (ticker, source, digest)).fetchone()
        if existing:
            return existing["id"]
        cur = con.execute("INSERT INTO filing_snapshots(ticker,market,source,content_hash,observed_at,raw_json) VALUES(?,?,?,?,?,?)",
                          (ticker, market, source, digest, stamp, canonical))
        sid = cur.lastrowid
        for fact in facts:
            con.execute("INSERT INTO filing_facts(snapshot_id,available_at,fact_json) VALUES(?,?,?)",
                        (sid, utc(fact["available_at"]), dumps(fact)))
    return sid


def facts_asof(con, ticker, as_of=None):
    cutoff = utc(as_of)
    rows = con.execute("""SELECT f.fact_json, s.source, s.observed_at FROM filing_facts f
        JOIN filing_snapshots s ON s.id=f.snapshot_id
        WHERE s.ticker=? AND s.observed_at<=? AND f.available_at<=?
        ORDER BY f.available_at, s.observed_at""", (ticker, cutoff, cutoff))
    result, seen = [], set()
    for row in rows:
        fact = loads(row["fact_json"], {})
        key = dumps(fact)
        if key in seen:
            continue
        seen.add(key)
        result.append({**fact, "source": row["source"], "observed_at": row["observed_at"]})
    return result


def history(con, ticker, as_of=None):
    cutoff = utc(as_of)
    snapshots = [dict(row) for row in con.execute("""SELECT id,source,market,content_hash,observed_at
        FROM filing_snapshots WHERE ticker=? AND observed_at<=? ORDER BY observed_at DESC""", (ticker, cutoff))]
    return {"ticker": ticker, "as_of": cutoff, "snapshots": snapshots,
            "facts": facts_asof(con, ticker, cutoff),
            "point_in_time_policy": "Both public availability and first observation must precede cutoff"}


def verify_metrics(con, ticker, metrics):
    facts = facts_asof(con, ticker)
    comparisons = []
    for metric in ("cash", "equity", "assets", "liabilities"):
        if metric == "cash" and metrics.get("cash_semantics", "cash") != "cash":
            continue
        value = metrics.get(metric)
        period = metrics.get("field_periods", {}).get(metric)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not period:
            continue
        matches = [f for f in facts if f["metric"] == metric and f["period_end"] == period
                   and f.get("period_start") is None and f["unit"] == metrics.get("financial_currency")
                   and f["scope"] == metrics.get("statement_scope")]
        if not matches:
            continue
        newest = max(f["available_at"] for f in matches)
        matches = [f for f in matches if f["available_at"] == newest]
        values = {f["value"] for f in matches}
        matched = len(values) == 1 and math.isclose(value, next(iter(values)), rel_tol=0.001, abs_tol=1)
        comparisons.append({"metric": metric, "period_end": period, "unit": metrics["financial_currency"],
            "provider_value": value, "official_values": sorted(values),
            "status": "matched" if matched else "conflict", "source_url": matches[0]["source_url"],
            "filing_ids": sorted({f["filing_id"] for f in matches})})
    status = "not_comparable" if not comparisons else "conflict" if any(c["status"] == "conflict" for c in comparisons) else "matched_fields"
    return {"status": status, "comparisons": comparisons, "official_facts_count": len(facts),
            "valuation_verified": False,
            "note": "일치한 항목만 확인됨. 정상 현금흐름·할인율·주식 수와 가치평가 전체 검증을 의미하지 않음"}
