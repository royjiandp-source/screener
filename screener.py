"""
Index-Relative Strength Screener (SG / US / KR)
지수보다 강한 종목 찾기 (싱가포르 / 미국 / 한국)

Rule (from the video): buy candidates are stocks whose moving-average slope
is rising while the index's moving-average slope is flat or falling.

Usage:
    python screener.py                      # all markets
    python screener.py --markets KR SG      # only some markets
    python screener.py --top 15 --news --themes --ai
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
HERE = Path(__file__).parent

# ---------------------------------------------------------------- universes
# STI constituents (check sgx.com occasionally; the list changes).
STI = {
    "D05": "DBS", "O39": "OCBC", "U11": "UOB", "Z74": "Singtel",
    "C38U": "CapitaLand Integrated Comm Trust", "A17U": "CapitaLand Ascendas REIT",
    "9CI": "CapitaLand Investment", "C6L": "Singapore Airlines", "BN4": "Keppel",
    "S68": "SGX", "S63": "ST Engineering", "U96": "Sembcorp Industries",
    "5E2": "Seatrium", "BS6": "Yangzijiang Shipbuilding", "F34": "Wilmar",
    "Y92": "Thai Beverage", "G13": "Genting Singapore", "S58": "SATS",
    "V03": "Venture Corp", "U14": "UOL", "C09": "City Developments",
    "H78": "Hongkong Land", "J36": "Jardine Matheson", "C07": "Jardine C&C",
    "D01": "DFI Retail", "M44U": "Mapletree Logistics Trust",
    "ME8U": "Mapletree Industrial Trust", "N2IU": "Mapletree Pan Asia Comm Trust",
    "J69U": "Frasers Centrepoint Trust", "AJBU": "Keppel DC REIT",
}


def universe_sg():
    return {f"{k}.SI": v for k, v in STI.items()}, {"^STI": "STI"}


def universe_us():
    r = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                     headers=UA, timeout=30)
    df = pd.read_html(r.text)[0]
    tickers = {s.replace(".", "-"): n for s, n in zip(df["Symbol"], df["Security"])}
    return tickers, {"^GSPC": "S&P 500"}


def universe_kr(top_n):
    import FinanceDataReader as fdr
    out = {}
    for market, suffix in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
        df = fdr.StockListing(market).sort_values("Marcap", ascending=False).head(top_n)
        out.update({f"{c}{suffix}": n for c, n in zip(df["Code"], df["Name"])})
    return out, {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}


def index_for(ticker, market):
    """Each stock is compared with its own index."""
    if market == "SG":
        return "^STI"
    if market == "US":
        return "^GSPC"
    return "^KQ11" if ticker.endswith(".KQ") else "^KS11"


# ---------------------------------------------------------------- data
def download_close(tickers, period="1y"):
    frames = []
    tickers = list(tickers)
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        df = yf.download(chunk, period=period, auto_adjust=True,
                         progress=False, threads=True)["Close"]
        if isinstance(df, pd.Series):
            df = df.to_frame(chunk[0])
        frames.append(df)
    return pd.concat(frames, axis=1).dropna(how="all")


# ---------------------------------------------------------------- scoring
def slope(series, ma, lookback):
    """% change of the moving average over `lookback` days."""
    m = series.rolling(ma).mean()
    return (m.iloc[-1] / m.iloc[-1 - lookback] - 1) * 100


def score_stock(close, idx):
    """Return metrics for one stock vs its index, or None if not enough data."""
    df = pd.concat([close, idx], axis=1, keys=["s", "i"]).dropna()
    if len(df) < 80:
        return None
    s, i = df["s"], df["i"]
    ma5, ma10, ma20, ma60 = (s.rolling(n).mean().iloc[-1] for n in (5, 10, 20, 60))
    price = s.iloc[-1]

    s20, i20 = slope(s, 20, 5), slope(i, 20, 5)
    s60, i60 = slope(s, 60, 10), slope(i, 60, 10)
    rs = s / i
    rs20 = (rs.iloc[-1] / rs.iloc[-21] - 1) * 100   # relative strength, 20 days

    if s20 > 0 and i20 <= 0:
        signal = "STRONG"        # stock up, index down/flat -> best case
    elif s20 < 0 and i20 > 0:
        signal = "WEAK"          # stock down, index up -> avoid
    elif s20 > i20:
        signal = "STRONGER"
    else:
        signal = "WEAKER"

    above20, above60 = price > ma20, price > ma60
    aligned = ma5 > ma10 > ma20
    score = (s20 - i20) * 2 + rs20 + 2 * above20 + 2 * above60 + 2 * aligned
    return {
        "price": round(price, 2), "signal": signal, "score": round(score, 2),
        "ma20_slope_%": round(s20, 2), "idx_ma20_slope_%": round(i20, 2),
        "ma60_slope_%": round(s60, 2), "idx_ma60_slope_%": round(i60, 2),
        "rs_20d_%": round(rs20, 2), "above_ma20": above20,
        "above_ma60": above60, "aligned_5_10_20": aligned,
    }


def screen(market, top, kr_top):
    print(f"[{market}] loading universe ...")
    if market == "SG":
        names, indexes = universe_sg()
    elif market == "US":
        names, indexes = universe_us()
    else:
        names, indexes = universe_kr(kr_top)
    print(f"[{market}] downloading {len(names)} stocks ...")
    closes = download_close(list(names) + list(indexes))
    got = [t for t in names if t in closes and closes[t].notna().any()]
    print(f"[{market}] price data OK for {len(got)}/{len(names)} stocks")
    if not got or not any(ix in closes and closes[ix].notna().any() for ix in indexes):
        print(f"[{market}] WARNING: no price data (Yahoo blocked / rate-limited / no internet?)")

    rows = []
    for t, name in names.items():
        ix = index_for(t, market)
        if t not in closes or ix not in closes:
            continue
        m = score_stock(closes[t], closes[ix])
        if m:
            rows.append({"market": market, "ticker": t, "name": name,
                         "index": indexes[ix], **m})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    picks = df[df["signal"].isin(["STRONG", "STRONGER"]) & df["above_ma20"]]
    return picks.sort_values("score", ascending=False).head(top)


# ---------------------------------------------------------------- themes
def naver_themes(cache_days=7):
    """Map 6-digit KR code -> list of Naver theme names. Cached to JSON."""
    cache = HERE / "naver_themes.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < cache_days * 86400:
        return json.loads(cache.read_text(encoding="utf-8"))
    print("[KR] building Naver theme map (first run takes ~1-2 min) ...")
    base = "https://finance.naver.com/sise/"
    themes, page = {}, 1
    while True:
        r = requests.get(f"{base}theme.naver?&page={page}", headers=UA, timeout=20)
        r.encoding = "euc-kr"
        found = re.findall(r'type=theme&no=(\d+)">([^<]+)</a>', r.text)
        new = {no: nm.strip() for no, nm in found if no not in themes}
        if not new:
            break
        themes.update(new)
        page += 1
    mapping = {}
    for no, tname in themes.items():
        r = requests.get(f"{base}sise_group_detail.naver?type=theme&no={no}",
                         headers=UA, timeout=20)
        for code in set(re.findall(r"/item/main\.naver\?code=(\d{6})", r.text)):
            mapping.setdefault(code, []).append(tname)
        time.sleep(0.15)
    cache.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return mapping


def sector_info(ticker):
    try:
        info = yf.Ticker(ticker).info
        return " / ".join(x for x in (info.get("sector"), info.get("industry")) if x)
    except Exception:
        return ""


# ---------------------------------------------------------------- news
def google_news(query, market, n=3):
    lang = {"KR": ("ko", "KR"), "US": ("en-US", "US"), "SG": ("en-SG", "SG")}[market]
    q = urllib.parse.quote(f"{query} when:7d")
    url = (f"https://news.google.com/rss/search?q={q}"
           f"&hl={lang[0]}&gl={lang[1]}&ceid={lang[1]}:{lang[0].split('-')[0]}")
    try:
        root = ET.fromstring(requests.get(url, headers=UA, timeout=15).content)
        return [{"title": it.findtext("title"), "link": it.findtext("link")}
                for it in root.iter("item")][:n]
    except Exception:
        return []


# ---------------------------------------------------------------- AI comment
def ai_comment(row, model):
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    news = "\n".join(f"- {h['title']}" for h in row["news"]) or "- (no recent news)"
    prompt = f"""Stock: {row['name']} ({row['ticker']}), compared with {row['index']}.
Stock 20d MA slope: {row['ma20_slope_%']}%, index 20d MA slope: {row['idx_ma20_slope_%']}%.
Relative strength vs index, last 20 days: {row['rs_20d_%']}%.
Themes/sector: {row['themes'] or 'unknown'}
Recent headlines:
{news}

In 2 short sentences, explain the most likely reason this stock is stronger than its index.
Use only the information above. If the headlines don't explain it, say so.
Answer first in English, then the same in Korean on a new line starting with "KR:"."""
    resp = client.models.generate_content(model=model, contents=prompt)
    return (resp.text or "").strip()


# ---------------------------------------------------------------- report
# Easy-to-read column labels (internal names stay the same).
LABELS = {
    "ma20_slope_%": "Stock trend % / 종목 추세",
    "idx_ma20_slope_%": "Index trend % / 지수 추세",
    "rs_20d_%": "Beat index 1M % / 지수 대비 1개월",
}
TIPS = {
    "ma20_slope_%": "Change of the stock's 20-day average over 5 days. + = stock rising / 종목 20일선 5일 변화율. + = 상승 중",
    "idx_ma20_slope_%": "Same for the index. + = market rising / 지수 20일선 5일 변화율. + = 시장 상승 중",
    "rs_20d_%": "How much the stock beat the index in the last 20 trading days / 최근 20거래일 동안 지수보다 더 오른 정도",
}


def to_html(df, path):
    cols = ["market", "ticker", "name", "index", "signal", "score", "price",
            "ma20_slope_%", "idx_ma20_slope_%", "rs_20d_%", "themes"]
    head = "".join(f'<th title="{html.escape(TIPS.get(c, ""))}">{html.escape(LABELS.get(c, c))}</th>'
                   for c in cols + ["news / AI"])
    body = []
    for _, r in df.iterrows():
        cells = "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols)
        news = "<br>".join(f'<a href="{html.escape(h["link"])}" target="_blank">'
                           f'{html.escape(h["title"])}</a>' for h in r.get("news", []))
        ai = html.escape(r.get("ai_comment", "")).replace("\n", "<br>")
        cls = "strong" if r["signal"] == "STRONG" else ""
        body.append(f'<tr class="{cls}">{cells}<td>{news}'
                    f'{"<hr>" + ai if ai else ""}</td></tr>')
    path.write_text(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strong vs Index {dt.date.today()}</title>
<style>body{{font-family:sans-serif;margin:20px}}table{{border-collapse:collapse;font-size:13px}}
td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}th{{background:#f3f3f3}}
tr.strong td{{background:#eaf7ea}}td:last-child{{max-width:420px}}</style>
<h2>Stocks stronger than the index / 지수보다 강한 종목 — {dt.date.today()}</h2>
<p>Green = STRONG (stock MA20 rising, index MA20 flat or falling). Not financial advice.</p>
<p>Stock/Index trend %: + = going up, - = going down. Beat index 1M %: + = stock did better than the index.<br>
종목/지수 추세 %: + 상승, - 하락. 지수 대비 1개월 %: + = 지수보다 더 잘함. (Hover a header for details / 제목에 마우스를 올리면 설명)</p>
<div style="overflow-x:auto"><table><tr>{head}</tr>{''.join(body)}</table></div>
<p><a href="../index.html">← All reports / 전체 결과</a></p>""", encoding="utf-8")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", nargs="+", default=["SG", "US", "KR"])
    ap.add_argument("--top", type=int, default=10, help="results per market")
    ap.add_argument("--kr-top", type=int, default=200,
                    help="largest N stocks per KR market to scan")
    ap.add_argument("--themes", action="store_true", help="add Naver themes / sectors")
    ap.add_argument("--news", action="store_true", help="add Google News headlines")
    ap.add_argument("--ai", action="store_true", help="add AI reason (needs GEMINI_API_KEY)")
    ap.add_argument("--model", default="gemini-3.5-flash")
    a = ap.parse_args()

    frames = []
    for m in a.markets:
        try:
            frames.append(screen(m.upper(), a.top, a.kr_top))
        except Exception as e:          # one market failing should not stop the others
            print(f"[{m.upper()}] ERROR: {type(e).__name__}: {e}")
    frames = [f for f in frames if not f.empty]
    results = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    stamp = dt.date.today().strftime("%Y%m%d")
    out_csv, out_html = HERE / f"strong_{stamp}.csv", HERE / f"strong_{stamp}.html"
    if results.empty:
        print("No stocks passed the filter today (or data download failed - see messages above).")
        out_html.write_text(f"""<!doctype html><meta charset="utf-8"><title>Strong vs Index {stamp}</title>
<h2>No results / 결과 없음 — {dt.date.today()}</h2>
<p>No stock passed the filter, or price data could not be downloaded. Check the terminal messages.</p>
<p>조건을 통과한 종목이 없거나, 가격 데이터 다운로드에 실패했습니다. 터미널 메시지를 확인하세요.</p>""",
                            encoding="utf-8")
        print(f"Saved: {out_html.resolve()}")
        return

    kr_map = naver_themes() if a.themes and (results["market"] == "KR").any() else {}
    themes, news, ai = [], [], []
    for _, r in results.iterrows():
        if a.themes:
            t = (", ".join(kr_map.get(r["ticker"][:6], [])[:4]) if r["market"] == "KR"
                 else sector_info(r["ticker"]))
        else:
            t = ""
        themes.append(t)
        news.append(google_news(r["name"], r["market"]) if (a.news or a.ai) else [])
    results["themes"], results["news"] = themes, news

    if a.ai:
        if not os.environ.get("GEMINI_API_KEY"):
            print("GEMINI_API_KEY not set -> skipping AI comments.")
        else:
            for _, r in results.iterrows():
                try:
                    ai.append(ai_comment(r, a.model))
                except Exception as e:
                    ai.append(f"(AI error: {e})")
            results["ai_comment"] = ai

    results.drop(columns=["news"]).rename(columns=LABELS).to_csv(out_csv, index=False, encoding="utf-8-sig")
    to_html(results, out_html)
    print(results[["market", "ticker", "name", "signal", "score", "rs_20d_%"]]
          .rename(columns={"rs_20d_%": "beat_index_1M_%"}).to_string(index=False))
    print(f"\nSaved: {out_csv.resolve()}\n       {out_html.resolve()}")


if __name__ == "__main__":
    main()
