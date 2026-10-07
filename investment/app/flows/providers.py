"""Optional fund/investor providers preserve provenance and missing states."""
from ..discovery.store import save_flow,flows
from ..filings.common import utc
from ..valuation import finite
from .etf import estimate_creation_flow


def refresh_etf(con,item,ticker,info):
    nav=info.get('navPrice');shares=info.get('sharesOutstanding')
    stamp=utc();current={'nav':nav if finite(nav) else None,'shares':shares if finite(shares) else None,'currency':info.get('currency'),'aum':info.get('totalAssets'),'source':'Yahoo Finance auxiliary fund quote','observed_at':stamp,'basis':'current_quote; NAV/share dates not independently verified','unresolved_corporate_action':True}
    # Auxiliary quote dates are insufficient to establish net creation: hold estimate.
    previous=flows(con,item['id'],'etf_nav')
    if previous:current['creation_estimate']=estimate_creation_flow(previous[0]['data'],current)
    save_flow(con,item['id'],'etf_nav',stamp[:10],current)
    holdings=[]
    try:
        df=ticker.funds_data.top_holdings
        for code,r in df.iterrows():holdings.append({'ticker':str(code),'name':r.get('Name'),'weight':r.get('Holding Percent')})
    except Exception:pass
    if holdings:save_flow(con,item['id'],'etf_holdings',stamp[:10],{'source':'Yahoo Finance fund holdings (auxiliary)','holdings':holdings,'coverage':'top_holdings_only','holdings_as_of':None,'note':'수집 시각은 실제 구성 기준일과 다릅니다.'})
    return {'status':'collected_partial','nav_status':'auxiliary_unverified_dates','holdings':len(holdings),'creation_flow':None}


def refresh_kr_investors(con,item,start,end):
    import os,contextlib,io
    if not os.environ.get('KRX_ID') or not os.environ.get('KRX_PW'):raise ValueError('KRX credentials required')
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        from pykrx import stock
    frame=stock.get_market_trading_value_by_date(start.replace('-',''),end.replace('-',''),item['code'],on='순매수',detail=True)
    if frame.empty:raise ValueError('No investor data returned')
    rows=[]
    for date,r in frame.iterrows():
        rows.append({'date':str(date.date()),'investors':{str(k):float(v) for k,v in r.items() if finite(v)},'currency':'KRW','measure':'net_trading_value'})
    data={'source':'KRX via pykrx','start':start,'end':end,'rows':rows,'currency':'KRW','measure':'investor_net_purchase','coverage':'provider investor classifications'}
    save_flow(con,item['id'],'institution_trades',end,data)
    return {'status':'captured','days':len(rows)}
