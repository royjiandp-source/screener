"""Published analyst opinion summaries and explicitly labelled valuation levels."""
import datetime as dt
import json
from pathlib import Path
from .valuation import finite
from .filings.common import utc
from .discovery.store import save_flow


def positive(value):
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if finite(value) and value>0 else None


def collect_research(con,item,ticker,info):
    stamp=utc();day=stamp[:10]
    opinions=[]
    status='collected'
    try:
        frame=ticker.upgrades_downgrades
        if frame is not None:
            cutoff=dt.date.fromisoformat(day)-dt.timedelta(days=180)
            for date,row in frame.sort_index(ascending=False).iterrows():
                date=date.date()
                if not cutoff<=date<=dt.date.fromisoformat(day):continue
                firm=row.get('Firm')
                if not isinstance(firm,str) or not firm.strip():continue
                opinions.append({'date':date.isoformat(),'firm':firm,'rating':str(row.get('ToGrade') or ''),
                                 'previous_rating':str(row.get('FromGrade') or ''),'action':str(row.get('Action') or ''),
                                 'target_current':positive(row.get('currentPriceTarget')), 'target_previous':positive(row.get('priorPriceTarget'))})
                if len(opinions)>=10:break
    except Exception:
        status='opinion_connection_failed'
    data={'source':'https://finance.yahoo.com/quote/'+item['ticker']+'/analysis/',
          'opinion_source':'https://finance.yahoo.com/quote/'+item['ticker']+'/upgrades-downgrades/',
          'coverage':'provider_summary_not_full_report','observed_at':stamp,
          'currency':info.get('currency'),'price':positive(info.get('currentPrice') or info.get('regularMarketPrice')),
          'price_time':info.get('regularMarketTime'),'target_mean':positive(info.get('targetMeanPrice')),
          'target_low':positive(info.get('targetLowPrice')),'target_high':positive(info.get('targetHighPrice')),
          'analysts':info.get('numberOfAnalystOpinions'),'consensus':info.get('recommendationKey'),
          'opinions':opinions,'status':status,
          'note':'공개 투자회사 의견의 보조 제공처 요약. 개별 리포트 원문·논거·목표주가 기간은 확인되지 않았습니다. 컨센서스 목표주가와 매매 검토가는 별도 기준입니다.'}
    save_flow(con,item['id'],'research_opinions',day,data)
    return {'reports':len(opinions),'target_available':data['target_mean'] is not None,'status':status}


def price_levels(analysis,research):
    valuation=analysis.get('valuation',{});currency=research.get('currency') or analysis.get('metrics',{}).get('currency')
    value=positive(valuation.get('scenarios',{}).get('base',{}).get('value'))
    compatible=currency and valuation.get('currency')==currency and valuation.get('status')=='estimated'
    return {'currency':currency,'current':research.get('price') or analysis.get('metrics',{}).get('price'),
            'buy_review':round(value*.8,2) if compatible and value else None,
            'sell_review':round(value,2) if compatible and value else None,
            'margin':20,'basis':'기준 내재가치 × 80% / 기준 내재가치 도달',
            'valuation_day':analysis.get('day'),'quote_observed':research.get('observed_at'),
            'target_mean':research.get('target_mean'),'target_low':research.get('target_low'),'target_high':research.get('target_high')}


def public_reports(ticker):
    path=Path(__file__).resolve().parent.parent/'research_sources.json'
    if not path.exists():return []
    return json.loads(path.read_text(encoding='utf-8')).get(ticker,[])
