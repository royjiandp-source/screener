# AI Investment Idea Discovery / AI 투자 아이디어 발굴 시스템

News → Theme → Industry → Stocks → Financials → Valuation → Risk → **Score (100)** → Watchlist.
뉴스 → 테마 → 산업 → 종목 → 재무 → 가치평가 → 리스크 → **점수(100점)** → 후보 리스트.

AI does not make investment decisions. It gives a list of companies worth reviewing.
AI가 투자 결정을 대신하지 않습니다. 검토할 가치가 있는 기업 리스트를 제공합니다.

## What it uses / 사용 데이터 (all free / 모두 무료)

| Module 모듈 | Source 소스 |
|---|---|
| News 뉴스 | Google News RSS (US / KR / SG), 11 topics |
| News analysis 뉴스 분석 | Gemini `gemini-3.5-flash` (keyword fallback if no key) |
| Financials 재무 | Yahoo Finance (income, balance sheet, cash flow) |
| Macro 거시 | FRED CSV (Fed rate, 10Y, CPI, PPI, GDP, unemployment, M2) — no key |

## Scoring / 점수 (100)

| Part | Points | Metrics |
|---|---|---|
| Financial health 재무 건전성 | 30 | ROE ≥15%, ROIC ≥10%, debt ratio ≤100%, FCF yield ≥5% |
| Growth 성장성 | 20 | Revenue growth, EPS growth (≥15%/yr = full) |
| Valuation 가치평가 | 20 | PER, PBR, EV/EBITDA |
| Theme momentum 테마 | 15 | News volume, positive news, 1-month price flow |
| Macro 거시 | 10 | Is the theme favored in the current cycle? |
| Risk 리스크 | 5 | Country, geopolitics, industry (tariffs/regulation/rates), debt, losses |

Missing data → half points for that part. 데이터가 없으면 그 항목은 절반 점수.
Themes, tickers, cycle preferences and risk lists are in **`themes.json`** — edit freely.
테마·종목·경기별 선호·리스크 목록은 `themes.json`에서 수정하세요.

## Run on your Mac / Mac에서 실행

```
cd investment
pip install -r requirements.txt
export GEMINI_API_KEY=your-key        # optional / 선택
uvicorn app.main:app --port 8000
```
Open http://localhost:8000 → press **Run now / 지금 실행** (first run 5–15 min).
브라우저에서 열고 **지금 실행**을 누르세요 (첫 실행 5~15분).

Command line only / 명령줄만:
```
python -m app.pipeline all                                  # news + scoring
python -m app.pipeline all --export report.html             # + static HTML
```

## Automatic schedule (while the server runs) / 자동 실행 (서버 실행 중)

| Time (SGT) | Job |
|---|---|
| 07:00, 12:00, 18:00, 23:00 | News collection + AI analysis / 뉴스 수집·분석 |
| 07:15 | Financials + scoring / 재무·점수 계산 |

Change the time zone with `INVEST_TZ` (default `Asia/Singapore`).

## API

| Endpoint | Returns |
|---|---|
| `GET /` | Dashboard 대시보드 |
| `GET /api/report` | Full report (themes, top stocks, value picks, avoid list, macro) |
| `GET /api/themes` | Theme ranking |
| `GET /api/stocks?market=KR&limit=20` | Scored stocks |
| `GET /api/stocks/{ticker}` | One stock with all metrics |
| `GET /api/macro` | Macro data + cycle |
| `GET /api/news?theme=Nuclear` | Analyzed news |
| `POST /api/run?step=all|news|score` | Run now |
| `GET /api/status` | Is a run in progress? |

Interactive docs: http://localhost:8000/docs

## Deploy (always on) / 서버 배포

Docker:
```
docker build -t invest .
docker run -d -p 8000:8000 -e GEMINI_API_KEY=your-key -v $PWD/data:/app/data invest
```
Works on any Docker host (Oracle Cloud free VM, Fly.io, Render, Railway…). Keep `/app/data`
on a persistent disk so news history is kept.
아무 Docker 서버에서 동작합니다. `/app/data`는 영구 디스크로 연결하세요.

GitHub Actions also builds a static copy every weekday: `…github.io/screener/invest/`.
GitHub Actions가 평일마다 정적 버전도 만듭니다.

## Tests / 테스트
```
pip install pytest httpx && python -m pytest -q
```

## Limits / 한계
- Phase 1. Not yet: ETF flows, insider trading, institutional buying, short selling (Phase 2);
  portfolio optimization, backtesting (Phase 3).
- "Money flow" uses the theme's 1-month price move as a proxy (no free institutional-flow data).
- Macro cycle uses US data for all markets.
- Yahoo data for KR/SG stocks can be incomplete → see "data coverage" in the stock details.
- Not financial advice. 투자 조언이 아닙니다.
