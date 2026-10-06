"""SEC Company Facts preserves filing accession, taxonomy, units and duration."""
import re

from .common import HTTP, after_day, amount, utc

TAGS = {
    "CashAndCashEquivalentsAtCarryingValue": "cash", "CashAndCashEquivalents": "cash",
    "StockholdersEquity": "equity", "Equity": "equity_total",
    "EquityAttributableToOwnersOfParent": "equity",
    "Assets": "assets", "Liabilities": "liabilities",
    "NetCashProvidedByUsedInOperatingActivities": "ocf",
    "CashFlowsFromUsedInOperatingActivities": "ocf",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "Revenues": "revenue", "Revenue": "revenue",
    "NetIncomeLoss": "net_income", "ProfitLoss": "net_income",
}


def parse_facts(payload, submissions=None):
    cik = str(payload["cik"]).zfill(10)
    recent = (submissions or {}).get("filings", {}).get("recent", {})
    accepted = dict(zip(recent.get("accessionNumber", []), recent.get("acceptanceDateTime", [])))
    rows = []
    for taxonomy in ("us-gaap", "ifrs-full"):
        for tag, concept in payload.get("facts", {}).get(taxonomy, {}).items():
            if tag not in TAGS:
                continue
            for unit, facts in concept.get("units", {}).items():
                for fact in facts:
                    value = amount(fact.get("val"))
                    accn, end, filed = fact.get("accn"), fact.get("end"), fact.get("filed")
                    if value is None or not accn or not end or not filed:
                        continue
                    stamp = accepted.get(accn)
                    if stamp and (stamp.endswith("Z") or "+" in stamp[10:]):
                        available = utc(stamp)
                        precision = "timestamp"
                    else:
                        available = after_day(filed, "America/New_York")
                        precision = "conservative_day_boundary"
                    rows.append({"entity_id": f"SEC:{cik}", "metric": TAGS[tag],
                        "raw_tag": f"{taxonomy}:{tag}", "value": value, "unit": unit,
                        "period_start": fact.get("start"), "period_end": end,
                        "scope": "consolidated", "filing_id": accn, "form": fact.get("form"),
                        "available_at": available, "time_precision": precision,
                        "source_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/"})
    return rows


class Client:
    def __init__(self, user_agent):
        if not user_agent or not re.search(r"[^\s@]+@[^\s@]+", user_agent):
            raise ValueError("SEC_USER_AGENT must contain an actual contact email")
        self.http = HTTP({"User-Agent": user_agent, "Accept": "application/json"})

    def entities(self):
        data = self.http.get("https://www.sec.gov/files/company_tickers.json")
        return {str(row["ticker"]).upper(): str(row["cik_str"]).zfill(10) for row in data.values()}

    def fetch(self, cik):
        if not re.fullmatch(r"\d{1,10}", str(cik)):
            raise ValueError("Invalid SEC CIK")
        cik = str(cik).zfill(10)
        facts = self.http.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        submissions = self.http.get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        if str(facts.get("cik")).zfill(10) != cik:
            raise ValueError("SEC entity mismatch")
        return {"companyfacts": facts, "submissions": submissions}, parse_facts(facts, submissions)
