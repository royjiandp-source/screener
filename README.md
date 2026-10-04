# Strong-vs-Index Screener / 지수보다 강한 종목 검색기

Finds stocks stronger than their own index in **Singapore, US, Korea**.
싱가포르·미국·한국에서 **지수보다 강한 종목**을 찾습니다.

| Market 시장 | Stocks scanned 대상 | Compared with 비교 지수 |
|---|---|---|
| SG | STI 30 stocks | STI |
| US | S&P 500 | S&P 500 |
| KR | Top 200 KOSPI + top 200 KOSDAQ (by market cap) | KOSPI / KOSDAQ |

## 1. Install / 설치
```
pip install -r requirements.txt
```

## 2. Run / 실행
```
python screener.py                         # basic / 기본
python screener.py --markets KR            # Korea only / 한국만
python screener.py --themes --news         # + themes, news / 테마·뉴스 추가
python screener.py --themes --news --ai    # + AI reason / AI 코멘트 추가
```
Output: `strong_YYYYMMDD.csv` and `strong_YYYYMMDD.html` (open in browser).
결과: CSV와 HTML 파일이 생깁니다. HTML은 브라우저로 여세요.

## 3. AI comments / AI 코멘트
Get an API key at console.anthropic.com, then:
API 키를 발급받은 뒤 설정하세요:
```
# Windows
set ANTHROPIC_API_KEY=sk-ant-...
# Mac / Linux
export ANTHROPIC_API_KEY=sk-ant-...
```
Cost is small (one short request per stock). 종목당 짧은 요청 1회라 비용이 적습니다.

## 4. Rules / 판단 규칙
| Signal | Meaning 의미 |
|---|---|
| STRONG | Stock MA20 ↗, index MA20 ↘ or flat. Best case. 종목↗ 지수↘ 최상 |
| STRONGER | Stock MA20 slope > index slope. 종목 기울기가 더 가파름 |
| WEAK / WEAKER | Filtered out. 제외 |

Only STRONG/STRONGER stocks above MA20 are shown. 20일선 위 종목만 표시합니다.
Score = 2×(slope gap) + 20-day relative strength + bonus (above MA20, MA60, 5>10>20 aligned).

## 5. Notes / 참고
- Naver themes are scraped from finance.naver.com. First run ~1-2 min, then cached 7 days.
  If Naver changes its page, themes may come back empty.
  네이버 테마는 첫 실행 1~2분, 이후 7일간 캐시. 네이버 페이지가 바뀌면 비어 나올 수 있음.
- US/SG use Yahoo sector/industry instead of themes. 미국·싱가포르는 섹터 정보를 씁니다.
- Data is daily (Yahoo Finance), not real-time. 일봉 데이터, 실시간 아님.
- STI list is hard-coded in screener.py. Update it when STI changes. STI 목록은 직접 수정.
- Not financial advice. 투자 조언이 아닙니다.

## 6. Run on GitHub every day / GitHub에서 매일 자동 실행
Runs weekdays ~07:00 SGT and publishes to `https://<your-id>.github.io/<repo>/`.
평일 오전 7시쯤(싱가포르) 자동 실행되고 위 주소에 결과가 올라갑니다.

1. github.com → **New repository** → name `screener` → **Public** → Create.
   (Free Pages needs a public repo. / 무료 Pages는 공개 저장소만 가능)
2. In Terminal, in this folder / 터미널에서 이 폴더로 이동 후:
   ```
   git init -b main
   git add .
   git commit -m "Screener"
   git remote add origin https://github.com/<your-id>/screener.git
   git push -u origin main
   ```
3. Repo → **Settings → Pages** → Source: **GitHub Actions**.
4. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   → Name `ANTHROPIC_API_KEY`, value `sk-ant-...` (for AI comments / AI 코멘트용).
5. Repo → **Actions** → *Daily screener* → **Run workflow** (first test / 첫 테스트).
   Takes ~10–20 min. Then open the Pages URL. / 10~20분 후 주소를 여세요.

Files / 파일: `.github/workflows/screener.yml` (schedule), `make_site.py` (builds `docs/`).
Change the time: edit the `cron` line (UTC). 시간 변경은 `cron` 줄(UTC 기준) 수정.
# screener
