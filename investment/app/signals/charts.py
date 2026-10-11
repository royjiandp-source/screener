"""Collect charts independently so valuation-only listings also have price history."""
import time
import datetime as dt
from ..discovery.store import save_flow
from ..filings.common import utc
from .prices import monthly_prices


def refresh_charts(con,markets,limit=100,max_seconds=180):
    import yfinance as yf
    from ..dashboard import build_report
    report=build_report(con,limit=1000000)
    cutoff=(dt.date.fromisoformat(utc()[:10])-dt.timedelta(days=7)).isoformat()
    rows=[r for r in report['observations']['items'] if r['listing']['market'] in markets and (not r.get('price_1m') or r['price_1m'].get('end','')<cutoff)]
    result={'attempted':0,'collected':0,'unavailable':0};started=time.monotonic()
    for row in rows[:limit]:
        if time.monotonic()-started>=max_seconds:break
        item=row['listing'];stamp=utc();result['attempted']+=1
        try:
            chart=monthly_prices(yf.Ticker(item['ticker']).history(period='3mo',auto_adjust=True))
            if not chart:raise ValueError('Insufficient price history')
            save_flow(con,item['id'],'monthly_chart',chart['end'],{'chart':chart,'source':'Yahoo Finance adjusted daily closes'})
            result['collected']+=1
        except Exception as exc:
            save_flow(con,item['id'],'chart_collection_status',stamp[:10],{'status':'unavailable','reason':type(exc).__name__})
            result['unavailable']+=1
    return result
