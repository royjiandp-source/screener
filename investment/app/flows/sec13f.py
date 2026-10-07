"""13F XML facts retain security identifier and option/share-unit distinctions."""
from lxml import etree
from ..filings.common import amount


def parse_13f(xml,metadata):
    if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper(): raise ValueError('Unsafe XML')
    root=etree.fromstring(xml.encode(),parser=etree.XMLParser(resolve_entities=False,no_network=True))
    rows=[]
    multiplier=metadata.get('value_multiplier')
    if multiplier not in (1,1000): raise ValueError('Explicit value unit is required')
    for entry in root.xpath('//*[local-name()="infoTable"]'):
        def text(name):
            value=entry.xpath('.//*[local-name()="'+name+'"] /text()')
            return value[0].strip() if value else None
        value=amount(text('value')); shares=amount(text('sshPrnamt'))
        if not text('cusip') or value is None or shares is None: continue
        rows.append({'cusip':text('cusip'),'issuer':text('nameOfIssuer'),'value':value*multiplier,'shares':shares,'share_type':text('sshPrnamtType'),'option':text('putCall'),'other_manager':text('otherManager'),**metadata})
    return rows


def resolve_filings(filings):
    """Resolve manager-specific restatements and supplements without cross-manager sums."""
    result={}
    seen=set()
    for f in sorted(filings,key=lambda r:(r['filed'],r['accession'])):
        if f['accession'] in seen:continue
        seen.add(f['accession']);q=f['quarter'];amendment=f['amendment']
        if amendment in ('original','restatement'):
            result[q]={**f,'holdings':list(f['holdings']),'accessions':[f['accession']]}
        elif amendment=='new_holdings' and q in result:
            result[q]['holdings']+=f['holdings'];result[q]['accessions'].append(f['accession']);result[q]['filed']=f['filed']
        else:
            result.setdefault(q,{**f,'holdings':[],'accessions':[]})['incomplete']=True
    return result


def reporting_date(value):
    import datetime as dt
    for fmt in ('%Y-%m-%d','%m-%d-%Y','%m/%d/%Y'):
        try:return dt.datetime.strptime(value,fmt).date().isoformat()
        except ValueError:pass
    raise ValueError('Unknown reporting period')


def refresh_manager(con,cik):
    import os,re,datetime as dt
    from ..filings.sec import Client
    from ..filings.common import after_day
    from ..discovery.store import save_flow,flows,init
    from ..db import loads
    if not re.fullmatch(r'\d{1,10}',cik):raise ValueError('Invalid manager CIK')
    user_agent=os.environ.get('SEC_USER_AGENT')
    if not user_agent:return {'status':'not_configured','required':'SEC_USER_AGENT'}
    http=Client(user_agent).http
    submissions=http.get('https://data.sec.gov/submissions/CIK'+cik.zfill(10)+'.json')
    recent=submissions.get('filings',{}).get('recent',{})
    filings=[]
    for i,form in enumerate(recent.get('form',[])):
        if form not in ('13F-HR','13F-HR/A'):continue
        filed=recent['filingDate'][i]
        # Current schema uses nearest-dollar values. Older unit formats are not inferred.
        if filed<'2023-07-01':continue
        accession=recent['accessionNumber'][i]
        primary=recent['primaryDocument'][i]
        if not re.fullmatch(r'[0-9-]+',accession) or not re.fullmatch(r'[A-Za-z0-9_.-]+',primary):continue
        directory='https://www.sec.gov/Archives/edgar/data/'+str(int(cik))+'/'+accession.replace('-','')+'/'
        xml=http.get(directory+primary,binary=True).decode()
        if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():raise ValueError('Unsafe primary XML')
        root=etree.fromstring(xml.encode(),parser=etree.XMLParser(resolve_entities=False,no_network=True))
        def get(name):
            matches=root.xpath('//*[local-name()="'+name+'"] /text()')
            return matches[0].strip() if matches else None
        quarter=get('periodOfReport') or get('reportCalendarOrQuarter') or recent.get('reportDate',['']*len(recent['form']))[i]
        quarter=reporting_date(quarter or '')
        if not quarter or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',quarter):raise ValueError('Unknown reporting period')
        kind='original'
        if form.endswith('/A'):
            text=(get('amendmentType') or '').lower()
            kind='restatement' if 'restat' in text else 'new_holdings' if 'new' in text else 'unknown'
        index=http.get(directory+'index.json')
        documents=[];holdings=[]
        for doc in index.get('directory',{}).get('item',[]):
            name=doc.get('name','')
            if name==primary or not re.fullmatch(r'[A-Za-z0-9_.-]+\.xml',name):continue
            content=http.get(directory+name,binary=True).decode()
            if 'informationTable' not in content and 'infoTable' not in content:continue
            rows=parse_13f(content,{'value_multiplier':1,'currency':'USD','manager':cik,'accession':accession,'quarter':quarter,'filed':filed,'source':directory+name})
            holdings+=rows;documents.append({'name':name,'raw_xml':content})
        f={'manager':cik,'quarter':quarter,'filed':filed,'accession':accession,'amendment':kind,'holdings':holdings,'source':directory,'raw_primary':xml,'raw_tables':documents,'coverage':'configured_manager_recent_submissions'}
        if not holdings:f['incomplete']=True
        save_flow(con,'manager:'+cik,'sec13f_raw',quarter,f,after_day(filed,'America/New_York'))
        filings.append(f)
        # Capture the last two reporting quarters, including amendments, from recent submissions.
        if len({f['quarter'] for f in filings})>2:break
    resolved=resolve_filings(filings)
    init(con)
    mapping={}
    for r in con.execute("SELECT id,data FROM listings WHERE market='US'"):
        item=loads(r['data'],{})
        if item.get('cusip'):mapping.setdefault(item['cusip'],[]).append(r['id'])
    mapped=0
    for quarter,f in resolved.items():
        for h in f['holdings']:
            if h.get('option') or h.get('share_type')!='SH':continue
            ids=mapping.get(h['cusip'],[])
            if len(ids)!=1:continue
            save_flow(con,ids[0],'institution_holdings',quarter,{**h,'accessions':f['accessions'],'complete':not f.get('incomplete'),'source':f['source'],'coverage':'configured_manager_only'},after_day(f['filed'],'America/New_York'))
            mapped+=1
    return {'status':'captured' if filings else 'empty','filings':len(filings),'mapped_rows':mapped,'manager':cik,'note':'분기 보유 자료. 확인된 CUSIP 연결만 사용하며 전체 기관 매매를 나타내지 않습니다.'}
