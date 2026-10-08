"""Inventory is a partial demand signal, never a substitute for order/volume data."""
import datetime as dt
from ..valuation import finite
from ..filings.common import utc
from ..discovery.store import flows, save_flow


def inventory_evidence(frame, currency, as_of):
    if not currency or frame is None or 'Inventory' not in frame.index:
        return None
    cutoff=dt.date.fromisoformat(as_of)
    dates=sorted((c for c in frame.columns if c.date() <= cutoff),reverse=True)
    if not dates:
        return None
    current=dates[0]
    # Compare the same fiscal season a year earlier, allowing calendar drift.
    previous=next((c for c in dates[1:] if 350 <= (current.date()-c.date()).days <= 380),None)
    if previous is None:
        return None
    try:
        a,b=float(frame.loc['Inventory',current]),float(frame.loc['Inventory',previous])
    except (TypeError,ValueError):
        return None
    if not finite(a) or not finite(b) or a<0 or b<0:
        return None
    return {'source':'Yahoo Finance auxiliary balance sheet', 'coverage':'inventory_only',
            'note':'전년 동기 재고 장부금액 비교. 재고 감소만으로 수요 회복을 확정할 수 없으며 수주·판매량·제품 가격은 별도 확인이 필요합니다.',
            'measurements':[{'metric':'inventory','product':'연결 재고 장부금액','unit':currency,
                             'current':float(a),'previous':float(b),
                             'current_period':current.date().isoformat(),'previous_period':previous.date().isoformat()}]}


def collect_inventory(con,item,ticker,info):
    existing=flows(con,item['id'],'demand')
    if existing and existing[0]['data'].get('coverage')!='inventory_only':
        return {'status':'manual_evidence_preserved'}
    stamp=utc()
    evidence=inventory_evidence(ticker.quarterly_balance_sheet,info.get('financialCurrency'),stamp[:10])
    frequency='quarterly'
    if evidence is None:
        evidence=inventory_evidence(ticker.balance_sheet,info.get('financialCurrency'),stamp[:10])
        frequency='annual'
    if evidence is None:
        return {'status':'not_available','reason':'비교 가능한 전년 동기 재고·재무 통화 없음'}
    evidence['frequency']=frequency
    period=evidence['measurements'][0]['current_period']
    save_flow(con,item['id'],'demand',period,evidence)
    return {'status':'collected_partial','period':period,'coverage':'inventory_only'}
