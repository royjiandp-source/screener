"""Validated issuer/source facts can supplement automated providers."""
from ..discovery.store import init,save_flow,flows
from ..filings.common import utc
from ..db import loads
from ..valuation import finite
from .etf import estimate_creation_flow

KINDS={'etf_nav','etf_holdings','etf_reported_flow','institution_trades','institution_holdings','demand','earnings_estimates'}


def ingest(con,lid,kind,period,data,available_at):
    init(con)
    if kind not in KINDS or not data.get('source'):raise ValueError('자료 유형과 출처가 필요합니다.')
    listing=con.execute('SELECT data FROM listings WHERE id=?',(lid,)).fetchone()
    if not listing:raise ValueError('Unknown listing')
    item=loads(listing[0],{})
    available=utc(available_at)
    if available>utc():raise ValueError('Future availability is not allowed')
    import datetime as dt
    dt.date.fromisoformat(period)
    if period>available[:10]:raise ValueError('Period must precede availability')
    if kind in ('demand','earnings_estimates') and item['type'] not in ('stock','adr'):raise ValueError('Company required')
    if kind=='demand':
        measurements=data.get('measurements')
        if not isinstance(measurements,list) or not measurements:raise ValueError('Comparable demand measurements required')
        for m in measurements:
            if (not isinstance(m,dict) or m.get('metric') not in ('orders','volume','inventory','product_price')
                    or not all(finite(m.get(k)) and m[k]>=0 for k in ('current','previous'))
                    or not all(isinstance(m.get(k),str) and m[k].strip() for k in ('unit','product','current_period','previous_period'))
                    or m['current_period']==m['previous_period']):raise ValueError('Demand requires comparable product, unit and periods')
    if kind=='earnings_estimates':
        if (not data.get('forecast_period') or not data.get('currency')
                or not all(finite(data.get(k)) for k in ('current','previous'))
                or not data.get('previous_observed_at')
                or utc(data['previous_observed_at'])>=utc(period+'T23:59:59Z')
                or data.get('previous_forecast_period',data['forecast_period'])!=data['forecast_period']):raise ValueError('Same forecast period and earlier estimate required')
    if kind.startswith('etf_') and item['type']!='etf':raise ValueError('ETF required')
    if kind=='etf_nav':
        if any(not finite(data.get(k)) or data[k]<=0 for k in ('nav','shares')) or not data.get('currency'):raise ValueError('NAV/share units and currency required')
        if data.get('nav_date')!=period or data.get('shares_date')!=period:raise ValueError('NAV/share dates must match period')
        previous=flows(con,lid,'etf_nav')
        previous=next((r for r in previous if r['period']<period and not r['data'].get('unresolved_corporate_action')),None)
        if previous:data={**data,'creation_estimate':estimate_creation_flow(previous['data'],data)}
    if kind=='etf_reported_flow':
        if not finite(data.get('net_creation')) or not data.get('currency'):raise ValueError('Reported flow and currency required')
    if kind=='institution_holdings':
        if not data.get('manager') or not data.get('accession') or not finite(data.get('shares')):raise ValueError('Manager, filing identity and share units required')
    if kind=='institution_trades':
        if not data.get('currency') or not data.get('rows'):raise ValueError('Investor rows and currency required')
    if kind=='etf_holdings':
        holdings=data.get('holdings')
        if not holdings or any(not r.get('ticker') or not finite(r.get('weight')) or not 0<=r['weight']<=1 for r in holdings):raise ValueError('Invalid holdings')
        if sum(r['weight'] for r in holdings)>1.01:raise ValueError('Holdings exceed 100%')
    save_flow(con,lid,kind,period,{**data,'origin':'source_import'},available)
    return {'status':'stored','kind':kind,'period':period}
