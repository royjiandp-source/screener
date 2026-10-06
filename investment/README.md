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
