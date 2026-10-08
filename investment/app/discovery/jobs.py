"""Persistent search evaluation jobs; each item commits independently."""
import threading
import uuid
from ..db import connect,dumps,loads
from ..filings.common import utc
from .store import init,search,SEARCH_MARKETS

_worker_lock=threading.Lock()


def create_job(con,listing_ids=None,search_query=None,market=None,idempotency_key=None,kind="valuation"):
    init(con)
    if kind == 'market_valuation':
        r=search(con,'',market,limit=1000000)
        listing_ids=[x['id'] for x in r['items'] if x['type'] in ('stock','adr')]
        search_query=None
    if search_query is not None:
        r=search(con,search_query,market,limit=1000000)
        listing_ids=[r['id'] for r in r['items']]
    ids=list(dict.fromkeys(listing_ids or []))
    if not ids: raise ValueError('검색 결과 또는 선택 종목이 없습니다.')
    items=[]
    for lid in ids:
        row=con.execute('SELECT data FROM listings WHERE id=? AND active=1',(lid,)).fetchone()
        if not row: raise ValueError('현재 목록에서 확인되지 않은 종목입니다.')
        item=loads(row[0],{})
        if item['market'] not in SEARCH_MARKETS:raise ValueError('지원하지 않는 시장입니다.')
        items.append(item)
    if idempotency_key:
        old=con.execute('SELECT id FROM discovery_jobs WHERE id=?',(idempotency_key,)).fetchone()
        if old: return old[0]
    jid=idempotency_key or uuid.uuid4().hex
    data={'kind':kind,'items':items,'total':len(items),'completed':0,'failed':0,'cancel_requested':False,'errors':[]}
    with con: con.execute('INSERT INTO discovery_jobs VALUES(?,?,?,?)',(jid,'queued',dumps(data),utc()))
    return jid


def job_status(con,jid):
    init(con); row=con.execute('SELECT * FROM discovery_jobs WHERE id=?',(jid,)).fetchone()
    if not row: raise ValueError('작업을 찾을 수 없습니다.')
    d=loads(row['data'],{}); d.pop('items',None)
    results=[{'listing_id':r['listing_id'],**loads(r['data'],{})} for r in con.execute('SELECT listing_id,data FROM discovery_results WHERE job_id=?',(jid,))]
    return {'id':jid,'state':row['state'],'created_at':row['created_at'],**d,'results':results}


def cancel_job(con,jid):
    init(con); r=con.execute('SELECT data FROM discovery_jobs WHERE id=?',(jid,)).fetchone()
    if not r: raise ValueError('Unknown job')
    d=loads(r[0],{});d['cancel_requested']=True
    with con: con.execute('UPDATE discovery_jobs SET data=? WHERE id=?',(dumps(d),jid))


def run_job(jid):
    from ..pipeline import score_tickers
    from ..countries import market_of
    if not _worker_lock.acquire(blocking=False): return
    con=connect();init(con)
    try:
        row=con.execute('SELECT * FROM discovery_jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['state'] not in ('queued','interrupted'): return
        d=loads(row['data'],{})
        with con: con.execute("UPDATE discovery_jobs SET state='running' WHERE id=?",(jid,))
        for item in d['items']:
            fresh=loads(con.execute('SELECT data FROM discovery_jobs WHERE id=?',(jid,)).fetchone()[0],{})
            if fresh.get('cancel_requested'):
                with con: con.execute("UPDATE discovery_jobs SET state='cancelled' WHERE id=?",(jid,))
                return
            if con.execute('SELECT 1 FROM discovery_results WHERE job_id=? AND listing_id=?',(jid,item['id'])).fetchone(): continue
            try:
                if d.get('kind')=='profile':
                    from .profiles import enrich_listing
                    result={**enrich_listing(con,item['id']),'source':item['source'],'ticker':item['ticker']}
                elif item['type']=='etf': result={'status':'fund_analysis','source':item['source'],'ticker':item['ticker'],'note':'ETF 상세에서 구성·자금 흐름을 확인하세요.'}
                elif item['type'] not in ('stock','adr','reit'): result={'status':'special_model_required','source':item['source'],'ticker':item['ticker']}
                elif market_of(item['ticker'])!=item['market']: result={'status':'unsupported_listing_identity','source':item['source'],'ticker':item['ticker']}
                else:
                    outcome=score_tickers(con,[item['ticker']])
                    if (outcome or {}).get('failed'):raise ValueError('Financial refresh failed')
                    scored=con.execute('SELECT data FROM stock_scores WHERE ticker=? ORDER BY day DESC LIMIT 1',(item['ticker'],)).fetchone()
                    result={'status':'completed','source':item['source'],'ticker':item['ticker'],'analysis':loads(scored[0],{}) if scored else {}}
                completed,failed=1,0
            except Exception:
                result={'status':'error','source':item['source'],'ticker':item['ticker'],'reason':'자료 수집 또는 계산 실패'}
                completed,failed=0,1
            with con:
                con.execute('INSERT OR REPLACE INTO discovery_results VALUES(?,?,?)',(jid,item['id'],dumps(result)))
                con.execute("UPDATE discovery_jobs SET data=json_set(data,'$.completed',json_extract(data,'$.completed')+?,'$.failed',json_extract(data,'$.failed')+?) WHERE id=?",(completed,failed,jid))
        with con: con.execute("UPDATE discovery_jobs SET state=CASE WHEN json_extract(data,'$.cancel_requested') THEN 'cancelled' ELSE 'completed' END WHERE id=?",(jid,))
    finally:
        con.close();_worker_lock.release()
        c=connect();init(c)
        queued=c.execute("SELECT id FROM discovery_jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone();c.close()
        if queued: threading.Thread(target=run_job,args=(queued[0],),daemon=True).start()


def recover(con):
    init(con)
    with con: con.execute("UPDATE discovery_jobs SET state='interrupted' WHERE state='running'")


def enqueue_resume(con,jid):
    init(con)
    with con:
        changed=con.execute("UPDATE discovery_jobs SET state='queued' WHERE id=? AND state='interrupted'",(jid,)).rowcount
    if not changed:raise ValueError('Only interrupted jobs can resume')


def start_pending(con):
    init(con)
    row=con.execute("SELECT id FROM discovery_jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
    if row:threading.Thread(target=run_job,args=(row[0],),daemon=True).start()
