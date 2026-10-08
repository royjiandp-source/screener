"""Listing markets are distinct from company domicile or revenue exposure."""
import re

COUNTRIES = {
    "KR": {"name": "한국", "currency": "KRW", "source": "Open DART / KRX", "url": "https://opendart.fss.or.kr/"},
    "US": {"name": "미국", "currency": "USD", "source": "SEC EDGAR", "url": "https://www.sec.gov/edgar/sec-api-documentation"},
    "SG": {"name": "싱가포르", "currency": "SGD", "source": "SGX", "url": "https://www.sgx.com/securities/company-announcements"},
}


SEARCH_MARKETS = ("KR", "SG", "US")

def market_of(ticker):
    ticker = ticker.upper()
    for suffix, code in ((".KS", "KR"), (".KQ", "KR"), (".SI", "SG")):
        if ticker.endswith(suffix):
            return code
    return "US" if re.fullmatch(r"[A-Z][A-Z0-9-]{0,14}", ticker) else "UNKNOWN"
