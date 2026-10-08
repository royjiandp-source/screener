"""Auxiliary published ownership, with explicit identities and reporting limits."""
import os
import re
import time
from ..db import loads
from ..filings.common import utc
from ..discovery.store import save_flow, search
from ..valuation import finite

CORE_FUNDS=('SPY','QQQ','VTI','VOO','SMH','SOXX','XLK','XLF','XLE','XLI','XLV','XLY','IWM','EFA','EWY')


def resolve_holding(con, ticker):
    rows=con.execute('SELECT id,data FROM listings WHERE active=1 AND ticker=?',(ticker,)).fetchall()
    if not rows and re.fullmatch(r'[0-9]{6}\.(KS|KQ)',ticker):
        rows=con.execute("SELECT id,data FROM listings WHERE active=1 AND market='KR' AND json_extract(data,'$.code')=? AND json_extract(data,'$.type')='stock'",(ticker[:6],)).fetchall()
    if len(rows)!=1:
        return None
    item=loads(rows[0]['data'],{})
    return {'listing_id':rows[0]['id'],'ticker':item['ticker'],'provider_ticker':ticker}


def refresh_holders(con,item,ticker,info):
    frame=ticker.institutional_holders
    count=0
    if frame is None:
        return {'status':'not_available','holders':0}
    stamp=utc()
    for _,row in frame.iterrows():
        manager=row.get('Holder');date=row.get('Date Reported')
        try:
            period=date.date().isoformat();shares=float(row.get('Shares'))
        except (ValueError,TypeError,AttributeError):
            continue
        if not isinstance(manager,str) or not manager.strip() or period>stamp[:10] or not finite(shares) or shares<0:
            continue
        pct=row.get('pctHeld')
        pct=float(pct) if pct is not None else None
        data={'manager':manager,'shares':shares,'value':None,'currency':info.get('currency'),
              'ownership_fraction':pct if finite(pct) and 0<=pct<=1 else None,
              'source':'https://finance.yahoo.com/quote/'+item['ticker']+'/holders/',
              'coverage':'auxiliary_reported_holders','complete':False,'share_type':'SH',
              'note':'보조 제공처의 공개 보유 자료. SEC 원문 검증·순매수·전체 기관 집계가 아니며 평가금액의 기준이 확인되지 않아 주식 수만 표시합니다.'}
        save_flow(con,item['id'],'institution_holdings',period,data)
        count+=1
    return {'status':'collected_partial' if count else 'not_available','holders':count}


def run_funds(con,markets,limit=None,max_seconds=180):
    import yfinance as yf
    from .providers import refresh_etf
    # Foreign-listed ETFs can hold companies in the selected markets.
    funds=[x for x in search(con,'',None,limit=1000000)['items'] if x['market'] in ('KR','SG','US') and x['type']=='etf']
    attempts={r['listing_id']:r['stamp'] for r in con.execute("SELECT listing_id,MAX(observed_at) stamp FROM flow_snapshots WHERE kind='fund_collection_status' GROUP BY listing_id")}
    day=utc()[:10]
    funds=[f for f in funds if attempts.get(f['id'],'')[:10]<day]
    funds.sort(key=lambda f:(attempts.get(f['id'],''), f['ticker'] not in CORE_FUNDS, f['ticker']))
    result={'attempted':0,'collected':0,'failed':0,'empty':0}
    limit=int(os.environ.get('INVEST_FUND_BATCH','15')) if limit is None else limit
    start=time.monotonic()
    for fund in funds[:max(0,limit)]:
        if time.monotonic()-start>=max_seconds:break
        try:
            ticker=yf.Ticker(fund['ticker']);r=refresh_etf(con,fund,ticker,ticker.info)
            key='collected' if r['holdings'] else 'empty'
        except Exception:
            key='failed'
        save_flow(con,fund['id'],'fund_collection_status',day,{'status':key})
        result[key]+=1;result['attempted']+=1
    return result
