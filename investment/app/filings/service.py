"""Official evidence collection for configured candidates, with per-source status."""
import datetime as dt
import os

from ..db import dumps, load_universe, loads
from . import dart, sec
from .common import utc
from .store import save_snapshot


def source_status(con):
    return {row["market"]: {**loads(row["data"], {}), "status": row["status"], "updated_at": row["updated_at"]}
            for row in con.execute("SELECT * FROM official_source_status")}


def collect(con, markets):
    universe = load_universe()
    statuses = {}
    years = universe.get("official_years") or [dt.datetime.now(dt.timezone.utc).year - 1]
    for market in markets:
        source = "SEC" if market == "US" else "DART" if market == "KR" else None
        status = {"source": source, "status": "not_supported", "captured": 0, "errors": [],
                  "coverage": "configured_candidates_only"}
        if source:
            config = os.environ.get("SEC_USER_AGENT" if market == "US" else "DART_API_KEY")
            if not config:
                status["status"] = "not_configured"
            else:
                try:
                    client = sec.Client(config) if market == "US" else dart.Client(config)
                    entities = client.entities()
                    for ticker in universe["markets"].get(market, []):
                        entity = entities.get(ticker if market == "US" else ticker.split(".")[0])
                        if not entity:
                            status["errors"].append({"ticker": ticker, "code": "entity_not_found"})
                            continue
                        con.execute("INSERT OR REPLACE INTO official_entities VALUES(?,?,?)",
                                    (ticker, source, f"{source}:{entity}"))
                        con.commit()
                        for year in ([None] if market == "US" else years):
                            try:
                                raw, facts = client.fetch(entity) if year is None else client.fetch(entity, int(year))
                                save_snapshot(con, ticker, market, source, raw, facts)
                                status["captured"] += 1
                                if not facts:
                                    status["errors"].append({"ticker": ticker, "code": "no_supported_facts", "year": year})
                            except Exception:
                                # Keep request exceptions and DART keys out of logs/API.
                                status["errors"].append({"ticker": ticker, "code": "capture_failed", "year": year})
                    status["status"] = "partial" if status["errors"] else "captured" if status["captured"] else "empty"
                except Exception:
                    status["status"] = "source_error"
                    status["errors"].append({"code": "source_setup_failed"})
        statuses[market] = status
        con.execute("INSERT OR REPLACE INTO official_source_status VALUES(?,?,?,?)",
                    (market, status["status"], utc(), dumps(status)))
        con.commit()
    return {"sources": statuses}
