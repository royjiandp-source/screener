"""Catalog search and asynchronous evaluation endpoints."""
import threading
from fastapi import APIRouter,HTTPException,Query
from pydantic import BaseModel,Field
from ..db import connect,loads
from ..countries import COUNTRIES
from .store import search,health,init,flows,replace_catalog,classify,SEARCH_MARKETS
from .providers import refresh_market
from .jobs import create_job,run_job,job_status,cancel_job

router=APIRouter(prefix='/api/discovery')
PATTERN='^(KR|US|SG)$'

class Evaluation(BaseModel):
    listing_ids:list[str]=Field(default_factory=list,max_length=5000)
    query:str|None=Field(None,max_length=100)
    market:str|None=None
    idempotency_key:str|None=Field(None,max_length=64,pattern='^[A-Za-z0-9-]+$')

@router.get('/search')
def find(query:str=Query('',max_length=100),market:str|None=Query(None,pattern=PATTERN),offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
    c=connect()
    try: return search(c,query,market,offset,limit)
    finally:c.close()

@router.get('/sources')
def sources():
    c=connect()
    try:return {m:d for m,d in health(c).items() if m in SEARCH_MARKETS}
    finally:c.close()

_refresh_lock=threading.Lock()
@router.post('/refresh')
def refresh(market:str=Query(...,pattern=PATTERN)):
    if not _refresh_lock.acquire(False): return {'started':False,'reason':'목록 갱신 중'}
    def work():
        c=connect()
        try: refresh_market(c,market)
        finally:c.close();_refresh_lock.release()
    threading.Thread(target=work,daemon=True).start()
    return {'started':True,'market':market}

@router.post('/evaluate')
def evaluate(body:Evaluation):
    if body.market and body.market not in SEARCH_MARKETS:raise HTTPException(422,'Unknown market')
    c=connect()
    try:jid=create_job(c,body.listing_ids,body.query,body.market,body.idempotency_key)
    except ValueError as e:raise HTTPException(422,str(e)) from None
    finally:c.close()
    threading.Thread(target=run_job,args=(jid,),daemon=True).start()
    return {'id':jid,'state':'queued'}

@router.get('/jobs/{jid}')
def status(jid:str):
    c=connect()
    try:return job_status(c,jid)
    except ValueError:raise HTTPException(404,'작업 없음') from None
    finally:c.close()

@router.post('/jobs/{jid}/cancel')
def cancel(jid:str):
    c=connect()
    try:cancel_job(c,jid);return {'cancel_requested':True}
    except ValueError:raise HTTPException(404,'작업 없음') from None
    finally:c.close()

@router.get('/detail')
def detail(listing_id:str):
    c=connect();init(c)
    try:
        row=c.execute('SELECT data FROM listings WHERE id=?',(listing_id,)).fetchone()
        if not row:raise HTTPException(404,'종목 없음')
        listing=loads(row[0],{})
        score=c.execute('SELECT data,day FROM stock_scores WHERE ticker=? ORDER BY day DESC LIMIT 1',(listing['ticker'],)).fetchone()
        from .profiles import observed_leadership
        from ..flows.institutions import institution_changes
        return {'institution_changes':institution_changes(flows(c,listing_id,'institution_holdings')),'leadership':observed_leadership(c,listing_id),'listing':listing,'valuation':loads(score[0],{}) if score else None,'analysis_day':score['day'] if score else None,'flows':flows(c,listing_id),'flow_status':'자료가 없으면 미수집 또는 미지원입니다.'}
    finally:c.close()

class CatalogImport(BaseModel):
    market:str
    source:str=Field(min_length=1,max_length=500)
    observed_at:str
    complete:bool=False
    rows:list[dict]=Field(max_length=100000)

@router.post('/import')
def catalog_import(body:CatalogImport):
    from .imports import import_catalog
    c=connect()
    try:return {'snapshot_id':import_catalog(c,body.market,body.rows,body.source,body.observed_at,body.complete)}
    except (ValueError,KeyError):raise HTTPException(422,'자료 출처·시점·종목 필드를 확인하세요.') from None
    finally:c.close()

class FlowImport(BaseModel):
    listing_id:str
    kind:str
    period:str
    available_at:str
    data:dict

@router.post('/flows/import')
def flow_import(body:FlowImport):
    from ..flows.ingest import ingest
    c=connect()
    try:return ingest(c,body.listing_id,body.kind,body.period,body.data,body.available_at)
    except (ValueError,KeyError):raise HTTPException(422,'자료 출처·종류·날짜·단위를 확인하세요.') from None
    finally:c.close()

@router.post('/enrich')
def enrich(body:Evaluation):
    if body.market and body.market not in SEARCH_MARKETS:raise HTTPException(422,'Unknown market')
    c=connect()
    try:jid=create_job(c,body.listing_ids,body.query,body.market,body.idempotency_key,kind='profile')
    except ValueError as e:raise HTTPException(422,str(e)) from None
    finally:c.close()
    threading.Thread(target=run_job,args=(jid,),daemon=True).start()
    return {'id':jid,'state':'queued','note':'분류·관찰 신호·ETF 자료 수집 작업을 시작합니다.'}

@router.post('/institution/refresh')
def institution_refresh(listing_id:str,start:str,end:str):
    import datetime as dt
    from ..flows.providers import refresh_kr_investors
    try:
        a,b=dt.date.fromisoformat(start),dt.date.fromisoformat(end)
        if b<a or (b-a).days>366:raise ValueError()
    except ValueError:raise HTTPException(422,'최대 366일의 날짜 범위를 지정하세요.') from None
    c=connect();init(c)
    try:
        row=c.execute('SELECT data FROM listings WHERE id=?',(listing_id,)).fetchone()
        if not row:raise HTTPException(404,'종목 없음')
        item=loads(row[0],{})
        if item['market']!='KR':return {'status':'not_supported','note':'미국은 13F 분기 보유를 조회해야 합니다.'}
        try:return refresh_kr_investors(c,item,start,end)
        except Exception:return {'status':'connection_unavailable','note':'KRX 투자자별 거래 자료의 연결 또는 접근 설정을 확인해야 합니다.'}
    finally:c.close()

@router.post('/institution/sec13f')
def sec13f(manager_cik:str=Query(...,pattern='^[0-9]{1,10}$')):
    from ..flows.sec13f import refresh_manager
    c=connect()
    try:
        try:return refresh_manager(c,manager_cik)
        except Exception:return {'status':'connection_unavailable','note':'SEC 연락처 설정·공시 형식·연결을 확인해야 합니다.'}
    finally:c.close()

@router.get('/leadership')
def candidates(query:str=Query('',max_length=100),market:str|None=Query(None,pattern=PATTERN)):
    from .profiles import observed_leadership
    c=connect()
    try:
        results=search(c,query,market,limit=1000000)
        rows=[]
        for item in results['items']:
            r=observed_leadership(c,item['id'])
            if r['signals']:rows.append({'listing':item,**r})
        rows.sort(key=lambda r:r['score'] if r['score'] is not None else -1,reverse=True)
        rs=[r for r in rows if r['signals'].get('rs_3m') is not None]
        return {'items':rows,'total_matches':results['total'],'observed':len(rows),'sector_breadth':sum(r['signals']['rs_3m']>0 for r in rs)/len(rs) if rs else None,'breadth_sample':len(rs),'note':'관찰 표본 기준; 분류되지 않은 기업과 미수집 자료는 포함되지 않습니다.'}
    finally:c.close()

@router.post('/jobs/{jid}/resume')
def resume(jid:str):
    c=connect()
    try:
        init(c);s=job_status(c,jid)
        if s['state']!='interrupted':raise HTTPException(409,'중단된 작업만 재개할 수 있습니다.')
        from .jobs import enqueue_resume
        enqueue_resume(c,jid)
    except ValueError:raise HTTPException(404,'작업 없음') from None
    finally:c.close()
    threading.Thread(target=run_job,args=(jid,),daemon=True).start()
    return {'id':jid,'state':'queued'}
