# Strong-vs-Index Screener / 지수보다 강한 종목 검색기

| Market 시장 | Stocks 대상 | Index 비교 지수 | Min price 최소 가격 |
|---|---|---|---|
| SG | STI 30 | STI | S$1 |
| US | S&P 500 | S&P 500 | US$5 |
| KR | Top 200 KOSPI + 200 KOSDAQ | KOSPI / KOSDAQ | ₩5,000 |

## Install / 설치
    pip install -r requirements.txt

## Run / 실행
    python screener.py               # basic / 기본
    python screener.py --markets KR  # Korea only / 한국만
    python screener.py --news --ai   # + news, AI reason / 뉴스·AI 코멘트

Open `strong_YYYYMMDD.html` in your browser. / 브라우저로 여세요.

## Live search app / 실시간 검색 앱
    python3 -m streamlit run app.py
- Opens in your browser. Every search downloads fresh prices (Yahoo, up to ~15 min delay).
- 브라우저가 열립니다. 검색할 때마다 최신 가격을 새로 받아 옵니다 (야후, 최대 약 15분 지연).
- Any stock works, even outside the screener list (e.g. 삼성전자, TSLA).
- Stock lists & Naver themes are cached 1 hour (CACHE_SECONDS in app.py). / 목록·테마는 1시간 저장.
- Stop: press Ctrl+C in Terminal. / 종료: 터미널에서 Ctrl+C.

## Search box in the daily report / 일일 리포트 검색창 (snapshot / 스냅샷)
- `삼성전자` → Samsung + related stocks (same Naver themes) / 삼성전자 + 관련주
- `반도체` → all semiconductor stocks (KR themes + US/SG sectors) / 반도체 종목 전체
- Click a theme chip to search it. / 테마 칩을 누르면 그 테마로 검색.

## Change price filter / 가격 기준 변경
Edit `MIN_PRICE` at the top of screener.py. / screener.py 위쪽 `MIN_PRICE` 숫자 수정.

## AI comments / AI 코멘트
    export ANTHROPIC_API_KEY=sk-ant-...
