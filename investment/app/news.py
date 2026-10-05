"""News collection module (Google News RSS, free). / 뉴스 수집 모듈."""
import datetime as dt
import email.utils
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from .db import now

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Collection targets from the design doc. / 수집 대상
TOPICS = ["AI", "Semiconductor", "Energy", "Defense", "Healthcare", "Cybersecurity",
          "Data Center", "Cloud", "Banking", "EV", "Nuclear"]
TOPICS_KO = {"AI": "인공지능 AI", "Semiconductor": "반도체", "Energy": "에너지",
             "Defense": "방산", "Healthcare": "헬스케어 바이오", "Cybersecurity": "사이버 보안",
             "Data Center": "데이터센터", "Cloud": "클라우드", "Banking": "은행 금융",
             "EV": "전기차 배터리", "Nuclear": "원전"}
EDITIONS = {"US": ("en-US", "US", "en"), "KR": ("ko", "KR", "ko"), "SG": ("en-SG", "SG", "en")}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def fetch_rss(topic: str, market: str, days: int = 2, n: int = 15) -> list[dict]:
    hl, gl, lang = EDITIONS[market]
    q = TOPICS_KO.get(topic, topic) if market == "KR" else f"{topic} stocks"
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} when:{days}d")
           + f"&hl={hl}&gl={gl}&ceid={gl}:{lang}")
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        pub = it.findtext("pubDate")
        try:
            pub = email.utils.parsedate_to_datetime(pub).astimezone(dt.timezone.utc).isoformat()
        except (TypeError, ValueError):
            pub = dt.datetime.now(dt.timezone.utc).isoformat()
        src = it.find("source")
        out.append({
            "title": _clean(it.findtext("title")),
            "url": it.findtext("link"),
            "source": src.text if src is not None else "",
            "published": pub,
            "content": _clean(it.findtext("description"))[:600],
            "market": market, "topic": topic,
        })
    return out[:n]


def collect(con, markets=("US", "KR", "SG"), topics=TOPICS) -> dict:
    """Fetch news for every topic/market and store new articles."""
    new, errors = 0, []
    stamp = now().isoformat()
    for m in markets:
        for t in topics:
            try:
                items = fetch_rss(t, m)
            except Exception as e:  # keep going on one failed feed
                errors.append(f"{m}/{t}: {type(e).__name__}")
                continue
            for a in items:
                cur = con.execute(
                    "INSERT OR IGNORE INTO articles(url,title,source,published,market,topic,content,collected)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (a["url"], a["title"], a["source"], a["published"], a["market"],
                     a["topic"], a["content"], stamp))
                new += cur.rowcount
    con.commit()
    return {"new_articles": new, "errors": errors}
