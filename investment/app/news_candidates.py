"""A separate review queue: headline catalysts never alter investment scores."""
import datetime as dt
import re
from .db import now

CATALYSTS={'수주·계약 관련':['수주','공급 계약','wins contract','secures contract','supply agreement'],
           '실적 전망 상향':['실적 상향','전망 상향','raises guidance','raises forecast','raises outlook'],
           '수요·판매 증가':['판매 증가','수요 증가','sales surge','sales rise','demand rises'],
           '승인·허가':['승인','허가','approval','approved'],
           '투자·사업 확대':['증설','신규 투자','expansion','new investment'],
           '주주환원':['자사주 매입','배당 확대','share buyback','raises dividend']}
CAUTION=('취소','철회','부인','루머','미승인','승인 실패','cancelled','canceled','denies','rumor','rumour','approval denied','not approved')
ALIASES={'005930.KS':['삼성전자','Samsung Electronics'],'000660.KS':['SK하이닉스','SK hynix'],'NVDA':['Nvidia','엔비디아'],'AAPL':['Apple','애플'],'MSFT':['Microsoft','마이크로소프트'],'AMD':['Advanced Micro Devices','AMD'],'TSLA':['Tesla','테슬라']}


def contains(text,name):
    return bool(re.search(r'(?<![a-z0-9])'+re.escape(name.casefold())+r'(?![a-z0-9])',text)) if name.isascii() else name.casefold() in text


def build_news_candidates(con,companies,eligible_ids,limit=30):
    cutoff=now().astimezone(dt.timezone.utc)-dt.timedelta(days=14)
    aliases=[]
    for item in companies:
        if item['id'] not in eligible_ids:continue
        name=re.split(r' - |,?\s+(?:Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited)\b',item['name'],flags=re.I)[0].strip()
        names={item['name'],*ALIASES.get(item['ticker'],[])}
        if len(name)>=4:names.add(name)
        aliases.append((item,names))
    rows=[];seen=set()
    for article in con.execute('SELECT * FROM articles ORDER BY published DESC LIMIT 2000'):
        try:date=dt.datetime.fromisoformat(article['published'].replace('Z','+00:00'))
        except (ValueError,TypeError,AttributeError):continue
        if date.tzinfo is None or date<cutoff or date>now():continue
        title=article['title'] or '';text=title.casefold()
        if any(contains(text,x) for x in CAUTION):continue
        signals=[label for label,words in CATALYSTS.items() if any(contains(text,w) for w in words)]
        if not signals or not str(article['url']).startswith(('https://','http://')):continue
        for item,names in aliases:
            if item['market']!=article['market'] or not any(contains(text,n) for n in names):continue
            key=(item['id'],re.sub(r'\W+','',text))
            if key in seen:continue
            seen.add(key)
            rows.append({'listing':item,'title':title,'url':article['url'],'source':article['source'],
                         'published':article['published'],'signals':signals,
                         'status':'원문·공시 확인 필요','basis':'기사 제목의 기업명 직접 일치 · 호재 유형 키워드 감지'})
            if len(rows)>=limit:return rows
    return rows
