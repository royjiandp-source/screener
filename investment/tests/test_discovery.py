import pytest

@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv('INVEST_DB', str(tmp_path/'test.db'))
    from app.db import connect
    c=connect(); yield c; c.close()


def row(code='ABC',kind='stock'):
    return dict(id='US:NASDAQ:'+code+':'+kind,market='US',exchange='NASDAQ',code=code,ticker=code,name='Example',type=kind,currency='USD')


def test_catalog_atomic_and_search(con):
    from app.discovery.store import replace_catalog,classify,search
    first=replace_catalog(con,'US',[row()], 'Nasdaq','2026-10-01T00:00:00Z',True)
    classify(con,row()['id'],'Semiconductor','industry','profile','Makes chips','2026-10-01T00:00:00Z')
    replace_catalog(con,'US',[], 'Nasdaq','2026-10-02T00:00:00Z',False)
    r=search(con,'반도체','US')
    assert r['total']==1 and r['items'][0]['evidence'][0]['evidence']=='Makes chips'
    assert r['catalog_snapshots']['US']==first
    assert search(con,'%')['total']==0


def test_parse_nasdaq():
    from app.discovery.providers import parse_nasdaq
    rows=parse_nasdaq('Symbol|Security Name|ETF|Test Issue\nABC|Example|N|N\nETF|Fund|Y|N\nTEST|Test|N|Y\nFile Creation Time: now|||','NASDAQ')
    assert [(r['code'],r['type']) for r in rows]==[('ABC','stock'),('ETF','etf')]
    with pytest.raises(ValueError): parse_nasdaq('<html>error</html>','NASDAQ')


def test_signals_require_data():
    from app.signals.leadership import relative_strength,leadership
    assert relative_strength([100,120],[100,110])==pytest.approx((1.2/1.1-1)*100)
    assert leadership({}, {}, 20)['score'] is None


def test_etf_price_increase_not_flow():
    from app.flows.etf import estimate_creation_flow
    assert estimate_creation_flow({'nav':100,'shares':10,'currency':'USD','corporate_actions_verified':True},{'nav':120,'shares':10,'currency':'USD','corporate_actions_verified':True})['flow']==0
    assert estimate_creation_flow({'nav':100,'shares':None,'currency':'USD'},{'nav':120,'shares':10,'currency':'USD'})['flow'] is None


def test_institution_value_is_not_purchase():
    from app.flows.institutions import holdings_change
    r=holdings_change({'shares':100,'value':1000},{'shares':100,'value':1500})
    assert r=={'shares_change':0,'value_change':500}


def test_job_preserves_unrelated_and_cancels(con,monkeypatch):
    from app.discovery.store import replace_catalog,search
    from app.discovery.jobs import create_job,run_job,job_status,cancel_job
    from app import pipeline
    replace_catalog(con,'US',[row(),row('XYZ')],'Nasdaq','2026-10-01T00:00:00Z',True)
    monkeypatch.setattr(pipeline,'score_tickers',lambda c,t: {'scored':len(t)})
    job=create_job(con,[row()['id']])
    run_job(job)
    assert job_status(con,job)['completed']==1
    second=create_job(con,[row('XYZ')['id']])
    cancel_job(con,second); run_job(second)
    assert job_status(con,second)['state']=='cancelled'
    assert search(con,'')['total']==2


def test_discovery_api(con):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        assert client.get('/api/discovery/search',params={'query':'반도체'}).status_code==200
        assert client.post('/api/discovery/evaluate',json={'listing_ids':['nope']}).status_code==422
        assert client.get('/api/discovery/search',params={'market':'bad'}).status_code==422


def test_13f_parser():
    from app.flows.sec13f import parse_13f
    xml='<informationTable xmlns="urn:test"><infoTable><nameOfIssuer>ABC</nameOfIssuer><cusip>123456789</cusip><value>100</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable></informationTable>'
    rows=parse_13f(xml,{'value_multiplier':1000})
    assert rows[0]['value']==100000 and rows[0]['shares']==10
    with pytest.raises(ValueError): parse_13f('<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><x>&a;</x>',{})


def test_prices_use_same_dates_and_full_history():
    import pandas as pd
    from app.signals.prices import price_signals
    dates=pd.bdate_range('2025-01-01',periods=253)
    a=pd.DataFrame({'Close':range(100,353),'Volume':[1000]*253},index=dates)
    b=pd.DataFrame({'Close':[100]*253,'Volume':[1000]*253},index=dates)
    assert price_signals(a,b)['rs_12m']==pytest.approx(252)
    assert price_signals(a.iloc[-20:],b)['rs_12m'] is None


def test_import_catalog_requires_provenance(con):
    from app.discovery.imports import import_catalog
    with pytest.raises(ValueError):import_catalog(con,'US',[row()], '', '2026-10-01T00:00:00Z',True)
    sid=import_catalog(con,'US',[row()],'Reviewed Nasdaq export','2026-10-01T00:00:00Z',True)
    assert sid


def test_flow_import_rejects_unknown_and_future(con):
    from app.flows.ingest import ingest
    from app.discovery.store import replace_catalog
    replace_catalog(con,'US',[row('FUND','etf')],'Nasdaq','2026-10-01T00:00:00Z',True)
    with pytest.raises(ValueError):ingest(con,'bad','etf_nav','2026-01-01',{'source':'Issuer','nav':10,'shares':10,'currency':'USD'},'2026-01-02T00:00:00Z')
    with pytest.raises(ValueError):ingest(con,row('FUND','etf')['id'],'etf_nav','2026-01-01',{'source':'Issuer','nav':10,'shares':10,'currency':'USD'},'2099-01-02T00:00:00Z')


def test_bad_import_does_not_replace_catalog(con):
    from app.discovery.imports import import_catalog
    from app.discovery.store import search
    import_catalog(con,'US',[row()],'file','2026-01-01T00:00:00Z',True)
    bad={**row('BAD'),'themes':['AI']}
    with pytest.raises(ValueError):import_catalog(con,'US',[bad],'file','2026-01-02T00:00:00Z',True)
    assert search(con,'ABC')['total']==1


def test_korean_industry_alias_and_ai_word_boundaries(con):
    from app.discovery.store import replace_catalog,classify,search
    replace_catalog(con,'US',[row(),row('RAIL')],'Nasdaq','2026-01-01T00:00:00Z',True)
    classify(con,row()['id'],'반도체 제조업','industry','KRX','반도체 제조업','2026-01-01T00:00:00Z')
    classify(con,row('RAIL')['id'],'Retail','industry','profile','Retail sales','2026-01-01T00:00:00Z')
    assert search(con,'반도체')['total']==1
    assert search(con,'AI')['total']==0


def test_profile_job_uses_job_progress(con,monkeypatch):
    from app.discovery.store import replace_catalog
    from app.discovery.jobs import create_job,run_job,job_status
    from app.discovery import profiles
    replace_catalog(con,'US',[row()],'Nasdaq','2026-01-01T00:00:00Z',True)
    monkeypatch.setattr(profiles,'enrich_listing',lambda c,lid:{'status':'collected'})
    jid=create_job(con,[row()['id']],kind='profile')
    run_job(jid)
    assert job_status(con,jid)['completed']==1
    assert job_status(con,jid)['results'][0]['status']=='collected'


def test_13f_restated_and_options_separate():
    from app.flows.sec13f import resolve_filings
    original={'quarter':'2026-03-31','accession':'a','filed':'2026-04-01','amendment':'original','holdings':[{'cusip':'X','shares':100}]}
    replacement={**original,'accession':'b','filed':'2026-04-02','amendment':'restatement','holdings':[{'cusip':'X','shares':120}]}
    add={**original,'accession':'c','filed':'2026-04-03','amendment':'new_holdings','holdings':[{'cusip':'Y','shares':5}]}
    assert [h['shares'] for h in resolve_filings([original,replacement,add])['2026-03-31']['holdings']]==[120,5]


def test_catalog_ids_and_time_validated(con):
    from app.discovery.store import replace_catalog
    bad={**row(),'id':'another-market-id'}
    with pytest.raises(ValueError):replace_catalog(con,'US',[bad],'Nasdaq','2026-01-01T00:00:00Z',True)
    with pytest.raises(ValueError):replace_catalog(con,'US',[row()],'Nasdaq','2099-01-01T00:00:00Z',True)


def test_listing_period_return_no_duplicate_history():
    from app.signals.leadership import leadership
    assert leadership({'revenue_change':1,'margin_change':1},{'rs_3m':1,'rs_6m':1,'rs_12m':1,'rs_percentile':.5,'liquidity_percentile':.5},20)['score']==70


def test_duplicate_source_rows_same_identity():
    from app.discovery.providers import deduplicate
    assert len(deduplicate([row(),row()]))==1
    with pytest.raises(ValueError):deduplicate([row(),{**row(),'name':'Different issuer'}])



def test_sec_reporting_dates():
    from app.flows.sec13f import reporting_date
    assert reporting_date('03-31-2026')=='2026-03-31'
    assert reporting_date('03/31/2026')=='2026-03-31'
    assert reporting_date('2026-03-31')=='2026-03-31'


def test_cached_nonfinite_value_does_not_break_api(con):
    from app.db import loads,dumps
    assert loads('{"mom_1m":NaN}')['mom_1m'] is None
    assert loads(dumps({'mom_1m':float('nan')}))['mom_1m'] is None


def test_cancel_during_collection_is_preserved(con,monkeypatch):
    from app.discovery.store import replace_catalog
    from app.discovery.jobs import create_job,run_job,cancel_job,job_status
    from app import pipeline
    replace_catalog(con,'US',[row(),row('XYZ')],'Nasdaq','2026-01-01T00:00:00Z',True)
    jid=create_job(con,[row()['id'],row('XYZ')['id']]);calls=[]
    def score(c,t):
        calls.extend(t);cancel_job(c,jid)
    monkeypatch.setattr(pipeline,'score_tickers',score)
    run_job(jid)
    assert calls==['ABC']
    assert job_status(con,jid)['state']=='cancelled'


def test_generic_industry_words_do_not_classify_theme():
    from app.discovery.profiles import theme_hits
    assert theme_hits('The company designs and manufactures furniture and equipment.','Semiconductor',{'keywords':['semiconductor'],'industries':['Design','Equipment']})==[]


def test_supplement_availability_follows_supplement():
    from app.flows.sec13f import resolve_filings
    base={'quarter':'2026-06-30','accession':'a','filed':'2026-08-01','amendment':'original','holdings':[{'cusip':'X','shares':10}]}
    extra={**base,'accession':'b','filed':'2026-09-01','amendment':'new_holdings','holdings':[{'cusip':'Y','shares':20}]}
    resolved=resolve_filings([base,extra])['2026-06-30']
    assert resolved['filed']=='2026-09-01'


def test_selective_score_preserves_theme_results(con,monkeypatch):
    from app import pipeline
    from app.db import today,dumps
    con.execute('INSERT INTO theme_scores VALUES(?,?,?)',(today(),'Original',dumps({'flow_1m':5})));con.commit()
    monkeypatch.setattr(pipeline,'get_financials',lambda c,t:{})
    pipeline.score_tickers(con,['ABC'])
    assert con.execute('SELECT count(*) FROM theme_scores WHERE theme="Original"').fetchone()[0]==1


def test_unverified_etf_split_never_estimates_flow():
    from app.flows.etf import estimate_creation_flow
    r=estimate_creation_flow({'nav':100,'shares':10,'currency':'USD'},{'nav':50,'shares':20,'currency':'USD'})
    assert r['flow'] is None


def test_resume_atomically_enqueues_job(con):
    from app.discovery.store import replace_catalog
    from app.discovery.jobs import create_job,enqueue_resume,job_status
    replace_catalog(con,'US',[row()],'Nasdaq','2026-01-01T00:00:00Z',True)
    jid=create_job(con,[row()['id']])
    con.execute("UPDATE discovery_jobs SET state='interrupted' WHERE id=?",(jid,));con.commit()
    enqueue_resume(con,jid)
    assert job_status(con,jid)['state']=='queued'


def test_institution_changes_require_same_manager_and_complete_data():
    from app.flows.institutions import institution_changes
    records=[{'period':'2026-03-31','available_at':'2026-04-01T00:00:00Z','data':{'manager':'M','shares':100,'value':1000,'currency':'USD','complete':True}}, {'period':'2026-06-30','available_at':'2026-07-01T00:00:00Z','data':{'manager':'M','shares':100,'value':1500,'currency':'USD','complete':True}}]
    r=institution_changes(records)[0]
    assert r['shares_change']==0 and r['value_change']==500


def test_classification_history_preserves_changes(con):
    from app.discovery.store import replace_catalog,classify
    replace_catalog(con,'US',[row()],'Nasdaq','2026-01-01T00:00:00Z',True)
    classify(con,row()['id'],'AI','theme','review','First evidence','2026-01-01T00:00:00Z')
    classify(con,row()['id'],'AI','theme','review','Revised evidence','2026-01-02T00:00:00Z')
    assert con.execute('SELECT count(*) FROM classification_history').fetchone()[0]==2


def test_discovery_rejects_foreign_origin_and_oversize(con,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.discovery import api
    monkeypatch.setattr(api,'refresh_market',lambda c,m:{})
    with TestClient(app) as client:
        assert client.post('/api/discovery/refresh?market=US',headers={'Origin':'https://unrelated.example'}).status_code==403
        assert client.post('/api/discovery/import',content='{}',headers={'Content-Length':'20000000','Content-Type':'application/json'}).status_code==413


def test_relative_strength_uses_adjusted_fund_benchmarks():
    from app.signals.prices import BENCHMARKS,price_signals
    import pandas as pd
    assert BENCHMARKS=={'KR':'069500.KS','US':'SPY','SG':'ES3.SI'}
    frame=pd.DataFrame({'Close':[100.0]*254},index=pd.date_range('2025-01-01',periods=254))
    assert price_signals(frame,frame)['return_basis']=='dividend_and_split_adjusted_fund_proxy'
