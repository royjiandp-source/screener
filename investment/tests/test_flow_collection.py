import pandas as pd
from test_dashboard import con, catalog, listing


def test_foreign_etf_resolves_unique_kr_code(con):
    from app.flows.collection import resolve_holding
    row=listing('005930','KR');catalog(con,[row],'KR')
    r=resolve_holding(con,'005930.KQ')
    assert r['listing_id']==row['id'] and r['ticker']=='005930.KS'
    assert r['provider_ticker']=='005930.KQ'
    assert resolve_holding(con,'005931.KQ') is None


def test_auxiliary_holders_keep_report_date_and_exclude_unverified_value(con):
    from app.flows.collection import refresh_holders
    from app.discovery.store import flows
    row=listing();catalog(con,[row])
    class Ticker:
        institutional_holders=pd.DataFrame([{'Holder':'Manager','Date Reported':pd.Timestamp('2026-06-30'),'Shares':100,'pctHeld':.1,'Value':999}, {'Holder':'Future','Date Reported':pd.Timestamp('2099-06-30'),'Shares':100}])
    r=refresh_holders(con,row,Ticker(),{'currency':'USD'})
    assert r['holders']==1
    f=flows(con,row['id'],'institution_holdings')[0]
    assert f['period']=='2026-06-30'
    assert f['data']['shares']==100 and f['data']['value'] is None
    assert f['data']['coverage']=='auxiliary_reported_holders'


def test_cross_market_etf_links_by_resolved_listing_id(con):
    from app.dashboard import build_report
    from app.discovery.store import save_flow
    stock=listing('005930','KR');fund=listing('EWY',kind='etf')
    catalog(con,[stock],'KR');catalog(con,[fund])
    save_flow(con,fund['id'],'etf_holdings','2026-10-08',{'source':'Provider','holdings':[{'ticker':stock['ticker'],'listing_id':stock['id'],'weight':.2}]})
    r=build_report(con,market='KR')['observations']['items'][0]
    assert r['etf_institution'][0]['fund']=='EWY'
    assert r['etf_institution'][0]['weight']==.2


def test_flow_display_keeps_multiple_managers_and_unverified_fund_date():
    from app.web import flow_summary
    records=[dict(kind='institution_holdings',period='2026-06-30',data={'manager':m,'shares':100,'ownership_fraction':.1,'coverage':'auxiliary_reported_holders'}) for m in ['Manager A','Manager B']]
    records.append(dict(kind='etf_holdings',fund='SPY',weight=.1,period='2026-10-08',data={'coverage':'top_holdings_only'}))
    text=flow_summary(records)
    assert 'Manager A' in text and 'Manager B' in text
    assert '100주' in text and '기관 공개 보유 (보조)' in text
    assert '구성 기준일 미확인' in text
