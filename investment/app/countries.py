"""Listing markets are distinct from company domicile or revenue exposure."""
import re

COUNTRIES = {
    "KR": {"name": "한국", "currency": "KRW", "source": "Open DART / KRX", "url": "https://opendart.fss.or.kr/"},
    "US": {"name": "미국", "currency": "USD", "source": "SEC EDGAR", "url": "https://www.sec.gov/edgar/sec-api-documentation"},
    "JP": {"name": "일본", "currency": "JPY", "source": "EDINET / JPX", "url": "https://disclosure2.edinet-fsa.go.jp/"},
    "TW": {"name": "대만", "currency": "TWD", "source": "MOPS / TWSE", "url": "https://mops.twse.com.tw/"},
    "HK": {"name": "홍콩", "currency": "HKD", "source": "HKEXnews", "url": "https://www.hkexnews.hk/"},
    "SG": {"name": "싱가포르", "currency": "SGD", "source": "SGX", "url": "https://www.sgx.com/securities/company-announcements"},
}


def market_of(ticker):
    ticker = ticker.upper()
    for suffix, code in ((".KS", "KR"), (".KQ", "KR"), (".SI", "SG"),
                         (".T", "JP"), (".TW", "TW"), (".TWO", "TW"), (".HK", "HK")):
        if ticker.endswith(suffix):
            return code
    return "US" if re.fullmatch(r"[A-Z][A-Z0-9-]{0,14}", ticker) else "UNKNOWN"
