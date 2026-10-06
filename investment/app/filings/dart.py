"""DART annual accounts and all periodic filings, including amendments."""
import calendar
import io
import re
import zipfile
import xml.etree.ElementTree as ET

from .common import HTTP, after_day, amount
from .sec import TAGS


def check_response(payload):
    status = payload.get("status")
    if status == "013":
        return []
    if status != "000":
        raise ValueError(f"DART status {status if status and re.fullmatch(r'[0-9]{3}', str(status)) else 'invalid'}")
    return payload.get("list", [])


def parse_accounts(payload, filings, requested_scope="CFS"):
    metadata = {f["rcept_no"]: f for f in filings}
    result = []
    for row in check_response(payload):
        if row.get("fs_div", requested_scope) != requested_scope:
            continue
        tag = row.get("account_id", "").split("_", 1)[-1]
        meta = metadata.get(row.get("rcept_no"))
        match = re.search(r"\((\d{4})\.(\d{2})\)", meta.get("report_nm", "")) if meta else None
        value, unit = amount(row.get("thstrm_amount")), row.get("currency")
        if tag not in TAGS or not meta or not match or value is None or not unit:
            continue
        year, month = map(int, match.groups())
        if not 1 <= month <= 12:
            continue
        end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        result.append({"entity_id": f"DART:{row['corp_code']}", "metric": TAGS[tag],
            "raw_tag": row["account_id"], "value": value, "unit": unit,
            "period_start": None, "period_end": end, "period_source": "report_title_month_end",
            "scope": "consolidated" if requested_scope == "CFS" else "standalone",
            "filing_id": row["rcept_no"], "form": meta.get("report_nm"),
            "available_at": after_day(meta["rcept_dt"], "Asia/Seoul"),
            "time_precision": "conservative_day_boundary",
            "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"})
    return result


class Client:
    def __init__(self, key):
        if not key:
            raise ValueError("DART_API_KEY is required")
        self.key, self.http = key, HTTP(interval=0.3)

    def get(self, endpoint, **params):
        return self.http.get(f"https://opendart.fss.or.kr/api/{endpoint}", {"crtfc_key": self.key, **params})

    def entities(self):
        data = self.http.get("https://opendart.fss.or.kr/api/corpCode.xml", {"crtfc_key": self.key}, binary=True)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo("CORPCODE.xml")
                if info.file_size > 100_000_000:
                    raise ValueError("DART entity archive too large")
                root = ET.fromstring(archive.read(info))
        except (zipfile.BadZipFile, KeyError, ET.ParseError):
            raise ValueError("DART entity archive unavailable") from None
        return {row.findtext("stock_code").strip(): row.findtext("corp_code")
                for row in root.findall("list") if (row.findtext("stock_code") or "").strip()}

    def fetch(self, corp_code, year):
        if not re.fullmatch(r"\d{8}", str(corp_code)) or not 2015 <= year <= 2100:
            raise ValueError("Invalid DART company or business year")
        filings, pages = [], []
        for page in range(1, 101):
            payload = self.get("list.json", corp_code=corp_code, bgn_de=f"{year}0101",
                               end_de=f"{year + 2}1231", last_reprt_at="N", pblntf_ty="A",
                               page_count=100, page_no=page)
            filings.extend(check_response(payload))
            pages.append(payload)
            if page >= int(payload.get("total_page", 1)):
                break
        else:
            raise ValueError("DART filing pagination incomplete")
        # This endpoint returns the current version; original versions are preserved
        # prospectively by snapshots, never reconstructed by backdating current data.
        accounts = self.get("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year),
                            reprt_code="11011", fs_div="CFS")
        return {"filings": pages, "accounts": accounts}, parse_accounts(accounts, filings)
