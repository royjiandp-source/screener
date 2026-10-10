"""
Live stock / theme search (SG / US / KR)
실시간 종목·테마 검색 (싱가포르 / 미국 / 한국)

Run / 실행:
    python3 -m streamlit run app.py

Every search downloads fresh prices from Yahoo (may be ~15 min delayed).
검색할 때마다 야후에서 최신 가격을 새로 받아 옵니다 (최대 약 15분 지연).
"""
import datetime as dt
import json
import re
import time

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

import screener as sc

st.set_page_config(page_title="Live Stock Search", page_icon="🔍", layout="wide")

# Korean keyword -> English sector words, so "반도체" also finds US/SG stocks.
ALIAS = {"반도체": "semiconductor", "은행": "bank", "리츠": "reit", "부동산": "real estate",
         "제약": "pharma", "바이오": "biotech", "자동차": "auto", "소프트웨어": "software",
         "보험": "insurance", "항공": "airline", "조선": "shipbuild", "통신": "telecom",
         "에너지": "energy", "석유": "oil", "방산": "defense", "2차전지": "batter",
         "배터리": "batter", "유통": "retail", "음식료": "food", "건설": "construction",
         "화학": "chemical", "철강": "steel", "전력": "utilit", "인터넷": "internet",
         "카지노": "casino", "해운": "marine", "증권": "capital markets", "게임": "interactive"}
INDEX_NAME = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ", "^GSPC": "S&P 500", "^STI": "STI"}
SIG_COLOR = {"STRONG": "#1a7f37", "STRONGER": "#4c9a5e", "WEAKER": "#9a6700", "WEAK": "#cf222e"}


# ---------------------------------------------------------------- stock lists (cached)
@st.cache_data(ttl=7 * 86400, show_spinner="Loading Korean stock list (first time ~30s) / 한국 종목 목록 로딩 중...")
def kr_list():
    """All KOSPI + KOSDAQ stocks {ticker: name}, in market-cap order. Cached 7 days."""
    cache = sc.HERE / "kr_stocks.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
        return json.loads(cache.read_text(encoding="utf-8"))
    out = {}
    for sosok, suffix in ((0, ".KS"), (1, ".KQ")):
        for page in range(1, 80):
            r = requests.get("https://finance.naver.com/sise/sise_market_sum.naver",
                             params={"sosok": sosok, "page": page}, headers=sc.UA, timeout=20)
            r.encoding = "euc-kr"
            found = re.findall(r'/item/main\.naver\?code=(\d{6})"\s+class="tltle">([^<]+)</a>',
                               r.text)
            new = [(c, n) for c, n in found if f"{c}{suffix}" not in out]
            if not new:
                break
            out.update({f"{c}{suffix}": n.strip() for c, n in new})
    if not out:  # backup source
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
        for c, n, m in zip(df["Code"], df["Name"], df["Market"]):
            if m in ("KOSPI", "KOSDAQ"):
                out[f"{c}{'.KS' if m == 'KOSPI' else '.KQ'}"] = n
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


@st.cache_data(ttl=7 * 86400, show_spinner="Loading Naver themes (first time 1-2 min) / 네이버 테마 로딩 중...")
def kr_themes():
    return sc.naver_themes()


@st.cache_data(ttl=86400, show_spinner="Loading S&P 500 list / S&P 500 목록 로딩 중...")
def us_list():
    names, _, sectors = sc.universe_us()
    return names, sectors


@st.cache_data(ttl=3600, show_spinner=False)
def yahoo_search(q):
    """Find any ticker on Yahoo (for stocks outside our lists)."""
    try:
        quotes = yf.Search(q, max_results=8).quotes
    except Exception:
        return {}
    return {x["symbol"]: x.get("shortname") or x.get("longname") or x["symbol"]
            for x in quotes if x.get("quoteType") == "EQUITY"}


@st.cache_data(ttl=86400, show_spinner=False)
def yahoo_sector(t):
    try:
        info = yf.Ticker(t).info
        return [x for x in (info.get("sector"), info.get("industry")) if x]
    except Exception:
        return []


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def universe():
    """names {ticker: name}, tags {ticker: [themes/sectors]}, warnings."""
    names, tags, warns = {}, {}, []
    try:
        kr = kr_list()
        try:
            th = kr_themes()
        except Exception as e:
            th, _ = {}, warns.append(f"KR themes: {e}")
        for t, n in kr.items():
            names[t], tags[t] = n, th.get(t[:6], [])
    except Exception as e:
        warns.append(f"KR list: {e}")
    try:
        un, us = us_list()
        names.update(un)
        tags.update(us)
    except Exception as e:
        warns.append(f"US list: {e}")
    sn, _, ss = sc.universe_sg()
    names.update(sn)
    tags.update(ss)
    return names, tags, warns


# ---------------------------------------------------------------- live prices
@st.cache_data(ttl=60, show_spinner=False)   # same search within 60s reuses data
def fetch(tickers):
    return sc.download_close(list(tickers))


def index_of(t):
    if t.endswith(".KS"):
        return "^KS11"
    if t.endswith(".KQ"):
        return "^KQ11"
    if t.endswith(".SI"):
        return "^STI"
    return "^GSPC"


def market_of(t):
    return {"^KS11": "KR", "^KQ11": "KR", "^STI": "SG"}.get(index_of(t), "US")


def analyse(tickers, names, tags, closes):
    rows = []
    for t in tickers:
        ix = index_of(t)
        if t not in closes or ix not in closes:
            continue
        s = closes[t].dropna()
        m = sc.score_stock(closes[t], closes[ix])
        if not m or len(s) < 2:
            continue
        rows.append({"market": market_of(t), "ticker": t, "name": names.get(t, t),
                     "signal": m["signal"], "score": m["score"], "price": m["price"],
                     "today_%": round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2),
                     "rs_20d_%": m["rs_20d_%"], "ma20_slope_%": m["ma20_slope_%"],
                     "index": INDEX_NAME[ix], "idx_ma20_slope_%": m["idx_ma20_slope_%"],
                     "above_ma20": m["above_ma20"], "date": s.index[-1].strftime("%Y-%m-%d"),
                     "themes": ", ".join(tags.get(t, [])[:5])})
    return pd.DataFrame(rows)


def show_table(df, title, only_strong):
    if df.empty:
        return
    if only_strong:
        df = df[df["signal"].isin(["STRONG", "STRONGER"])]
    df = df.sort_values("score", ascending=False)
    st.subheader(f"{title} ({len(df)})")
    st.dataframe(
        df.style.map(lambda v: f"color:{SIG_COLOR.get(v, '')};font-weight:600", subset=["signal"])
          .map(lambda v: "color:#cf222e" if v < 0 else "color:#1a7f37", subset=["today_%"]),
        hide_index=True, width="stretch")


def stock_card(t, names, closes, row):
    ix = index_of(t)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{names.get(t, t)} ({t})", f"{row['price']:,}", f"{row['today_%']}% today / 오늘")
    c2.metric("Signal / 신호", row["signal"])
    c3.metric("RS vs index, 20d / 지수 대비 20일", f"{row['rs_20d_%']}%")
    c4.metric("Last data / 최근 데이터", row["date"])
    df = pd.concat([closes[t], closes[ix]], axis=1, keys=[names.get(t, t), INDEX_NAME[ix]]).dropna()
    df = df.tail(120)
    st.line_chart(df / df.iloc[0] * 100, height=260)
    st.caption("Stock vs index, last 120 days, start = 100 / 종목 vs 지수, 최근 120일, 시작=100")


# ---------------------------------------------------------------- page
st.title("🔍 Live Stock & Theme Search / 실시간 종목·테마 검색")
names, tags, warns = universe()
for w in warns:
    st.warning(w)

c1, c2, c3 = st.columns([3, 1.4, 1])
q = c1.text_input("Stock or theme / 종목 또는 테마",
                  key="q", placeholder="예: 삼성전자, 반도체, NVDA, Tesla, DBS, bank")
only_strong = c2.checkbox("Only stronger than index / 지수보다 강한 종목만")
max_n = c3.number_input("Max stocks / 최대 종목", 10, 200, 60, step=10)
if st.button("🔄 Refresh prices / 가격 새로고침"):
    fetch.clear()

if q.strip():
    ql = q.strip().lower()
    # 1) stock name / ticker
    hits = [t for t, n in names.items()
            if ql in (n.lower(), t.lower(), t.split(".")[0].lower())]
    if not hits:
        hits = [t for t, n in names.items() if ql in n.lower()][:5]
    if not hits:   # anything else on Yahoo (e.g. TSLA, stocks outside our lists)
        for t, n in yahoo_search(q.strip()).items():
            names[t] = n
            hits.append(t)
        hits = hits[:5]
    for t in hits:
        if not tags.get(t):
            tags[t] = yahoo_sector(t)

    # 2) theme / sector
    words = [ql] + ([ALIAS[ql]] if ql in ALIAS else [])
    themed = [t for t in names if t not in hits
              and any(w in g.lower() for g in tags.get(t, []) for w in words)][:max_n]

    # 3) related: share themes / sector with the matched stocks
    hit_tags = {g for t in hits for g in tags.get(t, [])}
    shared = {t: sum(g in hit_tags for g in tags.get(t, []))
              for t in names if t not in hits and t not in themed}
    related = [t for t, n in sorted(shared.items(), key=lambda x: -x[1]) if n][:max_n]

    todo = list(dict.fromkeys(hits + themed + related))
    if not todo:
        st.info("No match / 결과 없음")
        st.stop()
    with st.spinner(f"Downloading live prices for {len(todo)} stocks / "
                    f"{len(todo)}개 종목 실시간 가격 받는 중..."):
        closes = fetch(tuple(sorted(set(todo) | {index_of(t) for t in todo})))
    st.caption(f"Fetched / 받은 시각: {dt.datetime.now():%Y-%m-%d %H:%M:%S} · "
               "Yahoo data, may be ~15 min delayed / 야후 데이터, 최대 15분 지연")

    df = analyse(todo, names, tags, closes)
    if df.empty:
        st.error("No price data from Yahoo. Try: pip3 install -U yfinance / 야후 데이터 없음")
        st.stop()
    # price filter for theme/related lists (the searched stock is always shown)
    df["_min"] = df["market"].map(sc.MIN_PRICE).fillna(0)
    cheap = (df["price"] < df["_min"]) & ~df["ticker"].isin(hits)
    df = df[~cheap].drop(columns="_min")

    hit_df = df[df["ticker"].isin(hits)]
    if not hit_df.empty:
        st.header("Matched stock / 검색 종목")
        for _, r in hit_df.iterrows():
            stock_card(r["ticker"], names, closes, r)
        if hit_tags:
            st.write("**Themes (click to search) / 테마 (클릭하면 검색):**")
            tag_list = sorted(hit_tags)[:24]
            cols = st.columns(6)
            for i, g in enumerate(tag_list):
                cols[i % 6].button(g, key=f"tag_{g}",
                                   on_click=lambda g=g: st.session_state.update(q=g))
        first = hit_df.iloc[0]
        with st.expander(f"📰 News: {first['name']} / 최근 뉴스"):
            for h in sc.google_news(first["name"], first["market"], n=5):
                st.markdown(f"- [{h['title']}]({h['link']})")

    show_table(df[df["ticker"].isin(themed)], f'Theme / sector "{q}" / 테마·섹터 종목', only_strong)
    rel = df[df["ticker"].isin(related)].copy()
    if not rel.empty:
        rel.insert(3, "shared", rel["ticker"].map(shared))
        show_table(rel, "Related stocks / 관련주", only_strong)

st.divider()
st.caption("Signal: STRONG = stock MA20 rising while index MA20 flat/falling. "
           f"Price filter for lists: {sc.MIN_PRICE}. Not financial advice. / 투자 조언 아님.")
