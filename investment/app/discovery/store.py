"""Versioned listing catalog and evidence-based sector search."""
import hashlib
import re
from ..db import dumps, loads, load_themes
from ..countries import COUNTRIES, SEARCH_MARKETS
from ..filings.common import utc

SCHEMA='''
CREATE TABLE IF NOT EXISTS catalog_snapshots(id INTEGER PRIMARY KEY,market TEXT,source TEXT,observed_at TEXT,complete INTEGER,active INTEGER,raw TEXT);
CREATE TABLE IF NOT EXISTS listings(id TEXT PRIMARY KEY,market TEXT,ticker TEXT,data TEXT,active INTEGER,snapshot_id INTEGER);
CREATE TABLE IF NOT EXISTS classifications(listing_id TEXT,label TEXT,kind TEXT,source TEXT,evidence TEXT,available_at TEXT,PRIMARY KEY(listing_id,label,source));
CREATE TABLE IF NOT EXISTS classification_history(id INTEGER PRIMARY KEY,listing_id TEXT,data TEXT,observed_at TEXT,hash TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS listing_events(id INTEGER PRIMARY KEY,listing_id TEXT,event TEXT,observed_at TEXT);
CREATE TABLE IF NOT EXISTS discovery_health(market TEXT PRIMARY KEY,data TEXT);
CREATE TABLE IF NOT EXISTS discovery_jobs(id TEXT PRIMARY KEY,state TEXT,data TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS discovery_results(job_id TEXT,listing_id TEXT,data TEXT,PRIMARY KEY(job_id,listing_id));
CREATE TABLE IF NOT EXISTS flow_snapshots(id INTEGER PRIMARY KEY,listing_id TEXT,kind TEXT,period TEXT,observed_at TEXT,available_at TEXT,data TEXT,hash TEXT UNIQUE);
'''

def init(con):
    con.executescript(SCHEMA)


def replace_catalog(con,market,rows,source,observed_at,complete):
    init(con)
    if market not in COUNTRIES: raise ValueError('Unknown market')
    for row in rows:
        expected=f"{market}:{row.get('exchange')}:{row.get('code')}:{row.get('type')}"
        if row.get('id') != expected:raise ValueError('Invalid listing identity')
        if row.get('type') not in ('stock','etf','reit','adr','preferred','other'):raise ValueError('Invalid instrument type')
        if row.get('market')!=market or any(not row.get(k) for k in ('id','ticker','code','exchange','name','type','currency')):
            raise ValueError('Invalid listing')
    if len({r['id'] for r in rows})!=len(rows): raise ValueError('Duplicate listing')
    if complete and not rows: raise ValueError('Empty complete catalog')
    observed_at=utc(observed_at)
    if observed_at>utc():raise ValueError('Future observation is not allowed')
    with con:
        sid=con.execute('INSERT INTO catalog_snapshots(market,source,observed_at,complete,active,raw) VALUES(?,?,?,?,?,?)',
            (market,source,observed_at,int(complete),int(complete),dumps(rows))).lastrowid
        if complete:
            con.execute('UPDATE catalog_snapshots SET active=0 WHERE market=? AND id!=?',(market,sid))
            active=[r[0] for r in con.execute('SELECT id FROM listings WHERE market=? AND active=1',(market,))]
            new={r['id'] for r in rows}
            for lid in set(active)-new:con.execute('INSERT INTO listing_events(listing_id,event,observed_at) VALUES(?,?,?)',(lid,'absent_from_latest_catalog',observed_at))
            con.execute('UPDATE listings SET active=0 WHERE market=?',(market,))
        for r in rows:
            con.execute('INSERT OR REPLACE INTO listings VALUES(?,?,?,?,1,?)',(r['id'],market,r['ticker'],dumps({**r,'source':source,'observed_at':observed_at}),sid))
    return sid


def classify(con,listing_id,label,kind,source,evidence,available_at):
    init(con)
    if not evidence or kind not in ('industry','theme'): raise ValueError('Classification needs evidence')
    record={'label':label,'kind':kind,'source':source,'evidence':evidence,'available_at':utc(available_at)}
    digest=hashlib.sha256((listing_id+dumps(record)).encode()).hexdigest()
    with con:
        con.execute('INSERT OR IGNORE INTO classification_history(listing_id,data,observed_at,hash) VALUES(?,?,?,?)',(listing_id,dumps(record),utc(),digest))
        con.execute('INSERT OR REPLACE INTO classifications VALUES(?,?,?,?,?,?)',(listing_id,label,kind,source,evidence,utc(available_at)))



def search(con,query,market=None,offset=0,limit=50,related=False):
    init(con)
    if market and market not in SEARCH_MARKETS: raise ValueError('Unsupported search market')
    q=query.strip().casefold()
    aliases={'반도체':'semiconductor','인공지능':'ai','전력':'power','원전':'nuclear','보안':'security','클라우드':'cloud','데이터센터':'data center','로봇':'robot','바이오':'biotech'}
    original=q
    q=aliases.get(q,q)
    terms={q,original,*[k for k,v in aliases.items() if v==q]}
    def matches(text):
        text=str(text).casefold()
        return any(re.search(r'(?<![a-z0-9])'+re.escape(t)+r'(?![a-z0-9])',text) if t.isascii() else t in text for t in terms if t)
    themes=load_themes()['themes']
    labels={label for label,m in themes.items() if q and any(matches(t) for t in [label,*m.get('keywords',[]),*m.get('industries',[])])}
    # Search cached evidence, not arbitrary company name alone for thematic membership.
    records=con.execute("SELECT * FROM listings WHERE active=1 AND market IN ('KR','US','SG')"+(' AND market=?' if market else ''),(market,) if market else ()).fetchall()
    evidence_by_id={}
    for e in con.execute("SELECT c.* FROM classifications c JOIN listings l ON l.id=c.listing_id WHERE l.active=1 AND l.market IN ('KR','US','SG')"):
        evidence_by_id.setdefault(e['listing_id'],[]).append({k:e[k] for k in ('label','kind','source','evidence','available_at')})
    found=[]; classified=0
    for row in records:
        r=loads(row['data'],{})
        evidence=evidence_by_id.get(row['id'],[])
        if evidence: classified+=1
        if not q or q == r['ticker'].casefold() or matches(r['name']) or any(e['label'] in labels or matches(e['label']) or matches(e['evidence']) for e in evidence):
            found.append({**r,'evidence':evidence,'matched_labels':[e['label'] for e in evidence if q and (e['label'] in labels or matches(e['label']) or matches(e['evidence']))]})
    if related and q:
        direct=[r for r in found if matches(r['name']) or q==r['ticker'].casefold() or q==r['code'].casefold()]
        peer_labels={(r['market'],e['label']) for r in direct for e in r['evidence'] if e['kind']=='industry'}
        seen={r['id'] for r in found}
        for row in records:
            if row['id'] in seen:continue
            r=loads(row['data'],{});evidence=evidence_by_id.get(row['id'],[])
            matched=[e['label'] for e in evidence if (r['market'],e['label']) in peer_labels]
            if matched:found.append({**r,'evidence':evidence,'matched_labels':matched})
        direct_ids={r['id'] for r in direct}
        found.sort(key=lambda r:r['id'] not in direct_ids)
    snapshots={r['market']:r['id'] for r in con.execute('SELECT id,market FROM catalog_snapshots WHERE active=1')}
    return {'items':found[offset:offset+limit],'total':len(found),'classified':classified,'total_listings':len(records),'catalog_snapshots':snapshots,'status':'available' if records else 'not_collected'}


def health(con):
    init(con)
    return {m:{'status':'not_collected',**loads((con.execute('SELECT data FROM discovery_health WHERE market=?',(m,)).fetchone() or [None])[0],{})} for m in COUNTRIES}


def set_health(con,market,data):
    init(con)
    with con: con.execute('INSERT OR REPLACE INTO discovery_health VALUES(?,?)',(market,dumps({**data,'updated_at':utc()})))


def save_flow(con,listing_id,kind,period,data,available_at=None):
    init(con); observed=utc(); available=utc(available_at or observed)
    raw=dumps(data); digest=hashlib.sha256((listing_id+kind+period+raw).encode()).hexdigest()
    with con: con.execute('INSERT OR IGNORE INTO flow_snapshots(listing_id,kind,period,observed_at,available_at,data,hash) VALUES(?,?,?,?,?,?,?)',(listing_id,kind,period,observed,available,raw,digest))


def flows(con,listing_id,kind=None,as_of=None):
    init(con); cutoff=utc(as_of)
    query='SELECT * FROM flow_snapshots WHERE listing_id=? AND observed_at<=? AND available_at<=?'
    args=[listing_id,cutoff,cutoff]
    if kind: query+=' AND kind=?'; args.append(kind)
    return [{**dict(r),'data':loads(r['data'],{})} for r in con.execute(query+' ORDER BY period DESC,id DESC',args)]
