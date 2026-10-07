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
    suffix={'KR':'.KQ' if exchange=='KOSDAQ' else '.KS','JP':'.T','TW':'.TWO' if exchange=='TPEx' else '.TW','HK':'.HK','SG':'.SI','US':''}[market]
    code=str(code).strip()
    if market=='HK': code=code.zfill(4)
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


def parse_hkex(df):
    if not {'Stock Code','Name of Securities','Category','Trading Currency'}.issubset(df.columns):raise ValueError('Unexpected HKEX schema')
    rows=[]
    for _,r in df.iterrows():
        code=str(r['Stock Code']).strip()
        if not code.isdigit():continue
        category=str(r['Category']).casefold();sub=str(r.get('Sub-Category','')).casefold()
        kind='stock' if category=='equity' else 'etf' if 'exchange traded fund' in sub else 'reit' if 'real estate investment trust' in sub else 'other'
        item=listing('HK','HKEX',str(int(code)).zfill(4),r['Name of Securities'],kind)
        item['currency']=str(r['Trading Currency']);item['isin']=str(r.get('ISIN',''));item['official_category']=str(r['Category'])+' / '+str(r.get('Sub-Category',''))
        rows.append(item)
    return rows


def fetch_catalog(market):
    http=HTTP()
    if market=='US':
        rows=[]
        for file,ex in [('nasdaqlisted.txt','NASDAQ'),('otherlisted.txt','OTHER')]:
            text=http.get('https://www.nasdaqtrader.com/dynamic/symdir/'+file,binary=True).decode('utf-8-sig')
            rows+=parse_nasdaq(text,ex)
        return rows,'Nasdaq Trader official directory'
    if market=='TW':
        rows=[]
        for url,ex in [('https://openapi.twse.com.tw/v1/opendata/t187ap03_L','TWSE'),('https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O','TPEx')]:
            data=http.get(url)
            if not isinstance(data,list) or not data: raise ValueError('Invalid Taiwan directory')
            for r in data:
                code=r.get('公司代號') or r.get('SecuritiesCompanyCode'); name=r.get('公司名稱') or r.get('CompanyName')
                if not code or not name: raise ValueError('Unexpected Taiwan schema')
                rows.append(listing('TW',ex,code,name,industry=r.get('產業別') or r.get('SecuritiesIndustryCode')))
        return rows,'TWSE / TPEx official company profiles'
    if market=='HK':
        url='https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx'
        frame=pd.read_excel(io.BytesIO(http.get(url,binary=True)),header=2,dtype=str)
        return parse_hkex(frame),'HKEX official full securities list'
    if market=='JP':
        url='https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx'
        df=pd.read_excel(io.BytesIO(http.get(url,binary=True)),dtype=str)
        if 'コード' not in df or '銘柄名' not in df: raise ValueError('Unexpected JPX schema')
        rows=[]
        for _,r in df.iterrows():
            segment=str(r.get('市場・商品区分',''))
            kind='etf' if 'ETF' in segment else 'reit' if 'REIT' in segment else 'stock' if '内国株式' in segment else 'other'
            rows.append(listing('JP','TSE',r['コード'],r['銘柄名'],kind,r.get('33業種区分')))
        return rows,'JPX official listed issues'
    if market=='KR':
        # KIND download is the official corporate directory, not an ETF list.
        rows=[]
        for filter_name,exchange in [('stockMkt','KOSPI'),('kosdaqMkt','KOSDAQ'),('konexMkt','KONEX')]:
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
        rows,source=fetch_catalog(market)
        sid=replace_catalog(con,market,rows,source,utc(),True)
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
        status={'status':'captured','listings':len(rows),'snapshot_id':sid,'source':source}
    except Exception:
        status={'status':'connection_unavailable','reason':'공식 목록의 응답·인증·형식을 확인해야 합니다. 이전 목록은 보존됩니다.'}
    set_health(con,market,status)
    return status
