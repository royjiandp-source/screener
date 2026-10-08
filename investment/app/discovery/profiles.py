"""Business evidence and comparable market signals from explicitly labelled auxiliary data."""
import math
import re
import yfinance as yf
from ..db import loads,load_themes
from ..filings.common import utc
from .store import init,classify,save_flow,flows
from ..signals.prices import BENCHMARKS,price_signals
from ..signals.leadership import leadership


def theme_hits(summary,label,meta):
    # Generic industry names such as Design/Equipment cannot establish a theme.
    keywords=[label,*meta.get('keywords',[])]
    return [k for k in keywords if len(k)>=3 and (re.search(r'(?<![a-z0-9])'+re.escape(k.casefold())+r's?(?![a-z0-9])',summary.casefold()) if k.isascii() else k.casefold() in summary.casefold())]


def enrich_listing(con,lid):
    init(con);row=con.execute('SELECT data FROM listings WHERE id=? AND active=1',(lid,)).fetchone()
    if not row:raise ValueError('Listing not found')
    item=loads(row[0],{});ticker=yf.Ticker(item['ticker']);info=ticker.info
    summary=info.get('longBusinessSummary') or ''
    source='Yahoo Finance auxiliary profile'
    for key in ('sector','industry'):
        if info.get(key):classify(con,lid,info[key],'industry',source,info[key],utc())
    for label,meta in load_themes()['themes'].items():
        hits=theme_hits(summary,label,meta)
        if hits:classify(con,lid,label,'theme',source,'Business description keywords: '+', '.join(hits)+' · '+summary,utc())
    if item['type']=='etf':
        from ..flows.providers import refresh_etf
        return refresh_etf(con,item,ticker,info)
    prices=ticker.history(period='2y',auto_adjust=True)
    benchmark=yf.Ticker(BENCHMARKS[item['market']]).history(period='2y',auto_adjust=True)
    # Local calendar dates align across timezones; retain no intraday comparisons.
    for frame in (prices,benchmark):
        if getattr(frame.index,'tz',None):frame.index=frame.index.tz_localize(None).normalize()
    signals=price_signals(prices,benchmark)
    trends={}
    inc=ticker.income_stmt;cf=ticker.cashflow
    def pair(frame,name):
        if name not in frame.index:return None
        cols=sorted(frame.columns,reverse=True)
        if len(cols)<2:return None
        a,b=frame.loc[name,cols[0]],frame.loc[name,cols[1]]
        if not math.isfinite(float(a)) or not math.isfinite(float(b)):return None
        return float(a),float(b),str(cols[0].date()),str(cols[1].date())
    revenue=pair(inc,'Total Revenue');op=pair(inc,'Operating Income');cash=pair(cf,'Operating Cash Flow')
    if revenue and revenue[1]>0:trends['revenue_change']=revenue[0]/revenue[1]-1
    if revenue and op and revenue[2:]==op[2:] and revenue[0]>0 and revenue[1]>0:trends['margin_change']=op[0]/revenue[0]-op[1]/revenue[1]
    if cash and revenue and cash[2:]==revenue[2:] and cash[1]>0:trends['cashflow_change']=cash[0]/cash[1]-1
    periods={k:{'current':r[2],'previous':r[3]} for k,r in [('revenue',revenue),('operating_income',op),('cashflow',cash)] if r}
    data={'signals':signals,'trends':trends,'financial_periods':periods,'market':item['market'],'source':'Yahoo Finance adjusted prices / annual statements','benchmark':BENCHMARKS[item['market']],'ticker':item['ticker'],'period':signals.get('as_of'),'status':'collected'}
    save_flow(con,lid,'leadership',signals.get('as_of') or utc()[:10],data)
    from ..flows.demand import collect_inventory
    try:
        data['demand_collection']=collect_inventory(con,item,ticker,info)
    except Exception as exc:
        data['demand_collection']={'status':'failed','reason':type(exc).__name__}
    from ..flows.collection import refresh_holders
    try:
        data['institution_collection']=refresh_holders(con,item,ticker,info)
    except Exception as exc:
        data['institution_collection']={'status':'failed','reason':type(exc).__name__}
    return data


def observed_leadership(con,lid):
    current=flows(con,lid,'leadership')
    if not current:return leadership({}, {}, 0)
    data=current[0]['data'];market=data['market'];period=data['period']
    pool=[]
    for r in con.execute('SELECT id FROM listings WHERE market=? AND active=1',(market,)):
        records=flows(con,r['id'],'leadership')
        if not records:continue
        d=records[0]['data'];s=d.get('signals',{})
        if s.get('return_basis')=='dividend_and_split_adjusted_fund_proxy' and d.get('period')==period and all(s.get(k) is not None for k in ('rs_3m','rs_6m','rs_12m','turnover_change')):
            pool.append((r['id'],sum(s[k] for k in ('rs_3m','rs_6m','rs_12m'))/3,s['turnover_change']))
    signals=dict(data['signals'])
    target=next((r for r in pool if r[0]==lid),None)
    if target and len(pool)>=20:
        signals['rs_percentile']=sum(r[1]<=target[1] for r in pool)/len(pool)
        signals['liquidity_percentile']=sum(r[2]<=target[2] for r in pool)/len(pool)
    return {**leadership(data['trends'],signals,len(pool)),'source':data['source'],'benchmark':data['benchmark'],'as_of':period,'coverage_note':'수집된 동기간 시장 표본 기준이며 시장 전체 순위가 아닙니다.'}
