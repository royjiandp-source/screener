import pandas as pd
from test_dashboard import con, catalog, listing


def frame(values, dates):
    return pd.DataFrame([values], index=['Inventory'], columns=pd.to_datetime(dates))


def test_inventory_uses_same_season_and_preserves_units():
    from app.flows.demand import inventory_evidence
    f=frame([80,50,100], ['2026-06-30','2026-03-31','2025-06-30'])
    d=inventory_evidence(f,'USD','2026-10-08')
    m=d['measurements'][0]
    assert (m['current'],m['previous'],m['unit'])==(80,100,'USD')
    assert m['previous_period']=='2025-06-30'
    assert d['coverage']=='inventory_only'


def test_inventory_requires_comparable_dates_currency_and_nonnegative_values():
    from app.flows.demand import inventory_evidence
    assert inventory_evidence(frame([80,100],['2026-06-30','2026-03-31']),'USD','2026-10-08') is None
    assert inventory_evidence(frame([80,100],['2026-06-30','2025-06-30']),None,'2026-10-08') is None
    assert inventory_evidence(frame([-1,100],['2026-06-30','2025-06-30']),'USD','2026-10-08') is None


def test_inventory_does_not_overwrite_manual_demand(con):
    from app.flows.demand import collect_inventory
    from app.flows.ingest import ingest
    from app.discovery.store import flows
    row=listing();catalog(con,[row])
    ingest(con,row['id'],'demand','2026-10-01',{'source':'Issuer','measurements':[dict(metric='orders',previous=10,current=20,unit='units',product='chips',previous_period='2025-Q2',current_period='2026-Q2')]},'2026-10-02T00:00:00Z')
    class Ticker:
        @property
        def quarterly_balance_sheet(self):
            raise AssertionError('Manual evidence must be preserved')
    assert collect_inventory(con,row,Ticker(),{'financialCurrency':'USD'})['status']=='manual_evidence_preserved'
    assert flows(con,row['id'],'demand')[0]['data']['source']=='Issuer'
