import pandas as pd
import pytest
from test_dashboard import con, catalog, listing


def test_price_levels_require_compatible_valid_valuation():
    from app.research import price_levels
    a={'metrics':{'currency':'USD'},'valuation':{'status':'estimated','currency':'USD','scenarios':{'base':{'value':100}}}}
    r=price_levels(a,{'currency':'USD','price':80,'target_mean':120})
    assert r['buy_review']==80 and r['sell_review']==100
    a['valuation']['currency']='KRW'
    assert price_levels(a,{'currency':'USD'})['buy_review'] is None


def test_research_retains_broker_date_and_does_not_invent_target(con):
    from app.research import collect_research
    from app.discovery.store import flows
    row=listing();catalog(con,[row])
    class T:
        upgrades_downgrades=pd.DataFrame([{'Firm':'Broker','ToGrade':'Buy','FromGrade':'Hold','Action':'up'}],index=pd.to_datetime(['2026-10-01']))
    r=collect_research(con,row,T(),{'currency':'USD','currentPrice':80,'targetMeanPrice':100,'numberOfAnalystOpinions':5})
    assert r['reports']==1
    d=flows(con,row['id'],'research_opinions')[0]['data']
    assert d['opinions'][0]['date']=='2026-10-01'
    assert d['opinions'][0]['target_current'] is None
    assert d['target_mean']==100
    assert d['coverage']=='provider_summary_not_full_report'


def test_price_display_separates_consensus_from_valuation():
    from app.web import research_detail
    row={'listing':{'ticker':'ABC'},'research':{'opinions':[],'analysts':3},'price_levels':{'currency':'USD','current':80,'buy_review':80,'sell_review':100,'target_mean':120}}
    text=research_detail(row)
    assert '매수 검토가 80.0 USD' in text
    assert '매도 검토가 100.0 USD' in text
    assert '평균 목표가 120.0 USD' in text
    assert '예상 체결가가 아닙니다' in text
