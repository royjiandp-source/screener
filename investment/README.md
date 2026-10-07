# 국가별 가치투자 후보 분석

기존 뉴스·테마 앱을 가치평가 중심으로 전환한 초기 구현입니다. **전체 설계 구현 완료 상태가 아닙니다.**

## 구현된 기능

- 한국·미국·일본·대만·홍콩·싱가포르 국가 필터와 국가별 분석 현황.
- 뉴스와 독립된 명시적 종목 목록: `universe.json` (거래소 전체 목록이 아닌 초기 후보 목록).
- Yahoo 보조 재무자료에서 같은 연도의 EBIT·세율·감가상각·설비투자·운전자본을 확인한 FCFF 계산.
- 완전한 연간 자료가 3개 이상일 때 FCFF 중앙값으로 초기 정상 현금흐름 추정.
- FCFF/WACC·FCFE/자기자본비용 구분, 순차입금 조정, 보수적·기준·낙관적 가치, 안전마진·9개 민감도 조합.
- 가치평가 35 / 사업 품질 25 / 재무 20 / 자본배분 10 / 성장 10의 초기 점수.
- 결측 항목 0점, 핵심 가치평가 자료 부족 시 총점 없음; 금융·REIT 전용 모형 필요 상태.
- 공식 자료 검증 여부, 통화, 수집 시각, 정상화 방법, 할인율 가정 표시.
- 국가별 화면·API, 자료 부족/추가 검토 목록, 정적 HTML 출력.
- SEC·DART 공식 공시 수집기, 기업 식별번호 매핑, 원본 해시·수집 시점별 이력 보존.
- 같은 기간·통화·연결 범위의 재무상태표 항목 대조와 충돌 시 검토 보류.
- 공개 시점과 첫 수집 시점을 모두 제한하는 과거 공시 조회.
- 역산 DCF: 다른 가정을 고정할 때 현재 가격에 내재된 현금흐름 성장률.

할인율 10%·영구성장률 2%는 `universe.json`의 **예시 초기 가정**이며 회사별 실제 자본비용이 아닙니다. 역사적 중앙값도 비경상 항목·주식보상·리스·ADR를 조정한 확정 가치가 아닙니다. 국가 간 점수는 업종별 보정 전입니다. 미국 FRED 지표는 미국 거시 참고 정보로만 표시합니다.

## 실행

```bash
cd investment
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest httpx
DISABLE_SCHEDULER=1 .venv/bin/python -m uvicorn app.main:app --port 8000
```

브라우저에서 `http://localhost:8000`을 열고 국가를 선택합니다. 처음에는 미수집 상태로 나타납니다. `지금 실행`은 보조 데이터와 뉴스 수집을 시작합니다. 자동 일정을 사용하려면 `DISABLE_SCHEDULER=1`을 제거합니다.

국가를 지정한 재무 수집:

```bash
.venv/bin/python -m app.pipeline score --markets KR US
.venv/bin/python -m app.pipeline score --markets JP TW HK SG
.venv/bin/python -m app.pipeline none --export report.html
```

`INVEST_DB`로 데이터베이스, `INVEST_UNIVERSE`로 후보 목록 경로를 변경할 수 있습니다. `GEMINI_API_KEY`는 선택 사항입니다. 뉴스 수집은 기존 US/KR/SG만 지원하며, 다른 국가의 주식 분석과는 독립적입니다.

## API

| 주소 | 내용 |
|---|---|
| `GET /?market=KR` | 국가별 화면 |
| `GET /api/countries` | 6개 국가의 설정 종목 수·분석 기록·가치평가 가능 수·상태 |
| `GET /api/report?market=US` | 국가별 리포트 |
| `GET /api/stocks?market=JP&limit=50` | 국가별 분석 종목, 보류 상태 포함 |
| `GET /api/stocks/{ticker}` | 가치 시나리오·가정·품질 포함 상세 |
| `POST /api/run?step=score` | 재무 분석 실행 |
| `GET /api/status` | 실행 상태 |
| `POST /api/run?step=official` | 한국·미국 공식 공시 수집 |
| `GET /api/filings/{ticker}?as_of=2026-10-06T00:00:00Z` | 그 시점까지 실제 수집된 공개 공시 항목·원본 해시 이력 |
| `GET /api/sources` | 국가별 공식 출처 설정·수집 상태 |

지원 시장 코드: KR, US, JP, TW, HK, SG. 기존 테마 점수는 뉴스 참고 표에서만 사용됩니다. 이전 버전의 저장된 투자 점수는 새로운 상위 목록에 포함하지 않습니다.

## 검증

프로젝트 루트에서:

```bash
investment/.venv/bin/python -m pytest -q
```

실제 데이터를 호출하지 않는 계산·파이프라인·API 통합 테스트입니다. 실제 공급자 연결과 데이터의 정확성 검증을 대체하지 않습니다.

## 공식 공시 설정과 대조 범위

미국은 `SEC_USER_AGENT`에 앱 이름과 실제 연락 가능한 이메일을, 한국은 `DART_API_KEY`에 Open DART 인증키를 환경변수로 설정해야 합니다. 빈 값이면 `not_configured`로 표시하고 네트워크 요청을 하지 않습니다. 키는 채팅에 올리지 말고 로컬 또는 GitHub Secrets에 보관하세요. GitHub에서는 `SEC_USER_AGENT`를 repository variable, `DART_API_KEY`를 secret으로 설정합니다.

로컬에서 `.env.example`을 `.env`로 복사해 값을 입력했다면:

```bash
.venv/bin/python -m uvicorn app.main:app --port 8010 --env-file .env
```

명령줄 수집에서는 환경변수를 내보낸 뒤 실행합니다.

```bash
.venv/bin/python -m app.pipeline official --markets US KR
.venv/bin/python -m app.pipeline score --markets US KR
```

기본 DART 수집은 직전 사업연도 사업보고서입니다. `universe.json`에 `"official_years": [2023, 2024, 2025]`를 넣어 확장할 수 있습니다. 공시 목록은 정정을 포함하지만 전체 재무제표 API가 반환하는 최신 버전을 저장하므로, 수집 이전의 원래 재무 수치를 복원한 것으로 취급하지 않습니다. SEC도 표준 US-GAAP/IFRS 태그 중 지원하는 항목만 수집하며, 기업별 확장 태그는 원본에서 별도 확인해야 합니다.

Yahoo의 연결 범위는 자동으로 확정하지 않습니다. 원문 검토 후 `company_assumptions`에서 해당 기업의 `statement_scope`를 `consolidated` 또는 `standalone`으로 명시할 수 있습니다. 범위가 미확인되면 `not_comparable`입니다. 날짜·통화·범위가 맞는 현금·자기자본·자산·부채만 대조하며, 현금흐름 전체·정상화·할인율·주식 수 검증은 별개입니다. 일부 항목이 일치해도 `valuation_verified`는 false를 유지합니다.

국가별로 가장 최근 분석일을 유지합니다. 서로 다른 날에 미국과 일본을 수집해도 다른 국가의 결과를 숨기지 않으며, 각 국가의 분석일을 표시합니다.

## 아직 구현하지 않은 핵심 범위

- 거래소 전체 종목 동기화와 한국·미국 이외의 공식 수집기.
- 안정적인 기업/증권 식별자, ADR·복수 상장 전환비율 처리.
- 국가별 회계 전체 표준화, 공식 항목을 이용한 전체 가치평가 검증, 가격·환율 시점의 엄밀한 정합성.
- 정성 경쟁우위·경영진 자본배분 근거 수집, 업종별 점수 보정, 금융·REIT 전용 모형.
- 과거 시점 백테스트, 상장폐지·거래비용·배당·환율 반영 검증. 공시의 과거 시점 조회만으로 수익률 백테스트가 완성되는 것은 아닙니다.

공식 규격: [SEC API](https://www.sec.gov/edgar/sec-api-documentation), [DART 전체 재무제표](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020), [DART 공시 검색](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001).

## 다음 단계로 보류

ETF 자금, 내부자 거래, 공매도, 기관 매매, 복잡한 포트폴리오 최적화는 핵심 가치평가와 데이터 검증이 작동한 뒤 도입합니다.

## 거래소 전체 검색과 관찰 지표

화면의 **섹터 검색**에서 국가와 검색어를 선택합니다. 결과에는 분류 근거와 출처가 표시됩니다. 선택 종목 또는 검색 결과 전체의 가치평가를 실행할 수 있습니다. 실행은 종목별로 진행되며 취소는 진행 중인 종목의 수집이 끝난 후 반영됩니다. 다른 종목의 기존 평가와 전체 테마 자료는 보존합니다. 검색 결과 전체의 관찰 자료 수집도 지원하지만 공급자 호출이 많으므로 시간이 걸립니다.

전체 목록과 테마 분류는 별개입니다. 공식 업종과 보조 사업 설명에서 확인한 테마 관계를 검색하며, 미분류 기업은 테마 검색에서 빠질 수 있습니다. 유사한 단어만으로 실제 사업 비중을 입증하지 않습니다. 관찰 점수는 미래 주도주나 수익률을 확정하는 예측값이 아닙니다.

현재 실제 연결을 확인한 범위:

| 시장 | 상장 목록 | ETF·기관 자료 |
|---|---|---|
| 한국 | KRX KIND 2,758개 기업 (기업 목록이며 우선주·ETF 전 종목 목록 아님) | 기관 순매수 수집기 구현; KRX 로그인 설정 필요 |
| 미국 | Nasdaq/기타 거래소 13,251개 증권, ETF 유형 분리 | ETF 보조 자료; SEC 13F 수집기, 연락처와 확인된 CUSIP 연결 필요 |
| 일본 | JPX 4,447개 증권 | 공식 ETF 자금·기관 자동 연결 미지원; 검증된 자료 입력 가능 |
| 대만 | TWSE/TPEx 1,988개 기업 | 공식 ETF 자금·기관 자동 연결 미지원; 검증된 자료 입력 가능 |
| 홍콩 | HKEX 17,265개 증권, 주식·ETF·기타 유형 구분 | 공식 ETF 자금·기관 자동 연결 미지원; 검증된 자료 입력 가능 |
| 싱가포르 | 자동 목록 연결 미구현; 출처가 있는 목록 입력 가능 | 공식 ETF 자금·기관 자동 연결 미지원; 검증된 자료 입력 가능 |

수치는 연결 검증 당시의 목록이며 기업 수와 증권 수를 서로 같은 것으로 비교하지 마세요. 전체 6개 국가에서 모든 ETF·기관 자료가 자동 수집되는 완료 상태가 아닙니다.

**관찰·ETF 자료 수집**은 사업 설명 분류, 조정 가격, 시장 대비 3/6/12개월 강세, 매출·이익률·영업현금흐름 변화와 거래대금 변화를 수집합니다. 상대강도 및 최소 두 실적 항목, 거래대금 순위, 같은 시점의 비교 표본 20개가 필요하며 부족하면 점수를 보류합니다. 개별 주식과 비교 ETF 모두 배당·분할 조정 수익률을 사용합니다. 비교 ETF는 KR 069500, US SPY, JP 1306, TW 0050, HK 2800, SG ES3이며 ETF 비용·추적 오차와 대표 지수의 시장 범위 차이가 있습니다. 기존 가격지수 기준 기록은 순위 표본에서 제외합니다. 수주·컨센서스 상향의 자동 수집과 예측력 백테스트는 포함되지 않습니다.

ETF 보조 자료는 NAV·규모·상위 보유 종목이며 자료 기준일이 독립 확인되지 않은 경우 설정/환매를 계산하지 않습니다. 실제 발행좌수·NAV·기업행동 확인이 있는 동일 기준일 자료를 입력할 때만 설정/환매 추정이 가능합니다. AUM 변화나 거래대금을 자금 유입이라고 표시하지 않습니다. 운용사별 공식 설정/환매 자동 수집기는 아직 연결하지 않았습니다.

한국 기관 자료는 `KRX_ID`, `KRX_PW`를 로컬 `.env`에 설정해야 합니다. DART 키와는 별개입니다. 서버가 실행 중이면 설정 후 다시 시작해야 합니다. 미국은 `SEC_USER_AGENT` 설정 후 기관의 CIK로 수집합니다. 13F는 분기 보유 공시로 실제 거래일이나 매수금액을 알 수 없습니다. 확인된 CUSIP 매핑이 없는 종목과 옵션은 주식 변화 분석에 자동 합치지 않습니다. 최근 공시의 두 분기 범위와 수정 공시를 대상으로 하며 관리자 전체 시장을 대표하지 않습니다. 공개된 동일 관리자 보유 수와 가치 변화는 구분하지만 자료가 없는 종목을 신규 매수·청산으로 단정하지 않습니다.

### 추가 API

- `GET /api/discovery/search?query=반도체&market=KR&offset=0&limit=50`
- `GET /api/discovery/sources`
- `POST /api/discovery/refresh?market=JP`
- `POST /api/discovery/evaluate`: `listing_ids` 또는 `query`와 선택적 `market`
- `POST /api/discovery/enrich`: 같은 입력으로 분류·관찰·ETF 자료 수집
- `GET /api/discovery/jobs/{id}` / `POST /api/discovery/jobs/{id}/cancel`
- `POST /api/discovery/jobs/{id}/resume`: 서버 재시작으로 중단된 작업 재개
- `GET /api/discovery/detail?listing_id=KR:KOSPI:000660:stock`
- `GET /api/discovery/leadership?query=반도체&market=KR`
- `POST /api/discovery/institution/refresh?listing_id=...&start=2026-09-01&end=2026-09-30`
- `POST /api/discovery/institution/sec13f?manager_cik=...`
- `POST /api/discovery/import` / `POST /api/discovery/flows/import`

자료 입력은 화면 **기관 공시·자료 연결**에서 JSON 파일을 불러오거나 API로 수행합니다. 목록 예:

```json
{
  "market": "SG", "source": "검토한 SGX 내보내기 자료",
  "observed_at": "2026-10-07T00:00:00Z", "complete": true,
  "rows": [{"id":"SG:SGX:EXAMPLE:stock", "market":"SG", "exchange":"SGX",
    "code":"EXAMPLE", "ticker":"EXAMPLE.SI", "name":"형식 예시 기업",
    "type":"stock", "currency":"SGD", "industry":"Semiconductors"}]
}
```

위 종목은 파일 형식만 설명하는 예시이며 실제 검색 목록에 자동 삽입하지 않습니다. 완전 목록의 `complete:true`는 해당 시장의 활성 목록을 대체하므로 전 종목 자료임을 확인해야 합니다. 부분 자료는 이전 활성 목록을 보존합니다. 입력된 출처와 자동 연결은 별도로 표시합니다.

ETF NAV 자료 예:

```json
{
  "listing_id":"US:NYSEARCA:EXAMPLE:etf", "kind":"etf_nav",
  "period":"2026-09-30", "available_at":"2026-10-01T00:00:00Z",
  "data":{"source":"확인한 운용사 원문", "nav":100, "shares":1000000,
    "currency":"USD", "nav_date":"2026-09-30", "shares_date":"2026-09-30",
    "corporate_actions_verified":true, "share_adjustment_factor":1}
}
```

현재 목록의 실제 식별자로 바꿔야 합니다. 기업행동 확인을 생략하면 추정은 보류합니다. 실제 설정/환매는 `etf_reported_flow`와 `net_creation`·통화, 보유 구성은 `etf_holdings`와 기준일·구성 비중을 사용합니다. 자료의 첫 수집 시점은 시스템이 현재 시각으로 기록하며 입력한 과거 날짜로 소급하지 않습니다. API 입력은 10MB, 변경 요청은 클라이언트별 분당 30회로 제한합니다. 정적 GitHub Pages 결과에는 검색·계산 서버가 포함되지 않습니다.
