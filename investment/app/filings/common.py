"""Shared parsing and bounded, credential-safe HTTP access."""
import datetime as dt
import math
import time
from zoneinfo import ZoneInfo

import requests


def utc(value=None):
    stamp = dt.datetime.now(dt.timezone.utc) if value is None else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required")
    return stamp.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def after_day(day, timezone):
    parsed = dt.datetime.strptime(day.replace("-", ""), "%Y%m%d")
    return utc((parsed + dt.timedelta(days=1)).replace(tzinfo=ZoneInfo(timezone)).isoformat())


def amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(str(value).replace(",", "").strip())
        return value if math.isfinite(value) else None
    except ValueError:
        return None


class HTTP:
    def __init__(self, headers=None, interval=0.25):
        self.session = requests.Session()
        self.headers = headers or {}
        self.interval = interval
        self.last_request = 0

    def get(self, url, params=None, binary=False):
        for attempt in range(3):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.session.get(url, params=params, headers=self.headers, timeout=25)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                if response.status_code != 200:
                    raise ValueError(f"Official source HTTP {response.status_code}")
                return response.content if binary else response.json()
            except (requests.RequestException, ValueError) as exc:
                # Never include URL query strings, request exceptions or credentials.
                if isinstance(exc, ValueError) and str(exc).startswith("Official source HTTP"):
                    raise exc from None
                if attempt == 2:
                    raise ValueError("Official source request failed") from None
        raise ValueError("Official source request failed")
