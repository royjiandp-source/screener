"""Two independent screening tracks, with source/date-aware evidence."""
import pytest


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv('INVEST_DB', str(tmp_path / 'dashboard.db'))
    monkeypatch.setenv('DISABLE_SCHEDULER', '1')
    from app.db import connect
    c = connect()
    yield c
    c.close()


def listing(code='ABC', market='US', kind='stock'):
    exchange = {'US': 'NASDAQ', 'KR': 'KOSPI', 'SG': 'SGX', 'JP': 'TSE'}[market]
    suffix = {'US': '', 'KR': '.KS', 'SG': '.SI', 'JP': '.T'}[market]
    return dict(id=f'{market}:{exchange}:{code}:{kind}', market=market, exchange=exchange,
                code=code, ticker=code+suffix, name='Example '+code, type=kind,
                currency={'US': 'USD', 'KR': 'KRW', 'SG': 'SGD', 'JP': 'JPY'}[market])


def catalog(c, rows, market='US'):
    from app.discovery.store import replace_catalog, classify
    replace_catalog(c, market, rows, 'Exchange export', '2026-10-01T00:00:00Z', True)
    for row in rows:
        classify(c, row['id'], 'Semiconductor', 'industry', 'Issuer', 'Makes chips', '2026-10-01T00:00:00Z')


def score(c, row, total=80, day='2026-10-06', state='analyzable', version='value-v1'):
    from app.db import dumps
    data = dict(market=row['market'], total=total, score_version=version, analysis_status=state,
                metrics={'name': row['name'], 'currency': row['currency']}, parts={},
                valuation={'status': 'estimated', 'scenarios': {'base': {'safety_margin': 25, 'value': 100}}})
    c.execute('INSERT INTO stock_scores VALUES(?,?,?,?,?)', (day, row['ticker'], row['market'], total, dumps(data)))
    c.commit()


def observation(c, row, date='2026-10-06', rs3=3, rs6=6):
    from app.discovery.store import save_flow
    save_flow(c, row['id'], 'leadership', date, {
        'market': row['market'], 'period': date, 'source': 'Adjusted prices', 'benchmark': 'SPY',
        'signals': {'as_of': date, 'rs_3m': rs3, 'rs_6m': rs6, 'rs_12m': 8,
                    'return_3m': 5, 'return_6m': 10, 'turnover_change': .1,
                    'return_basis': 'dividend_and_split_adjusted_fund_proxy'},
        'trends': {'revenue_change': .1, 'margin_change': .02, 'cashflow_change': .2}})


def test_threshold_latest_active_types_and_pagination(con):
    from app.dashboard import build_report
    rows = [listing(c) for c in ['AAA', 'BBB', 'LOW', 'OLD', 'REVIEW', 'LEGACY']]+[listing('FUND', kind='etf')]
    catalog(con, rows)
    for row in rows:
        score(con, row, 70 if row['code']=='BBB' else 69.9 if row['code']=='LOW' else 90,
              state='review_required' if row['code']=='REVIEW' else 'analyzable',
              version='old' if row['code']=='LEGACY' else 'value-v1')
    score(con, listing('OLD'), None, day='2026-10-07', state='data_insufficient')
    score(con, listing('DELISTED'), 100)
    # Scores for markets outside KR/SG/US (e.g. old JP rows) never appear.
    con.execute('INSERT INTO stock_scores VALUES(?,?,?,?,?)', ('2026-10-08', '7203.T', 'JP', 100,
                '{"score_version":"value-v1","analysis_status":"analyzable","total":100}'))
    result = build_report(con, query='does not match', limit=1, min_score=70)
    assert result['observations']['total'] == 0
    assert result['value_candidates']['total'] == 2
    assert result['value_candidates']['items'][0]['listing']['code'] == 'AAA'
    second = build_report(con, value_offset=1, limit=1, min_score=70)
    assert second['value_candidates']['items'][0]['analysis']['total'] == 70
    assert build_report(con, min_score=91)['value_candidates']['total'] == 0
    assert set(result['coverage']) == {'KR', 'SG', 'US'}


def test_breadth_groups_are_same_market_sector_date(con):
    from app.dashboard import build_report
    a,b,old = [listing(k) for k in ['A','B','C']]
    catalog(con, [a,b,old])
    observation(con,a)
    observation(con,b,rs3=-3)
    observation(con,old,date='2026-10-05')
    sg=listing('D','SG');catalog(con,[sg],'SG');observation(con,sg)
    r=build_report(con, market='US')
    first=next(x for x in r['observations']['items'] if x['listing']['code']=='A')
    breadth=first['checks']['breadth']
    assert breadth['sample_3m']==2 and breadth['total_members']==3
    assert breadth['strong_3m']==.5 and breadth['strong_6m']==1
    assert first['checks']['demand']['status']=='unknown'
    assert first['checks']['estimates']['status']=='unknown'
    assert first['leadership']['score'] is None


def test_signal_imports_require_comparable_evidence(con):
    from app.flows.ingest import ingest
    from app.dashboard import build_report
    row=listing();catalog(con,[row])
    measurement={'metric':'orders','previous':100,'current':120,'unit':'units','product':'chips',
                 'previous_period':'2025-Q2','current_period':'2026-Q2'}
    data={'source':'Issuer report','measurements':[measurement]}
    ingest(con,row['id'],'demand','2026-10-01',data,'2026-10-02T00:00:00Z')
    estimates={'source':'Forecast provider','forecast_period':'2027-FY','currency':'USD',
               'previous':2,'current':3,'previous_observed_at':'2026-09-01T00:00:00Z'}
    ingest(con,row['id'],'earnings_estimates','2026-10-01',estimates,'2026-10-02T00:00:00Z')
    checks=build_report(con)['observations']['items'][0]['checks']
    assert checks['demand']['status']=='improving'
    assert checks['estimates']['change']==pytest.approx(.5)
    with pytest.raises(ValueError):
        ingest(con,row['id'],'demand','2026-10-01',{'source':'Issuer','measurements':[{**measurement,'unit':''}]},'2026-10-02T00:00:00Z')
    with pytest.raises(ValueError):
        ingest(con,row['id'],'earnings_estimates','2026-10-01',{**estimates,'previous_forecast_period':'2026-FY'},'2026-10-02T00:00:00Z')


def test_etf_holdings_link_preserves_actual_flow_semantics(con):
    from app.discovery.store import save_flow
    from app.dashboard import build_report
    a,fund=listing(),listing('FUND',kind='etf');catalog(con,[a,fund])
    save_flow(con,fund['id'],'etf_holdings','2026-10-01',{'source':'Issuer','holdings':[{'ticker':'ABC','weight':.1}]})
    save_flow(con,fund['id'],'etf_nav','2026-10-01',{'source':'Issuer','aum':1234,'currency':'USD'})
    r=build_report(con)['observations']['items'][0]
    assert r['etf_institution'][0]['kind']=='etf_holdings'
    assert r['etf_institution'][0]['listing_id']==fund['id']
    assert all(x.get('net_creation') is None for x in r['etf_institution'])


def test_market_job_ignores_sector_and_excludes_funds(con):
    from app.discovery.jobs import create_job,job_status
    from app.db import loads
    catalog(con,[listing(),listing('XYZ'),listing('FUND',kind='etf')])
    jid=create_job(con,search_query='no matching sector',market='US',kind='market_valuation')
    assert job_status(con,jid)['total']==2
    data=loads(con.execute('SELECT data FROM discovery_jobs WHERE id=?',(jid,)).fetchone()[0])
    assert {r['code'] for r in data['items']}=={'ABC','XYZ'}


def test_removed_logic_api_and_two_table_empty_ui(con):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import pipeline
    from app.web import render
    c=TestClient(app)
    assert c.get('/api/countries').status_code==404
    assert c.get('/api/macro').status_code==404
    assert c.get('/?market=JP').status_code==422
    assert c.get('/api/report?min_score=101').status_code==422
    r=c.get('/api/report').json()
    assert 'macro' not in r and 'countries' not in r
    assert not hasattr(pipeline,'get_macro') and not hasattr(pipeline,'country_table')
    assert 'macro' not in [x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    page=c.get('/').text
    assert page.count('data-result-table=')==2
    assert '국가별 가치투자' not in page and '미국 거시 참고 정보' not in page
    for label in ['수요 회복','이익 개선','예상 실적 상향','시장 대비 강세','상승의 확산','가격 부담']:
        assert label in page
    static=render(pipeline.report(con),static=True)
    assert static.count('data-result-table=')==2 and 'fetch(' not in static
    assert '<button' not in static


def test_daily_score_uses_catalog_and_never_seed_universe(con,monkeypatch):
    from app import pipeline
    catalog(con,[listing('CATALOG')])
    requested=[]
    monkeypatch.setattr(pipeline,'get_financials',lambda c,ts: requested.extend(ts) or {})
    pipeline.run_score(con,markets=('US',))
    assert requested==['CATALOG']


def test_failed_refresh_preserves_previous_score_and_job_reports_failure(con,monkeypatch):
    from app import pipeline
    from app.discovery.jobs import create_job,run_job,job_status
    row=listing();catalog(con,[row]);score(con,row)
    monkeypatch.setattr(pipeline,'get_financials',lambda c,ts:{'ABC':{'fetch_error':True}})
    jid=create_job(con,market='US',kind='market_valuation');run_job(jid)
    assert job_status(con,jid)['failed']==1
    assert pipeline.stocks(con,market='US')[0]['day']=='2026-10-06'
    assert pipeline.stocks(con,market='US')[0]['total']==80


def test_partial_source_import_is_searchable_without_claiming_full_catalog(con):
    from app.discovery.imports import import_catalog
    from app.dashboard import build_report
    import_catalog(con,'SG',[listing('ABC','SG')],'Reviewed SGX rows','2026-10-01T00:00:00Z',False)
    report=build_report(con,market='SG')
    assert report['observations']['total']==1
    assert report['coverage']['SG']['complete'] is False
    assert report['coverage']['SG']['source']=='Reviewed SGX rows'


def test_sector_search_uses_matched_theme_instead_of_unrelated_first_industry(con):
    from app.discovery.store import classify
    from app.dashboard import build_report
    a,b=listing('A'),listing('B');catalog(con,[a,b])
    for row in (a,b):
        classify(con,row['id'],'AI Infrastructure','theme','Issuer','AI server business','2026-10-01T00:00:00Z')
        observation(con,row)
    r=build_report(con,query='AI')
    assert all(row['sector']=='AI Infrastructure' for row in r['observations']['items'])


def test_fund_search_has_explicit_pagination(con):
    from fastapi.testclient import TestClient
    from app.main import app
    catalog(con,[listing('FUND1',kind='etf'),listing('FUND2',kind='etf')])
    r=TestClient(app).get('/api/discovery/funds?limit=1&offset=1').json()
    assert r['total']==2 and len(r['items'])==1
    assert r['items'][0]['listing']['ticker']=='FUND2'


def test_unclassified_companies_have_no_invented_sector_breadth(con):
    from app.discovery.store import replace_catalog
    from app.dashboard import build_report
    a,b=listing('A'),listing('B')
    replace_catalog(con,'US',[a,b],'Exchange','2026-10-01T00:00:00Z',True)
    observation(con,a,rs3=10);observation(con,b,rs3=-10)
    for row in build_report(con)['observations']['items']:
        assert row['checks']['breadth']['strong_3m'] is None
        assert row['checks']['breadth']['total_members']==0


def test_catalog_failure_is_visible_even_when_prior_catalog_is_retained(con):
    from app.discovery.store import set_health
    from app.pipeline import report
    from app.web import render
    catalog(con,[listing()]);set_health(con,'US',{'status':'connection_unavailable'})
    assert '갱신 실패' in render(report(con))
    assert '이전 목록' in render(report(con))


def test_static_export_includes_every_high_score_candidate(con):
    from app.pipeline import static_report
    from app.web import render
    rows=[listing(f'COMPANY{i:03}') for i in range(51)];catalog(con,rows)
    for row in rows:score(con,row)
    r=static_report(con)
    assert len(r['value_candidates']['items'])==51
    page=render(r,static=True)
    assert 'COMPANY050' in page


def test_breadth_can_be_weakening(con):
    from app.dashboard import build_report
    rows = [listing(c) for c in ['W1', 'W2', 'W3']]
    catalog(con, rows)
    from app.discovery.store import classify
    for r in rows:
        classify(con, r['id'], 'Weak sector', 'industry', 'Exchange', 'Weak sector', '2026-10-01T00:00:00Z')
        observation(con, r, rs3=-5, rs6=-8)
    item = build_report(con)['observations']['items'][0]
    assert item['checks']['breadth']['status'] == 'weakening'


def test_api_themes_removed(con):
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get('/api/themes').status_code == 404


def test_one_bad_etf_row_keeps_other_holdings(con):
    import pandas as pd
    from app.flows.providers import refresh_etf
    from app.discovery.store import flows
    fund = listing('FND', kind='etf'); catalog(con, [fund])
    class T:
        class funds_data:
            top_holdings = pd.DataFrame({'Name': ['A', 'B'], 'Holding Percent': [None, 0.1]}, index=['AAA', 'BBB'])
    refresh_etf(con, fund, T(), {'navPrice': 10, 'sharesOutstanding': 100, 'currency': 'USD'})
    saved = flows(con, fund['id'], 'etf_holdings')[0]['data']['holdings']
    assert [h['ticker'] for h in saved] == ['BBB']
