# 거래소 전체 검색과 자금 흐름 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if selected by the user. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 거래소 전체 목록에서 섹터를 검색·평가하고, 근거를 확인할 수 있는 주도주 후보·ETF·기관 분석을 제공한다.

**Architecture:** 시장 목록, 섹터 분류, 검색 평가 작업, 가격·펀드·기관 자료를 독립 저장한다. 현재 가치평가 엔진을 재사용하고 국가별 공급자의 연결 상태·분류 커버리지를 공개한다. SQLite 작업 큐와 제한된 작업자 한 개로 시작해 기존 로컬 운영 방식에 맞춘다.

**Tech Stack:** Python, FastAPI, SQLite, pandas, requests, yfinance, 기존 HTML/JavaScript. 공식 Excel 목록에 필요한 openpyxl/xlrd만 추가한다. 한국 자료 연결에 pykrx가 필요한 경우 설치 전 현재 공식 경로와 라이브러리 호환성을 검증한다.

**Spec:** `docs/superpowers/specs/2026-10-07-sector-discovery-design.md` (사용자 승인됨)

## Global Constraints

- 대상 시장은 KR·US·JP·TW·HK·SG다. 시장 목록 확보와 테마 분류 완료를 구분한다.
- 공시·자료 기준일, 공개 가능 시점, 첫 수집 시점, 원본 출처를 보존한다.
- 미분류·결측·미지원·연결 실패를 구별하고 자료를 꾸며 채우지 않는다.
- ETF에 기업 FCFF DCF를 적용하지 않는다. ETF 거래대금·투자자 순매수·설정/환매는 별개다.
- 미국 13F는 분기 보유 변화이며 실시간 순매수로 표시하지 않는다.
- 신규 평가가 기존 다른 종목·국가의 결과를 삭제하지 않는다.
- 검색 결과 전체 평가는 묶음 처리하며 진행률·취소를 지원한다. 상위 N개로 조용히 제한하지 않는다.
- 유료 계약·계정·데이터 구독을 자동으로 만들지 않는다. 키를 출력·커밋하지 않는다.
- 내부자 거래·공매도·포트폴리오 최적화는 이 계획의 범위가 아니다.

## Review Focus

1. 같은 티커 문자열의 다른 시장, ADR·우선주·ETF가 섞여도 종목을 잘못 연결하지 않는다 (Task 1).
2. 과거/부분 목록 또는 HTML 오류가 내려와도 정상 목록을 삭제하지 않는다 (Task 2).
3. 검색 중 목록 갱신이나 중복 클릭이 있어도 선택한 전체 결과를 누락 없이 평가한다 (Task 3).
4. 배당·분할·환율·거래 휴일 차이로 거짓 상대강도나 ETF 유입을 만들지 않는다 (Tasks 4–5).
5. 정정 13F와 불명확한 CUSIP이 중복 또는 잘못된 기관 보유 증가를 만들지 않는다 (Task 6).

실행 공통 명령: 루트에서 `investment/.venv/bin/python -m pytest -q`. 각 작업은 아래 테스트를 먼저 추가해 실패 확인 → 구현 → 해당 테스트 통과 → 변경 파일 검토 순서다. 사용자 변경인 `.github/workflows/screener.yml`을 일괄 커밋에 섞지 않는다.

## Task 1: 종목 목록·분류·근거 저장

**Files:** Create `investment/app/discovery/__init__.py`, `models.py`, `store.py`, `tests/test_discovery_store.py`; modify `investment/app/db.py`.

**Interfaces:** `replace_catalog(con, market, rows, source, observed_at, complete)`는 새 snapshot id를 반환한다. `classify(con, listing_id, label, kind, source, evidence, available_at)`는 근거를 추가한다. `search(con, query, market=None, offset=0, limit=50)`는 `items,total,catalog_snapshot,classified,total_listings,status`를 반환한다. listing id는 `market:exchange:code:instrument_type`다.

- [ ] 아래 테스트를 먼저 작성하고 실패 확인한다.

```python
def test_incomplete_catalog_keeps_previous(con):
    first = replace_catalog(con, 'US', [us_stock], 'Nasdaq', stamp, True)
    replace_catalog(con, 'US', [], 'Nasdaq', stamp2, False)
    assert search(con, '반도체')['catalog_snapshot'] == first

def test_market_identity_and_evidence(con):
    replace_catalog(con, 'US', [us_stock, us_etf], 'Nasdaq', stamp, True)
    replace_catalog(con, 'SG', [sg_stock_same_code], 'SGX', stamp, True)
    classify(con, us_stock['id'], 'Semiconductor', 'industry', 'profile', 'chip design', stamp)
    r = search(con, '반도체', market='US')
    assert r['total'] == 1
    assert r['items'][0]['id'] == us_stock['id']
    assert r['items'][0]['evidence']
```

- [ ] 모델은 필수 market/exchange/code/ticker/name/type/currency/source/date를 검증한다. stock/ETF/REIT/ADR/preferred/other를 별도 enum으로 둔다. 이름을 종목 ID로 쓰지 않는다.
- [ ] 테이블 `catalog_snapshots`, `listings`, `listing_classifications`, `classification_aliases`, `source_health`를 추가한다. snapshot에는 complete/count/hash/raw/source/observed_at를 저장한다. 성공한 완전 snapshot만 active를 교체하고 미존재 listing에는 inactive 시점을 기록한다. 분류와 목록 이력은 삭제하지 않는다.
- [ ] 검색은 파라미터 바인딩과 escaped LIKE를 사용한다. 반도체/semiconductor, AI/인공지능/artificial intelligence 별칭을 추가하며 단어 경계를 사용한다. 기존 themes.json 근거는 curated_theme로 수입한다. 검색 전체 수와 분류 커버리지를 계산한다.
- [ ] 실패한 snapshot, 특수문자 `%_`, 같은 코드 다른 시장, ETF 혼입, 중복 분류 테스트를 실행한다.

## Task 2: 6개 시장 목록 연결과 분류 확장

**Files:** Create `investment/app/discovery/providers/{__init__,nasdaq,krx,jpx,taiwan,hkex,sgx}.py`, `refresh.py`, `profiles.py`, `tests/test_catalog_providers.py`; modify `investment/requirements.txt`, `.env.example`, `README.md`.

**Interfaces:** 각 provider `fetch_catalog(http)->{rows,raw,source,complete,as_of}`; `refresh_market(con,market)->status`; `enrich_profiles(con,listing_ids)->counts`. 인증 설정은 각 provider에만 전달한다.

- [ ] 공식 목록 fixture를 저장하고 parser의 실제 헤더와 유형을 고정한다.

```python
def test_nasdaq_excludes_test_issues():
    rows = parse_nasdaq('Symbol|Security Name|ETF|Test Issue\nABC|Example|N|N\nTEST|Test|N|Y\nFile Creation Time: 20261007|||')
    assert [r['code'] for r in rows] == ['ABC']

def test_html_error_does_not_become_catalog():
    with pytest.raises(ValueError):
        parse_nasdaq('<html>Access denied</html>')
```

- [ ] Nasdaq official `dynamic/symdir/nasdaqlisted.txt` + `otherlisted.txt`를 사용한다. 다른 거래소 코드를 보존하고 테스트 종목 및 footer를 제외한다. ETF Y는 별도 유형이다.
- [ ] JPX 공식 상장 목록 페이지의 실제 Excel 링크를 확인하고 다운로드한다. TWSE `openapi.twse.com.tw/v1/opendata/t187ap03_L`, TPEx 공식 OpenAPI 목록의 실제 schema를 확인한다. 한국 KRX, 홍콩 HKEX full securities list, SGX 공식 목록은 현재 공개 경로·인증·이용조건을 확인한 뒤 fixture와 parser를 함께 만든다. 경로를 추측해 성공 처리하지 않는다.
- [ ] 소스가 인증/계약을 요구하면 해당 시장 `configuration_required`와 필요한 설정 이름을 저장한다. 동일 모델의 검증된 CSV import를 추가해 출처/기준일/완전 여부를 필수로 받는다. CSV import만으로 공식 live connection이라 표시하지 않는다.
- [ ] profiles는 공식 업종이 있으면 보존하고 보조 사업 설명을 별도 출처로 저장한다. AI 등 테마는 검토된 keyword 규칙의 근거 문장을 함께 보존한다. business text 없이 종목 이름만 매칭해 테마 확정하지 않는다. 캐시와 per-source 속도 제한을 적용한다.
- [ ] 시장별 목록 수·분류 수·미분류·갱신일·오류 상태를 조회해 실제 연결을 확인한다. 실제 자료에 대한 테스트는 네트워크 없는 회귀 테스트와 분리한다.

## Task 3: 섹터 검색과 선택/전체 평가 작업

**Files:** Create `investment/app/discovery/jobs.py`, `api.py`, `tests/test_discovery_jobs.py`; modify `pipeline.py`, `main.py`, `web.py`, `db.py`.

**Interfaces:** `create_job(con, listing_ids=None, search_snapshot=None)->job_id`; `run_job(job_id)->None`; `cancel_job(con,job_id)`; `score_tickers(con,tickers)->results`. GET `/api/discovery/search`, POST `/api/discovery/refresh`, POST `/api/discovery/evaluate`, GET `/api/discovery/jobs/{id}`, POST `/api/discovery/jobs/{id}/cancel`.

- [ ] 작업 스냅샷과 다른 결과 보존 테스트를 먼저 작성한다.

```python
def test_search_job_is_frozen_and_preserves_other_stock(con):
    job = create_job(con, listing_ids=[a['id'], b['id']])
    score_existing(con, unrelated)
    run_job(job)
    assert job_status(con, job)['completed'] == 2
    assert latest_result(con, unrelated['id']) is not None

def test_etf_never_calls_company_dcf(con, fake_financials):
    job = create_job(con, listing_ids=[etf['id']])
    run_job(job)
    assert fake_financials.calls == []
    assert job_results(con, job)[0]['status'] == 'fund_analysis'
```

- [ ] `run_score`에서 종목별 평가를 `score_tickers`로 추출한다. 기존 market-wide 삭제는 검색 평가에서 사용하지 않는다. 결과 최신 조회도 시장별 날짜가 아닌 종목별 최신 자료를 가져오도록 바꾸고 기존 tests를 갱신한다.
- [ ] 검색 결과 ID를 작업 생성 때 고정하고 jobs/job_items로 저장한다. 한 worker, 10개 묶음, 각 종목 완료 즉시 commit, ticker cache 재사용, 체크포인트 재시작, 취소는 다음 종목 시작 전에 확인한다. 종목 오류는 다른 종목을 막지 않는다. 시작 시 오래된 running 작업은 interrupted로 표시한다.
- [ ] 입력 ID는 저장된 목록에서 검증하며 최대 request payload와 페이지 크기는 제한하되 전체 검색 결과 평가는 서버 쪽 snapshot으로 만든다. 중복 클릭은 idempotency key로 같은 작업을 반환한다. SEC/DART는 해당 listing identifier를 해결한 종목만 연결한다.
- [ ] 화면에 검색창/국가/결과 분류근거/checkbox/선택 평가/전체 평가/상태/취소/점수/안전마진/보류 사유를 추가한다. JS는 textContent와 DOM 노드로 결과를 구성해 공급자 텍스트의 HTML 실행을 막는다. 정적 export에서는 검색과 실행 버튼을 제거한다.
- [ ] 여러 국가·검색 중 refresh·부분 오류·취소·브라우저 새로고침 후 상태 보존·기존 결과 보존을 검증한다.

## Task 4: 주도주·섹터 관찰 후보

**Files:** Create `investment/app/signals/{__init__,prices,leadership}.py`, `tests/test_leadership.py`; modify `discovery/api.py`, `web.py`, `db.py`.

**Interfaces:** `relative_strength(asset,benchmark,horizon)->float|None`; `leadership(metrics,price_signals,coverage)->dict`; `sector_breadth(rows)->dict`. `/api/signals/leadership?market=&sector=`는 근거와 자료 기준일을 포함한다.

- [ ] 같은 기간 비교, 불충분 자료 보류 테스트를 추가한다.

```python
def test_relative_strength_matched_days():
    assert relative_strength([100,120], [100,110], 1) == pytest.approx((1.2/1.1-1)*100)

def test_missing_series_is_not_neutral_score():
    r = leadership({}, {}, {'classified': 5, 'total': 20})
    assert r['score'] is None
    assert r['missing']
```

- [ ] 배당·분할 조정 가격을 표준화해 저장한다. 시장별 대표 benchmark를 명시하고 날짜 교집합 및 필요한 lookback을 검증한다. 환산 없는 시장별 수익률만 비교한다. 63/126/252 거래일은 실제 관측 일수 기준이며 신규 상장은 부족 기간을 제외한다.
- [ ] 초기 관찰 지표는 RS 3/6/12개월 평균 rank(40), 동일 회계기간 매출·영업이익률·현금흐름 개선(40), 실제 거래대금/유동성 개선(20)이다. 공통 비교시장 표본과 가중치를 반환한다. 상대강도와 최소 2개 실적 항목 및 비교표본 20개가 없으면 score=None. 결측 항목은 missing과 weight coverage로 표시한다. 수주·전망 데이터는 확인된 원문근거만 보조로 보여주고 자동 점수에 억지 포함하지 않는다.
- [ ] 섹터별 RS 양수 기업 비율과 표본/전체를 계산한다. 가치점수·안전마진·역산 성장률은 별도 컬럼이다. 가격에 선반영된 기대와 신호의 방향이 다를 수 있음을 근거로 보여준다.
- [ ] 미래 시점 데이터 혼입, 조정되지 않은 분할 자료 거절, 낮은 거래대금, 신규 상장, 표본 부족을 검증한다. 예측 확률·확정 주도주라고 표시하지 않는다.

## Task 5: ETF 구성과 자금 흐름

**Files:** Create `investment/app/flows/{__init__,etf,providers}.py`, `tests/test_etf_flows.py`; modify `db.py`, `discovery/api.py`, `web.py`, `README.md`.

**Interfaces:** `estimate_creation_flow(previous,current)->dict`; `store_etf_snapshot(con,row)`; `etf_detail(con,listing_id,as_of=None)->dict`. snapshot은 NAV,발행좌수,AUM,통화,기간,분할계수,출처,공개/관측 시점을 가진다.

- [ ] 가격상승을 자금유입과 구분하는 테스트를 먼저 작성한다.

```python
def test_price_change_is_not_creation():
    r = estimate_creation_flow({'nav':100,'shares':10,'currency':'USD'}, {'nav':120,'shares':10,'currency':'USD'})
    assert r['flow'] == 0

def test_missing_shares_is_not_zero():
    r = estimate_creation_flow({'nav':100,'shares':None,'currency':'USD'}, {'nav':120,'shares':10,'currency':'USD'})
    assert r['flow'] is None
```

- [ ] 한국 ETF 목록/거래 자료와 미국 issuer의 공식 holdings/NAV/shares 파일을 실제 schema 기반 adapter로 연결한다. issuer별 adapter registry를 둬 다른 issuer URL을 추측하지 않는다. JP/TW/HK/SG는 실제 공개 ETF 목록/issuer 자료 확인 후 별도 adapter를 등록하고 미연결 상태를 제공한다.
- [ ] reported net creation/redemption을 우선한다. 두 snapshot의 shares가 분할조정 가능하고 통화·기준일이 맞을 때만 `current_nav*(current_shares-adjusted_previous_shares)`를 estimated_flow로 제공한다. AUM 차이는 flow로 쓰지 않는다. 분배금·병합 이벤트를 확인할 수 없으면 ambiguous_corporate_action으로 보류한다.
- [ ] 구성 종목과 가중치의 기준일을 저장하고 확정 identifier로만 연결한다. 합계와 중복을 검증한다. 거래대금/투자자 순매수/펀드 설정환매에 각각 이름·단위·기간·출처를 붙인다.
- [ ] split·통화변경·기간불일치·실제0/결측·holdings stale 사례를 테스트하고 ETF 상세화면과 섹터 보조근거를 연결한다.

## Task 6: 기관 순매수와 13F 보유 변화

**Files:** Create `investment/app/flows/{institutions,sec13f,krx_investors}.py`, `tests/test_institutions.py`; modify `db.py`, `discovery/api.py`, `web.py`, `.env.example`.

**Interfaces:** `holdings_change(previous,current)->dict`; `parse_13f(xml,metadata)->rows`; `institution_detail(con,listing_id,as_of=None)->dict`; `refresh_institutions(con,market)->status`.

- [ ] 실제 거래와 보유 변화 구분, 정정/매핑 테스트를 먼저 작성한다.

```python
def test_price_change_not_purchase():
    r = holdings_change({'shares':100,'value':1000}, {'shares':100,'value':1500})
    assert r['shares_change'] == 0
    assert r['value_change'] == 500

def test_unmapped_cusip_not_attached(con):
    store_holding(con, cusip='UNKNOWN', shares=100, quarter='2026-06-30')
    assert institution_detail(con, stock_id)['holdings'] == []
```

- [ ] 한국 KRX 기관합계/세부 투자자 거래를 원래 분류·통화·매수/매도/순매수·기간과 함께 저장한다. 정상 휴일 빈 자료와 source error를 구분하며 공개 시점 없이 미래 과거조회에 쓰지 않는다.
- [ ] SEC 연락처 설정이 있을 때 configured manager CIK 목록의 submissions와 공식 information table XML을 읽는다. XML 외부 엔티티를 차단한다. accession,form,quarter,filing_date,amendment flag,shares,value 단위,put/call,other manager를 보존한다. 공시 시기별 value 단위는 문서에서 확인해 schema별 표준화한다.
- [ ] 동일분기 최신 정정의 restatement/replacement와 supplemental 추가 자료를 구분한다. 중복 manager 지분을 전체 기관으로 합산하지 않는다. manager별 변화와 선택 관리자 coverage를 제공한다. 옵션과 주식 수를 합치지 않는다. 신규/청산은 같은 manager의 완전한 양분기 자료가 있을 때만 판단한다.
- [ ] CUSIP 연결은 출처가 확인된 mapping만 쓰며 이름의 퍼지 매칭은 사용하지 않는다. JP/TW/HK/SG는 확인된 공식 투자자별 거래/보유 자료 adapter를 등록하고 없으면 unsupported로 표시한다.
- [ ] late filing·amendment·옵션·복수 관리자·불완전 전분기·키없는 상태·시점 제한을 검증한다. 화면 명칭은 KR 기관 순매수와 US 분기 보유 변화로 분리한다.

## Task 7: 통합 검증과 운영

**Files:** Create `investment/tests/test_discovery_api.py`; modify `README.md`, `main.py`, `.github/workflows/screener.yml` 중 테스트에 필요한 부분만 검토한다.

- [ ] 전체 흐름 테스트를 추가한다.

```python
def test_sector_to_evaluation_and_evidence(client, populated_catalog):
    found = client.get('/api/discovery/search', params={'query':'반도체','market':'KR'}).json()
    job = client.post('/api/discovery/evaluate', json={'listing_ids':[x['id'] for x in found['items']]}).json()
    result = wait_test_worker(job['id'])
    assert result['state'] == 'completed'
    assert result['completed'] == found['total']
    assert all('source' in r for r in result['results'])
```

- [ ] 실행 명령, 환경 설정명, 분류규칙 검토, source별 연결상태, 자료 지연, ETFflow 추정 산식, 13F 관리자 범위, 정적 export 제한을 문서화한다. 거래소 전체 수집 실패/부분분류 상태를 UI에서 확인한다.
- [ ] 전체 pytest, diff whitespace 검증, 실제 공급자 소수 샘플 연결, 검색→평가→상세/취소 UI 확인을 실행한다. live 수집은 모든 종목 valuation으로 무조건 확장하지 않고 검색 작업으로 실행한다.
- [ ] 신규 실행과 검색은 로컬에서 확인한다. GitHub Pages는 계산 서버가 아니므로 정적 결과만 가능하고, 배포는 기존 default branch 보호를 유지한다. push/배포 여부는 별도 보고한다.
- [ ] 전체 변경을 새로운 관점으로 리뷰하고 실패를 수정한다. 6개 시장별 목록/분류/ETF/기관의 구현 및 실연결 현황표를 최종 결과로 제공한다. 미연결 공급자의 인증·계약 제약은 구체적으로 보고하며 전체 완료로 주장하지 않는다.

## 자체 검토

명세의 검색·가치평가·주도주·ETF·기관·시점 보존·시장별 상태를 Tasks 1–7에 대응했다. 시장별 라이브 연결은 소스 조사와 테스트를 각각 Task 2/5/6에 포함했으며 CSV 경로만으로 live 연결을 주장하지 않는다. 원천 데이터 제약은 구현으로 없앨 수 없으므로 해당 상태와 필수 설정을 화면에 노출한다. 인터페이스명과 데이터 단위는 task마다 명시했고 최신조회 변경은 Task 3의 회귀 검증에 포함했다.
