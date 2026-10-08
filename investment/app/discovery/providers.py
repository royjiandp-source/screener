"""Source adapters: never substitute a seed universe for an exchange catalog."""
import csv
import io
import re
import requests
import pandas as pd
from ..countries import COUNTRIES
from ..filings.common import HTTP,utc
from .store import replace_catalog,classify,set_health
from ..db import load_themes


def listing(market,exchange,code,name,kind='stock',industry=None):
    suffix={'KR':'.KQ' if exchange=='KOSDAQ' else '.KS','SG':'.SI','US':''}[market]
    code=str(code).strip()
    return {'id':f'{market}:{exchange}:{code}:{kind}','market':market,'exchange':exchange,'code':code,'ticker':code.replace('.','-') if market=='US' else code+suffix,'name':name,'type':kind,'currency':COUNTRIES[market]['currency'],'industry':industry}


def parse_nasdaq(text,exchange):
    rows=csv.DictReader(io.StringIO(text),delimiter='|')
    key='Symbol' if exchange=='NASDAQ' else 'ACT Symbol'
    if not rows.fieldnames or key not in rows.fieldnames or 'Test Issue' not in rows.fieldnames: raise ValueError('Invalid Nasdaq directory')
    result=[]
    for r in rows:
        if not r.get(key) or r[key].startswith('File Creation') or r.get('Test Issue')!='N': continue
        kind='etf' if r.get('ETF')=='Y' else 'other' if re.search(r'\b(warrant|unit|preferred|rights)\b',r.get('Security Name',''),re.I) else 'adr' if 'depositary' in r.get('Security Name','').lower() else 'stock'
        result.append(listing('US',exchange if exchange=='NASDAQ' else {'N':'NYSE','A':'AMEX','P':'NYSEARCA','Z':'CBOE','V':'IEX'}.get(r.get('Exchange'),r.get('Exchange','OTHER')),r[key],r.get('Security Name') or r[key],kind))
    return result


def deduplicate(rows):
    unique={}
    for r in rows:
        old=unique.get(r['id'])
        if old and (old['name']!=r['name'] or old.get('industry')!=r.get('industry')):
            raise ValueError('Conflicting official listing identities')
        unique.setdefault(r['id'],r)
    return list(unique.values())





# Fallback SG list when the SGX securities feed is unreachable: STI constituents + configured
# candidates. Stored as a PARTIAL catalog (complete=False) and labelled as such in the UI.
SG_CONFIGURED = {
    'D05':('DBS Group','stock'),'O39':('OCBC Bank','stock'),'U11':('UOB','stock'),'Z74':('Singtel','stock'),
    'C38U':('CapitaLand Integrated Commercial Trust','reit'),'A17U':('CapitaLand Ascendas REIT','reit'),
    '9CI':('CapitaLand Investment','stock'),'C6L':('Singapore Airlines','stock'),'BN4':('Keppel','stock'),
    'S68':('Singapore Exchange','stock'),'S63':('ST Engineering','stock'),'U96':('Sembcorp Industries','stock'),
    '5E2':('Seatrium','stock'),'BS6':('Yangzijiang Shipbuilding','stock'),'F34':('Wilmar International','stock'),
    'Y92':('Thai Beverage','stock'),'G13':('Genting Singapore','stock'),'S58':('SATS','stock'),
    'V03':('Venture Corporation','stock'),'U14':('UOL Group','stock'),'C09':('City Developments','stock'),
    'H78':('Hongkong Land','stock'),'J36':('Jardine Matheson','stock'),'C07':('Jardine Cycle & Carriage','stock'),
    'D01':('DFI Retail Group','stock'),'M44U':('Mapletree Logistics Trust','reit'),
    'ME8U':('Mapletree Industrial Trust','reit'),'N2IU':('Mapletree Pan Asia Commercial Trust','reit'),
    'J69U':('Frasers Centrepoint Trust','reit'),'AJBU':('Keppel DC REIT','reit'),
    'DCRU':('Digital Core REIT','reit'),'558':('UMS Integration','stock'),'AWX':('AEM Holdings','stock'),
    'BSL':('Raffles Medical Group','stock'),'Q0F':('IHH Healthcare','stock'),
}
SGX_TYPES = {'stocks':'stock','businesstrusts':'stock','reits':'reit','etfs':'etf'}


def fetch_sg(http):
    """Try the SGX securities feed (full list); fall back to the configured partial list."""
    try:
        data = http.get('https://api.sgx.com/securities/v1.1', params={'excludetypes':'bonds','params':'nc,n,type'})
        prices = (data or {}).get('data', {}).get('prices', [])
        rows = [listing('SG','SGX',p['nc'],p['n'],SGX_TYPES[p['type']])
                for p in prices if p.get('nc') and p.get('n') and p.get('type') in SGX_TYPES]
        if len(rows) < 300:
            raise ValueError('Unexpected SGX schema')
        return deduplicate(rows), 'SGX securities feed', True
    except Exception:
        rows = [listing('SG','SGX',code,name,kind) for code,(name,kind) in SG_CONFIGURED.items()]
        return rows, 'Configured SG list (STI + candidates) - partial, not the full exchange', False


def fetch_catalog(market):
    http=HTTP()
    if market=='US':
        rows=[]
        for file,ex in [('nasdaqlisted.txt','NASDAQ'),('otherlisted.txt','OTHER')]:
            text=http.get('https://www.nasdaqtrader.com/dynamic/symdir/'+file,binary=True).decode('utf-8-sig')
            rows+=parse_nasdaq(text,ex)
        return rows,'Nasdaq Trader official directory'
    if market=='SG':
        return fetch_sg(http)
    if market=='KR':
        # KIND download is the official corporate directory, not an ETF list.
        rows=[]
        for filter_name,exchange in [('stockMkt','KOSPI'),('kosdaqMkt','KOSDAQ')]:  # KONEX excluded: little price/financial data
            raw=http.get('https://kind.krx.co.kr/corpgeneral/corpList.do',params={'method':'download','searchType':'13','marketType':filter_name},binary=True)
            df=pd.read_html(io.StringIO(raw.decode('euc-kr')))[0]
            if not {'회사명','종목코드','업종'}.issubset(df.columns) or df.empty: raise ValueError('Unexpected KIND schema')
            for _,r in df.iterrows():
                code=str(r['종목코드']).split('.')[0].zfill(6)
                if not re.fullmatch(r'[0-9A-Z]{6}',code): raise ValueError('Invalid Korean code')
                item=listing('KR',exchange,code,r['회사명'],industry=r['업종'])
                item['business_description']=str(r.get('주요제품',''))
                rows.append(item)
        return deduplicate(rows),'KRX KIND corporate directory'
    raise ValueError('Official automatic catalog connection not configured')


def refresh_market(con,market):
    try:
        result=fetch_catalog(market)
        rows,source=result[0],result[1]
        complete=result[2] if len(result)>2 else True
        sid=replace_catalog(con,market,rows,source,utc(),complete)
        themes=load_themes()['themes']
        for r in rows:
            if r.get('industry') and str(r['industry'])!='nan':
                classify(con,r['id'],str(r['industry']),'industry',source,str(r['industry']),utc())
            for label,meta in themes.items():
                business=r.get('business_description','')
                hits=[k for k in meta.get('keywords',[]) if len(k)>=3 and k.casefold() in business.casefold()]
                if hits:classify(con,r['id'],label,'theme',source,business,utc())
                if r['ticker'] in meta.get('tickers',{}).get(market,[]):
                    classify(con,r['id'],label,'theme','reviewed theme configuration','Configured thematic relationship',utc())
        status={'status':'captured' if complete else 'partial','listings':len(rows),'snapshot_id':sid,'source':source}
    except Exception:
        status={'status':'connection_unavailable','reason':'공식 목록의 응답·인증·형식을 확인해야 합니다. 이전 목록은 보존됩니다.'}
    set_health(con,market,status)
    return status
