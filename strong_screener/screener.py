"""
Index-Relative Strength Screener (SG / US / KR)
지수보다 강한 종목 찾기 (싱가포르 / 미국 / 한국)

Rule (from the video): buy candidates are stocks whose moving-average slope
is rising while the index's moving-average slope is flat or falling.

Usage:
    python screener.py                      # all markets
    python screener.py --markets KR SG      # only some markets
    python screener.py --top 15 --news --ai

The HTML report has a search box / HTML 리포트에 검색창이 있습니다:
    삼성전자 -> 삼성전자 + 관련주 (same Naver themes)
    반도체   -> all semiconductor stocks (KR themes + US/SG sectors)
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

# Stocks below these prices are dropped everywhere (top list, search, CSV).
# 이 가격 미만 종목은 모든 결과에서 제외합니다.
MIN_PRICE = {"SG": 1, "KR": 5000, "US": 5}   # SGD / KRW / USD

# ---------------------------------------------------------------- universes
# STI constituents with sector (check sgx.com occasionally; the list changes).
STI = {
    "D05": ("DBS", "Financials / Banks"),
    "O39": ("OCBC", "Financials / Banks"),
    "U11": ("UOB", "Financials / Banks"),
    "Z74": ("Singtel", "Communication / Telecom"),
    "C38U": ("CapitaLand Integrated Comm Trust", "Real Estate / REIT"),
    "A17U": ("CapitaLand Ascendas REIT", "Real Estate / REIT"),
    "9CI": ("CapitaLand Investment", "Real Estate / Investment"),
    "C6L": ("Singapore Airlines", "Industrials / Airlines"),
    "BN4": ("Keppel", "Industrials / Conglomerate"),
    "S68": ("SGX", "Financials / Exchanges"),
    "S63": ("ST Engineering", "Industrials / Aerospace & Defense"),
    "U96": ("Sembcorp Industries", "Utilities / Energy"),
    "5E2": ("Seatrium", "Industrials / Shipbuilding"),
    "BS6": ("Yangzijiang Shipbuilding", "Industrials / Shipbuilding"),
    "F34": ("Wilmar", "Consumer Staples / Agribusiness"),
    "Y92": ("Thai Beverage", "Consumer Staples / Beverages"),
    "G13": ("Genting Singapore", "Consumer Discretionary / Casinos"),
    "S58": ("SATS", "Industrials / Aviation Services"),
    "V03": ("Venture Corp", "Information Technology / Electronics"),
    "U14": ("UOL", "Real Estate / Developer"),
    "C09": ("City Developments", "Real Estate / Developer"),
    "H78": ("Hongkong Land", "Real Estate / Developer"),
    "J36": ("Jardine Matheson", "Industrials / Conglomerate"),
    "C07": ("Jardine C&C", "Consumer Discretionary / Auto"),
    "D01": ("DFI Retail", "Consumer Staples / Retail"),
    "M44U": ("Mapletree Logistics Trust", "Real Estate / REIT"),
    "ME8U": ("Mapletree Industrial Trust", "Real Estate / REIT"),
    "N2IU": ("Mapletree Pan Asia Comm Trust", "Real Estate / REIT"),
    "J69U": ("Frasers Centrepoint Trust", "Real Estate / REIT"),
    "AJBU": ("Keppel DC REIT", "Real Estate / REIT"),
}


def universe_sg():
    names = {f"{k}.SI": v[0] for k, v in STI.items()}
    sectors = {f"{k}.SI": [p.strip() for p in v[1].split("/")] for k, v in STI.items()}
    return names, {"^STI": "STI"}, sectors


def universe_us():
    r = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                     headers=UA, timeout=30)
    df = pd.read_html(r.text)[0]
    names, sectors = {}, {}
    for _, row in df.iterrows():
        t = str(row["Symbol"]).replace(".", "-")
        names[t] = row["Security"]
        sectors[t] = [x for x in (row.get("GICS Sector"), row.get("GICS Sub-Industry"))
                      if isinstance(x, str)]
    return names, {"^GSPC": "S&P 500"}, sectors


def universe_kr(top_n):
    import FinanceDataReader as fdr
    out = {}
    for market, suffix in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
        df = fdr.StockListing(market).sort_values("Marcap", ascending=False).head(top_n)
        out.update({f"{c}{suffix}": n for c, n in zip(df["Code"], df["Name"])})
    return out, {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}, {}   # KR themes come from Naver


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


def screen(market, kr_top):
    """Score every stock in the market. Returns all stocks above MIN_PRICE."""
    print(f"[{market}] loading universe ...")
    if market == "SG":
        names, indexes, sectors = universe_sg()
    elif market == "US":
        names, indexes, sectors = universe_us()
    else:
        names, indexes, sectors = universe_kr(kr_top)
    print(f"[{market}] downloading {len(names)} stocks ...")
    closes = download_close(list(names) + list(indexes))
    if closes.empty or not any(ix in closes for ix in indexes):
        print(f"[{market}] WARNING: no price data from Yahoo. "
              "Try: pip install -U yfinance  (then wait a few minutes and rerun)")

    rows = []
    for t, name in names.items():
        ix = index_for(t, market)
        if t not in closes or ix not in closes:
            continue
        m = score_stock(closes[t], closes[ix])
        if m:
            rows.append({"market": market, "ticker": t, "name": name,
                         "index": indexes[ix], "tags": sectors.get(t, []), **m})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    before = len(df)
    df = df[df["price"] >= MIN_PRICE.get(market, 0)]
    print(f"[{market}] scored {before}, kept {len(df)} "
          f"(price >= {MIN_PRICE.get(market, 0)})")
    return df


def top_picks(df, top):
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


def add_kr_themes(df):
    """Fill `tags` for KR rows from Naver themes (needed for the search box)."""
    if df.empty or not (df["market"] == "KR").any():
        return df
    try:
        kr_map = naver_themes()
    except Exception as e:
        print(f"[KR] Naver themes failed: {type(e).__name__}: {e}")
        return df
    df = df.copy()
    df["tags"] = [kr_map.get(t[:6], []) if m == "KR" else tags
                  for m, t, tags in zip(df["market"], df["ticker"], df["tags"])]
    return df


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
    import anthropic
    client = anthropic.Anthropic()
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
    msg = client.messages.create(model=model, max_tokens=300,
                                 messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()


# ---------------------------------------------------------------- report
SEARCH_JS = r"""
const DATA = __DATA__;
// Korean keyword -> English sector words, so "반도체" also finds US/SG stocks.
const ALIAS = {"반도체":"semiconductor","은행":"bank","리츠":"reit","부동산":"real estate",
  "제약":"pharma","바이오":"biotech","자동차":"auto","소프트웨어":"software","보험":"insurance",
  "항공":"airline","조선":"shipbuild","통신":"telecom","에너지":"energy","석유":"oil",
  "게임":"interactive","방산":"defense","2차전지":"batter","배터리":"batter","유통":"retail",
  "음식료":"food","건설":"construction","화학":"chemical","철강":"steel","전력":"utilit",
  "인터넷":"internet","카지노":"casino","해운":"marine","증권":"capital markets"};
const SIG = {STRONG:"#1a7f37",STRONGER:"#4c9a5e",WEAKER:"#9a6700",WEAK:"#cf222e"};
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const low = s => String(s).toLowerCase();

function row(d, shared) {
  const tags = d.tags.slice(0, 6).map(t =>
    `<span class="chip" onclick="go('${esc(t).replace(/'/g,"\\'")}')">${esc(t)}</span>`).join("");
  return `<tr><td>${d.market}</td><td>${esc(d.ticker)}</td><td><b>${esc(d.name)}</b></td>
    <td style="color:${SIG[d.signal]};font-weight:600">${d.signal}</td><td>${d.score}</td>
    <td>${d.price.toLocaleString()}</td><td>${d.rs}%</td>
    <td>${shared ? shared + " shared / 공통 " : ""}</td><td>${tags}</td></tr>`;
}
function table(title, list, sharedMap) {
  if (!list.length) return "";
  return `<h3>${title} (${list.length})</h3><table><tr><th>mkt</th><th>ticker</th><th>name</th>
    <th>signal</th><th>score</th><th>price</th><th>RS 20d</th><th>related</th><th>themes / sector</th></tr>
    ${list.map(d => row(d, sharedMap ? sharedMap.get(d) : 0)).join("")}</table>`;
}
function go(q) { $("#q").value = q; search(); window.scrollTo(0, $("#q").offsetTop - 10); }

function search() {
  const q = low($("#q").value.trim());
  const onlyStrong = $("#strong").checked;
  const ok = d => !onlyStrong || d.signal === "STRONG" || d.signal === "STRONGER";
  const bySc = (a, b) => b.score - a.score;
  if (!q) { $("#out").innerHTML = ""; return; }

  // 1) stock name / ticker match
  const hits = DATA.filter(d => low(d.name).includes(q) || low(d.ticker).includes(q));
  // 2) theme / sector match (plus English alias for Korean words)
  const words = [q]; if (ALIAS[q]) words.push(ALIAS[q]);
  const themed = DATA.filter(d => !hits.includes(d) &&
    d.tags.some(t => words.some(w => low(t).includes(w)))).filter(ok).sort(bySc);
  // 3) related stocks: share themes/sector with the matched stock(s)
  const hitTags = new Set(hits.flatMap(d => d.tags));
  const shared = new Map();
  DATA.forEach(d => {
    if (hits.includes(d) || themed.includes(d)) return;
    const n = d.tags.filter(t => hitTags.has(t)).length;
    if (n) shared.set(d, n);
  });
  const related = [...shared.keys()].filter(ok)
    .sort((a, b) => shared.get(b) - shared.get(a) || b.score - a.score).slice(0, 50);

  let h = table("Matched stocks / 검색 종목", hits);
  if (hits.length && hitTags.size) {
    h += `<p>Themes of matched stock (click) / 해당 종목 테마 (클릭): ` +
      [...hitTags].map(t => `<span class="chip" onclick="go('${esc(t).replace(/'/g,"\\'")}')">${esc(t)}</span>`).join("") + `</p>`;
  }
  h += table(`Theme / sector "${esc(q)}" / 테마·섹터 종목`, themed);
  h += table("Related stocks / 관련주 (most shared themes first)", related, shared);
  $("#out").innerHTML = h || "<p>No results / 결과 없음</p>";
}
$("#q").addEventListener("input", search);
$("#strong").addEventListener("change", search);
"""


def to_html(top, all_df, path):
    cols = ["market", "ticker", "name", "index", "signal", "score", "price",
            "ma20_slope_%", "idx_ma20_slope_%", "rs_20d_%", "themes"]
    head = "".join(f"<th>{c}</th>" for c in cols + ["news / AI"])
    body = []
    for _, r in top.iterrows():
        cells = "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols)
        news = "<br>".join(f'<a href="{html.escape(h["link"] or "")}" target="_blank">'
                           f'{html.escape(h["title"] or "")}</a>' for h in r.get("news", []))
        ai = html.escape(r.get("ai_comment", "") or "").replace("\n", "<br>")
        cls = "strong" if r["signal"] == "STRONG" else ""
        body.append(f'<tr class="{cls}">{cells}<td>{news}'
                    f'{"<hr>" + ai if ai else ""}</td></tr>')

    data = [{"market": r["market"], "ticker": r["ticker"], "name": str(r["name"]),
             "signal": r["signal"], "score": float(r["score"]), "price": float(r["price"]),
             "rs": float(r["rs_20d_%"]), "tags": list(r["tags"])}
            for _, r in all_df.iterrows()] if not all_df.empty else []
    js = SEARCH_JS.replace("__DATA__", json.dumps(data, ensure_ascii=False)
                           .replace("</", "<\\/"))
    limits = ", ".join(f"{k} ≥ {v:,}" for k, v in MIN_PRICE.items())

    path.write_text(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strong vs Index {dt.date.today()}</title>
<style>body{{font-family:sans-serif;margin:20px}}table{{border-collapse:collapse;font-size:13px;margin-bottom:12px}}
td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}th{{background:#f3f3f3}}
tr.strong td{{background:#eaf7ea}}td:last-child{{max-width:420px}}
.box{{background:#f6f8fa;border:1px solid #d0d7de;border-radius:8px;padding:14px;margin:14px 0}}
#q{{font-size:16px;padding:8px 10px;width:min(420px,90%);border:1px solid #888;border-radius:6px}}
.chip{{display:inline-block;background:#ddf4ff;border-radius:10px;padding:1px 8px;margin:2px;
cursor:pointer;font-size:12px}}.chip:hover{{background:#b6e3ff}}</style>
<h2>Stocks stronger than the index / 지수보다 강한 종목 — {dt.date.today()}</h2>

<div class="box">
<b>🔍 Search stock or theme / 종목·테마 검색</b><br>
<input id="q" placeholder="예: 삼성전자, 반도체, NVDA, DBS, bank" autofocus>
<label><input type="checkbox" id="strong"> Only stronger than index / 지수보다 강한 종목만</label>
<div style="font-size:12px;color:#555;margin-top:6px">
Searches all {len(data)} scanned stocks. Stock name → stock + related stocks (same themes).
Theme → all stocks in that theme. Click a theme chip to search it.<br>
스캔한 전체 {len(data)}개 종목에서 검색. 종목명 → 종목 + 관련주(같은 테마). 테마명 → 해당 테마 전체. 테마 칩을 누르면 그 테마로 검색.</div>
<div id="out"></div>
</div>

<h3>Top picks / 상위 종목</h3>
<p>Green = STRONG (stock MA20 rising, index MA20 flat or falling).
Price filter / 가격 필터: {limits}. Not financial advice.</p>
<table><tr>{head}</tr>{''.join(body)}</table>
<script>{js}</script>""", encoding="utf-8")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", nargs="+", default=["SG", "US", "KR"])
    ap.add_argument("--top", type=int, default=10, help="results per market")
    ap.add_argument("--kr-top", type=int, default=200,
                    help="largest N stocks per KR market to scan")
    ap.add_argument("--themes", action="store_true",
                    help="(kept for old commands; themes are now always on)")
    ap.add_argument("--news", action="store_true", help="add Google News headlines")
    ap.add_argument("--ai", action="store_true", help="add AI reason (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    a = ap.parse_args()

    parts = []
    for m in a.markets:
        try:
            parts.append(screen(m.upper(), a.kr_top))
        except Exception as e:  # one market failing should not stop the others
            print(f"[{m}] ERROR: {type(e).__name__}: {e}")
    all_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    stamp = dt.date.today().strftime("%Y%m%d")
    out_csv, out_html = HERE / f"strong_{stamp}.csv", HERE / f"strong_{stamp}.html"
    out_all = HERE / f"all_{stamp}.csv"
    if all_df.empty:
        out_html.write_text("<meta charset='utf-8'><h2>No stocks passed the filter today."
                            " Check the terminal for errors.</h2>", encoding="utf-8")
        print(f"\nNo results. Saved: {out_html.resolve()}")
        return

    all_df = add_kr_themes(all_df)
    all_df["themes"] = [", ".join(t[:4]) for t in all_df["tags"]]
    top = pd.concat([top_picks(g, a.top) for _, g in all_df.groupby("market", sort=False)],
                    ignore_index=True)

    top["news"] = [google_news(r["name"], r["market"]) if (a.news or a.ai) else []
                   for _, r in top.iterrows()]
    if a.ai:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY not set -> skipping AI comments.")
        else:
            ai = []
            for _, r in top.iterrows():
                try:
                    ai.append(ai_comment(r, a.model))
                except Exception as e:
                    ai.append(f"(AI error: {e})")
            top["ai_comment"] = ai

    top.drop(columns=["news", "tags"]).to_csv(out_csv, index=False, encoding="utf-8-sig")
    all_df.drop(columns=["tags"]).to_csv(out_all, index=False, encoding="utf-8-sig")
    to_html(top, all_df, out_html)
    if not top.empty:
        print(top[["market", "ticker", "name", "signal", "score", "rs_20d_%"]]
              .to_string(index=False))
    print(f"\nSaved: {out_html.resolve()}\n       {out_csv.resolve()}\n       {out_all.resolve()}")


if __name__ == "__main__":
    main()
